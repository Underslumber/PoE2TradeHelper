// Economy table page

function buildColumns(data) {
  const cols = [
    { data: 'name', title: t('item'), render: (data, type, row) => {
        const iconPath = row.icon_local ? `/icons/${row.icon_local}` : row.icon_url;
        const icon = iconPath ? `<img src="${iconPath}" alt="icon">` : '';
        return `<span class="icon-cell">${icon}<span>${data}</span></span>`;
      }
    }
  ];
  (data.columns || []).forEach(col => {
    cols.push({ data: `columns.${col}`, title: col, defaultContent: '' });
  });
  return cols;
}

function loadTable() {
  const league = byId('league').value;
  const category = byId('category').value;
  const search = byId('search').value;
  const params = new URLSearchParams();
  if (league) params.append('league', league);
  if (category) params.append('category', category);
  if (search) params.append('q', search);
  fetch(`/api/rows?${params.toString()}`)
    .then(r => r.json())
    .then(data => {
      const columns = buildColumns(data);
      if (window.economyTable) {
        window.economyTable.clear();
        window.economyTable.destroy();
      }
      const header = byId('columns-header');
      header.innerHTML = '';
      columns.forEach(col => {
        const th = document.createElement('th');
        th.textContent = col.title;
        header.appendChild(th);
      });
      window.economyTable = new DataTable('#economy-table', {
        data: data.rows,
        columns: columns,
        paging: true,
        searching: false,
        info: true,
        order: [],
      });
    });
}

function initEconomyTable() {
  applyLanguage();
  ['league', 'category', 'search'].forEach(id => {
    const el = byId(id);
    el.addEventListener('change', loadTable);
    if (id === 'search') {
      el.addEventListener('keyup', () => {
        clearTimeout(window._searchTimer);
        window._searchTimer = setTimeout(loadTable, 300);
      });
    }
  });
  loadTable();
}

window.initEconomyTable = initEconomyTable;

// Shared live page state

const i18n = window.POE2_I18N || { ru: {}, en: {} };

const state = {
  lang: localStorage.getItem('poe2-lang') || 'ru',
  leagues: [],
  categories: {},
  categoryMeta: [],
  selectedCategory: 'Currency',
  selectedItemId: null,
  detailTarget: 'auto',
  rates: {},
  detailRates: {},
  advice: [],
  mainView: 'market',
  activeAdviceTab: 'buy',
  crossDeals: [],
  crossDealsKey: '',
  isLoadingCrossDeals: false,
  activeTrades: [],
  marketChains: [],
  activeTradesKey: '',
  isLoadingActiveTrades: false,
  sellerLots: null,
  sellerLotsCache: {},
  sellerLotMarketCache: {},
  isLoadingSellerLots: false,
  sellerLotsAbortController: null,
  sellerLotsRequestId: 0,
  autoRefreshMs: Number(localStorage.getItem('poe2-auto-refresh-ms') ?? 60000),
  autoRefreshTimer: null,
  isRefreshing: false,
  sort: { key: 'name', direction: 'asc' },
};

const preferredTargets = ['exalted', 'divine', 'chaos'];
const CROSS_MIN_VOLUME = 10;

// DOM helpers

function byId(id) {
  return document.getElementById(id);
}

function setText(id, value) {
  const element = byId(id);
  if (element) element.textContent = value;
}

// Localization

function t(key) {
  const messages = i18n[state.lang] || {};
  return Object.prototype.hasOwnProperty.call(messages, key) ? messages[key] : key;
}

function applyLanguage() {
  document.documentElement.lang = state.lang;
  document.querySelectorAll('[data-i18n]').forEach(el => {
    el.textContent = t(el.dataset.i18n);
  });
  document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
    el.placeholder = t(el.dataset.i18nPlaceholder);
  });
  document.querySelector('.language-switch')?.setAttribute('aria-label', state.lang === 'ru' ? 'Язык' : 'Language');
  byId('lang-ru')?.classList.toggle('active', state.lang === 'ru');
  byId('lang-en')?.classList.toggle('active', state.lang === 'en');
  fillStatusSelect();
  fillTargetCurrencySelect();
  fillAutoRefreshSelect();
  renderTargetCurrencyInfo();
  renderCategories();
  renderMarket();
  renderAdvice(state.advice);
  renderSellerLots();
  switchMainView(state.mainView);
  fillDetailTargetSelect();
  renderSelectedItemDetail();
  renderHistory();
}

function entryName(entry) {
  return state.lang === 'ru' ? (entry.text_ru || entry.text) : entry.text;
}

function categoryName(category) {
  return state.lang === 'ru' ? (category.label_ru || category.label) : category.label;
}

// Page feedback

function setLiveError(message) {
  const error = byId('live-error');
  if (!error) return;
  if (!message) {
    error.classList.add('d-none');
    error.textContent = '';
    return;
  }
  error.textContent = message;
  error.classList.remove('d-none');
}

// Formatting

function formatAmount(value) {
  if (value === null || value === undefined || value === '') return '-';
  const number = Number(value);
  if (!Number.isFinite(number)) return String(value);
  if (Math.abs(number) >= 1000) return Intl.NumberFormat(state.lang === 'ru' ? 'ru-RU' : 'en-US', { maximumFractionDigits: 1, notation: 'compact' }).format(number);
  return Number.isInteger(number) ? String(number) : number.toFixed(4).replace(/0+$/, '').replace(/\.$/, '');
}

function formatChange(value) {
  if (value === null || value === undefined || value === '') return '-';
  const number = Number(value);
  if (!Number.isFinite(number)) return '-';
  const sign = number > 0 ? '+' : '';
  return `${sign}${number.toFixed(1).replace(/\.0$/, '')}%`;
}

function escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function loadingMarkup(message, mode = 'block') {
  const className = mode === 'inline' ? 'loading-inline' : 'loading-block';
  return `<span class="${className}"><span class="loading-spinner" aria-hidden="true"></span><span>${escapeHtml(message)}</span></span>`;
}

function cleanPoeText(value) {
  return String(value ?? '').replace(/\[[^\]|]+\|([^\]]+)\]/g, '$1');
}

function rarityLabel(rarity) {
  const key = `rarity${String(rarity || '').toLowerCase().replace(/^\w/, char => char.toUpperCase())}`;
  return t(key) === key ? (rarity || '-') : t(key);
}

function setLoadingStatus(element, message) {
  if (!element) return;
  element.innerHTML = loadingMarkup(message, 'inline');
}

function formatDateTime(value) {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '-';
  return date.toLocaleString(state.lang === 'ru' ? 'ru-RU' : 'en-US');
}

// Currency and filter options

function hasTarget(target) {
  return (state.categories.Currency || []).some(entry => entry.id === target);
}

function defaultTarget() {
  if (hasTarget('exalted')) return 'exalted';
  if (hasTarget('divine')) return 'divine';
  return (state.categories.Currency || [])[0]?.id || 'divine';
}

function currencyEntry(target) {
  return (state.categories.Currency || []).find(entry => entry.id === target);
}

function currencyLabel(target) {
  const entry = currencyEntry(target);
  if (!entry) return target || '-';
  return entryName(entry);
}

function currencyIcon(target) {
  return currencyEntry(target)?.image || '';
}

function currencyMarkup(target) {
  if (!target) return '-';
  const icon = currencyIcon(target);
  const label = currencyLabel(target);
  const code = state.lang === 'ru' ? '' : `<span class="currency-code">(${target})</span>`;
  return `${icon ? `<img src="${icon}" alt="">` : ''}<span>${label}</span>${code}`;
}

function selectedTarget() {
  return byId('target-currency')?.value || defaultTarget();
}

function renderCurrencyElement(element, target) {
  if (!element) return;
  element.innerHTML = currencyMarkup(target);
}

function renderTargetCurrencyInfo(target = selectedTarget()) {
  renderCurrencyElement(byId('target-currency-preview'), target);
  renderCurrencyElement(byId('summary-target-currency'), target);
  const shortLabel = target ? `(${currencyLabel(target)})` : '';
  setText('best-target-label', shortLabel);
  setText('median-target-label', shortLabel);
}

function targetOptions(includeAuto = false) {
  const currencyEntries = state.categories.Currency || [];
  const ordered = preferredTargets
    .map(id => currencyEntries.find(entry => entry.id === id))
    .filter(Boolean)
    .map(entry => ({ id: entry.id, text: state.lang === 'ru' ? entryName(entry) : `${entryName(entry)} (${entry.id})` }));
  if (!includeAuto) return ordered;
  return [{ id: 'auto', text: t('autoTarget') }, ...ordered];
}

