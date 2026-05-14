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
  detailChartMetric: 'price',
  chartDays: Number(localStorage.getItem('poe2-chart-days') || 7),
  detailDemandCache: {},
  detailSeriesCache: {},
  accountChartSeriesCache: {},
  accountChartSeriesLoading: {},
  maxChartDaysAvailable: 7,
  rates: {},
  detailRates: {},
  advice: [],
  mainView: 'market',
  activeAdviceTab: 'market',
  crossDeals: [],
  crossDealsKey: '',
  isLoadingCrossDeals: false,
  activeTrades: [],
  marketChains: [],
  activeTradesKey: '',
  isLoadingActiveTrades: false,
  historyTrends: [],
  historyTrendsKey: '',
  isLoadingHistoryTrends: false,
  sellerLots: null,
  sellerLotsCache: {},
  sellerLotMarketCache: {},
  isLoadingSellerLots: false,
  sellerLotsAbortController: null,
  sellerLotsRequestId: 0,
  account: {
    authenticated: false,
    user: null,
    pins: [],
    trades: [],
    notifications: [],
    telegramConfigured: false,
    benchmarkCurrency: localStorage.getItem('poe2-account-benchmark') || 'divine',
    benchmarkRates: {},
  },
  isAccountLoading: false,
  autoRefreshMs: Number(localStorage.getItem('poe2-auto-refresh-ms') ?? 60000),
  autoRefreshTimer: null,
  isRefreshing: false,
  sort: { key: 'name', direction: 'asc' },
};

const preferredTargets = ['exalted', 'divine', 'chaos'];
const CROSS_MIN_VOLUME = 10;
const MARKET_SIGNAL_MIN_VOLUME = 10;
const MARKET_SIGNAL_MEDIUM_VOLUME = 50;
const MARKET_SIGNAL_NOTABLE_CHANGE = 8;
const MARKET_SIGNAL_STRONG_CHANGE = 25;
const MARKET_SIGNAL_TOP_CANDIDATES = 8;

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
  fillBenchmarkCurrencySelect();
  fillAutoRefreshSelect();
  fillChartDaysSelects();
  renderTargetCurrencyInfo();
  renderCategories();
  renderMarket();
  renderAdvice(state.advice);
  renderSellerLots();
  renderCabinet();
  renderDetailAccountStatus();
  switchMainView(state.mainView);
  fillDetailTargetSelect();
  renderSelectedItemDetail();
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

function formatChartAmount(value) {
  if (value === null || value === undefined || value === '') return '-';
  const number = Number(value);
  if (!Number.isFinite(number)) return String(value);
  if (Math.abs(number) >= 1000) {
    return Intl.NumberFormat(state.lang === 'ru' ? 'ru-RU' : 'en-US', { maximumFractionDigits: 1, notation: 'compact' }).format(number);
  }
  if (Number.isInteger(number)) return String(number);
  const rounded = number.toFixed(1).replace(/\.0$/, '');
  return rounded === '0' || rounded === '-0' ? formatAmount(number) : rounded;
}

function chartDayOptions() {
  const maxDays = Math.max(7, Number(state.maxChartDaysAvailable || 7));
  return [3, 7, 14, 30]
    .filter(days => days <= 7 || maxDays >= days)
    .map(days => ({ id: String(days), text: `${days}` }));
}

function selectedChartDays() {
  const allowed = chartDayOptions().map(option => Number(option.id));
  return allowed.includes(state.chartDays) ? state.chartDays : Math.max(...allowed.filter(days => days <= 7));
}

function chartBasisText(days) {
  return state.lang === 'ru' ? `цена за ${days} д.` : `${days}-day price`;
}

function chartPeriodLabel(days, available) {
  const visible = Math.min(days, available || days);
  if (state.lang === 'ru') {
    return visible === days ? `${days} д.` : `доступно ${visible} д.`;
  }
  return visible === days ? `${days}d` : `${visible}d available`;
}

function fillChartDaysSelects() {
  const selected = selectedChartDays();
  if (state.chartDays !== selected) {
    state.chartDays = selected;
    localStorage.setItem('poe2-chart-days', String(state.chartDays));
  }
  document.querySelectorAll('[data-chart-days-select]').forEach(select => {
    fillSelect(select, chartDayOptions(), String(selected));
  });
}

function updateChartDays(value) {
  const days = Number(value);
  const allowed = chartDayOptions().map(option => Number(option.id));
  state.chartDays = allowed.includes(days) ? days : selectedChartDays();
  localStorage.setItem('poe2-chart-days', String(state.chartDays));
  fillChartDaysSelects();
  renderCabinet();
  queueAccountChartSeriesLoad();
  renderSelectedItemDetail();
}

function limitedChartValues(values) {
  const days = selectedChartDays();
  return (values || []).slice(-days);
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

// Account, pins, and trade journal

function setAccountStatus(message) {
  ['account-status', 'auth-status'].forEach(id => {
    const element = byId(id);
    if (element) element.textContent = message || '';
  });
}

function setAuthStatusHtml(html) {
  const element = byId('auth-status');
  if (element) element.innerHTML = html || '';
}

function setDetailAccountStatus(message) {
  const element = byId('detail-account-status');
  if (element) element.textContent = message || '';
}

function renderDetailAccountStatus() {
  if (!byId('detail-account-status')) return;
  setDetailAccountStatus(state.account.authenticated ? '' : t('loginToUseCabinet'));
}

async function fetchAccountJson(url, options = {}) {
  const response = await fetch(url, {
    credentials: 'same-origin',
    ...options,
    headers: {
      ...(options.headers || {}),
    },
  });
  let data = {};
  try {
    data = await response.json();
  } catch {
    data = {};
  }
  if (!response.ok || data.error) {
    const localized = data.error_key && t(data.error_key) !== data.error_key ? t(data.error_key) : '';
    throw new Error(localized || data.error || data.detail || t('accountRequestError'));
  }
  return data;
}

function sendAccountJson(url, body, method = 'POST') {
  return fetchAccountJson(url, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {}),
  });
}

function accountItemName(item) {
  return state.lang === 'ru' ? (item.item_name_ru || item.item_name) : item.item_name;
}

function selectedItemPayload() {
  if (!state.selectedItemId) return null;
  const entry = findEntry(state.selectedItemId);
  if (!entry) return null;
  const categoryRates = state.rates[state.selectedCategory] || {};
  const row = rowsById(categoryRates).get(entry.id) || {};
  const target = categoryRates.target || selectedTarget();
  return {
    league: byId('live-league')?.value || '',
    category: state.selectedCategory,
    item_id: entry.id,
    item_name: entry.text || entryName(entry),
    item_name_ru: entry.text_ru || entry.text || entryName(entry),
    icon_url: entry.image || '',
    target_currency: target,
    last_price: rateValue(row),
    last_source: categoryRates.source || '',
  };
}

async function loadAccountCollections() {
  if (!state.account.authenticated) return;
  const [pinsData, tradesData] = await Promise.all([
    fetchAccountJson('/api/account/pins'),
    fetchAccountJson('/api/account/trades'),
  ]);
  state.account.pins = pinsData.pins || [];
  state.account.trades = tradesData.trades || [];
  const notificationsData = await fetchAccountJson('/api/account/notifications');
  state.account.notifications = notificationsData.notifications || [];
  state.account.telegramConfigured = Boolean(notificationsData.telegram_configured);
}

async function loadAccountState() {
  state.isAccountLoading = true;
  try {
    const data = await fetchAccountJson('/api/auth/me');
    state.account.authenticated = Boolean(data.authenticated);
    state.account.user = data.user || null;
    state.account.pins = [];
    state.account.trades = [];
    state.account.notifications = [];
    state.account.telegramConfigured = false;
    if (state.account.authenticated) {
      await loadAccountCollections();
    }
  } catch (error) {
    state.account.authenticated = false;
    state.account.user = null;
    state.account.pins = [];
    state.account.trades = [];
    state.account.notifications = [];
    state.account.telegramConfigured = false;
    setAccountStatus(error.message || String(error));
  } finally {
    state.isAccountLoading = false;
    renderCabinet();
    renderDetailAccountStatus();
  }
}

async function refreshAccountData(message = '') {
  if (!state.account.authenticated) return;
  await loadAccountCollections();
  renderCabinet();
  renderDetailAccountStatus();
  if (message) setAccountStatus(message);
}

async function handleLogin(event) {
  event.preventDefault();
  setAccountStatus('');
  try {
    const data = await sendAccountJson('/api/auth/login', {
      username: byId('login-username')?.value || '',
      password: byId('login-password')?.value || '',
    });
    state.account.authenticated = Boolean(data.authenticated);
    state.account.user = data.user || null;
    await refreshAccountData(t('loginDone'));
  } catch (error) {
    setAccountStatus(error.message || String(error));
  }
}

async function handleRegister(event) {
  event.preventDefault();
  setAccountStatus('');
  try {
    const data = await sendAccountJson('/api/auth/register', {
      username: byId('register-username')?.value || '',
      email: byId('register-email')?.value || '',
      display_name: byId('register-display-name')?.value || '',
      password: byId('register-password')?.value || '',
    });
    state.account.authenticated = Boolean(data.authenticated);
    state.account.user = data.user || null;
    if (data.verification_required) {
      renderCabinet();
      renderVerificationStatus(data, t('registerCheckEmail'));
      return;
    }
    await refreshAccountData(t('registerDone'));
  } catch (error) {
    setAccountStatus(error.message || String(error));
  }
}

async function resendVerification() {
  setAccountStatus('');
  try {
    const data = await sendAccountJson('/api/auth/resend-verification', {
      username: byId('login-username')?.value || '',
      password: byId('login-password')?.value || '',
    });
    if (data.verification_required) {
      renderVerificationStatus(data, t('verificationResent'));
    } else {
      setAccountStatus(t('emailAlreadyVerified'));
    }
  } catch (error) {
    setAccountStatus(error.message || String(error));
  }
}

function renderVerificationStatus(data, message) {
  const email = escapeHtml(data.email || '');
  if (data.dev_verification_url) {
    setAuthStatusHtml(`${escapeHtml(message)} ${email}<br><a href="${escapeHtml(data.dev_verification_url)}">${t('devVerificationLink')}</a>`);
    return;
  }
  setAccountStatus(`${message} ${email}`);
}

function showVerificationQueryStatus() {
  const params = new URLSearchParams(window.location.search);
  if (params.get('verified') === '1') {
    switchMainView('cabinet');
    setAccountStatus(t('emailVerified'));
  } else if (params.get('verify') === 'invalid') {
    switchMainView('cabinet');
    setAccountStatus(t('emailVerificationInvalid'));
  }
}

