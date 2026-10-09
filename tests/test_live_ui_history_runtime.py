from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "app" / "web" / "static" / "app.js"


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is required for live UI history runtime tests")
def test_history_caches_refresh_by_snapshot_and_retry_without_losing_good_series() -> None:
    script = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = fs.readFileSync(process.argv[1], 'utf8');
function extract(name) {
  const start = source.search(new RegExp(`^(?:async )?function ${name}\\(`, 'm'));
  const close = source.slice(start).match(/\r?\n}\r?\n/);
  assert(start >= 0 && close, `missing function ${name}`);
  const end = start + close.index + close[0].length - (close[0].endsWith('\r\n') ? 2 : 1);
  return source.slice(start, end + 1);
}
const functions = [
  'historySeriesCacheIsFresh', 'historySeriesRetryPending',
  'baseMarketHistoryKey', 'loadBaseMarketHistory',
  'accountChartKey', 'accountChartRequest', 'accountChartCachedSeries', 'loadAccountChartSeries',
  'historyTrendsKey', 'detailSeriesKey', 'loadHistoricalItemSeries',
].map(extract).join('\n');
const context = {
  URLSearchParams,
  Date,
  HISTORY_SERIES_LIMIT: 1500,
  HISTORY_SERIES_CACHE_TTL_MS: 300000,
  HISTORY_SERIES_RETRY_MS: 30000,
  state: {
    baseMarket: { league: 'Fate', target: 'exalted', status: 'any', created_ts: 200 },
    baseMarketHistoryCache: {}, baseMarketHistoryLoading: {}, baseMarketHistoryRetryAt: {},
    accountChartSeriesCache: {}, accountChartSeriesLoading: {}, accountChartSeriesRetryAt: {},
    detailSeriesCache: {}, detailSeriesLoading: {}, detailSeriesRetryAt: {},
    selectedCategory: 'Currency', rates: {},
  },
  requests: [],
  byId: () => null,
  selectedTarget: () => 'exalted',
  baseMarketLowPrice: row => row.low,
  renderBaseMarketDetail: () => {},
  rowsById: data => new Map((data.rows || []).map(row => [row.id, row])),
  rateValue: row => row?.median,
  updateMaxChartDaysFromSeries: () => {},
  fetch: null,
};
context.fetch = (url) => new Promise((resolve, reject) => context.requests.push({ url, resolve, reject }));
vm.createContext(context);
vm.runInContext(functions + '\nglobalThis.historyApi = { loadBaseMarketHistory, baseMarketHistoryKey, accountChartRequest, accountChartCachedSeries, loadAccountChartSeries, detailSeriesKey, loadHistoricalItemSeries, historySeriesCacheIsFresh };', context);
function finish(request, series) { request.resolve({ ok: true, json: async () => ({ series }) }); }