function availableTargetIds() {
  return targetOptions(false).map(entry => entry.id);
}

function statusOptions() {
  return [
    { id: 'any', text: t('statusAny') },
    { id: 'online', text: t('statusOnline') },
  ];
}

function autoRefreshOptions() {
  return [
    { id: '0', text: t('autoRefreshOff') },
    { id: '60000', text: t('autoRefresh1m') },
    { id: '300000', text: t('autoRefresh5m') },
    { id: '1800000', text: t('autoRefresh30m') },
    { id: '3600000', text: t('autoRefresh1h') },
  ];
}

// Market table

function sortValue(row, key) {
  if (key === 'name') return row.name.toLowerCase();
  if (key === 'id') return row.id.toLowerCase();
  const value = row[key];
  return value === null || value === undefined || value === '' ? null : Number(value);
}

function compareRows(left, right) {
  const key = state.sort.key;
  const direction = state.sort.direction === 'asc' ? 1 : -1;
  const a = sortValue(left, key);
  const b = sortValue(right, key);
  if (a === null && b === null) return 0;
  if (a === null) return 1;
  if (b === null) return -1;
  if (typeof a === 'string' && typeof b === 'string') {
    return a.localeCompare(b, state.lang === 'ru' ? 'ru' : 'en') * direction;
  }
  return (a - b) * direction;
}

function renderSortIndicators() {
  document.querySelectorAll('[data-sort-key]').forEach(button => {
    const active = button.dataset.sortKey === state.sort.key;
    button.classList.toggle('active', active);
    const icon = button.querySelector('.sort-icon');
    if (icon) icon.textContent = active ? (state.sort.direction === 'asc' ? '↑' : '↓') : '↕';
  });
}

function fillSelect(select, entries, selectedId) {
  select.innerHTML = '';
  entries.forEach(entry => {
    const option = document.createElement('option');
    option.value = entry.id;
    option.textContent = entry.text;
    if (entry.id === selectedId) option.selected = true;
    select.appendChild(option);
  });
}

function fillStatusSelect() {
  const select = byId('live-status');
  if (!select) return;
  const selected = select.value || 'any';
  fillSelect(select, statusOptions(), selected);
}

function fillTargetCurrencySelect() {
  const select = byId('target-currency');
  if (!select) return;
  const selected = select.value || defaultTarget();
  fillSelect(select, targetOptions(false), selected);
}

function fillAutoRefreshSelect() {
  const select = byId('auto-refresh-interval');
  if (!select) return;
  fillSelect(select, autoRefreshOptions(), String(state.autoRefreshMs || 0));
}

function renderCategories() {
  const list = byId('category-list');
  if (!list) return;
  list.innerHTML = '';
  state.categoryMeta.forEach(category => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = `category-button ${category.id === state.selectedCategory ? 'active' : ''}`;
    button.innerHTML = `
      ${category.icon ? `<img src="${category.icon}" alt="">` : '<span class="category-placeholder"></span>'}
      <span>${categoryName(category)}</span>
      <small>${category.count}</small>
    `;
    button.addEventListener('click', () => {
      state.selectedCategory = category.id;
      state.selectedItemId = null;
      state.crossDeals = [];
      state.crossDealsKey = '';
      state.activeTrades = [];
      state.marketChains = [];
      state.activeTradesKey = '';
      setText('category-title', categoryName(category));
      byId('item-detail-panel')?.classList.add('d-none');
      renderCategories();
      renderMarket();
      renderAdvice((state.rates[state.selectedCategory] || {}).advice || []);
      loadLatestCachedRates();
    });
    list.appendChild(button);
  });
}

function renderMarket() {
  const body = byId('market-results');
  if (!body) return;
  renderTargetCurrencyInfo((state.rates[state.selectedCategory] || {}).target || selectedTarget());
  const search = (byId('market-search').value || '').toLowerCase();
  const entries = (state.categories[state.selectedCategory] || [])
    .filter(entry => !search || entry.text.toLowerCase().includes(search) || (entry.text_ru || '').toLowerCase().includes(search) || entry.id.toLowerCase().includes(search));
  const categoryRates = state.rates[state.selectedCategory] || {};
  const rateRows = new Map((categoryRates.rows || []).map(row => [row.id, row]));
  const visibleRows = entries.map(entry => {
    const priced = rateRows.get(entry.id) || entry;
    return {
      entry,
      priced,
      name: entryName(entry),
      id: entry.id,
      best: priced.best,
      median: priced.median,
      change: priced.change,
      offers: priced.offers || 0,
      volume: priced.volume || 0,
    };
  }).sort(compareRows);
  setText('items-total', entries.length);
  setText('priced-total', [...rateRows.values()].filter(row => row.best !== null && row.best !== undefined).length);
  setText('rate-source', categoryRates.source || '-');
  setText('last-snapshot', categoryRates.created_ts
    ? `${new Date(categoryRates.created_ts * 1000).toLocaleTimeString(state.lang === 'ru' ? 'ru-RU' : 'en-US')}${categoryRates.cached ? ` ${t('cacheLabel')}` : ''}`
    : '-');
  renderSortIndicators();
  body.innerHTML = '';
  if (!entries.length) {
    body.innerHTML = `<tr><td colspan="7" class="text-secondary">${t('noItems')}</td></tr>`;
    return;
  }
  visibleRows.forEach(row => {
    const { entry, priced } = row;
    const changeClass = Number(priced.change) > 0 ? 'change-up' : Number(priced.change) < 0 ? 'change-down' : '';
    const tr = document.createElement('tr');
    tr.className = `market-row ${entry.id === state.selectedItemId ? 'active' : ''}`;
    tr.innerHTML = `
      <td class="name-cell">${entry.image ? `<img src="${entry.image}" alt="">` : ''}<span>${entryName(entry)}</span></td>
      <td class="muted-id">${entry.id}</td>
      <td>${formatAmount(priced.best)}</td>
      <td>${formatAmount(priced.median)}</td>
      <td class="${changeClass}">${formatChange(priced.change)}</td>
      <td>${formatAmount(priced.offers || 0)}</td>
      <td>${formatAmount(priced.volume || 0)}</td>
    `;
    tr.addEventListener('click', () => openItemDetail(entry.id));
    body.appendChild(tr);
  });
}

// Seller lots

function lotNativePrice(lot) {
  return `${formatAmount(lot.price_amount)} ${currencyLabel(lot.price_currency)}`;
}

function lotTargetPrice(value, target = selectedTarget()) {
  return value === null || value === undefined ? '-' : `${formatAmount(value)} ${currencyLabel(target)}`;
}

function verdictLabel(kind) {
  if (kind === 'cheap') return t('verdictCheap');
  if (kind === 'fair') return t('verdictFair');
  if (kind === 'expensive') return t('verdictExpensive');
  return t('verdictUnknown');
}

function confidenceLabel(value) {
  if (value === 'high') return t('confidenceHigh');
  if (value === 'medium') return t('confidenceMedium');
  if (value === 'low') return t('confidenceLow');
  return t('confidenceInsufficient');
}

function comparisonLabel(mode) {
  if (mode === 'type-level-stat-ids') return t('comparisonExactStats');
  if (mode === 'type-level-stat-ids-minus-one') return t('comparisonStatsMinusOne');
  if (mode === 'type-level-loose-stats') return t('comparisonLooseStats');
  return t('comparisonTypeOnly');
}