async function logoutAccount() {
  try {
    await fetchAccountJson('/api/auth/logout', { method: 'POST' });
  } finally {
    state.account.authenticated = false;
    state.account.user = null;
    state.account.pins = [];
    state.account.trades = [];
    state.account.notifications = [];
    state.account.telegramConfigured = false;
    renderCabinet();
    renderDetailAccountStatus();
  }
}

function matchingPin(payload) {
  return state.account.pins.find(pin => (
    pin.league === payload.league
    && pin.category === payload.category
    && pin.item_id === payload.item_id
  ));
}

async function pinSelectedPosition() {
  if (!state.account.authenticated) {
    switchMainView('cabinet');
    setAccountStatus(t('loginRequiredForPin'));
    return;
  }
  const payload = selectedItemPayload();
  if (!payload) {
    setDetailAccountStatus(t('selectItemFirst'));
    return;
  }
  try {
    await sendAccountJson('/api/account/pins', payload);
    await refreshAccountData(t('pinSaved'));
    setDetailAccountStatus(t('pinSaved'));
  } catch (error) {
    setDetailAccountStatus(error.message || String(error));
  }
}

async function accountBenchmarkPrice(targetCurrency, benchmarkCurrency, leagueOverride = '') {
  if (!targetCurrency || !benchmarkCurrency) return null;
  if (targetCurrency === benchmarkCurrency) return 1;
  const league = leagueOverride || byId('live-league')?.value || '';
  const status = byId('live-status')?.value || 'any';
  const key = `${league}|${targetCurrency}|${benchmarkCurrency}|${status}`;
  if (Object.prototype.hasOwnProperty.call(state.account.benchmarkRates, key)) {
    return state.account.benchmarkRates[key];
  }
  const params = new URLSearchParams({ league, category: 'Currency', target: targetCurrency, status });
  try {
    const response = await fetch(`/api/trade/category-rates?${params.toString()}`);
    const data = await response.json();
    if (!response.ok || data.error) throw new Error(data.error || t('tradeError'));
    const price = rateValue(rowsById(data).get(benchmarkCurrency));
    state.account.benchmarkRates[key] = price;
    return price;
  } catch {
    state.account.benchmarkRates[key] = null;
    return null;
  }
}

async function withEntryBenchmark(payload) {
  const benchmarkCurrency = payload.benchmark_currency || state.account.benchmarkCurrency || 'divine';
  const entryBenchmarkPrice = await accountBenchmarkPrice(payload.entry_currency, benchmarkCurrency, payload.league);
  return {
    ...payload,
    benchmark_currency: benchmarkCurrency,
    ...(entryBenchmarkPrice ? { entry_benchmark_price: entryBenchmarkPrice } : {}),
  };
}

async function createTradeFromPayload(payload, message) {
  if (!state.account.authenticated) {
    switchMainView('cabinet');
    setAccountStatus(t('loginRequiredForTrade'));
    return;
  }
  if (!payload.entry_price || payload.entry_price <= 0) {
    setAccountStatus(t('entryPriceRequired'));
    setDetailAccountStatus(t('entryPriceRequired'));
    return;
  }
  try {
    await sendAccountJson('/api/account/trades', await withEntryBenchmark(payload));
    await refreshAccountData(message);
    setDetailAccountStatus(message);
  } catch (error) {
    setAccountStatus(error.message || String(error));
    setDetailAccountStatus(error.message || String(error));
  }
}

async function markSelectedEntry() {
  const payload = selectedItemPayload();
  if (!payload) {
    setDetailAccountStatus(t('selectItemFirst'));
    return;
  }
  const pin = matchingPin(payload);
  await createTradeFromPayload({
    ...payload,
    pin_id: pin?.id,
    quantity: 1,
    entry_price: payload.last_price,
    entry_currency: payload.target_currency,
    benchmark_currency: state.account.benchmarkCurrency || 'divine',
  }, t('tradeOpened'));
}

async function startTradeFromPin(pinId) {
  const pin = state.account.pins.find(item => item.id === pinId);
  if (!pin) return;
  const price = Number(document.querySelector(`[data-pin-entry-price="${pinId}"]`)?.value || pin.last_price || 0);
  const quantity = Number(document.querySelector(`[data-pin-quantity="${pinId}"]`)?.value || 1);
  await createTradeFromPayload({
    pin_id: pin.id,
    league: pin.league,
    category: pin.category,
    item_id: pin.item_id,
    item_name: pin.item_name,
    item_name_ru: pin.item_name_ru,
    icon_url: pin.icon_url,
    quantity,
    entry_price: price,
    entry_currency: pin.target_currency,
    benchmark_currency: state.account.benchmarkCurrency || 'divine',
  }, t('tradeOpened'));
}

async function closeTrade(tradeId) {
  const trade = state.account.trades.find(item => item.id === tradeId);
  if (!trade) return;
  const exitPrice = Number(document.querySelector(`[data-trade-exit-price="${tradeId}"]`)?.value || 0);
  if (!exitPrice || exitPrice <= 0) {
    setAccountStatus(t('exitPriceRequired'));
    return;
  }
  try {
    const exitBenchmarkPrice = await accountBenchmarkPrice(trade.entry_currency, trade.benchmark_currency || state.account.benchmarkCurrency || 'divine', trade.league);
    await sendAccountJson(`/api/account/trades/${tradeId}`, {
      exit_price: exitPrice,
      exit_currency: trade.entry_currency,
      ...(exitBenchmarkPrice ? { exit_benchmark_price: exitBenchmarkPrice } : {}),
    }, 'PATCH');
    await refreshAccountData(t('tradeClosed'));
  } catch (error) {
    setAccountStatus(error.message || String(error));
  }
}

async function deletePin(pinId) {
  try {
    await fetchAccountJson(`/api/account/pins/${pinId}`, { method: 'DELETE' });
    await refreshAccountData(t('pinDeleted'));
  } catch (error) {
    setAccountStatus(error.message || String(error));
  }
}

async function deleteTrade(tradeId) {
  try {
    await fetchAccountJson(`/api/account/trades/${tradeId}`, { method: 'DELETE' });
    await refreshAccountData(t('tradeDeleted'));
  } catch (error) {
    setAccountStatus(error.message || String(error));
  }
}

function notificationEventOptions() {
  return [
    { id: 'price_above', text: t('notificationPriceAbove') },
    { id: 'price_below', text: t('notificationPriceBelow') },
    { id: 'change_pct', text: t('notificationChangePct') },
    { id: 'any_update', text: t('notificationAnyUpdate') },
  ];
}

function notificationEventLabel(eventType) {
  return (notificationEventOptions().find(item => item.id === eventType) || {}).text || eventType;
}

function fillNotificationControls() {
  const pinSelect = byId('notification-pin');
  const eventSelect = byId('notification-event');
  if (pinSelect) {
    fillSelect(
      pinSelect,
      state.account.pins.map(pin => ({ id: String(pin.id), text: accountItemName(pin) })),
      pinSelect.value || String(state.account.pins[0]?.id || ''),
    );
  }
  if (eventSelect) {
    fillSelect(eventSelect, notificationEventOptions(), eventSelect.value || 'price_above');
  }
}

async function createNotification(event) {
  event.preventDefault();
  if (!state.account.authenticated) return;
  const eventType = byId('notification-event')?.value || 'price_above';
  try {
    await sendAccountJson('/api/account/notifications', {
      pin_id: byId('notification-pin')?.value || '',
      event_type: eventType,
      threshold_value: eventType === 'any_update' ? null : byId('notification-threshold')?.value || '',
      chat_id: byId('notification-chat-id')?.value || '',
    });
    await refreshAccountData(t('notificationCreated'));
  } catch (error) {
    setAccountStatus(error.message || String(error));
  }
}

async function deleteNotification(ruleId) {
  try {
    await fetchAccountJson(`/api/account/notifications/${ruleId}`, { method: 'DELETE' });
    await refreshAccountData(t('notificationDeleted'));
  } catch (error) {
    setAccountStatus(error.message || String(error));
  }
}

async function toggleNotification(ruleId) {
  const rule = state.account.notifications.find(item => item.id === ruleId);
  if (!rule) return;
  try {
    await sendAccountJson(`/api/account/notifications/${ruleId}`, { enabled: !rule.enabled }, 'PATCH');
    await refreshAccountData(t('notificationUpdated'));
  } catch (error) {
    setAccountStatus(error.message || String(error));
  }
}

async function testNotification(ruleId) {
  try {
    await fetchAccountJson(`/api/account/notifications/${ruleId}/test`, { method: 'POST' });
    await refreshAccountData(t('notificationTestSent'));
  } catch (error) {
    setAccountStatus(error.message || String(error));
  }
}

function bindAccountEvents() {
  byId('login-form')?.addEventListener('submit', handleLogin);
  byId('register-form')?.addEventListener('submit', handleRegister);
  byId('resend-verification')?.addEventListener('click', resendVerification);
  byId('logout-button')?.addEventListener('click', logoutAccount);
  byId('pin-selected')?.addEventListener('click', pinSelectedPosition);
  byId('entry-selected')?.addEventListener('click', markSelectedEntry);
  byId('benchmark-currency')?.addEventListener('change', event => {
    state.account.benchmarkCurrency = event.target.value || defaultTarget();
    localStorage.setItem('poe2-account-benchmark', state.account.benchmarkCurrency);
    renderCabinet();
  });
  byId('notification-form')?.addEventListener('submit', createNotification);
  byId('cabinet-panel')?.addEventListener('click', event => {
    const button = event.target.closest('[data-account-action]');
    if (!button) return;
    event.preventDefault();
    const action = button.dataset.accountAction;
    const pinId = Number(button.dataset.pinId || 0);
    const tradeId = Number(button.dataset.tradeId || 0);
    const ruleId = Number(button.dataset.ruleId || 0);
    if (action === 'start-trade') startTradeFromPin(pinId);
    if (action === 'remove-pin') deletePin(pinId);
    if (action === 'close-trade') closeTrade(tradeId);
    if (action === 'remove-trade') deleteTrade(tradeId);
    if (action === 'remove-notification') deleteNotification(ruleId);
    if (action === 'toggle-notification') toggleNotification(ruleId);
    if (action === 'test-notification') testNotification(ruleId);
  });
}

function priceWithCurrency(value, currency) {
  return value === null || value === undefined || value === '' ? t('priceUnknown') : `${formatAmount(value)} ${currencyLabel(currency)}`;
}

