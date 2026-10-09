from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "app" / "web" / "static" / "app.js"


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is required for the live UI runtime test")
def test_item_base_refresh_reloads_saved_data_and_keeps_request_identity() -> None:
    script = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = fs.readFileSync(process.argv[1], 'utf8');
const start = source.indexOf('async function refreshBaseMarket(forceRefresh = true) {');
const close = source.slice(start).match(/\r?\n}\r?\n/);
const end = close ? start + close.index + close[0].length - (close[0].endsWith('\r\n') ? 2 : 1) : -1;
assert(start >= 0 && end >= 0, 'refreshBaseMarket must remain an extractable top-level function');

const context = {
  URLSearchParams,
  AbortController,
  state: {
    isLoadingBaseMarket: false,
    baseMarketParams: null,
    baseMarketAbortController: null,
    baseMarketRequestId: 0,
    baseMarket: null,
    baseMarketError: '',
    focusedBaseMarketId: '',
  },
  query: { league: 'Dawn', target: 'exalted', status: 'securable', q: '' },
  requests: [],
  byId: () => null,
  baseMarketRequestParams: null,
  baseMarketRefreshJob: () => null,
  baseMarketJobIsActive: () => false,
  scheduleBaseMarketPoll: () => {},
  renderBaseMarket: () => {},
  loadingMarkup: () => '',
  t: (key) => key,
  window: { setTimeout: () => 1, clearTimeout: () => {} },
  fetch: null,
};
context.baseMarketRequestParams = (force) => ({ ...context.query, ...(force ? { refresh: 'true' } : {}) });
context.fetch = (url, options) => new Promise((resolve) => context.requests.push({ url, signal: options.signal, resolve }));
vm.createContext(context);
vm.runInContext(source.slice(start, end + 2) + '\nglobalThis.refresh = refreshBaseMarket;', context);

function resolveRequest(request, payload) {
  request.resolve({ ok: true, json: async () => payload });
}

(async () => {
  // Сохранённое отображение не должно блокировать следующий запрос endpoint.
  const firstRead = context.refresh(false);
  resolveRequest(context.requests[0], { rows: [], stored: true, revision: 1 });
  await firstRead;
  const nextRead = context.refresh(false);
  assert.equal(context.requests.length, 2, 'each non-forced poll must read the saved endpoint again');
  resolveRequest(context.requests[1], { rows: [], stored: true, revision: 2 });
  await nextRead;
  assert.equal(context.state.baseMarket.revision, 2, 'the UI must accept the newer saved payload');

  // Ключ опроса не учитывает параметр принудительного обновления.
  context.state.isLoadingBaseMarket = false;
  context.query = { league: 'Dawn', target: 'exalted', status: 'securable', q: 'belt' };
  const forced = context.refresh(true);
  assert.match(context.requests[2].url, /[?&]refresh=true(?:&|$)/);
  const sameQueryPoll = context.refresh(false);
  await sameQueryPoll;
  assert.equal(context.requests.length, 3, 'a poll must leave the same forced request in flight');
  assert.equal(context.requests[2].signal.aborted, false);
  resolveRequest(context.requests[2], { rows: [], revision: 3 });
  await forced;

  // Смена фильтра отменяет предыдущий fetch, а его поздний ответ игнорируется.
  context.query = { league: 'Dawn', target: 'exalted', status: 'securable', q: 'ring' };
  const oldFilter = context.refresh(false);
  const oldRequest = context.requests[3];
  context.query = { league: 'Dawn', target: 'exalted', status: 'securable', q: 'amulet' };
  const newFilter = context.refresh(false);
  const newRequest = context.requests[4];
  assert.equal(oldRequest.signal.aborted, true, 'changing filters must abort the previous fetch');
  resolveRequest(newRequest, { rows: [], revision: 'amulet' });
  await newFilter;
  resolveRequest(oldRequest, { rows: [], revision: 'ring' });
  await oldFilter;
  assert.equal(context.state.baseMarket.revision, 'amulet', 'a late old-filter response must be ignored');
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
"""
    result = subprocess.run(
        [shutil.which("node") or "node", "-e", script, str(APP_JS)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == 0, f"Node runtime harness failed:\n{result.stdout}\n{result.stderr}"