function renderSellerLotCard(lot) {
  const market = lot.market || {};
  const verdict = lot.verdict || { kind: 'unknown' };
  const target = lot.target || selectedTarget();
  const mods = (lot.explicit_mods || []).slice(0, 2).map(cleanPoeText).map(escapeHtml).join(' · ');
  const delta = verdict.delta_pct === null || verdict.delta_pct === undefined ? '' : ` (${formatChange(verdict.delta_pct)})`;
  const lotName = cleanPoeText(lot.display_name);
  const lotBase = cleanPoeText(lot.base_type);
  return `
    <article class="lot-card ${escapeHtml(verdict.kind || 'unknown')}">
      <div class="lot-card-grid">
        <div>
          <div class="lot-title">
            ${lot.icon ? `<img src="${escapeHtml(lot.icon)}" alt="">` : '<span class="category-placeholder"></span>'}
            <div>
              <strong>${escapeHtml(lotName)}</strong>
              <small>${escapeHtml([rarityLabel(lot.rarity), lotBase, lot.item_level ? `ilvl ${lot.item_level}` : ''].filter(Boolean).join(' / '))}</small>
            </div>
          </div>
          ${mods ? `<div class="lot-card-note">${mods}</div>` : ''}
          <div class="lot-card-note">${t('stashSection')}: ${escapeHtml(lot.stash || '-')} · ${t('listed')}: ${formatDateTime(lot.indexed)}</div>
        </div>
        <div>
          <span class="lot-card-label">${t('sellerPrice')}</span>
          <strong class="lot-card-value">${lotNativePrice(lot)}</strong>
          <span class="lot-card-note">${lotTargetPrice(lot.price_target, target)}</span>
        </div>
        <div>
          <span class="lot-card-label">${t('currentMarketPrice')}</span>
          ${market.pending ? loadingMarkup(t('marketEvaluating'), 'inline') : `
            <strong class="lot-card-value">${lotTargetPrice(market.current, target)}</strong>
            <span class="lot-card-note">${t('marketLots')}: ${formatAmount(market.count || 0)}</span>
            <span class="lot-card-note">${t('confidence')}: ${confidenceLabel(market.confidence)} · ${comparisonLabel(market.comparison?.mode)}</span>
          `}
        </div>
        <div>
          <span class="lot-card-label">${t('marketRange')}</span>
          <strong class="lot-card-value">${lotTargetPrice(market.min, target)} - ${lotTargetPrice(market.p75, target)}</strong>
          <span class="lot-card-note">${t('similarBasis')}</span>
        </div>
        <div>
          <span class="advice-badge">${verdictLabel(verdict.kind)}</span>
          <strong class="lot-card-value">${delta || '-'}</strong>
        </div>
      </div>
    </article>
  `;
}

function renderSellerLots() {
  const list = byId('lot-results');
  if (!list) return;
  if (state.isLoadingSellerLots) {
    list.innerHTML = '';
    return;
  }
  if (!state.sellerLots) {
    list.innerHTML = `<p class="text-secondary">${t('sellerLotsEmpty')}</p>`;
    return;
  }
  const lots = state.sellerLots.lots || [];
  if (!lots.length) {
    list.innerHTML = `<p class="text-secondary">${t('sellerLotsNoResults')}</p>`;
    return;
  }
  list.innerHTML = lots.map(renderSellerLotCard).join('');
}

async function fetchSellerLotMarket(lot, params, requestId) {
  if (!lot.id || state.sellerLotsRequestId !== requestId) return;
  const marketParams = new URLSearchParams({
    league: params.league,
    seller: params.seller,
    lot_id: lot.id,
    target: params.target,
    status: params.status,
  });
  const cacheKey = marketParams.toString();
  try {
    const cached = state.sellerLotMarketCache[cacheKey];
    let data = cached;
    if (!data) {
      const controller = new AbortController();
      const timeoutId = window.setTimeout(() => controller.abort(), 45000);
      try {
        const response = await fetch(`/api/trade/seller-lot-market?${marketParams.toString()}`, { signal: controller.signal });
        data = await response.json();
        if (!response.ok || data.error) throw new Error(data.error || t('tradeError'));
      } finally {
        window.clearTimeout(timeoutId);
      }
    }
    if (!cached) state.sellerLotMarketCache[cacheKey] = data;
    if (state.sellerLotsRequestId !== requestId || !state.sellerLots?.lots) return;
    const targetLot = state.sellerLots.lots.find(item => item.id === lot.id);
    if (!targetLot) return;
    targetLot.market = data.market || targetLot.market;
    targetLot.verdict = data.verdict || targetLot.verdict;
    targetLot.price_target = data.price_target ?? targetLot.price_target;
    targetLot.target = data.target || targetLot.target;
    renderSellerLots();
  } catch (error) {
    if (state.sellerLotsRequestId !== requestId || !state.sellerLots?.lots) return;
    const targetLot = state.sellerLots.lots.find(item => item.id === lot.id);
    if (!targetLot) return;
    targetLot.market = { ...(targetLot.market || {}), pending: false, confidence: 'insufficient', error: error.message || String(error) };
    renderSellerLots();
  }
}

async function loadSellerLotMarkets(params, requestId) {
  const lots = state.sellerLots?.lots || [];
  const queue = lots.filter(lot => lot.id);
  const workers = [0, 1].map(async () => {
    while (queue.length && state.sellerLotsRequestId === requestId) {
      const lot = queue.shift();
      await fetchSellerLotMarket(lot, params, requestId);
    }
  });
  await Promise.allSettled(workers);
  const status = byId('lot-search-status');
  if (state.sellerLotsRequestId === requestId && status && state.sellerLots) {
    status.textContent = `${t('marketLots')}: ${formatAmount(state.sellerLots.matched_total ?? state.sellerLots.total ?? state.sellerLots.lots?.length ?? 0)}`;
  }
}

async function searchSellerLots() {
  const seller = (byId('lot-seller')?.value || '').trim();
  const status = byId('lot-search-status');
  const button = byId('search-lots');
  if (!seller) {
    if (status) status.textContent = t('sellerRequired');
    return;
  }
  const league = byId('live-league')?.value || '';
  const target = selectedTarget();
  const liveStatus = byId('live-status')?.value || 'any';
  const query = (byId('lot-query')?.value || '').trim();
  const limit = byId('lot-limit')?.value || '10';
  const params = { league, seller, q: query, target, status: liveStatus, limit };
  const searchParams = new URLSearchParams({ ...params, analyze: 'false' });
  const cacheKey = searchParams.toString();
  if (state.sellerLotsCache[cacheKey]) {
    state.sellerLots = state.sellerLotsCache[cacheKey];
    if (status) status.textContent = `${t('marketLots')}: ${formatAmount(state.sellerLots.matched_total ?? state.sellerLots.total ?? state.sellerLots.lots?.length ?? 0)} · ${t('cacheLabel')}`;
    renderSellerLots();
    return;
  }
  const requestId = Date.now();
  state.sellerLotsRequestId = requestId;
  if (state.sellerLotsAbortController) {
    state.sellerLotsAbortController.abort();
  }
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), 90000);
  state.sellerLotsAbortController = controller;
  state.isLoadingSellerLots = true;
  state.sellerLots = null;
  if (status) setLoadingStatus(status, t('sellerLotsLoading'));
  if (button) button.disabled = true;
  renderSellerLots();
  try {
    const response = await fetch(`/api/trade/seller-lots?${searchParams.toString()}`, { signal: controller.signal });
    const data = await response.json();
    if (state.sellerLotsRequestId !== requestId) return;
    if (!response.ok || data.error) throw new Error(data.error || t('tradeError'));
    state.sellerLots = data;
    state.sellerLotsCache[cacheKey] = data;
    if (status) {
      const cacheLabel = data.cached ? ` · ${t('cacheLabel')}` : '';
      const timeoutLabel = data.analysis_timed_out ? ` · ${t('partialResults')}` : '';
      status.textContent = `${t('marketLots')}: ${formatAmount(data.matched_total ?? data.total ?? data.lots?.length ?? 0)}${cacheLabel}${timeoutLabel}`;
    }
    loadSellerLotMarkets(params, requestId);
  } catch (error) {
    if (state.sellerLotsRequestId !== requestId) return;
    state.sellerLots = { lots: [] };
    const isAbort = error?.name === 'AbortError';
    if (status) status.textContent = isAbort ? t('sellerLotsTimeout') : (error.message || String(error));
  } finally {
    window.clearTimeout(timeoutId);
    if (state.sellerLotsRequestId === requestId) {
      state.isLoadingSellerLots = false;
      state.sellerLotsAbortController = null;
      if (button) button.disabled = false;
      renderSellerLots();
    }
  }
}

// Item detail and charts

function fillDetailTargetSelect() {
  const select = byId('detail-target-currency');
  if (!select) return;
  const previous = select.value || state.detailTarget || 'auto';
  fillSelect(select, targetOptions(true), previous);
  if (![...select.options].some(option => option.value === previous)) {
    select.value = 'auto';
  }
}

function findEntry(itemId) {
  return (state.categories[state.selectedCategory] || []).find(entry => entry.id === itemId);
}