function accountMarketForItem(item) {
  const serverMarket = item.market || {};
  const serverPrice = Number(serverMarket.price);
  if (Number.isFinite(serverPrice) && serverPrice > 0) {
    return {
      ...serverMarket,
      price: serverPrice,
      target_currency: serverMarket.target_currency || item.target_currency || item.entry_currency,
    };
  }
  if (item.category === state.selectedCategory) {
    const categoryRates = state.rates[state.selectedCategory] || {};
    const row = rowsById(categoryRates).get(item.item_id);
    const price = rateValue(row);
    if (price) {
      return {
        price,
        target_currency: categoryRates.target || item.target_currency || item.entry_currency || selectedTarget(),
        source: categoryRates.source || '',
        created_ts: categoryRates.created_ts,
        change: row?.change,
        sparkline: row?.sparkline || [],
        sparkline_kind: row?.sparkline_kind,
        volume: row?.volume || 0,
      };
    }
  }
  const fallbackPrice = Number(item.last_price);
  return {
    price: Number.isFinite(fallbackPrice) && fallbackPrice > 0 ? fallbackPrice : null,
    target_currency: item.target_currency || item.entry_currency,
    source: item.last_source || '',
    created_ts: null,
    change: null,
    sparkline: [],
    volume: 0,
  };
}

function accountMarketTime(market) {
  if (!market?.created_ts) return '';
  return formatDateTime(Number(market.created_ts) * 1000);
}

function renderAccountMarketMeta(item) {
  const market = accountMarketForItem(item);
  const target = market.target_currency || item.target_currency || item.entry_currency;
  const timestamp = accountMarketTime(market);
  return `
    <span>${t('currentMarketPrice')}: ${priceWithCurrency(market.price, target)}</span>
    ${market.change !== null && market.change !== undefined ? `<span>${t('last7days')}: ${formatChange(market.change)}</span>` : ''}
    ${market.volume ? `<span>${t('volume')}: ${formatAmount(market.volume)}</span>` : ''}
    ${market.source ? `<span>${t('source')}: ${escapeHtml(market.source)}</span>` : ''}
    ${timestamp ? `<span>${t('marketSnapshot')}: ${escapeHtml(timestamp)}</span>` : ''}
  `;
}

function renderAccountChart(item) {
  const market = accountMarketForItem(item);
  const cachedSeries = accountChartCachedSeries(item);
  const visibleCachedSeries = hourlyTimedSeries(visibleTimedSeries(cachedSeries));
  const cachedValues = visibleCachedSeries.map(point => point.value);
  const sparklineValues = limitedChartValues(chartValuesForCurrent(market.sparkline || [], market.price, market.change));
  const usesHistory = timedSeriesCoversDays(visibleCachedSeries, selectedChartDays()) && cachedValues.length > sparklineValues.length;
  const values = usesHistory ? cachedValues : sparklineValues;
  if (values.length < 2) {
    return `<div class="account-market-chart empty">${t('chartNoData')}</div>`;
  }
  return `<div class="account-market-chart">${miniSignalChart(values, usesHistory ? chartBasisText(selectedChartDays()) : chartBasisText(values.length), market.price, market.change, {
    series: usesHistory ? visibleCachedSeries : [],
  })}</div>`;
}

function pnlClass(value) {
  const number = Number(value);
  if (number > 0) return 'positive';
  if (number < 0) return 'negative';
  return 'neutral';
}

function pnlBadge(available, amount, percent, currency, unavailableText) {
  if (!available) return `<span class="trade-pnl neutral">${unavailableText}</span>`;
  return `<span class="trade-pnl ${pnlClass(amount)}">${priceWithCurrency(amount, currency)} (${formatChange(percent)})</span>`;
}

function benchmarkSummary(trade, mode) {
  const benchmark = trade.benchmark_currency || 'divine';
  const currentBenchmark = mode === 'closed' ? trade.exit_benchmark_price : trade.current_benchmark_price;
  const change = mode === 'closed' ? trade.benchmark_change_percent : trade.current_benchmark_change_percent;
  const currentLabel = mode === 'closed' ? t('benchmarkExit') : t('benchmarkCurrent');
  if (!trade.entry_benchmark_price || !currentBenchmark) {
    return `<span>${t('benchmarkBasis')}: ${currencyLabel(benchmark)} · ${t('benchmarkMissing')}</span>`;
  }
  return `
    <span>${t('benchmarkBasis')}: ${currencyLabel(benchmark)}</span>
    <span>${t('benchmarkEntry')}: ${priceWithCurrency(trade.entry_benchmark_price, trade.entry_currency)}</span>
    <span>${currentLabel}: ${priceWithCurrency(currentBenchmark, trade.entry_currency)}</span>
    ${change !== null && change !== undefined ? `<span>${t('benchmarkChange')}: ${formatChange(change)}</span>` : ''}
  `;
}

function renderPinCard(pin) {
  const name = accountItemName(pin);
  const market = accountMarketForItem(pin);
  const target = market.target_currency || pin.target_currency;
  const priceValue = market.price ?? pin.last_price ?? '';
  return `
    <article class="pin-card">
      <div class="pin-market-layout">
        <div>
          <div class="pin-title">
            ${pin.icon_url ? `<img src="${escapeHtml(pin.icon_url)}" alt="">` : '<span class="category-placeholder"></span>'}
            <div>
              <strong>${escapeHtml(name)}</strong>
              <small>${escapeHtml(pin.league)} / ${escapeHtml(pin.category)} / ${escapeHtml(pin.item_id)}</small>
            </div>
          </div>
          <div class="pin-meta">
            ${renderAccountMarketMeta(pin)}
            ${pin.last_price ? `<span>${t('entryReference')}: ${priceWithCurrency(pin.last_price, pin.target_currency)}</span>` : ''}
          </div>
        </div>
        ${renderAccountChart(pin)}
      </div>
      <div class="pin-trade-row">
        <label class="compact-field">
          <span>${t('entryPrice')}</span>
          <input class="form-control form-control-sm" type="number" min="0" step="any" value="${escapeHtml(priceValue)}" data-pin-entry-price="${pin.id}">
        </label>
        <label class="compact-field">
          <span>${t('quantity')}</span>
          <input class="form-control form-control-sm" type="number" min="0.0001" step="any" value="1" data-pin-quantity="${pin.id}">
        </label>
        <button class="btn btn-primary btn-sm" type="button" data-account-action="start-trade" data-pin-id="${pin.id}">${t('markEntry')}</button>
        <button class="btn btn-outline-light btn-sm" type="button" data-account-action="remove-pin" data-pin-id="${pin.id}">${t('unpinPosition')}</button>
      </div>
      <div class="pin-meta"><span>${t('entryWillUseBenchmark')}: ${currencyLabel(state.account.benchmarkCurrency || 'divine')}</span><span>${t('entryCurrency')}: ${currencyLabel(target)}</span></div>
    </article>
  `;
}

function renderTradePnl(trade) {
  if (trade.status !== 'closed') return '';
  return `
    <div class="trade-pnl-row">
      <span>${t('finalMargin')}</span>
      ${pnlBadge(trade.pnl_available, trade.pnl_amount, trade.pnl_percent, trade.pnl_currency, t('pnlUnavailable'))}
    </div>
    <div class="trade-pnl-row">
      <span>${t('realFinalMargin')}</span>
      ${pnlBadge(trade.real_pnl_available, trade.real_pnl_amount, trade.real_pnl_percent, trade.real_pnl_currency, t('realPnlUnavailable'))}
    </div>
  `;
}

function renderOpenTradeSnapshot(trade) {
  const market = accountMarketForItem(trade);
  return `
    <div class="trade-metric-grid">
      <div>
        <span class="summary-label">${t('currentMarketPrice')}</span>
        <strong>${priceWithCurrency(market.price, market.target_currency || trade.entry_currency)}</strong>
      </div>
      <div>
        <span class="summary-label">${t('currentMargin')}</span>
        ${pnlBadge(trade.current_pnl_available, trade.current_pnl_amount, trade.current_pnl_percent, trade.current_pnl_currency, t('currentPnlUnavailable'))}
      </div>
      <div>
        <span class="summary-label">${t('realCurrentMargin')}</span>
        ${pnlBadge(trade.current_real_pnl_available, trade.current_real_pnl_amount, trade.current_real_pnl_percent, trade.current_real_pnl_currency, t('realPnlUnavailable'))}
      </div>
    </div>
    <div class="pin-meta">${benchmarkSummary(trade, 'open')}</div>
    ${renderAccountChart(trade)}
  `;
}

function renderTradeCard(trade) {
  const name = accountItemName(trade);
  const isOpen = trade.status !== 'closed';
  const market = accountMarketForItem(trade);
  const exitPriceValue = isOpen && market.price ? market.price : '';
  return `
    <article class="trade-card ${isOpen ? 'open' : 'closed'}">
      <div class="trade-card-head">
        <div class="pin-title">
          ${trade.icon_url ? `<img src="${escapeHtml(trade.icon_url)}" alt="">` : '<span class="category-placeholder"></span>'}
          <div>
            <strong>${escapeHtml(name)}</strong>
            <small>${escapeHtml(trade.league)} / ${escapeHtml(trade.category)} / ${escapeHtml(trade.item_id)}</small>
          </div>
        </div>
        <span class="trade-status-pill">${isOpen ? t('tradeStatusOpen') : t('tradeStatusClosed')}</span>
      </div>
      <div class="pin-meta">
        <span>${t('entryMoment')}: ${formatDateTime(trade.entry_at)}</span>
        <span>${t('entryPrice')}: ${priceWithCurrency(trade.entry_price, trade.entry_currency)}</span>
        <span>${t('quantity')}: ${formatAmount(trade.quantity)}</span>
        ${isOpen ? renderAccountMarketMeta(trade) : ''}
        ${trade.exit_at ? `<span>${t('exitMoment')}: ${formatDateTime(trade.exit_at)}</span>` : ''}
        ${trade.exit_price ? `<span>${t('exitPrice')}: ${priceWithCurrency(trade.exit_price, trade.exit_currency)}</span>` : ''}
      </div>
      ${isOpen ? renderOpenTradeSnapshot(trade) : `
        <div class="pin-meta">${benchmarkSummary(trade, 'closed')}</div>
        ${renderTradePnl(trade)}
        ${renderAccountChart(trade)}
      `}
      ${isOpen ? `
        <div class="pin-trade-row">
          <label class="compact-field">
            <span>${t('exitPrice')}</span>
            <input class="form-control form-control-sm" type="number" min="0" step="any" value="${escapeHtml(exitPriceValue)}" data-trade-exit-price="${trade.id}">
          </label>
          <button class="btn btn-primary btn-sm" type="button" data-account-action="close-trade" data-trade-id="${trade.id}">${t('markExit')}</button>
          <button class="btn btn-outline-light btn-sm" type="button" data-account-action="remove-trade" data-trade-id="${trade.id}">${t('deleteTrade')}</button>
        </div>
      ` : `
        <div class="pin-trade-row">
          <button class="btn btn-outline-light btn-sm" type="button" data-account-action="remove-trade" data-trade-id="${trade.id}">${t('deleteTrade')}</button>
        </div>
      `}
    </article>
  `;
}