(async () => {
  const baseRow = { id: 'base:test', low: 5, stored_created_ts: 100 };
  const baseKey = 'Fate|exalted|any|base:test';
  context.state.baseMarketHistoryCache[baseKey] = {
    series: [{ ts: 100, value: 4 }], revisionTs: 100, fetchedAt: Date.now(),
  };
  const baseLoad = context.historyApi.loadBaseMarketHistory(baseRow);
  assert.equal(context.requests.length, 1, 'a changed base snapshot must refresh its cached history');
  context.state.baseMarket = { league: 'Standard', target: 'divine', status: 'online', created_ts: 300 };
  finish(context.requests[0], [{ created_ts: 50, value: 3 }]);
  await baseLoad;
  const loadedBase = context.state.baseMarketHistoryCache[baseKey];
  assert.equal(loadedBase.revisionTs, 200);
  assert(!loadedBase.series.some(point => point.ts === 200 && point.value === 5), 'do not assign the aggregate snapshot timestamp to a retained base price');
  assert(loadedBase.series.some(point => point.ts === 100 && point.value === 5), 'append the retained row only at its stored observation timestamp');
  assert(!loadedBase.series.some(point => point.ts === 300), 'a later league switch must not relabel the old row');

  const accountItem = {
    league: 'Fate', category: 'Currency', item_id: 'divine',
    market: { target_currency: 'exalted', created_ts: 400, price: 10 },
  };
  const accountRequest = context.historyApi.accountChartRequest(accountItem);
  context.state.accountChartSeriesCache[accountRequest.key] = {
    series: [{ ts: 100, value: 8 }], revisionTs: 100, fetchedAt: Date.now(),
  };
  const accountLoad = context.historyApi.loadAccountChartSeries(accountRequest);
  assert.equal(context.requests.length, 2, 'account chart history must refresh after a newer market snapshot');
  finish(context.requests[1], [{ created_ts: 200, value: 9 }]);
  await accountLoad;
  const accountEntry = context.state.accountChartSeriesCache[accountRequest.key];
  assert.equal(accountEntry.revisionTs, 400);
  assert(accountEntry.series.some(point => point.ts === 400 && point.value === 10));
  assert.equal(context.historyApi.accountChartCachedSeries(accountItem).at(-1).value, 10);

  const itemBaseAccount = {
    league: 'Fate', category: 'ItemBases', item_id: 'base:test',
    market: { target_currency: 'exalted', created_ts: 500, price: 11 },
  };
  const itemBaseRequest = context.historyApi.accountChartRequest(itemBaseAccount);
  assert.equal(itemBaseRequest.currentTs, 0, 'ItemBases account charts must not use the aggregate timestamp without a row observation timestamp');
  const itemBaseLoad = context.historyApi.loadAccountChartSeries(itemBaseRequest);
  finish(context.requests[2], [{ created_ts: 100, value: 8 }]);
  await itemBaseLoad;
  assert(!context.historyApi.accountChartCachedSeries(itemBaseAccount).some(point => point.ts === 500), 'the account chart must not fabricate a retained base point at the aggregate timestamp');

  const currentData = {
    league: 'Fate', category: 'Currency', target: 'exalted', status: 'any', created_ts: 500,
    rows: [{ id: 'divine', median: 11, volume: 20 }],
  };
  const detailKey = context.historyApi.detailSeriesKey(currentData, 'divine', 'price');
  const detailLoad = context.historyApi.loadHistoricalItemSeries(currentData, 'divine', 'price');
  const deduplicatedLoad = context.historyApi.loadHistoricalItemSeries(currentData, 'divine', 'price');
  assert.equal(context.requests.length, 4, 'concurrent detail renders must share one history request');
  finish(context.requests[3], [{ created_ts: 300, value: 10 }]);
  const [detailSeries, duplicateSeries] = await Promise.all([detailLoad, deduplicatedLoad]);
  assert.deepEqual(detailSeries, duplicateSeries);
  assert.equal(context.state.detailSeriesCache[detailKey].revisionTs, 500);

  const baseDetail = {
    league: 'Fate', category: 'ItemBases', target: 'exalted', status: 'any', created_ts: 600,
    rows: [{ id: 'base:test', median: 12 }],
  };
  const baseDetailLoad = context.historyApi.loadHistoricalItemSeries(baseDetail, 'base:test', 'price');
  finish(context.requests[4], [{ created_ts: 100, value: 8 }]);
  await baseDetailLoad;
  assert(!context.state.detailSeriesCache[context.historyApi.detailSeriesKey(baseDetail, 'base:test', 'price')].series.some(point => point.ts === 600), 'ItemBases detail history must not use the aggregate snapshot timestamp without row observation time');

  const expired = { series: [{ ts: 1, value: 2 }], revisionTs: 500, fetchedAt: Date.now() - 300001 };
  assert.equal(context.historyApi.historySeriesCacheIsFresh(expired, 500), false, 'same-revision history must expire by TTL');

  // A temporary failure leaves a usable old series and suppresses immediate retries.
  const retryItem = { ...accountItem, market: { ...accountItem.market, created_ts: 600, price: 12 } };
  const retryRequest = context.historyApi.accountChartRequest(retryItem);
  const oldEntry = { series: [{ ts: 200, value: 9 }], revisionTs: 400, fetchedAt: Date.now() };
  context.state.accountChartSeriesCache[retryRequest.key] = oldEntry;
  const failedLoad = context.historyApi.loadAccountChartSeries(retryRequest);
  context.requests[5].reject(new Error('temporary history failure'));
  await failedLoad;
  assert.equal(context.state.accountChartSeriesCache[retryRequest.key], oldEntry);
  const beforeRetry = context.requests.length;
  await context.historyApi.loadAccountChartSeries(retryRequest);
  assert.equal(context.requests.length, beforeRetry, 'retry backoff must prevent a tight failure loop');
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
    result = subprocess.run(
        [shutil.which("node") or "node", "-e", script, str(APP_JS)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == 0, f"Node history runtime harness failed:\n{result.stdout}\n{result.stderr}"


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is required for live UI history runtime tests")
def test_pending_market_history_trend_is_reloaded_for_latest_snapshot() -> None:
    script = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = fs.readFileSync(process.argv[1], 'utf8');
function extract(name) {
  const start = source.search(new RegExp(`^(?:async )?function ${name}\\(`, 'm'));
  const close = source.slice(start).match(/\r?\n}\r?\n/);
  assert(start >= 0 && close, `missing function ${name}`);
  const end = start + close.index + close[0].length - (close[0].endsWith('\r\n') ? 2 : 1);
  return source.slice(start, end + 1);
}
const functions = ['historyTrendsKey', 'loadHistoryTrends'].map(extract).join('\n');
const context = {
  URLSearchParams,
  state: {
    selectedCategory: 'Currency', rates: {}, historyTrends: [], historyTrendsKey: '',
    pendingHistoryTrendsData: null, isLoadingHistoryTrends: false,
  },
  requests: [],
  byId: () => null,
  selectedTarget: () => 'exalted',
  renderMarketSignals: () => {},
  buildHistoryTrends: current => [current.created_ts],
  t: key => key,
  fetch: null,
};
context.fetch = (url) => new Promise(resolve => context.requests.push({ url, resolve }));
vm.createContext(context);
vm.runInContext(functions + '\nglobalThis.load = loadHistoryTrends;', context);
function snapshot(ts) { return { league: 'Fate', category: 'Currency', target: 'exalted', status: 'any', created_ts: ts }; }
function finish(request) { request.resolve({ ok: true, json: async () => ({ history: [] }) }); }
(async () => {
  const first = context.load(snapshot(100));
  context.load(snapshot(200));
  context.load(snapshot(300));
  assert.equal(context.requests.length, 1);
  finish(context.requests[0]);
  await first;
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.equal(context.requests.length, 2, 'the latest pending snapshot must trigger another history read');
  assert.match(context.requests[1].url, /since_ts|limit=/);
  finish(context.requests[1]);
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.deepEqual(Array.from(context.state.historyTrends), [300]);
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
    result = subprocess.run(
        [shutil.which("node") or "node", "-e", script, str(APP_JS)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == 0, f"Node trend runtime harness failed:\n{result.stdout}\n{result.stderr}"