function findAnyEntry(itemId) {
  for (const entries of Object.values(state.categories)) {
    const entry = entries.find(item => item.id === itemId);
    if (entry) return entry;
  }
  return null;
}

function entryIcon(entry) {
  return entry?.image || '';
}

function itemTitleMarkup(name, icon) {
  return `<span class="advice-item-title">${icon ? `<img src="${icon}" alt="">` : ''}<span>${name}</span></span>`;
}

function ratesCacheKey(target) {
  const league = byId('live-league')?.value || '';
  const status = byId('live-status')?.value || 'any';
  return `${league}|${state.selectedCategory}|${target}|${status}`;
}

function rowsById(data) {
  return new Map((data?.rows || []).map(row => [row.id, row]));
}

function currentRowFor(itemId) {
  const tableRates = state.rates[state.selectedCategory] || {};
  return rowsById(tableRates).get(itemId) || findEntry(itemId);
}

function autoTargetFor(row) {
  const currentTarget = (state.rates[state.selectedCategory] || {}).target || byId('target-currency')?.value || defaultTarget();
  const value = Number(row?.best ?? row?.median);
  if (currentTarget === 'exalted' && Number.isFinite(value) && value >= 250 && hasTarget('divine')) return 'divine';
  if (currentTarget === 'divine' && Number.isFinite(value) && value > 0 && value < 0.25 && hasTarget('exalted')) return 'exalted';
  return currentTarget || defaultTarget();
}

async function ensureRatesForTarget(target) {
  const tableRates = state.rates[state.selectedCategory] || {};
  if (tableRates.target === target) return tableRates;
  const key = ratesCacheKey(target);
  if (state.detailRates[key]) return state.detailRates[key];

  const league = byId('live-league').value;
  const status = byId('live-status').value;
  const params = new URLSearchParams({ league, category: state.selectedCategory, target, status });
  const response = await fetch(`/api/trade/category-rates?${params.toString()}`);
  const data = await response.json();
  if (!response.ok || data.error) throw new Error(data.error || t('tradeError'));
  state.detailRates[key] = data;
  return data;
}

function renderSparkline(values) {
  const chart = byId('detail-chart');
  if (!chart) return;
  const data = (values || []).map(Number).filter(Number.isFinite);
  if (data.length < 2) {
    chart.innerHTML = `<div class="detail-chart-empty">${t('chartNoData')}</div>`;
    return;
  }
  const width = 720;
  const height = 190;
  const pad = 18;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;
  const points = data.map((value, index) => {
    const x = pad + (index / (data.length - 1)) * (width - pad * 2);
    const y = height - pad - ((value - min) / range) * (height - pad * 2);
    return `${x.toFixed(2)},${y.toFixed(2)}`;
  });
  const area = `${pad},${height - pad} ${points.join(' ')} ${width - pad},${height - pad}`;
  chart.innerHTML = `
    <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${t('priceChartLabel')}">
      <line class="detail-chart-grid" x1="${pad}" y1="${pad}" x2="${width - pad}" y2="${pad}"></line>
      <line class="detail-chart-grid" x1="${pad}" y1="${height / 2}" x2="${width - pad}" y2="${height / 2}"></line>
      <line class="detail-chart-grid" x1="${pad}" y1="${height - pad}" x2="${width - pad}" y2="${height - pad}"></line>
      <polygon class="detail-chart-area" points="${area}"></polygon>
      <polyline class="detail-chart-line" points="${points.join(' ')}"></polyline>
    </svg>
  `;
}

function miniSignalChart(values, basisText, currentValue = null, changeValue = null) {
  const data = (values || []).map(Number).filter(Number.isFinite);
  if (data.length < 2) {
    return `<aside class="advice-chart empty"><span>${t('noSignalChart')}</span></aside>`;
  }
  const width = 360;
  const height = 128;
  const leftPad = 40;
  const rightPad = 10;
  const topPad = 10;
  const bottomPad = 28;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;
  const points = data.map((value, index) => {
    const x = leftPad + (index / (data.length - 1)) * (width - leftPad - rightPad);
    const y = height - bottomPad - ((value - min) / range) * (height - topPad - bottomPad);
    return { x, y };
  });
  const polyline = points.map(point => `${point.x.toFixed(2)},${point.y.toFixed(2)}`).join(' ');
  const current = points[points.length - 1];
  const previous = points[Math.max(0, points.length - 3)];
  const highlightX = Math.max(leftPad, previous.x - 3);
  const highlightWidth = Math.max(14, width - rightPad - highlightX);
  const directionClass = data[data.length - 1] >= data[0] ? 'up' : 'down';
  const plotBottom = height - bottomPad;
  const plotRight = width - rightPad;
  const gridX = points.map(point => point.x);
  const gridY = [0, 0.25, 0.5, 0.75, 1].map(ratio => topPad + ratio * (plotBottom - topPad));
  const valueAtY = y => max - ((y - topPad) / (plotBottom - topPad)) * range;
  const dateFormatter = new Intl.DateTimeFormat(state.lang === 'ru' ? 'ru-RU' : 'en-GB', { day: '2-digit', month: '2-digit' });
  const today = new Date();
  const dayLabels = points.map((point, index) => {
    const daysAgo = data.length - 1 - index;
    const date = new Date(today);
    date.setDate(today.getDate() - daysAgo);
    const label = dateFormatter.format(date);
    return `<text class="advice-chart-x-label" x="${point.x.toFixed(2)}" y="${height - 7}" text-anchor="middle">${label}</text>`;
  }).join('');
  const absoluteCurrent = Number(currentValue);
  const canScaleValues = Number.isFinite(absoluteCurrent) && absoluteCurrent > 0 && data.every(value => value > 0);
  const scale = canScaleValues ? absoluteCurrent / data[data.length - 1] : null;
  const valueLabels = canScaleValues ? [gridY[0], gridY[2], gridY[4]].map(y => (
    `<text class="advice-chart-y-label" x="${leftPad - 7}" y="${(y + 3).toFixed(2)}" text-anchor="end">${formatAmount(valueAtY(y) * scale)}</text>`
  )).join('') : '';
  const displayCurrent = Number.isFinite(absoluteCurrent) && absoluteCurrent > 0 ? absoluteCurrent : data[data.length - 1];
  const firstValue = data[0];
  const numericChange = Number(changeValue);
  const change = Number.isFinite(numericChange) ? numericChange : (firstValue ? ((data[data.length - 1] - firstValue) / firstValue) * 100 : null);
  return `
    <aside class="advice-chart ${directionClass}">
      <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${t('priceChartLabel')}">
        ${gridX.map(x => `<line class="advice-chart-grid day" x1="${x.toFixed(2)}" y1="${topPad}" x2="${x.toFixed(2)}" y2="${plotBottom}"></line>`).join('')}
        ${gridY.map(y => `<line class="advice-chart-grid" x1="${leftPad}" y1="${y.toFixed(2)}" x2="${plotRight}" y2="${y.toFixed(2)}"></line>`).join('')}
        <rect class="advice-chart-current-area" x="${highlightX.toFixed(2)}" y="${topPad}" width="${highlightWidth.toFixed(2)}" height="${plotBottom - topPad}"></rect>
        <line class="advice-chart-current-line" x1="${leftPad}" y1="${current.y.toFixed(2)}" x2="${plotRight}" y2="${current.y.toFixed(2)}"></line>
        <polyline class="advice-chart-line" points="${polyline}"></polyline>
        <circle class="advice-chart-point" cx="${current.x.toFixed(2)}" cy="${current.y.toFixed(2)}" r="3.4"></circle>
        ${valueLabels}
        ${dayLabels}
      </svg>
      <div class="advice-chart-label"><span>${t('currentPoint')}: ${formatAmount(displayCurrent)}</span><span>${t('sevenDayChange')}: ${formatChange(change)}</span></div>
      <div class="advice-chart-basis">${t('signalBasis')}: ${basisText}</div>
    </aside>
  `;
}

function renderAdviceCard(card, contentHtml, chartHtml) {
  card.innerHTML = `
    <div class="advice-card-layout">
      <div class="advice-card-content">${contentHtml}</div>
      ${chartHtml || ''}
    </div>
  `;
}