function renderNotificationCard(rule) {
  const pin = rule.pin || {};
  const name = accountItemName(pin);
  const threshold = rule.event_type === 'any_update' || rule.threshold_value === null || rule.threshold_value === undefined
    ? ''
    : `<span>${t('notificationThreshold')}: ${formatAmount(rule.threshold_value)}</span>`;
  return `
    <article class="notification-card ${rule.enabled ? 'enabled' : 'disabled'}">
      <div class="pin-title">
        ${pin.icon_url ? `<img src="${escapeHtml(pin.icon_url)}" alt="">` : '<span class="category-placeholder"></span>'}
        <div>
          <strong>${escapeHtml(name || '-')}</strong>
          <small>${escapeHtml(pin.league || '')} / ${escapeHtml(pin.category || '')} / ${escapeHtml(pin.item_id || '')}</small>
        </div>
      </div>
      <div class="pin-meta">
        <span>${t('notificationEvent')}: ${notificationEventLabel(rule.event_type)}</span>
        ${threshold}
        <span>${t('telegramChatId')}: ${escapeHtml(rule.chat_id)}</span>
        <span>${t('lastKnownPrice')}: ${priceWithCurrency(rule.last_price ?? pin.last_price, pin.target_currency)}</span>
        ${rule.last_triggered_at ? `<span>${t('lastNotification')}: ${formatDateTime(rule.last_triggered_at)}</span>` : ''}
      </div>
      <div class="pin-trade-row">
        <button class="btn btn-outline-light btn-sm" type="button" data-account-action="toggle-notification" data-rule-id="${rule.id}">${rule.enabled ? t('pauseNotification') : t('resumeNotification')}</button>
        <button class="btn btn-outline-light btn-sm" type="button" data-account-action="test-notification" data-rule-id="${rule.id}">${t('sendTestNotification')}</button>
        <button class="btn btn-outline-light btn-sm" type="button" data-account-action="remove-notification" data-rule-id="${rule.id}">${t('deleteNotification')}</button>
      </div>
    </article>
  `;
}

function renderNotificationPanel() {
  fillNotificationControls();
  const status = byId('telegram-config-status');
  if (status) {
    status.textContent = state.account.telegramConfigured ? t('telegramConfigured') : t('telegramNotConfigured');
  }
  const list = byId('notifications-list');
  if (!list) return;
  if (!state.account.pins.length) {
    list.innerHTML = `<p class="text-secondary">${t('notificationsNeedPins')}</p>`;
    return;
  }
  list.innerHTML = state.account.notifications.length
    ? state.account.notifications.map(renderNotificationCard).join('')
    : `<p class="text-secondary">${t('noNotifications')}</p>`;
}