async function renderSelectedItemDetail() {
  const panel = byId('item-detail-panel');
  if (!panel || !state.selectedItemId) return;
  const entry = findEntry(state.selectedItemId);
  if (!entry) {
    panel.classList.add('d-none');
    return;
  }
  panel.classList.remove('d-none');
  setText('detail-name', entryName(entry));
  setText('detail-id', entry.id);
  const detailIcon = byId('detail-icon');
  if (entry.image) {
    detailIcon.src = entry.image;
  } else {
    detailIcon.removeAttribute('src');
  }

  const select = byId('detail-target-currency');
  state.detailTarget = select?.value || 'auto';
  const baseRow = currentRowFor(entry.id);
  const target = state.detailTarget === 'auto' ? autoTargetFor(baseRow) : state.detailTarget;
  renderCurrencyElement(byId('detail-target-currency-preview'), target);
  setText('detail-value-target-label', `(${currencyLabel(target)})`);
  setText('detail-median-target-label', `(${currencyLabel(target)})`);
  byId('detail-note').innerHTML = loadingMarkup(t('loading'));
  try {
    const data = await ensureRatesForTarget(target);
    const row = rowsById(data).get(entry.id) || entry;
    setText('detail-value', `${formatAmount(row.best)} ${currencyLabel(target)}`);
    setText('detail-median', `${formatAmount(row.median)} ${currencyLabel(target)}`);
    setText('detail-volume', formatAmount(row.volume || 0));
    const detailChange = byId('detail-change');
    if (detailChange) {
      detailChange.textContent = formatChange(row.change);
      detailChange.className = Number(row.change) > 0 ? 'change-up' : Number(row.change) < 0 ? 'change-down' : '';
    }
    renderSparkline(row.sparkline || []);
    setText('detail-note', `${t('detailSourceNote')} ${t('source')}: ${data.source || '-'}.`);
  } catch (error) {
    setText('detail-note', error.message || String(error));
    renderSparkline([]);
  }
}

function openItemDetail(itemId) {
  state.selectedItemId = itemId;
  fillDetailTargetSelect();
  renderMarket();
  renderSelectedItemDetail();
}

function switchMainView(view) {
  state.mainView = ['signals', 'lots'].includes(view) ? view : 'market';
  document.querySelectorAll('.main-view-tab').forEach(button => {
    button.classList.toggle('active', button.dataset.mainTab === state.mainView);
  });
  document.querySelectorAll('[data-main-view]').forEach(element => {
    element.classList.toggle('view-hidden', element.dataset.mainView !== state.mainView);
  });
  if (state.mainView === 'signals' && state.activeAdviceTab === 'cross') loadCrossCurrencyDeals();
  if (state.mainView === 'lots') renderSellerLots();
}

// Signal rendering

function renderAdvice(advice) {
  const panel = byId('advice-panel');
  if (!panel) return;
  state.advice = advice || [];
  panel.classList.remove('d-none');
  renderTrendSignals();
  renderOperationSignals();
  renderCrossDeals();
  renderActiveTrades();
  switchAdviceTab(state.activeAdviceTab);
}

function currentSignalRows() {
  const categoryRates = state.rates[state.selectedCategory] || {};
  const rateRows = rowsById(categoryRates);
  return (state.categories[state.selectedCategory] || [])
    .map(entry => {
      const row = rateRows.get(entry.id);
      const change = Number(row?.change);
      const volume = Number(row?.volume || 0);
      const value = rateValue(row);
      if (!row || !Number.isFinite(change) || !value || volume < CROSS_MIN_VOLUME) return null;
      return { entry, row, change, volume, value, target: categoryRates.target || selectedTarget() };
    })
    .filter(Boolean);
}

function trendSignals(direction) {
  const rows = currentSignalRows().filter(item => direction === 'buy' ? item.change < 0 : item.change > 0);
  return rows.sort((left, right) => {
    const changeOrder = direction === 'buy' ? left.change - right.change : right.change - left.change;
    return changeOrder || right.volume - left.volume;
  }).slice(0, 30);
}

function renderTrendSignals() {
  renderTrendSignalList(byId('advice-list-buy'), trendSignals('buy'), 'buy');
  renderTrendSignalList(byId('advice-list-sell'), trendSignals('sell'), 'sell');
}

function renderTrendSignalList(list, signals, direction) {
  if (!list) return;
  list.innerHTML = '';
  if (!signals.length) {
    list.innerHTML = `<p class="text-secondary">${t(direction === 'buy' ? 'noBuySignals' : 'noSellSignals')}</p>`;
    return;
  }
  signals.forEach(item => {
    const card = document.createElement('article');
    card.className = `advice-card ${direction === 'buy' ? 'weak' : 'signal'}`;
    const badge = direction === 'buy' ? t('priceDrop') : t('priceRise');
    const action = direction === 'buy' ? t('buySignals') : t('sellSignals');
    renderAdviceCard(card, `
      <div class="advice-title-row"><span class="advice-badge">${badge}</span><strong>${itemTitleMarkup(entryName(item.entry), entryIcon(item.entry))}</strong></div>
      <p>${action}: ${formatAmount(item.value)} ${currencyLabel(item.target)} (${formatChange(item.change)})</p>
      <div class="deal-meta"><span>${t('volume')}: ${formatAmount(item.volume)}</span><span>${t('offers')}: ${formatAmount(item.row.offers || 0)}</span></div>
    `, miniSignalChart(item.row.sparkline || [], t('priceChartBasis'), item.value, item.change));
    list.appendChild(card);
  });
}

function renderOperationSignals() {
  const list = byId('advice-list-ops');
  if (!list) return;
  const maxSteps = Number(byId('chain-max-steps')?.value || 5);
  const operations = state.advice.filter(item => Number(item.path_steps || 1) <= maxSteps);
  if (operations.length) {
    renderAdviceList(list, operations, t('noAdvice'));
    return;
  }
  list.innerHTML = '';
  if (state.isLoadingActiveTrades) {
    list.innerHTML = loadingMarkup(t('operationsLoading'));
    return;
  }
  if (state.marketChains.length) {
    list.innerHTML = state.marketChains.map(renderMarketChain).join('');
    return;
  }
  if (state.activeTrades.length) {
    list.innerHTML = `<p class="text-secondary">${t('operationWatchHint')}</p>${state.activeTrades.slice(0, 10).map(renderActiveTradeOperation).join('')}`;
    return;
  }
  list.innerHTML = `<p class="text-secondary">${t('noMarketChains')}</p>`;
}

function renderActiveTradeOperation(item) {
  return `
    <article class="advice-card watch">
      <div class="advice-card-layout">
        <div class="advice-card-content">
          <div class="advice-title-row"><span class="advice-badge">${t('watchLabel')}</span><strong>${itemTitleMarkup(item.name, item.image)}</strong></div>
          <p>${t('buyFor')} ${formatAmount(item.buy.value)} ${currencyLabel(item.buy.target)} → ${t('sellFor')} ${formatAmount(item.sell.value)} ${currencyLabel(item.sell.target)}</p>
          <div class="deal-meta">
            <span>${t('spread')}: ${formatAmount(item.profit)} ${currencyLabel(selectedTarget())} (${formatChange(item.margin * 100)})</span>
            <span>${t('demandVolume')}: ${formatAmount(item.volume)}</span>
          </div>
        </div>
        ${miniSignalChart(item.sparkline || [], t('priceChartBasis'), item.sell.value)}
      </div>
    </article>
  `;
}

function renderAdviceList(list, advice, emptyText) {
  list.innerHTML = '';
  if (!advice || !advice.length) {
    list.innerHTML = `<p class="text-secondary">${emptyText}</p>`;
    return;
  }
  advice.forEach(item => {
    const card = document.createElement('article');
    const severity = item.severity || item.kind || 'watch';
    card.className = `advice-card ${severity}`;
    const title = state.lang === 'ru' ? item.title_ru : item.title_en;
    const sourceName = state.lang === 'ru' ? item.source_name_ru : item.source_name_en;
    const resultName = state.lang === 'ru' ? item.result_name_ru : item.result_name_en;
    const message = adviceMessage(item, sourceName, resultName);
    const titleMarkup = adviceTitleMarkup(item, sourceName, resultName);
    const basis = state.lang === 'ru' ? item.basis_ru : item.basis_en;
    renderAdviceCard(
      card,
      `<div class="advice-title-row"><span class="advice-badge">${title}</span><strong>${titleMarkup}</strong></div><p>${message}</p>`,
      miniSignalChart(item.result_sparkline || [], basis || t('resultChartBasis'), item.result_value),
    );
    list.appendChild(card);
  });
}