function renderCabinet() {
  const panel = byId('cabinet-panel');
  if (!panel) return;
  const authPanel = byId('auth-panel');
  const dashboard = byId('account-dashboard');
  authPanel?.classList.toggle('d-none', state.account.authenticated);
  dashboard?.classList.toggle('d-none', !state.account.authenticated);
  if (!state.account.authenticated) {
    setText('pinned-count', '0');
    setText('open-trades-count', '0');
    setText('closed-trades-count', '0');
    return;
  }
  fillBenchmarkCurrencySelect();
  setText('account-user-label', state.account.user?.display_name || state.account.user?.username || '');
  const openTrades = state.account.trades.filter(trade => trade.status !== 'closed');
  const closedTrades = state.account.trades.filter(trade => trade.status === 'closed');
  setText('pinned-count', state.account.pins.length);
  setText('open-trades-count', openTrades.length);
  setText('closed-trades-count', closedTrades.length);
  const pinsList = byId('pins-list');
  if (pinsList) {
    pinsList.innerHTML = state.account.pins.length
      ? state.account.pins.map(renderPinCard).join('')
      : `<p class="text-secondary">${t('noPinnedPositions')}</p>`;
  }
  const openTradesList = byId('open-trades-list');
  if (openTradesList) {
    openTradesList.innerHTML = openTrades.length
      ? openTrades.map(renderTradeCard).join('')
      : `<p class="text-secondary">${t('noOpenTrades')}</p>`;
  }
  const closedTradesList = byId('closed-trades-list');
  if (closedTradesList) {
    closedTradesList.innerHTML = closedTrades.length
      ? closedTrades.map(renderTradeCard).join('')
      : `<p class="text-secondary">${t('noClosedTrades')}</p>`;
  }
  queueAccountChartSeriesLoad();
  renderNotificationPanel();
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

function fillBenchmarkCurrencySelect() {
  const select = byId('benchmark-currency');
  if (!select) return;
  const fallback = hasTarget('divine') ? 'divine' : defaultTarget();
  const selected = hasTarget(state.account.benchmarkCurrency) ? state.account.benchmarkCurrency : fallback;
  state.account.benchmarkCurrency = selected;
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
      state.historyTrends = [];
      state.historyTrendsKey = '';
      state.isLoadingHistoryTrends = false;
      state.detailDemandCache = {};
      state.detailSeriesCache = {};
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
  if (mode === 'poe-ninja-aggregate') return t('comparisonPoeNinja');
  if (mode === 'type-level-stat-ids') return t('comparisonExactStats');
  if (mode === 'type-level-stat-ids-minus-one') return t('comparisonStatsMinusOne');
  if (mode === 'type-level-loose-stats') return t('comparisonLooseStats');
  return t('comparisonTypeOnly');
}

function sellerUnitNote(lot, market, target) {
  const stackSize = Number(lot.stack_size || 1);
  const parts = [];
  if (stackSize > 1) parts.push(`${t('stackSize')}: ${formatAmount(stackSize)}`);
  if (market?.unit_priced && lot.price_unit_target) parts.push(`${t('perUnit')}: ${lotTargetPrice(lot.price_unit_target, target)}`);
  return parts.length ? `<span class="lot-card-note">${parts.join(' · ')}</span>` : '';
}

function marketSourceNote(market) {
  if (market?.source === 'poe.ninja') {
    const change = market.change === null || market.change === undefined ? '' : ` · ${t('last7days')}: ${formatChange(market.change)}`;
    return `${t('source')}: poe.ninja · ${t('volume')}: ${formatAmount(market.volume || 0)}${change}`;
  }
  return `${t('marketLots')}: ${formatAmount(market?.count || 0)}`;
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
          ${sellerUnitNote(lot, market, target)}
        </div>
        <div>
          <span class="lot-card-label">${t('currentMarketPrice')}</span>
          ${market.pending ? loadingMarkup(t('marketEvaluating'), 'inline') : `
            <strong class="lot-card-value">${lotTargetPrice(market.current, target)}</strong>
            <span class="lot-card-note">${marketSourceNote(market)}</span>
            <span class="lot-card-note">${t('confidence')}: ${confidenceLabel(market.confidence)} · ${comparisonLabel(market.comparison?.mode)}</span>
          `}
        </div>
        <div>
          <span class="lot-card-label">${t('marketRange')}</span>
          <strong class="lot-card-value">${lotTargetPrice(market.min, target)} - ${lotTargetPrice(market.p75, target)}</strong>
          <span class="lot-card-note">${market.source === 'poe.ninja' ? t('poeNinjaAggregateBasis') : t('similarBasis')}</span>
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

function positiveFiniteValues(values) {
  return (values || [])
    .map(Number)
    .filter(value => Number.isFinite(value) && value > 0);
}

function priceSeriesFromChange(values, currentValue, totalChange = null) {
  const current = Number(currentValue);
  if (!Number.isFinite(current) || current <= 0) return [];
  const points = (values || [])
    .map(Number)
    .filter(Number.isFinite);
  const numericChange = Number(totalChange);
  let changes = points;
  if (Number.isFinite(numericChange) && Math.abs(numericChange) > 0.0001 && points.length >= 2) {
    const last = points[points.length - 1];
    const inferredScale = last / numericChange;
    const looksScaled = inferredScale > 0
      && Math.abs(inferredScale - 1) > 0.08
      && (points.some(value => value <= -99.9 || Math.abs(value) > 500) || Math.abs(last - numericChange) > Math.max(0.5, Math.abs(numericChange) * 0.2));
    if (looksScaled) {
      changes = points.map(value => value / inferredScale);
    }
  }
  changes = changes.filter(value => value > -99.9);
  if (changes.length < 2) return [];
  const lastFactor = 1 + (changes[changes.length - 1] / 100);
  if (lastFactor <= 0) return [];
  const baseline = current / lastFactor;
  return changes
    .map(change => baseline * (1 + change / 100))
    .filter(value => Number.isFinite(value) && value > 0);
}

function priceSeriesForRow(row) {
  const currentValue = Number(row?.best ?? row?.median);
  const values = positiveFiniteValues(row?.sparkline || []);
  if (row?.sparkline_kind === 'price') return values;
  if (!Number.isFinite(currentValue) || currentValue <= 0) return values;
  if (values.length >= 2) {
    const last = values[values.length - 1];
    if (last > 0 && Math.abs(last - currentValue) / currentValue < 0.08) return values;
  }
  return priceSeriesFromChange(row?.sparkline || [], currentValue, row?.change);
}

function chartValuesForCurrent(values, currentValue, totalChange = null) {
  const current = Number(currentValue);
  const positiveValues = positiveFiniteValues(values);
  if (!Number.isFinite(current) || current <= 0) return positiveValues;
  const last = positiveValues[positiveValues.length - 1];
  if (positiveValues.length >= 2 && last > 0 && Math.abs(last - current) / current < 0.08) return positiveValues;
  const converted = priceSeriesFromChange(values, current, totalChange);
  return converted.length ? converted : positiveValues;
}

function accountChartKey(item) {
  const market = item?.market || {};
  return [
    item?.league || '',
    item?.category || '',
    market.target_currency || item?.target_currency || item?.entry_currency || selectedTarget(),
    'any',
    item?.item_id || '',
  ].join('|');
}

function accountChartRequest(item) {
  const market = item?.market || {};
  return {
    key: accountChartKey(item),
    league: item?.league || '',
    category: item?.category || '',
    target: market.target_currency || item?.target_currency || item?.entry_currency || selectedTarget(),
    status: 'any',
    itemId: item?.item_id || '',
    currentTs: Number(market.created_ts || 0),
    currentValue: Number(market.price || item?.last_price || 0),
  };
}

function visibleTimedSeries(series) {
  if (!series?.length) return [];
  const latestTs = Math.max(...series.map(point => Number(point.ts || 0)).filter(Number.isFinite));
  const cutoffTs = latestTs - selectedChartDays() * 86400;
  return series
    .filter(point => Number(point.ts || 0) >= cutoffTs)
    .filter(point => Number.isFinite(point.value) && point.value > 0);
}

function hourlyTimedSeries(series) {
  if (!series?.length) return [];
  const buckets = new Map();
  series.forEach(point => {
    const ts = Number(point.ts || 0);
    const value = Number(point.value);
    if (!Number.isFinite(ts) || ts <= 0 || !Number.isFinite(value) || value <= 0) return;
    const hourTs = Math.floor(ts / 3600) * 3600;
    const previous = buckets.get(hourTs);
    if (!previous || ts >= previous.ts) {
      buckets.set(hourTs, { ts, hourTs, value });
    }
  });
  return [...buckets.values()]
    .sort((left, right) => left.hourTs - right.hourTs)
    .map(point => ({ ts: point.hourTs, value: point.value }));
}

function timedSeriesSpanDays(series) {
  const timestamps = (series || [])
    .map(point => Number(point.ts || 0))
    .filter(value => Number.isFinite(value) && value > 0);
  if (timestamps.length < 2) return 0;
  return (Math.max(...timestamps) - Math.min(...timestamps)) / 86400;
}

function timedSeriesCoversDays(series, days) {
  return timedSeriesSpanDays(series) >= Math.max(1, Number(days || 0) - 1.1);
}

function updateMaxChartDaysFromSeries(seriesList = []) {
  const previous = state.maxChartDaysAvailable;
  const maxSpan = Math.max(0, ...seriesList.map(timedSeriesSpanDays));
  state.maxChartDaysAvailable = maxSpan >= 29.5 ? 30 : maxSpan >= 13.5 ? 14 : 7;
  if (state.maxChartDaysAvailable !== previous) {
    fillChartDaysSelects();
  }
}

function accountChartCachedSeries(item) {
  return state.accountChartSeriesCache[accountChartKey(item)] || [];
}

async function loadAccountChartSeries(request) {
  if (!request.itemId || !request.league || !request.category || !request.target) return;
  if (state.accountChartSeriesCache[request.key] || state.accountChartSeriesLoading[request.key]) return;
  state.accountChartSeriesLoading[request.key] = true;
  try {
    const params = new URLSearchParams({
      limit: '200',
      league: request.league,
      category: request.category,
      target: request.target,
      status: request.status,
    });
    const response = await fetch(`/api/trade/history?${params.toString()}`);
    const data = await response.json();
    if (!response.ok || data.error) throw new Error(data.error || t('cacheLoadError'));
    const seen = new Set();
    const series = (data.history || [])
      .filter(snapshot => snapshot && Number(snapshot.created_ts || 0) > 0)
      .sort((left, right) => Number(left.created_ts || 0) - Number(right.created_ts || 0))
      .map(snapshot => {
        const createdTs = Number(snapshot.created_ts || 0);
        if (seen.has(createdTs)) return null;
        seen.add(createdTs);
        const row = rowsById(snapshot).get(request.itemId);
        const value = rateValue(row);
        return Number.isFinite(value) && value > 0 ? { ts: createdTs, value } : null;
      })
      .filter(value => value !== null);
    if (request.currentTs > 0 && request.currentValue > 0 && !seen.has(request.currentTs)) {
      series.push({ ts: request.currentTs, value: request.currentValue });
    }
    state.accountChartSeriesCache[request.key] = series;
  } catch {
    state.accountChartSeriesCache[request.key] = [];
  } finally {
    delete state.accountChartSeriesLoading[request.key];
  }
}

function queueAccountChartSeriesLoad() {
  if (!state.account.authenticated || state.mainView !== 'cabinet') return;
  const items = [
    ...state.account.pins,
    ...state.account.trades,
  ];
  const requests = Array.from(new Map(items.map(item => {
    const request = accountChartRequest(item);
    return [request.key, request];
  })).values()).filter(request => request.itemId && !state.accountChartSeriesCache[request.key] && !state.accountChartSeriesLoading[request.key]);
  updateMaxChartDaysFromSeries(items.map(accountChartCachedSeries));
  if (!requests.length) return;
  Promise.all(requests.map(loadAccountChartSeries)).then(() => {
    updateMaxChartDaysFromSeries(items.map(accountChartCachedSeries));
    if (state.mainView === 'cabinet') renderCabinet();
  });
}

function chartMetric() {
  return state.detailChartMetric === 'demand' ? 'demand' : 'price';
}

function renderDetailChartTabs() {
  const metric = chartMetric();
  document.querySelectorAll('[data-detail-chart]').forEach(button => {
    const active = button.dataset.detailChart === metric;
    button.classList.toggle('active', active);
    button.setAttribute('aria-pressed', active ? 'true' : 'false');
  });
}

function demandHistoryKey(currentData, itemId) {
  return `${historyTrendsKey(currentData)}|${itemId}|demand`;
}

function detailSeriesKey(currentData, itemId, metric) {
  return `${historyTrendsKey(currentData)}|${itemId}|${metric}`;
}

async function loadHistoricalItemSeries(currentData, itemId, metric) {
  const key = detailSeriesKey(currentData, itemId, metric);
  if (state.detailSeriesCache[key]) return state.detailSeriesCache[key];
  const params = new URLSearchParams({
    limit: '200',
    league: currentData.league || byId('live-league')?.value || '',
    category: currentData.category || state.selectedCategory,
    target: currentData.target || selectedTarget(),
    status: currentData.status || byId('live-status')?.value || 'any',
  });
  const response = await fetch(`/api/trade/history?${params.toString()}`);
  const data = await response.json();
  if (!response.ok || data.error) throw new Error(data.error || t('cacheLoadError'));
  const snapshots = [...(data.history || []), currentData]
    .filter(snapshot => snapshot && Number(snapshot.created_ts || 0) > 0)
    .sort((left, right) => Number(left.created_ts || 0) - Number(right.created_ts || 0));
  const seen = new Set();
  const series = snapshots
    .map(snapshot => {
      const createdTs = Number(snapshot.created_ts || 0);
      if (seen.has(createdTs)) return null;
      seen.add(createdTs);
      const row = rowsById(snapshot).get(itemId);
      const value = metric === 'demand' ? Number(row?.volume) : rateValue(row);
      return Number.isFinite(value) && value > 0 ? { ts: createdTs, value } : null;
    })
    .filter(value => value !== null);
  state.detailSeriesCache[key] = series;
  updateMaxChartDaysFromSeries([series]);
  return series;
}

async function loadDemandSeries(currentData, itemId) {
  const key = demandHistoryKey(currentData, itemId);
  if (state.detailDemandCache[key]) return state.detailDemandCache[key];
  const series = await loadHistoricalItemSeries(currentData, itemId, 'demand');
  state.detailDemandCache[key] = series;
  return series;
}

function historyChartLabels(series) {
  if (!series.length) return [];
  const firstTs = Number(series[0].ts || 0);
  const lastTs = Number(series[series.length - 1].ts || 0);
  const locale = state.lang === 'ru' ? 'ru-RU' : 'en-GB';
  const options = lastTs - firstTs <= 36 * 60 * 60
    ? { hour: '2-digit', minute: '2-digit' }
    : { day: '2-digit', month: '2-digit' };
  const formatter = new Intl.DateTimeFormat(locale, options);
  return series.map(point => formatter.format(new Date(Number(point.ts || 0) * 1000)));
}

function intermediateGridX(points, subdivisions = 4) {
  if (!Array.isArray(points) || points.length < 2 || points.length > 40) return [];
  const lines = [];
  for (let index = 0; index < points.length - 1; index += 1) {
    const left = points[index].x;
    const right = points[index + 1].x;
    for (let step = 1; step < subdivisions; step += 1) {
      lines.push(left + ((right - left) * step) / subdivisions);
    }
  }
  return lines;
}

function normalizedTimedSeries(series, length) {
  if (!Array.isArray(series) || series.length !== length) return [];
  const normalized = series
    .map(point => ({ ts: Number(point.ts || 0), value: Number(point.value) }))
    .filter(point => Number.isFinite(point.ts) && point.ts > 0 && Number.isFinite(point.value) && point.value > 0);
  return normalized.length === length ? normalized : [];
}

function timeGridX(series, leftPad, plotWidth, stepHours = 6) {
  if (series.length < 2) return [];
  const minTs = series[0].ts;
  const maxTs = series[series.length - 1].ts;
  const range = maxTs - minTs;
  if (range <= 0) return [];
  const stepSeconds = stepHours * 3600;
  let cursor = Math.ceil(minTs / stepSeconds) * stepSeconds;
  const lines = [];
  while (cursor < maxTs) {
    if (cursor > minTs) {
      lines.push(leftPad + ((cursor - minTs) / range) * plotWidth);
    }
    cursor += stepSeconds;
  }
  return lines;
}

function timedAxisLabels(points, series) {
  if (!points.length || !series.length) return [];
  const locale = state.lang === 'ru' ? 'ru-RU' : 'en-GB';
  const dayFormatter = new Intl.DateTimeFormat(locale, { day: '2-digit', month: '2-digit' });
  const hourFormatter = new Intl.DateTimeFormat(locale, { hour: '2-digit', minute: '2-digit' });
  const spanSeconds = series[series.length - 1].ts - series[0].ts;
  const labels = [];
  if (spanSeconds <= 36 * 3600) {
    const step = Math.max(1, Math.ceil((points.length - 1) / 6));
    points.forEach((point, index) => {
      if (index === 0 || index === points.length - 1 || index % step === 0) {
        labels.push({ point, label: hourFormatter.format(new Date(series[index].ts * 1000)) });
      }
    });
    return labels;
  }
  const seenDays = new Set();
  points.forEach((point, index) => {
    const date = new Date(series[index].ts * 1000);
    const key = `${date.getFullYear()}-${date.getMonth()}-${date.getDate()}`;
    if (seenDays.has(key)) return;
    seenDays.add(key);
    labels.push({ point, label: dayFormatter.format(date) });
  });
  const step = Math.max(1, Math.ceil(labels.length / 7));
  return labels.filter((label, index) => index === 0 || index === labels.length - 1 || index % step === 0);
}

function renderSparkline(values, options = {}) {
  const chart = byId('detail-chart');
  if (!chart) return;
  const data = positiveFiniteValues(values);
  if (data.length < 2) {
    chart.innerHTML = `<div class="detail-chart-empty">${options.emptyText || t('chartNoData')}</div>`;
    return;
  }
  const width = Math.max(720, Math.round(chart.getBoundingClientRect().width || chart.clientWidth || 720));
  const height = 190;
  const leftPad = 58;
  const rightPad = 18;
  const topPad = 16;
  const bottomPad = 30;
  const displayData = data;
  const min = Math.min(...displayData);
  const max = Math.max(...displayData);
  const range = max - min || 1;
  const plotRight = width - rightPad;
  const plotBottom = height - bottomPad;
  const plotWidth = plotRight - leftPad;
  const plotHeight = plotBottom - topPad;
  const timedSeries = normalizedTimedSeries(options.series, displayData.length);
  const minTs = timedSeries.length ? timedSeries[0].ts : null;
  const maxTs = timedSeries.length ? timedSeries[timedSeries.length - 1].ts : null;
  const timeRange = timedSeries.length && maxTs > minTs ? maxTs - minTs : null;
  const points = displayData.map((value, index) => {
    const x = timeRange
      ? leftPad + ((timedSeries[index].ts - minTs) / timeRange) * plotWidth
      : leftPad + (index / (displayData.length - 1)) * plotWidth;
    const y = plotBottom - ((value - min) / range) * plotHeight;
    return { x, y };
  });
  const polyline = points.map(point => `${point.x.toFixed(2)},${point.y.toFixed(2)}`).join(' ');
  const area = `${leftPad},${plotBottom} ${polyline} ${plotRight},${plotBottom}`;
  const gridY = [0, 0.125, 0.25, 0.375, 0.5, 0.625, 0.75, 0.875, 1].map(ratio => topPad + ratio * plotHeight);
  const valueAtY = y => max - ((y - topPad) / plotHeight) * range;
  const tickStep = Math.max(1, Math.ceil((displayData.length - 1) / 6));
  const gridPoints = points.filter((_, index) => index === 0 || index === points.length - 1 || index % tickStep === 0);
  const gridX = gridPoints.map(point => point.x);
  const hourGridX = timedSeries.length
    ? timeGridX(timedSeries, leftPad, plotWidth, 6)
    : intermediateGridX(points, displayData.length <= 8 ? 24 : 4);
  const dateFormatter = new Intl.DateTimeFormat(state.lang === 'ru' ? 'ru-RU' : 'en-GB', { day: '2-digit', month: '2-digit' });
  const today = new Date();
  const xLabels = Array.isArray(options.xLabels) ? options.xLabels : [];
  const dayLabels = timedSeries.length ? timedAxisLabels(points, timedSeries) : gridPoints.map(point => {
    const index = points.indexOf(point);
    const daysAgo = displayData.length - 1 - index;
    const date = new Date(today);
    date.setDate(today.getDate() - daysAgo);
    return { point, label: xLabels[index] || dateFormatter.format(date) };
  });
  chart.innerHTML = `
    <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${options.label || t('priceChartLabel')}">
      ${hourGridX.map(x => `<line class="detail-chart-grid hour" x1="${x.toFixed(2)}" y1="${topPad}" x2="${x.toFixed(2)}" y2="${plotBottom}"></line>`).join('')}
      ${gridX.map(x => `<line class="detail-chart-grid day" x1="${x.toFixed(2)}" y1="${topPad}" x2="${x.toFixed(2)}" y2="${plotBottom}"></line>`).join('')}
      ${gridY.map(y => `<line class="detail-chart-grid" x1="${leftPad}" y1="${y.toFixed(2)}" x2="${plotRight}" y2="${y.toFixed(2)}"></line>`).join('')}
      <polygon class="detail-chart-area" points="${area}"></polygon>
      <polyline class="detail-chart-line" points="${polyline}"></polyline>
      ${gridY.map(y => `<text class="detail-chart-y-label" x="${leftPad - 8}" y="${(y + 4).toFixed(2)}" text-anchor="end">${formatChartAmount(valueAtY(y))}</text>`).join('')}
      ${dayLabels.map(({ point, label }) => `<text class="detail-chart-x-label" x="${point.x.toFixed(2)}" y="${height - 9}" text-anchor="middle">${label}</text>`).join('')}
    </svg>
  `;
}

function miniSignalChart(values, basisText, currentValue = null, changeValue = null, options = {}) {
  const data = chartValuesForCurrent(values, currentValue, changeValue);
  if (data.length < 2) {
    return `<aside class="advice-chart empty"><span>${t('noSignalChart')}</span></aside>`;
  }
  const width = 960;
  const height = 128;
  const leftPad = 40;
  const rightPad = 10;
  const topPad = 10;
  const bottomPad = 28;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;
  const timedSeries = normalizedTimedSeries(options.series, data.length);
  const minTs = timedSeries.length ? timedSeries[0].ts : null;
  const maxTs = timedSeries.length ? timedSeries[timedSeries.length - 1].ts : null;
  const timeRange = timedSeries.length && maxTs > minTs ? maxTs - minTs : null;
  const points = data.map((value, index) => {
    const plotWidth = width - leftPad - rightPad;
    const x = timeRange
      ? leftPad + ((timedSeries[index].ts - minTs) / timeRange) * plotWidth
      : leftPad + (index / (data.length - 1)) * plotWidth;
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
  const tickStep = Math.max(1, Math.ceil((points.length - 1) / 6));
  const gridPoints = points
    .map((point, index) => ({ ...point, index }))
    .filter(point => point.index === 0 || point.index === points.length - 1 || point.index % tickStep === 0);
  const gridX = gridPoints.map(point => point.x);
  const hourGridX = timedSeries.length
    ? timeGridX(timedSeries, leftPad, width - leftPad - rightPad, 6)
    : intermediateGridX(points, data.length <= 8 ? 24 : 4);
  const gridY = [0, 0.1667, 0.3333, 0.5, 0.6667, 0.8333, 1].map(ratio => topPad + ratio * (plotBottom - topPad));
  const valueAtY = y => max - ((y - topPad) / (plotBottom - topPad)) * range;
  const dateFormatter = new Intl.DateTimeFormat(state.lang === 'ru' ? 'ru-RU' : 'en-GB', { day: '2-digit', month: '2-digit' });
  const today = new Date();
  const xLabels = Array.isArray(options.xLabels) ? options.xLabels : [];
  const dayLabels = timedSeries.length ? timedAxisLabels(points, timedSeries).map(({ point, label }) => (
    `<text class="advice-chart-x-label" x="${point.x.toFixed(2)}" y="${height - 7}" text-anchor="middle">${label}</text>`
  )).join('') : gridPoints.map(point => {
    const index = point.index;
    const daysAgo = data.length - 1 - index;
    const date = new Date(today);
    date.setDate(today.getDate() - daysAgo);
    const label = xLabels[index] || dateFormatter.format(date);
    return `<text class="advice-chart-x-label" x="${point.x.toFixed(2)}" y="${height - 7}" text-anchor="middle">${label}</text>`;
  }).join('');
  const absoluteCurrent = Number(currentValue);
  const canScaleValues = Number.isFinite(absoluteCurrent) && absoluteCurrent > 0 && data.every(value => value > 0);
  const scale = canScaleValues ? absoluteCurrent / data[data.length - 1] : null;
  const valueLabels = canScaleValues ? [gridY[0], gridY[2], gridY[4]].map(y => (
    `<text class="advice-chart-y-label" x="${leftPad - 7}" y="${(y + 3).toFixed(2)}" text-anchor="end">${formatChartAmount(valueAtY(y) * scale)}</text>`
  )).join('') : '';
  const displayCurrent = Number.isFinite(absoluteCurrent) && absoluteCurrent > 0 ? absoluteCurrent : data[data.length - 1];
  const firstValue = data[0];
  const numericChange = Number(changeValue);
  const change = Number.isFinite(numericChange) ? numericChange : (firstValue ? ((data[data.length - 1] - firstValue) / firstValue) * 100 : null);
  return `
    <aside class="advice-chart ${directionClass}">
      <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${t('priceChartLabel')}">
        ${hourGridX.map(x => `<line class="advice-chart-grid hour" x1="${x.toFixed(2)}" y1="${topPad}" x2="${x.toFixed(2)}" y2="${plotBottom}"></line>`).join('')}
        ${gridX.map(x => `<line class="advice-chart-grid day" x1="${x.toFixed(2)}" y1="${topPad}" x2="${x.toFixed(2)}" y2="${plotBottom}"></line>`).join('')}
        ${gridY.map(y => `<line class="advice-chart-grid" x1="${leftPad}" y1="${y.toFixed(2)}" x2="${plotRight}" y2="${y.toFixed(2)}"></line>`).join('')}
        <rect class="advice-chart-current-area" x="${highlightX.toFixed(2)}" y="${topPad}" width="${highlightWidth.toFixed(2)}" height="${plotBottom - topPad}"></rect>
        <line class="advice-chart-current-line" x1="${leftPad}" y1="${current.y.toFixed(2)}" x2="${plotRight}" y2="${current.y.toFixed(2)}"></line>
        <polyline class="advice-chart-line" points="${polyline}"></polyline>
        <circle class="advice-chart-point" cx="${current.x.toFixed(2)}" cy="${current.y.toFixed(2)}" r="3.4"></circle>
        ${valueLabels}
        ${dayLabels}
      </svg>
      <div class="advice-chart-label"><span>${t('currentPoint')}: ${formatChartAmount(displayCurrent)}</span><span>${t('sevenDayChange')}: ${formatChange(change)}</span></div>
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

async function renderDetailChart(row, currentData, target, requestItemId) {
  renderDetailChartTabs();
  const metric = chartMetric();
  if (metric === 'demand') {
    setText('detail-chart-title', `${t('chartMetricDemand')} · ${chartPeriodLabel(selectedChartDays(), selectedChartDays())}`);
    byId('detail-note').innerHTML = loadingMarkup(t('loading'));
    try {
      const series = await loadDemandSeries(currentData, row.id);
      if (state.selectedItemId !== requestItemId || chartMetric() !== 'demand') return;
      const latestTs = Number(currentData.created_ts || Date.now() / 1000);
      const cutoffTs = latestTs - selectedChartDays() * 86400;
      const visibleSeries = hourlyTimedSeries(series.filter(point => Number(point.ts || 0) >= cutoffTs));
      setText('detail-chart-title', `${t('chartMetricDemand')} · ${chartPeriodLabel(selectedChartDays(), visibleSeries.length)}`);
      renderSparkline(visibleSeries.map(point => point.value), {
        emptyText: t('demandChartNoData'),
        label: t('demandChartLabel'),
        series: visibleSeries,
      });
      setText('detail-note', `${t('detailDemandSourceNote')} ${t('source')}: ${currentData.source || '-'}.`);
    } catch (error) {
      if (state.selectedItemId !== requestItemId || chartMetric() !== 'demand') return;
      setText('detail-note', error.message || String(error));
      renderSparkline([], { emptyText: t('demandChartNoData'), label: t('demandChartLabel') });
    }
    return;
  }
  const priceValues = limitedChartValues(priceSeriesForRow(row));
  try {
    byId('detail-note').innerHTML = loadingMarkup(t('loading'));
    const series = await loadHistoricalItemSeries(currentData, row.id, 'price');
    if (state.selectedItemId !== requestItemId || chartMetric() !== 'price') return;
    const latestTs = Number(currentData.created_ts || Date.now() / 1000);
    const cutoffTs = latestTs - selectedChartDays() * 86400;
    const visibleSeries = hourlyTimedSeries(series.filter(point => Number(point.ts || 0) >= cutoffTs));
    if (timedSeriesCoversDays(visibleSeries, selectedChartDays()) && visibleSeries.length > priceValues.length) {
      setText('detail-chart-title', `${t('chartMetricPrice')} (${currencyLabel(target)}) · ${chartPeriodLabel(selectedChartDays(), visibleSeries.length)}`);
      renderSparkline(visibleSeries.map(point => point.value), {
        emptyText: t('chartNoData'),
        label: t('priceChartLabel'),
        series: visibleSeries,
      });
      setText('detail-note', `${t('detailSourceNote')} ${t('source')}: ${currentData.source || '-'}.`);
      return;
    }
  } catch {
    if (state.selectedItemId !== requestItemId || chartMetric() !== 'price') return;
  }
  setText('detail-chart-title', `${t('chartMetricPrice')} (${currencyLabel(target)}) · ${chartPeriodLabel(selectedChartDays(), priceValues.length)}`);
  renderSparkline(priceValues, {
    emptyText: t('chartNoData'),
    label: t('priceChartLabel'),
  });
  setText('detail-note', `${t('detailSourceNote')} ${t('source')}: ${currentData.source || '-'}.`);
  if (!state.detailSeriesCache[detailSeriesKey(currentData, row.id, 'price')]) {
    loadHistoricalItemSeries(currentData, row.id, 'price').catch(() => {});
  }
}

async function renderSelectedItemDetail() {
  const panel = byId('item-detail-panel');
  if (!panel || !state.selectedItemId) return;
  const requestItemId = state.selectedItemId;
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
    if (state.selectedItemId !== requestItemId) return;
    const row = rowsById(data).get(entry.id) || entry;
    setText('detail-value', `${formatAmount(row.best)} ${currencyLabel(target)}`);
    setText('detail-median', `${formatAmount(row.median)} ${currencyLabel(target)}`);
    setText('detail-volume', formatAmount(row.volume || 0));
    const detailChange = byId('detail-change');
    if (detailChange) {
      detailChange.textContent = formatChange(row.change);
      detailChange.className = Number(row.change) > 0 ? 'change-up' : Number(row.change) < 0 ? 'change-down' : '';
    }
    await renderDetailChart(row, data, target, requestItemId);
  } catch (error) {
    const isDemand = chartMetric() === 'demand';
    renderDetailChartTabs();
    setText('detail-chart-title', isDemand ? t('chartMetricDemand') : t('chartMetricPrice'));
    setText('detail-note', error.message || String(error));
    renderSparkline([], {
      emptyText: isDemand ? t('demandChartNoData') : t('chartNoData'),
      label: isDemand ? t('demandChartLabel') : t('priceChartLabel'),
    });
  }
}

function openItemDetail(itemId) {
  state.selectedItemId = itemId;
  fillDetailTargetSelect();
  renderMarket();
  renderSelectedItemDetail();
}

function switchMainView(view) {
  state.mainView = ['signals', 'lots', 'cabinet'].includes(view) ? view : 'market';
  document.querySelectorAll('.main-view-tab').forEach(button => {
    button.classList.toggle('active', button.dataset.mainTab === state.mainView);
  });
  document.querySelectorAll('[data-main-view]').forEach(element => {
    element.classList.toggle('view-hidden', element.dataset.mainView !== state.mainView);
  });
  if (state.mainView === 'signals' && state.activeAdviceTab === 'cross') loadCrossCurrencyDeals();
  if (state.mainView === 'lots') renderSellerLots();
  if (state.mainView === 'cabinet') renderCabinet();
  if (window.location.pathname === '/') {
    const params = new URLSearchParams(window.location.search);
    if (state.mainView === 'market') {
      params.delete('view');
    } else {
      params.set('view', state.mainView);
    }
    const query = params.toString();
    window.history.replaceState(null, '', `${window.location.pathname}${query ? `?${query}` : ''}${window.location.hash}`);
  }
}

// Signal rendering

function renderAdvice(advice) {
  const panel = byId('advice-panel');
  if (!panel) return;
  state.advice = advice || [];
  panel.classList.remove('d-none');
  renderMarketSignals();
  renderTrendSignals();
  renderOperationSignals();
  renderCrossDeals();
  renderActiveTrades();
  switchAdviceTab(state.activeAdviceTab);
}

function currentSignalRows(options = {}) {
  const minVolume = options.minVolume ?? MARKET_SIGNAL_MIN_VOLUME;
  const categoryRates = state.rates[state.selectedCategory] || {};
  const rateRows = rowsById(categoryRates);
  return (state.categories[state.selectedCategory] || [])
    .map(entry => {
      const row = rateRows.get(entry.id);
      const change = Number(row?.change);
      const volume = Number(row?.volume || 0);
      const value = rateValue(row);
      if (!row || !Number.isFinite(change) || !value || volume < minVolume) return null;
      return { entry, row, change, volume, value, target: categoryRates.target || selectedTarget() };
    })
    .filter(Boolean);
}

function marketSignalRows() {
  return currentSignalRows({ minVolume: 0 })
    .filter(item => Math.abs(item.change) >= MARKET_SIGNAL_NOTABLE_CHANGE || item.volume > 0);
}

function snapshotRowValue(row) {
  const value = Number(row?.median ?? row?.best);
  return Number.isFinite(value) && value > 0 ? value : null;
}

function buildHistoryTrends(currentData, history) {
  const currentTs = Number(currentData?.created_ts || 0);
  const previous = [...(history || [])]
    .sort((left, right) => Number(right.created_ts || 0) - Number(left.created_ts || 0))
    .find(snapshot => Number(snapshot.created_ts || 0) < currentTs - 0.001);
  if (!previous) return [];
  const previousRows = rowsById(previous);
  return (state.categories[state.selectedCategory] || [])
    .map(entry => {
      const currentRow = rowsById(currentData).get(entry.id);
      const previousRow = previousRows.get(entry.id);
      const currentValue = snapshotRowValue(currentRow);
      const previousValue = snapshotRowValue(previousRow);
      if (!currentValue || !previousValue) return null;
      const delta = currentValue - previousValue;
      const deltaPct = (delta / previousValue) * 100;
      if (!Number.isFinite(deltaPct) || Math.abs(deltaPct) < 2) return null;
      return {
        entry,
        currentRow,
        previousValue,
        currentValue,
        delta,
        deltaPct,
        target: currentData.target || selectedTarget(),
      };
    })
    .filter(Boolean)
    .sort((left, right) => Math.abs(right.deltaPct) - Math.abs(left.deltaPct))
    .slice(0, 12);
}

function historyTrendsKey(data = state.rates[state.selectedCategory] || {}) {
  return [
    data.league || byId('live-league')?.value || '',
    data.category || state.selectedCategory,
    data.target || selectedTarget(),
    data.status || byId('live-status')?.value || 'any',
    data.created_ts || '',
  ].join('|');
}

function liquidityKind(volume) {
  if (volume < MARKET_SIGNAL_MIN_VOLUME) return 'low';
  if (volume < MARKET_SIGNAL_MEDIUM_VOLUME) return 'medium';
  return 'high';
}

function liquidityLabel(volume) {
  const kind = liquidityKind(volume);
  if (kind === 'high') return t('liquidityHigh');
  if (kind === 'medium') return t('liquidityMedium');
  return t('liquidityLow');
}

function riskLabel(item) {
  if (item.volume < MARKET_SIGNAL_MIN_VOLUME) return t('riskHigh');
  if (item.volume < MARKET_SIGNAL_MEDIUM_VOLUME) return t('riskMedium');
  return t('riskLow');
}

function signalSeverity(item, direction) {
  if (item.volume < MARKET_SIGNAL_MIN_VOLUME) return 'watch';
  const strong = Math.abs(item.change) >= MARKET_SIGNAL_STRONG_CHANGE;
  if (direction === 'drop') return strong ? 'weak' : 'watch';
  if (direction === 'rise') return strong ? 'signal' : 'watch';
  return 'watch';
}

function rangePosition(item) {
  const values = priceSeriesForRow(item.row);
  if (Number.isFinite(item.value)) values.push(item.value);
  if (values.length < 2) return null;
  const min = Math.min(...values);
  const max = Math.max(...values);
  if (!Number.isFinite(min) || !Number.isFinite(max) || max <= min) return null;
  return Math.max(0, Math.min(1, (item.value - min) / (max - min)));
}

function rangePositionLabel(position) {
  if (position === null || position === undefined) return '-';
  if (position <= 0.35) return t('rangeLow');
  if (position >= 0.65) return t('rangeHigh');
  return t('rangeMid');
}

function dealAction(item) {
  if (item.change < 0) {
    return {
      kind: 'buy',
      label: t('dealBuyDip'),
      reason: t('dealBuyDipReason'),
    };
  }
  return {
    kind: 'sell',
    label: t('dealSellMomentum'),
    reason: t('dealSellMomentumReason'),
  };
}

function rangeAlignment(item, position) {
  if (position === null || position === undefined) return 0.9;
  return item.change < 0
    ? 1.15 - Math.min(1, position) * 0.4
    : 0.75 + Math.min(1, position) * 0.4;
}

function scoredDealCandidate(item) {
  const position = rangePosition(item);
  const alignment = rangeAlignment(item, position);
  const changeScore = Math.abs(item.change) * 1.08;
  const volumeScore = Math.log10(item.volume + 1) * 12;
  const score = Math.max(1, Math.min(100, Math.round((changeScore + volumeScore) * alignment)));
  return {
    ...item,
    action: dealAction(item),
    position,
    score,
  };
}

function dealCandidates(rows) {
  return rows
    .filter(item => item.volume >= MARKET_SIGNAL_MIN_VOLUME && Math.abs(item.change) >= MARKET_SIGNAL_NOTABLE_CHANGE)
    .map(scoredDealCandidate)
    .sort((left, right) => right.score - left.score || right.volume - left.volume)
    .slice(0, MARKET_SIGNAL_TOP_CANDIDATES);
}

function dealSeverity(score) {
  if (score >= 75) return 'signal';
  if (score >= 50) return 'weak';
  return 'watch';
}

function renderMarketSignals() {
  const panel = byId('advice-list-market');
  if (!panel) return;
  const rows = marketSignalRows();
  if (!rows.length) {
    panel.innerHTML = `<p class="text-secondary">${t('noMarketSignals')}</p>`;
    return;
  }
  const drops = rows
    .filter(item => item.volume >= MARKET_SIGNAL_MIN_VOLUME && item.change <= -MARKET_SIGNAL_NOTABLE_CHANGE)
    .sort((left, right) => left.change - right.change || right.volume - left.volume)
    .slice(0, 5);
  const rises = rows
    .filter(item => item.volume >= MARKET_SIGNAL_MIN_VOLUME && item.change >= MARKET_SIGNAL_NOTABLE_CHANGE)
    .sort((left, right) => right.change - left.change || right.volume - left.volume)
    .slice(0, 5);
  const lowLiquidity = rows
    .filter(item => item.volume > 0 && item.volume < MARKET_SIGNAL_MIN_VOLUME && Math.abs(item.change) >= MARKET_SIGNAL_STRONG_CHANGE)
    .sort((left, right) => Math.abs(right.change) - Math.abs(left.change))
    .slice(0, 5);
  panel.innerHTML = `
    <p class="text-secondary market-signal-hint">${t('marketSignalsHint')}</p>
    ${renderMarketHealthSection(rows)}
    ${renderDealCandidateSection(dealCandidates(rows))}
    ${renderHistoryTrendSection()}
    <div class="market-signal-board">
      ${renderMarketSignalGroup(t('marketDrops'), drops, 'drop', t('noMarketDrops'))}
      ${renderMarketSignalGroup(t('marketRises'), rises, 'rise', t('noMarketRises'))}
      ${renderMarketSignalGroup(t('marketLowLiquidity'), lowLiquidity, 'risk', t('noMarketLowLiquidity'))}
    </div>
  `;
}

function renderMarketHealthSection(rows) {
  const total = (state.categories[state.selectedCategory] || []).length;
  const priced = rows.length;
  const high = rows.filter(item => liquidityKind(item.volume) === 'high').length;
  const medium = rows.filter(item => liquidityKind(item.volume) === 'medium').length;
  const low = rows.filter(item => item.volume > 0 && liquidityKind(item.volume) === 'low').length;
  const strong = rows.filter(item => Math.abs(item.change) >= MARKET_SIGNAL_STRONG_CHANGE).length;
  return `
    <section class="market-health-grid">
      <div>
        <span class="summary-label">${t('marketCoverage')}</span>
        <strong>${formatAmount(priced)} / ${formatAmount(total)}</strong>
      </div>
      <div>
        <span class="summary-label">${t('liquidityHigh')}</span>
        <strong>${formatAmount(high)}</strong>
      </div>
      <div>
        <span class="summary-label">${t('liquidityMedium')}</span>
        <strong>${formatAmount(medium)}</strong>
      </div>
      <div>
        <span class="summary-label">${t('liquidityLow')}</span>
        <strong>${formatAmount(low)}</strong>
      </div>
      <div>
        <span class="summary-label">${t('strongMoves')}</span>
        <strong>${formatAmount(strong)}</strong>
      </div>
    </section>
  `;
}

function renderHistoryTrendSection() {
  if (state.isLoadingHistoryTrends) {
    return `<section class="history-trend-section"><h3>${t('snapshotTrend')}</h3>${loadingMarkup(t('snapshotTrendLoading'))}</section>`;
  }
  if (!state.historyTrends.length) {
    return '';
  }
  const cheaper = state.historyTrends
    .filter(item => item.deltaPct < 0)
    .sort((left, right) => left.deltaPct - right.deltaPct)
    .slice(0, 4);
  const pricier = state.historyTrends
    .filter(item => item.deltaPct > 0)
    .sort((left, right) => right.deltaPct - left.deltaPct)
    .slice(0, 4);
  if (!cheaper.length && !pricier.length) return '';
  return `
    <section class="history-trend-section">
      <h3>${t('snapshotTrend')}</h3>
      <div class="history-trend-grid">
        ${renderHistoryTrendGroup(t('snapshotCheaper'), cheaper, t('noSnapshotCheaper'))}
        ${renderHistoryTrendGroup(t('snapshotPricier'), pricier, t('noSnapshotPricier'))}
      </div>
    </section>
  `;
}

function renderHistoryTrendGroup(title, items, emptyText) {
  return `
    <div class="history-trend-group">
      <h4>${title}</h4>
      ${items.length ? items.map(renderHistoryTrendItem).join('') : `<p class="text-secondary">${emptyText}</p>`}
    </div>
  `;
}

function renderHistoryTrendItem(item) {
  const changeClass = item.deltaPct > 0 ? 'change-up' : 'change-down';
  return `
    <article class="history-trend-item">
      <strong>${itemTitleMarkup(entryName(item.entry), entryIcon(item.entry))}</strong>
      <span class="${changeClass}">${formatChange(item.deltaPct)}</span>
      <small>${formatAmount(item.previousValue)} → ${formatAmount(item.currentValue)} ${currencyLabel(item.target)}</small>
    </article>
  `;
}

function renderDealCandidateSection(items) {
  return `
    <section class="deal-candidate-section">
      <h3>${t('dealCandidates')}</h3>
      <div class="deal-candidate-grid">
        ${items.length ? items.map(renderDealCandidate).join('') : `<p class="text-secondary">${t('noDealCandidates')}</p>`}
      </div>
    </section>
  `;
}

function renderDealCandidate(item) {
  const changeClass = item.change > 0 ? 'change-up' : 'change-down';
  const severity = dealSeverity(item.score);
  const rangeText = rangePositionLabel(item.position);
  const rangePct = item.position === null || item.position === undefined ? '' : ` (${Math.round(item.position * 100)}%)`;
  return `
    <article class="advice-card ${severity}">
      <div class="deal-candidate-layout">
        <div class="deal-score">
          <span>${t('dealScore')}</span>
          <strong>${item.score}</strong>
        </div>
        <div class="advice-card-content">
          <div class="advice-title-row"><span class="advice-badge">${item.action.label}</span><strong>${itemTitleMarkup(entryName(item.entry), entryIcon(item.entry))}</strong></div>
          <p>${item.action.reason}</p>
          <div class="deal-meta">
            <span>${t('value')}: ${formatAmount(item.value)} ${currencyLabel(item.target)}</span>
            <span>${t('last7days')}: <span class="${changeClass}">${formatChange(item.change)}</span></span>
            <span>${t('volume')}: ${formatAmount(item.volume)}</span>
            <span>${t('riskLabel')}: ${riskLabel(item)}</span>
            <span>${t('rangePosition')}: ${rangeText}${rangePct}</span>
          </div>
        </div>
        ${miniSignalChart(item.row.sparkline || [], t('priceChartBasis'), item.value, item.change)}
      </div>
    </article>
  `;
}

function renderMarketSignalGroup(title, items, direction, emptyText) {
  return `
    <section class="market-signal-group">
      <h3>${title}</h3>
      <div class="market-signal-list">
        ${items.length ? items.map(item => renderMarketSignalItem(item, direction)).join('') : `<p class="text-secondary">${emptyText}</p>`}
      </div>
    </section>
  `;
}

function renderMarketSignalItem(item, direction) {
  const changeClass = item.change > 0 ? 'change-up' : 'change-down';
  const severity = signalSeverity(item, direction);
  const badge = direction === 'drop' ? t('priceDrop') : direction === 'rise' ? t('priceRise') : t('riskLabel');
  return `
    <article class="advice-card ${severity}">
      <div class="advice-card-layout compact">
        <div class="advice-card-content">
          <div class="advice-title-row"><span class="advice-badge">${badge}</span><strong>${itemTitleMarkup(entryName(item.entry), entryIcon(item.entry))}</strong></div>
          <p>${formatAmount(item.value)} ${currencyLabel(item.target)} · <span class="${changeClass}">${formatChange(item.change)}</span></p>
          <div class="deal-meta">
            <span>${t('volume')}: ${formatAmount(item.volume)}</span>
            <span>${t('liquidity')}: ${liquidityLabel(item.volume)}</span>
            ${item.row.max_volume_currency ? `<span>${t('tradedFor')}: ${currencyMarkup(item.row.max_volume_currency)}</span>` : ''}
          </div>
        </div>
        ${miniSignalChart(item.row.sparkline || [], t('priceChartBasis'), item.value, item.change)}
      </div>
    </article>
  `;
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
  ['market', 'buy', 'sell', 'ops', 'active', 'cross'].forEach(name => {
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

// Data loading

async function loadHistoryTrends(currentData) {
  const key = historyTrendsKey(currentData);
  if (!currentData?.created_ts || state.historyTrendsKey === key || state.isLoadingHistoryTrends) return;
  state.historyTrendsKey = key;
  state.historyTrends = [];
  state.isLoadingHistoryTrends = true;
  renderMarketSignals();
  const params = new URLSearchParams({
    limit: '24',
    league: currentData.league || byId('live-league')?.value || '',
    category: currentData.category || state.selectedCategory,
    target: currentData.target || selectedTarget(),
    status: currentData.status || byId('live-status')?.value || 'any',
  });
  try {
    const response = await fetch(`/api/trade/history?${params.toString()}`);
    const data = await response.json();
    if (!response.ok || data.error) throw new Error(data.error || t('cacheLoadError'));
    if (state.historyTrendsKey !== key) return;
    state.historyTrends = buildHistoryTrends(currentData, data.history || []);
  } catch {
    if (state.historyTrendsKey === key) state.historyTrends = [];
  } finally {
    if (state.historyTrendsKey === key) {
      state.isLoadingHistoryTrends = false;
      renderMarketSignals();
    }
  }
}

function applyRatesData(data) {
  state.rates[state.selectedCategory] = data;
  setText('rate-source', data.source || '-');
  renderMarket();
  renderAdvice(data.advice || []);
  renderSelectedItemDetail();
  loadHistoryTrends(data);
  if (state.account.authenticated) {
    refreshAccountData().catch(() => {});
  }
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
    fillChartDaysSelects();
    fillDetailTargetSelect();

    setText('category-title', categoryName(state.categoryMeta.find(c => c.id === state.selectedCategory) || { label: state.selectedCategory }));
    byId('refresh-rates').addEventListener('click', refreshRates);
    byId('refresh-static').addEventListener('click', () => window.location.reload());
    byId('market-search').addEventListener('input', renderMarket);
    byId('search-lots')?.addEventListener('click', searchSellerLots);
    bindAccountEvents();
    ['lot-seller', 'lot-query'].forEach(id => {
      byId(id)?.addEventListener('keydown', event => {
        if (event.key === 'Enter') searchSellerLots();
      });
    });
    byId('detail-target-currency').addEventListener('change', event => {
      state.detailTarget = event.target.value;
      renderSelectedItemDetail();
    });
    document.querySelectorAll('[data-chart-days-select]').forEach(select => {
      select.addEventListener('change', event => updateChartDays(event.target.value));
    });
    document.querySelectorAll('[data-detail-chart]').forEach(button => {
      button.addEventListener('click', () => {
        state.detailChartMetric = button.dataset.detailChart === 'demand' ? 'demand' : 'price';
        renderSelectedItemDetail();
      });
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
        state.historyTrends = [];
        state.historyTrendsKey = '';
        state.isLoadingHistoryTrends = false;
        state.detailDemandCache = {};
        state.detailSeriesCache = {};
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
    const requestedView = new URLSearchParams(window.location.search).get('view');
    if (['market', 'signals', 'lots', 'cabinet'].includes(requestedView)) {
      state.mainView = requestedView;
    }
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
    loadAccountState().then(showVerificationQueryStatus);
    scheduleAutoRefresh();
  } catch (error) {
    setLiveError(error.message || String(error));
  }
}

window.initLiveTrade = initLiveTrade;