function adviceTitleMarkup(item, sourceName, resultName) {
  const sourceEntry = findAnyEntry(item.source);
  const resultEntry = findAnyEntry(item.result);
  if (sourceName && resultName) {
    return `
      <span class="advice-path">
        ${entryIcon(sourceEntry) ? `<img src="${entryIcon(sourceEntry)}" alt="">` : ''}
        <span>${sourceName}</span>
        <span class="advice-arrow">→</span>
        ${entryIcon(resultEntry) ? `<img src="${entryIcon(resultEntry)}" alt="">` : ''}
        <span>${resultName}</span>
      </span>
    `;
  }
  return itemTitleMarkup(sourceName || resultName || '', entryIcon(sourceEntry) || entryIcon(resultEntry));
}

function emotionRiskText(item) {
  if (state.lang !== 'ru') {
    if (item.severity === 'signal') return 'Volume is acceptable and margin is meaningful.';
    if (item.low_volume) return 'Low volume: check the order book manually before trading.';
    if (item.severity === 'weak') return 'Estimated profit exists, but check the order book and price freshness.';
    return 'Margin is too small or negative for action.';
  }
  if (item.severity === 'signal') return 'Объем достаточный, маржа заметная.';
  if (item.low_volume) return 'Объем низкий: проверь стакан вручную перед сделкой.';
  if (item.severity === 'weak') return 'Есть расчетная прибыль, но проверь стакан и свежесть цены.';
  return 'Маржа слишком мала или отрицательная для действия.';
}

function adviceMessage(item, sourceName, resultName) {
  if (item.kind === 'emotion_path' && sourceName && resultName) {
    const target = currencyLabel(item.target);
    if (state.lang === 'ru') {
      return `${item.input_count} × ${sourceName} → ${resultName} (${item.path_steps} шаг.): прибыль ${formatAmount(item.profit)} ${target}, маржа ${formatChange(item.margin * 100)}, минимальный объем ${formatAmount(item.min_volume)}. ${emotionRiskText(item)}`;
    }
    const stepLabel = item.path_steps === 1 ? 'step' : 'steps';
    return `${item.input_count} x ${sourceName} -> ${resultName} (${item.path_steps} ${stepLabel}): profit ${formatAmount(item.profit)} ${target}, margin ${formatChange(item.margin * 100)}, minimum volume ${formatAmount(item.min_volume)}. ${emotionRiskText(item)}`;
  }
  return state.lang === 'ru' ? item.message_ru : item.message_en;
}

function switchAdviceTab(tab) {
  state.activeAdviceTab = tab;
  document.querySelectorAll('.advice-tab').forEach(button => {
    button.classList.toggle('active', button.dataset.adviceTab === tab);
  });
  ['buy', 'sell', 'ops', 'active', 'cross'].forEach(name => {
    byId(`advice-list-${name}`)?.classList.toggle('d-none', name !== tab);
  });
  if (tab === 'ops') renderOperationSignals();
  if (tab === 'ops') loadActiveTrades();
  if (tab === 'active') loadActiveTrades();
  if (tab === 'cross') loadCrossCurrencyDeals();
}

function renderCrossDeals() {
  const list = byId('advice-list-cross');
  if (!list) return;
  list.innerHTML = '';
  if (state.isLoadingCrossDeals) {
    list.innerHTML = loadingMarkup(t('crossLoading'));
    return;
  }
  if (!state.crossDeals.length) {
    list.innerHTML = `<p class="text-secondary">${t('noCrossDeals')}</p>`;
    return;
  }
  if (!state.crossDeals.some(deal => deal.profitable)) {
    list.innerHTML = `<p class="text-secondary">${t('crossWatchHint')}</p>`;
  }
  state.crossDeals.forEach(deal => {
    const card = document.createElement('article');
    card.className = `advice-card ${deal.severity}`;
    const badge = deal.severity === 'signal' ? t('signalLabel') : deal.severity === 'weak' ? t('weakSignalLabel') : t('watchLabel');
    const entry = findAnyEntry(deal.id);
    const name = entry ? entryName(entry) : deal.name;
    renderAdviceCard(card, `
      <div class="advice-title-row"><span class="advice-badge">${badge}</span><strong>${itemTitleMarkup(name, entryIcon(entry))}</strong></div>
      <p>${t('buyFor')} ${formatAmount(deal.buyValue)} ${currencyLabel(deal.buyTarget)} ${state.lang === 'ru' ? '→' : '->'} ${t('sellFor')} ${formatAmount(deal.sellValue)} ${currencyLabel(deal.sellTarget)}</p>
      <div class="deal-meta"><span>${t('spread')}: ${formatAmount(deal.profit)} ${currencyLabel(deal.baseTarget)} (${formatChange(deal.margin * 100)})</span><span>${t('demandVolume')}: ${formatAmount(deal.volume)}</span></div>
    `, miniSignalChart(deal.sparkline || [], t('priceChartBasis'), deal.sellValue));
    list.appendChild(card);
  });
}

// Cross-currency and active trades

function rateValue(row) {
  const value = Number(row?.median ?? row?.best);
  return Number.isFinite(value) && value > 0 ? value : null;
}

function medianNumber(values) {
  const sorted = values.filter(Number.isFinite).sort((a, b) => a - b);
  if (!sorted.length) return null;
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

function inferConversionFactor(baseData, otherData) {
  const baseRows = rowsById(baseData);
  const ratios = [];
  (otherData?.rows || []).forEach(row => {
    const baseRow = baseRows.get(row.id);
    const baseValue = rateValue(baseRow);
    const otherValue = rateValue(row);
    if (baseValue && otherValue) ratios.push(baseValue / otherValue);
  });
  return medianNumber(ratios);
}

function crossDealsKey() {
  const league = byId('live-league')?.value || '';
  const status = byId('live-status')?.value || '';
  return `${league}|${state.selectedCategory}|${selectedTarget()}|${status}`;
}

function multiTargetDealsKey() {
  return `${crossDealsKey()}|${availableTargetIds().join(',')}`;
}

function datasetFactors(datasets, baseTarget) {
  const baseData = datasets.get(baseTarget);
  const factors = new Map([[baseTarget, 1]]);
  if (!baseData?.rows?.length) return factors;
  datasets.forEach((data, target) => {
    if (target === baseTarget) return;
    const factor = inferConversionFactor(baseData, data);
    if (factor) factors.set(target, factor);
  });
  return factors;
}

function tradeOptionsForEntry(entry, datasets, factors) {
  const options = [];
  datasets.forEach((data, target) => {
    const factor = factors.get(target);
    const row = rowsById(data).get(entry.id);
    const value = rateValue(row);
    const volume = Number(row?.volume || 0);
    if (factor && value && volume >= CROSS_MIN_VOLUME) {
      options.push({
        target,
        value,
        baseValue: value * factor,
        volume,
        row,
      });
    }
  });
  return options;
}

function buildCrossCurrencyDeals(datasets, baseTarget) {
  const baseData = datasets.get(baseTarget);
  if (!baseData?.rows?.length) return [];
  const factors = datasetFactors(datasets, baseTarget);
  const deals = [];
  (state.categories[state.selectedCategory] || []).forEach(entry => {
    const options = tradeOptionsForEntry(entry, datasets, factors);
    if (options.length < 2) return;
    options.sort((left, right) => left.baseValue - right.baseValue);
    const buy = options[0];
    const sell = options[options.length - 1];
    if (buy.target === sell.target) return;
    const profit = sell.baseValue - buy.baseValue;
    const margin = buy.baseValue ? profit / buy.baseValue : 0;
    const volume = Math.min(buy.volume, sell.volume);
    if (volume < CROSS_MIN_VOLUME) return;
    deals.push({
      id: entry.id,
      name: entryName(entry),
      buyTarget: buy.target,
      sellTarget: sell.target,
      buyValue: buy.value,
      sellValue: sell.value,
      baseTarget,
      profit,
      margin,
      volume,
      sparkline: (rowsById(baseData).get(entry.id) || {}).sparkline || [],
      profitable: profit > 0 && margin >= 0.005,
      severity: profit > 0 && margin >= 0.08 ? 'signal' : profit > 0 && margin >= 0.005 ? 'weak' : 'watch',
    });
  });
  return deals.sort((left, right) => {
    if (left.profitable !== right.profitable) return left.profitable ? -1 : 1;
    return right.margin - left.margin || right.profit - left.profit;
  }).slice(0, 30);
}

function buildActiveTradeTable(datasets, baseTarget) {
  const baseData = datasets.get(baseTarget);
  if (!baseData?.rows?.length) return [];
  const factors = datasetFactors(datasets, baseTarget);
  return (state.categories[state.selectedCategory] || [])
    .map(entry => {
      const options = tradeOptionsForEntry(entry, datasets, factors);
      if (!options.length) return null;
      options.sort((left, right) => left.baseValue - right.baseValue);
      const buy = options[0];
      const sell = options[options.length - 1];
      const profit = sell.baseValue - buy.baseValue;
      const margin = buy.baseValue ? profit / buy.baseValue : 0;
      const volume = Math.min(...options.map(option => option.volume));
      const baseRow = rowsById(baseData).get(entry.id);
      const marketRow = baseRow || sell.row || buy.row;
      const activity = Math.max(...options.map(option => option.volume));
      return {
        id: entry.id,
        entry,
        name: entryName(entry),
        image: entryIcon(entry),
        activity,
        volume,
        buy,
        sell,
        profit,
        margin,
        marketCurrency: marketRow?.max_volume_currency || '',
        marketRate: Number(marketRow?.max_volume_rate || 0),
        prices: options.sort((left, right) => availableTargetIds().indexOf(left.target) - availableTargetIds().indexOf(right.target)),
        sparkline: baseRow?.sparkline || sell.row?.sparkline || [],
      };
    })
    .filter(Boolean)
    .sort((left, right) => right.activity - left.activity)
    .slice(0, 20);
}

function renderMarketBasis(item) {
  if (!item.marketCurrency) return '-';
  return currencyMarkup(item.marketCurrency);
}

function buildMarketChains(activeTrades, baseTarget, maxSteps) {
  if (!activeTrades.length) return [];
  const profitable = activeTrades
    .filter(item => item.profit > 0 && item.margin >= 0.005 && item.buy.target !== item.sell.target)
    .sort((left, right) => right.margin - left.margin || right.profit - left.profit)
    .slice(0, 12);
  const chains = [];
  for (const start of profitable) {
    let amount = start.buy.baseValue;
    const steps = [];
    let minVolume = Infinity;
    for (let index = 0; index < Math.max(1, maxSteps); index += 1) {
      const candidates = profitable
        .filter(item => !steps.some(step => step.id === item.id))
        .map(item => {
          const nextAmount = amount * (item.sell.baseValue / item.buy.baseValue);
          return { item, nextAmount, gain: nextAmount - amount };
        })
        .sort((left, right) => right.gain - left.gain);
      const next = candidates[0];
      if (!next || next.gain <= 0) break;
      steps.push(next.item);
      amount = next.nextAmount;
      minVolume = Math.min(minVolume, next.item.volume);
    }
    if (!steps.length) continue;
    const initial = steps[0].buy.baseValue;
    const profit = amount - initial;
    const margin = initial ? profit / initial : 0;
    if (profit <= 0) continue;
    chains.push({
      steps,
      startValue: initial,
      finishValue: amount,
      profit,
      margin,
      baseTarget,
      minVolume: Number.isFinite(minVolume) ? minVolume : 0,
    });
  }
  return chains
    .sort((left, right) => right.margin - left.margin || right.profit - left.profit)
    .slice(0, 10);
}

function renderActiveTrades() {
  const panel = byId('advice-list-active');
  if (!panel) return;
  if (state.isLoadingActiveTrades) {
    panel.innerHTML = loadingMarkup(t('activeTradesLoading'));
    return;
  }
  if (!state.activeTrades.length) {
    panel.innerHTML = `<p class="text-secondary">${t('noActiveTrades')}</p>`;
    return;
  }
  panel.innerHTML = `
    <p class="text-secondary">${t('activeTradesHint')}</p>
    <div class="active-trades-wrap">
      <table class="active-trades-table">
        <thead>
          <tr>
            <th>${t('name')}</th>
            <th>${t('activeScore')}</th>
            <th>${t('bestBuy')}</th>
            <th>${t('bestSell')}</th>
            <th>${t('tradedFor')}</th>
            <th>${t('profit')}</th>
            <th>${t('pricesByCurrency')}</th>
          </tr>
        </thead>
        <tbody>
          ${state.activeTrades.map(item => `
            <tr>
              <td>${itemTitleMarkup(item.name, item.image)}</td>
              <td>${formatAmount(item.activity)}</td>
              <td>${formatAmount(item.buy.value)} ${currencyLabel(item.buy.target)}</td>
              <td>${formatAmount(item.sell.value)} ${currencyLabel(item.sell.target)}</td>
              <td>${renderMarketBasis(item)}</td>
              <td class="${item.profit > 0 ? 'change-up' : ''}">${formatAmount(item.profit)} ${currencyLabel(selectedTarget())} (${formatChange(item.margin * 100)})</td>
              <td>${item.prices.map(price => `${formatAmount(price.value)} ${currencyLabel(price.target)}`).join(' / ')}</td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    </div>
    <h3 class="signals-subtitle">${t('marketChains')}</h3>
    <div class="market-chain-list">
      ${state.marketChains.length ? state.marketChains.map(renderMarketChain).join('') : `<p class="text-secondary">${t('noMarketChains')}</p>`}
    </div>
  `;
}

function renderMarketChain(chain) {
  const route = chain.steps.map(step => itemTitleMarkup(step.name, step.image)).join('<span class="advice-arrow">→</span>');
  const stepRows = chain.steps.map((step, index) => `
    <div class="chain-step">
      <strong>${t('step')} ${index + 1}</strong>
      <span>${t('buyFor')} ${formatAmount(step.buy.value)} ${currencyLabel(step.buy.target)} → ${t('sellFor')} ${formatAmount(step.sell.value)} ${currencyLabel(step.sell.target)}</span>
    </div>
  `).join('');
  return `
    <article class="market-chain-card">
      <div class="advice-title-row"><span class="advice-badge">${t('profit')}</span><strong>${route}</strong></div>
      <div class="deal-meta">
        <span>${t('start')}: ${formatAmount(chain.startValue)} ${currencyLabel(chain.baseTarget)}</span>
        <span>${t('finish')}: ${formatAmount(chain.finishValue)} ${currencyLabel(chain.baseTarget)}</span>
        <span>${t('profit')}: ${formatAmount(chain.profit)} ${currencyLabel(chain.baseTarget)} (${formatChange(chain.margin * 100)})</span>
        <span>${t('minVolume')}: ${formatAmount(chain.minVolume)}</span>
      </div>
      <div class="chain-steps">${stepRows}</div>
    </article>
  `;
}

async function loadActiveTrades() {
  const key = multiTargetDealsKey();
  if (state.activeTradesKey === key || state.isLoadingActiveTrades) {
    renderActiveTrades();
    if (state.activeAdviceTab === 'ops') renderOperationSignals();
    return;
  }
  const targets = availableTargetIds();
  if (targets.length < 2) {
    state.activeTrades = [];
    state.marketChains = [];
    state.activeTradesKey = key;
    renderActiveTrades();
    if (state.activeAdviceTab === 'ops') renderOperationSignals();
    return;
  }
  state.isLoadingActiveTrades = true;
  renderActiveTrades();
  if (state.activeAdviceTab === 'ops') renderOperationSignals();
  try {
    const datasets = new Map();
    for (const target of targets) {
      datasets.set(target, await ensureRatesForTarget(target));
    }
    state.activeTrades = buildActiveTradeTable(datasets, selectedTarget());
    const maxSteps = Number(byId('chain-max-steps')?.value || 5);
    state.marketChains = buildMarketChains(state.activeTrades, selectedTarget(), maxSteps);
    state.activeTradesKey = key;
  } catch {
    state.activeTrades = [];
    state.marketChains = [];
    state.activeTradesKey = key;
  } finally {
    state.isLoadingActiveTrades = false;
    renderActiveTrades();
    if (state.activeAdviceTab === 'ops') renderOperationSignals();
  }
}

async function loadCrossCurrencyDeals() {
  const key = crossDealsKey();
  if (state.crossDealsKey === key || state.isLoadingCrossDeals) {
    renderCrossDeals();
    return;
  }
  const targets = availableTargetIds();
  if (targets.length < 2) {
    state.crossDeals = [];
    state.crossDealsKey = key;
    renderCrossDeals();
    return;
  }
  state.isLoadingCrossDeals = true;
  renderCrossDeals();
  try {
    const datasets = new Map();
    for (const target of targets) {
      datasets.set(target, await ensureRatesForTarget(target));
    }
    state.crossDeals = buildCrossCurrencyDeals(datasets, selectedTarget());
    state.crossDealsKey = key;
  } catch {
    state.crossDeals = [];
    state.crossDealsKey = key;
  } finally {
    state.isLoadingCrossDeals = false;
    renderCrossDeals();
  }
}

// History and data loading

async function renderHistory() {
  const list = byId('history-list');
  if (!list) return;
  try {
    const response = await fetch('/api/trade/history?limit=12');
    const data = await response.json();
    const history = data.history || [];
    if (!history.length) {
      list.innerHTML = `<span class="text-secondary">${t('noHistory')}</span>`;
      return;
    }
    list.innerHTML = history.map(item => {
      const date = new Date(item.created_ts * 1000).toLocaleString(state.lang === 'ru' ? 'ru-RU' : 'en-US');
      return `<div class="history-item"><strong>${item.league}</strong><span>${item.category} / ${item.target}</span><time>${date}</time></div>`;
    }).join('');
  } catch {
    list.innerHTML = `<span class="text-secondary">${t('noHistory')}</span>`;
  }
}

function applyRatesData(data) {
  state.rates[state.selectedCategory] = data;
  setText('rate-source', data.source || '-');
  renderMarket();
  renderAdvice(data.advice || []);
  renderSelectedItemDetail();
  renderHistory();
}

async function loadLatestCachedRates() {
  const league = byId('live-league')?.value;
  const target = byId('target-currency')?.value;
  const status = byId('live-status')?.value;
  if (!league || !target || !status) return false;
  const category = state.selectedCategory;
  const params = new URLSearchParams({ league, category, target, status });
  try {
    const response = await fetch(`/api/trade/category-rates/latest?${params.toString()}`);
    const data = await response.json();
    if (!response.ok || data.error) throw new Error(data.error || t('cacheLoadError'));
    if (category !== state.selectedCategory || !data.cached || !Array.isArray(data.rows) || !data.rows.length) {
      return false;
    }
    applyRatesData(data);
    return true;
  } catch {
    return false;
  }
}

function scheduleAutoRefresh() {
  if (state.autoRefreshTimer) {
    clearInterval(state.autoRefreshTimer);
    state.autoRefreshTimer = null;
  }
  if (!state.autoRefreshMs) return;
  state.autoRefreshTimer = setInterval(() => {
    if (!document.hidden) {
      refreshRates({ silent: true });
    }
  }, state.autoRefreshMs);
}

async function refreshRates(options = {}) {
  if (state.isRefreshing) return;
  state.isRefreshing = true;
  const league = byId('live-league').value;
  const target = byId('target-currency').value;
  const status = byId('live-status').value;
  const statusEl = byId('rate-status');
  setLiveError('');
  if (!options.silent) setLoadingStatus(statusEl, t('updateLong'));
  const params = new URLSearchParams({ league, category: state.selectedCategory, target, status });
  try {
    const response = await fetch(`/api/trade/category-rates?${params.toString()}`);
    const data = await response.json();
    if (!response.ok || data.error) throw new Error(data.error || t('tradeError'));
    const stamp = new Date(data.created_ts * 1000).toLocaleTimeString(state.lang === 'ru' ? 'ru-RU' : 'en-US');
    setText('last-snapshot', data.cached ? `${stamp} ${t('cacheLabel')}` : stamp);
    applyRatesData(data);
    statusEl.textContent = data.cached ? t('cacheLabel') : '';
  } catch (error) {
    setLiveError(error.message || String(error));
    statusEl.textContent = '';
  } finally {
    state.isRefreshing = false;
  }
}

async function initLiveTrade() {
  const leagueSelect = byId('live-league');
  if (!leagueSelect) return;
  try {
    setLiveError('');
    byId('lang-ru').addEventListener('click', () => {
      state.lang = 'ru';
      localStorage.setItem('poe2-lang', state.lang);
      applyLanguage();
    });
    byId('lang-en').addEventListener('click', () => {
      state.lang = 'en';
      localStorage.setItem('poe2-lang', state.lang);
      applyLanguage();
    });
    const [leaguesResponse, staticResponse] = await Promise.all([
      fetch('/api/trade/leagues'),
      fetch('/api/trade/static'),
    ]);
    const leaguesData = await leaguesResponse.json();
    const staticData = await staticResponse.json();
    if (!leaguesResponse.ok || leaguesData.error) throw new Error(leaguesData.error || t('leaguesLoadError'));
    if (!staticResponse.ok || staticData.error) throw new Error(staticData.error || t('staticLoadError'));
    state.leagues = leaguesData.leagues || [];
    state.categories = staticData.categories || {};
    state.categoryMeta = staticData.category_meta || [];
    if (!state.categories[state.selectedCategory]) state.selectedCategory = state.categoryMeta[0]?.id || 'Currency';

    fillSelect(leagueSelect, state.leagues.map(league => ({ id: league.id, text: league.text })), state.leagues[0]?.id);
    fillStatusSelect();
    fillTargetCurrencySelect();
    fillAutoRefreshSelect();
    fillDetailTargetSelect();

    setText('category-title', categoryName(state.categoryMeta.find(c => c.id === state.selectedCategory) || { label: state.selectedCategory }));
    byId('refresh-rates').addEventListener('click', refreshRates);
    byId('refresh-static').addEventListener('click', () => window.location.reload());
    byId('market-search').addEventListener('input', renderMarket);
    byId('search-lots')?.addEventListener('click', searchSellerLots);
    ['lot-seller', 'lot-query'].forEach(id => {
      byId(id)?.addEventListener('keydown', event => {
        if (event.key === 'Enter') searchSellerLots();
      });
    });
    byId('detail-target-currency').addEventListener('change', event => {
      state.detailTarget = event.target.value;
      renderSelectedItemDetail();
    });
    document.querySelectorAll('[data-advice-tab]').forEach(button => {
      button.addEventListener('click', () => switchAdviceTab(button.dataset.adviceTab));
    });
    document.querySelectorAll('[data-main-tab]').forEach(button => {
      button.addEventListener('click', () => switchMainView(button.dataset.mainTab));
    });
    byId('chain-max-steps')?.addEventListener('change', () => {
      renderOperationSignals();
      if (state.activeAdviceTab === 'active') {
        state.marketChains = buildMarketChains(state.activeTrades, selectedTarget(), Number(byId('chain-max-steps')?.value || 5));
        renderActiveTrades();
      } else {
        switchAdviceTab('ops');
      }
    });
    byId('auto-refresh-interval').addEventListener('change', event => {
      state.autoRefreshMs = Number(event.target.value || 0);
      localStorage.setItem('poe2-auto-refresh-ms', String(state.autoRefreshMs));
      scheduleAutoRefresh();
    });
    ['live-league', 'target-currency', 'live-status'].forEach(id => {
      byId(id).addEventListener('change', () => {
        state.rates = {};
        state.detailRates = {};
        state.crossDeals = [];
        state.crossDealsKey = '';
        state.activeTrades = [];
        state.marketChains = [];
        state.activeTradesKey = '';
        state.sellerLots = null;
        setText('last-snapshot', '-');
        setText('rate-source', '-');
        renderTargetCurrencyInfo();
        renderMarket();
        renderAdvice([]);
        renderSelectedItemDetail();
        loadLatestCachedRates();
      });
    });
    document.querySelectorAll('[data-sort-key]').forEach(button => {
      button.addEventListener('click', () => {
        const key = button.dataset.sortKey;
        if (state.sort.key === key) {
          state.sort.direction = state.sort.direction === 'asc' ? 'desc' : 'asc';
        } else {
          state.sort.key = key;
          state.sort.direction = key === 'name' || key === 'id' ? 'asc' : 'desc';
        }
        renderMarket();
      });
    });
    applyLanguage();
    loadLatestCachedRates();
    scheduleAutoRefresh();
    renderHistory();
  } catch (error) {
    setLiveError(error.message || String(error));
  }
}

window.initLiveTrade = initLiveTrade;
