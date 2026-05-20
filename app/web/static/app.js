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
const HISTORY_SERIES_LIMIT = 1500;
const MAIN_VIEW_STORAGE_KEY = 'poe2-main-view';
const PUBLIC_MAIN_VIEWS = ['market', 'signals', 'lots', 'cabinet'];

function loadJsonState(key, fallback) {
  try {
    const value = JSON.parse(localStorage.getItem(key) || '');
    return value && typeof value === 'object' ? value : fallback;
  } catch {
    return fallback;
  }
}

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
  categorySidebarOpen: false,
  activeAdviceTab: 'market',
  crossDeals: [],
  crossDealsMeta: null,
  crossDealsKey: '',
  isLoadingCrossDeals: false,
  activeTrades: [],
  activeTradesKey: '',
  isLoadingActiveTrades: false,
  historyTrends: [],
  historyTrendsKey: '',
  isLoadingHistoryTrends: false,
  aiAnalysis: {
    job: null,
    isRunning: false,
    pollTimer: null,
  },
  aiHistory: {
    items: [],
    isLoading: false,
    error: '',
    loaded: false,
  },
  itemParser: {
    result: null,
    isLoading: false,
    error: '',
    loadingKey: '',
  },
  currencyAnalysis: {
    context: null,
    error: '',
    isLoading: false,
    aiJob: null,
    aiRunning: false,
    pollTimer: null,
  },
  rubMarket: {
    context: null,
    error: '',
    isLoading: false,
    loadedKey: '',
  },
  accountActiveTab: localStorage.getItem('poe2-account-tab') || 'tracking',
  sellerLots: null,
  sellerLotsParams: null,
  sellerLotsCache: {},
  sellerLotMarketCache: {},
  sellerLotProfiles: loadJsonState('poe2-seller-lot-profiles', {}),
  focusedSellerLotId: '',
  isLoadingSellerLots: false,
  sellerLotsAbortController: null,
  sellerLotsRequestId: 0,
  lotSubtab: localStorage.getItem('poe2-lot-subtab') || 'seller',
  baseMarket: null,
  baseMarketParams: null,
  baseMarketCache: {},
  baseMarketHistoryCache: {},
  baseMarketHistoryLoading: {},
  baseMarketError: '',
  focusedBaseMarketId: '',
  isLoadingBaseMarket: false,
  baseMarketAbortController: null,
  baseMarketFilterTimer: null,
  account: {
    authenticated: false,
    user: null,
    pins: [],
    trades: [],
    tradeReport: null,
    notifications: [],
    adminUsers: [],
    adminMetrics: null,
    telegramConfigured: false,
    targetCurrency: localStorage.getItem('poe2-account-target') || 'exalted',
    benchmarkCurrency: localStorage.getItem('poe2-account-benchmark') || 'divine',
    benchmarkRates: {},
    defaultSeller: '',
  },
  isAccountLoading: false,
  autoRefreshMs: Number(localStorage.getItem('poe2-auto-refresh-ms') ?? 30000),
  autoRefreshTimer: null,
  isRefreshing: false,
  isCheckingLatest: false,
  sort: { key: 'name', direction: 'asc' },
};

const preferredTargets = ['exalted', 'divine', 'chaos'];
const CROSS_MIN_VOLUME = 10;
const SELLER_LOT_AUTO_MARKET_LIMIT = 20;
const MARKET_SIGNAL_MIN_VOLUME = 10;
const MARKET_SIGNAL_MEDIUM_VOLUME = 50;
const MARKET_SIGNAL_NOTABLE_CHANGE = 8;
const MARKET_SIGNAL_STRONG_CHANGE = 25;
const MARKET_SIGNAL_TOP_CANDIDATES = 8;
const LEAGUES_REFERENCE_TIMEOUT_MS = 5000;
const STATIC_REFERENCE_TIMEOUT_MS = 5000;

function fallbackTradeLeagues() {
  return [
    { id: 'Fate of the Vaal', text: 'Fate of the Vaal', realm: 'poe2' },
  ];
}

function fallbackStaticCategories() {
  return {
    Currency: [
      { id: 'exalted', text: 'Exalted Orb', text_ru: 'Сфера возвышения', image: null },
      { id: 'divine', text: 'Divine Orb', text_ru: 'Божественная сфера', image: null },
      { id: 'chaos', text: 'Chaos Orb', text_ru: 'Сфера хаоса', image: null },
    ],
  };
}

function fallbackStaticCategoryMeta(categories) {
  return [{
    id: 'Currency',
    label: 'Currency',
    label_ru: 'Валюта',
    count: categories.Currency?.length || 0,
    icon: null,
  }];
}

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
  fillAccountTargetCurrencySelect();
  fillBenchmarkCurrencySelect();
  fillAutoRefreshSelect();
  fillChartDaysSelects();
  renderTargetCurrencyInfo();
  renderCategories();
  renderMarket();
  renderAdvice(state.advice);
  renderSellerLots();
  renderCabinet();
  renderAdminNavigation();
  renderAdminPanel();
  renderAiNavigation();
  renderAiPanel();
  renderAiHistory();
  renderItemParser();
  renderRubMarketPanel();
  renderLotSubtabs();
  renderBaseMarket();
  renderDetailAccountStatus();
  switchMainView(state.mainView);
  renderCategorySidebar();
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

function roundedPriceValue(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return null;
  const rounded = Math.round(number * 100) / 100;
  return Object.is(rounded, -0) ? 0 : rounded;
}

function formatPriceAmount(value) {
  if (value === null || value === undefined || value === '') return '-';
  const number = Number(value);
  if (!Number.isFinite(number)) return String(value);
  if (number > 0 && number < 0.01) return '<0.01';
  const rounded = roundedPriceValue(number);
  if (rounded === null) return String(value);
  if (Math.abs(rounded) >= 1000) {
    return Intl.NumberFormat(state.lang === 'ru' ? 'ru-RU' : 'en-US', { maximumFractionDigits: 2, notation: 'compact' }).format(rounded);
  }
  return Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(2).replace(/0+$/, '').replace(/\.$/, '');
}

function priceInputValue(value) {
  const number = Number(value);
  const rounded = roundedPriceValue(value);
  if (rounded === null) return '';
  if (number > 0 && rounded === 0) return '0.01';
  return Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(2).replace(/0+$/, '').replace(/\.$/, '');
}

function formatChartAmount(value) {
  if (value === null || value === undefined || value === '') return '-';
  const number = Number(value);
  if (!Number.isFinite(number)) return String(value);
  if (number > 0 && number < 0.01) return '<0.01';
  if (Math.abs(number) >= 1000) {
    return Intl.NumberFormat(state.lang === 'ru' ? 'ru-RU' : 'en-US', { maximumFractionDigits: 2, notation: 'compact' }).format(number);
  }
  if (Number.isInteger(number)) return String(number);
  const abs = Math.abs(number);
  const decimals = abs >= 0.01 ? 2 : 6;
  return number.toFixed(decimals).replace(/0+$/, '').replace(/\.$/, '');
}

function chartDecimalsForStep(step) {
  const normalizedStep = Math.abs(Number(step));
  if (!Number.isFinite(normalizedStep) || normalizedStep <= 0) return null;
  let decimals = 0;
  let scaled = normalizedStep;
  while (scaled < 1 && decimals < 6) {
    scaled *= 10;
    decimals += 1;
  }
  return Math.min(6, decimals + 1);
}

function formatChartAmountWithDecimals(value, decimals) {
  if (value === null || value === undefined || value === '') return '-';
  const number = Number(value);
  if (!Number.isFinite(number)) return String(value);
  if (number > 0 && number < 0.01) return '<0.01';
  if (Math.abs(number) >= 1000) {
    return Intl.NumberFormat(state.lang === 'ru' ? 'ru-RU' : 'en-US', { maximumFractionDigits: 2, notation: 'compact' }).format(number);
  }
  if (decimals === null || decimals === undefined) return formatChartAmount(number);
  const cappedDecimals = Math.max(0, Math.min(2, decimals));
  if (Number.isInteger(number) && cappedDecimals <= 0) return String(number);
  return number.toFixed(cappedDecimals).replace(/0+$/, '').replace(/\.$/, '');
}

function chartAmountFormatter(minValue, maxValue, tickCount = 6) {
  const min = Number(minValue);
  const max = Number(maxValue);
  if (!Number.isFinite(min) || !Number.isFinite(max)) return formatChartAmount;
  const step = Math.abs(max - min) / Math.max(1, tickCount);
  const decimals = chartDecimalsForStep(step);
  return value => formatChartAmountWithDecimals(value, decimals);
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

function snapshotLabel(data = {}) {
  if (data.stored) return t('savedSnapshotLabel');
  if (data.cached) return t('cacheLabel');
  return '';
}

function formatSnapshotStamp(data = {}) {
  const createdTs = Number(data.created_ts || 0);
  if (!createdTs) return '-';
  const stamp = new Date(createdTs * 1000).toLocaleTimeString(state.lang === 'ru' ? 'ru-RU' : 'en-US');
  const label = snapshotLabel(data);
  return label ? `${stamp} ${label}` : stamp;
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

function accountCanUseAi() {
  return Boolean(state.account.authenticated && state.account.user?.can_use_ai);
}

function accountFiatRubEnabled() {
  return Boolean(state.account.authenticated && state.account.user?.fiat_rub_enabled);
}

function accountDefaultSeller() {
  return state.account.user?.default_seller_account || state.account.defaultSeller || '';
}

function applyDefaultSellerToSearch({ force = false } = {}) {
  const input = byId('lot-seller');
  const seller = accountDefaultSeller();
  if (!input || !seller) return;
  if (force || !input.value.trim()) {
    input.value = seller;
  }
}

function applyAccountUserPreferences(user) {
  if (user?.account_target_currency) {
    state.account.targetCurrency = user.account_target_currency;
    localStorage.setItem('poe2-account-target', state.account.targetCurrency);
  }
  state.account.defaultSeller = user?.default_seller_account || '';
  applyDefaultSellerToSearch();
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

async function sendJson(url, body, method = 'POST') {
  const response = await fetch(url, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {}),
  });
  const data = await response.json();
  if (!response.ok || data.error) throw new Error(data.error || data.detail || t('tradeError'));
  return data;
}

function accountItemName(item) {
  return state.lang === 'ru' ? (item.item_name_ru || item.item_name) : item.item_name;
}

async function selectedItemPayload(targetOverride = null) {
  if (!state.selectedItemId) return null;
  const entry = findEntry(state.selectedItemId);
  if (!entry) return null;
  const target = targetOverride || selectedTarget();
  let categoryRates = state.rates[state.selectedCategory] || {};
  if (target && categoryRates.target !== target) {
    categoryRates = await ensureRatesForTarget(target);
  }
  const row = rowsById(categoryRates).get(entry.id) || {};
  return {
    league: byId('live-league')?.value || '',
    category: state.selectedCategory,
    item_id: entry.id,
    item_name: entry.text || entryName(entry),
    item_name_ru: entry.text_ru || entry.text || entryName(entry),
    icon_url: entry.image || '',
    target_currency: categoryRates.target || target,
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
  state.account.tradeReport = tradesData.report || null;
  const notificationsData = await fetchAccountJson('/api/account/notifications');
  state.account.notifications = notificationsData.notifications || [];
  state.account.telegramConfigured = Boolean(notificationsData.telegram_configured);
  if (state.account.user?.is_admin) {
    const [adminData, metricsData] = await Promise.all([
      fetchAccountJson('/api/admin/users'),
      fetchAccountJson('/api/admin/metrics'),
    ]);
    state.account.adminUsers = adminData.users || [];
    state.account.adminMetrics = metricsData || null;
  } else {
    state.account.adminUsers = [];
    state.account.adminMetrics = null;
  }
}

async function loadAccountState() {
  state.isAccountLoading = true;
  try {
    const data = await fetchAccountJson('/api/auth/me');
    state.account.authenticated = Boolean(data.authenticated);
    state.account.user = data.user || null;
    applyAccountUserPreferences(state.account.user);
    state.account.pins = [];
    state.account.trades = [];
    state.account.tradeReport = null;
    state.account.notifications = [];
    state.account.adminUsers = [];
    state.account.adminMetrics = null;
    state.account.telegramConfigured = false;
    state.rubMarket.context = null;
    state.rubMarket.error = '';
    state.rubMarket.loadedKey = '';
    if (state.account.authenticated) {
      await loadAccountCollections();
    }
  } catch (error) {
    state.account.authenticated = false;
    state.account.user = null;
    state.account.pins = [];
    state.account.trades = [];
    state.account.tradeReport = null;
    state.account.notifications = [];
    state.account.adminUsers = [];
    state.account.adminMetrics = null;
    state.account.telegramConfigured = false;
    state.rubMarket.context = null;
    state.rubMarket.error = '';
    state.rubMarket.loadedKey = '';
    setAccountStatus(error.message || String(error));
  } finally {
    state.isAccountLoading = false;
    renderCabinet();
    renderAdminNavigation();
    renderAdminPanel();
    renderAiNavigation();
    renderAiPanel();
    renderDetailAccountStatus();
  }
}

async function refreshAccountData(message = '') {
  if (!state.account.authenticated) return;
  await loadAccountCollections();
  renderCabinet();
  renderAdminNavigation();
  renderAdminPanel();
  renderAiNavigation();
  renderAiPanel();
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
    applyAccountUserPreferences(state.account.user);
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
    applyAccountUserPreferences(state.account.user);
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
  let handled = false;
  if (params.get('verified') === '1') {
    switchMainView('cabinet');
    setAccountStatus(t('emailVerified'));
    handled = true;
  } else if (params.get('verify') === 'invalid') {
    switchMainView('cabinet');
    setAccountStatus(t('emailVerificationInvalid'));
    handled = true;
  }
  if (handled && window.location.pathname === '/') {
    params.delete('verified');
    params.delete('verify');
    params.delete('view');
    const query = params.toString();
    window.history.replaceState(null, '', `${window.location.pathname}${query ? `?${query}` : ''}${window.location.hash}`);
  }
}

async function logoutAccount() {
  try {
    await fetchAccountJson('/api/auth/logout', { method: 'POST' });
  } finally {
    clearAiPollTimer();
    clearCurrencyAiPollTimer();
    state.account.authenticated = false;
    state.account.user = null;
    state.account.pins = [];
    state.account.trades = [];
    state.account.tradeReport = null;
    state.account.notifications = [];
    state.account.adminUsers = [];
    state.account.adminMetrics = null;
    state.account.telegramConfigured = false;
    state.currencyAnalysis.aiJob = null;
    state.currencyAnalysis.aiRunning = false;
    state.currencyAnalysis.error = '';
    state.rubMarket.context = null;
    state.rubMarket.error = '';
    state.rubMarket.loadedKey = '';
    state.rubMarket.isLoading = false;
    renderCabinet();
    renderAdminNavigation();
    renderAdminPanel();
    renderAiNavigation();
    renderAiPanel();
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
  try {
    const payload = await selectedItemPayload(accountTargetCurrency());
    if (!payload) {
      setDetailAccountStatus(t('selectItemFirst'));
      return;
    }
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
  if (String(benchmarkCurrency).startsWith('basket:')) {
    try {
      const params = new URLSearchParams({ league, target: targetCurrency, benchmark: benchmarkCurrency, status });
      const response = await fetch(`/api/trade/benchmark?${params.toString()}`);
      const data = await response.json();
      if (!response.ok || data.error) throw new Error(data.error || t('tradeError'));
      const value = Number(data.value);
      state.account.benchmarkRates[key] = Number.isFinite(value) && value > 0 ? value : null;
      return state.account.benchmarkRates[key];
    } catch {
      state.account.benchmarkRates[key] = null;
      return null;
    }
  }
  const params = new URLSearchParams({ league, category: 'Currency', target: targetCurrency, status });
  try {
    let data = null;
    try {
      data = await fetchLatestStoredRates({ league, category: 'Currency', target: targetCurrency, status });
    } catch {
      data = null;
    }
    if (!data) {
      const response = await fetch(`/api/trade/category-rates?${params.toString()}`);
      data = await response.json();
      if (!response.ok || data.error) throw new Error(data.error || t('tradeError'));
    }
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
  let payload = null;
  try {
    payload = await selectedItemPayload(accountTargetCurrency());
  } catch (error) {
    setDetailAccountStatus(error.message || String(error));
    return;
  }
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
    fee_amount: Number(document.querySelector(`[data-pin-fee-amount="${pinId}"]`)?.value || 0) || null,
    fee_currency: pin.target_currency,
    strategy_tag: document.querySelector(`[data-pin-strategy="${pinId}"]`)?.value || '',
    entry_reason: document.querySelector(`[data-pin-entry-reason="${pinId}"]`)?.value || '',
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
      fee_amount: Number(document.querySelector(`[data-trade-fee-amount="${tradeId}"]`)?.value || trade.fee_amount || 0) || null,
      fee_currency: trade.entry_currency,
      exit_reason: document.querySelector(`[data-trade-exit-reason="${tradeId}"]`)?.value || '',
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

async function saveAdminUserPermissions(userId) {
  const card = document.querySelector(`[data-admin-user-card="${userId}"]`);
  if (!card) return;
  try {
    await sendAccountJson(`/api/admin/users/${userId}/permissions`, {
      is_admin: Boolean(card.querySelector('[data-admin-permission="is_admin"]')?.checked),
      can_use_ai: Boolean(card.querySelector('[data-admin-permission="can_use_ai"]')?.checked),
    }, 'PATCH');
    await refreshAccountData(t('adminPermissionsSaved'));
  } catch (error) {
    setAccountStatus(error.message || String(error));
  }
}

async function saveAccountPreferences(payload) {
  if (!state.account.authenticated) return;
  try {
    const data = await sendAccountJson('/api/account/preferences', payload, 'PATCH');
    state.account.user = data.user || state.account.user;
    applyAccountUserPreferences(state.account.user);
    if (Object.prototype.hasOwnProperty.call(payload, 'fiat_rub_enabled') && accountFiatRubEnabled()) {
      state.accountActiveTab = 'rub';
      localStorage.setItem('poe2-account-tab', state.accountActiveTab);
    }
    if (!accountFiatRubEnabled()) {
      state.rubMarket.context = null;
      state.rubMarket.error = '';
      state.rubMarket.loadedKey = '';
      if (state.accountActiveTab === 'rub') {
        state.accountActiveTab = 'tracking';
        localStorage.setItem('poe2-account-tab', state.accountActiveTab);
      }
    }
    renderCabinet();
    setAccountStatus(t('accountPreferencesSaved'));
  } catch (error) {
    setAccountStatus(error.message || String(error));
    renderCabinet();
  }
}

async function saveDefaultSellerFromProfile() {
  await saveAccountPreferences({ default_seller_account: byId('default-seller-account')?.value || '' });
  applyDefaultSellerToSearch({ force: true });
}

async function saveDefaultSellerFromSearch() {
  if (!state.account.authenticated) {
    const status = byId('lot-search-status');
    if (status) status.textContent = t('loginRequiredForSellerProfile');
    return;
  }
  const seller = byId('lot-seller')?.value || '';
  await saveAccountPreferences({ default_seller_account: seller });
  applyDefaultSellerToSearch({ force: true });
  const status = byId('lot-search-status');
  if (status) status.textContent = t('defaultSellerSaved');
}

function bindAccountEvents() {
  byId('login-form')?.addEventListener('submit', handleLogin);
  byId('register-form')?.addEventListener('submit', handleRegister);
  byId('resend-verification')?.addEventListener('click', resendVerification);
  byId('logout-button')?.addEventListener('click', logoutAccount);
  byId('pin-selected')?.addEventListener('click', pinSelectedPosition);
  byId('entry-selected')?.addEventListener('click', markSelectedEntry);
  byId('account-target-currency')?.addEventListener('change', event => {
    state.account.targetCurrency = event.target.value || defaultTarget();
    localStorage.setItem('poe2-account-target', state.account.targetCurrency);
    saveAccountPreferences({ account_target_currency: state.account.targetCurrency });
  });
  byId('benchmark-currency')?.addEventListener('change', event => {
    state.account.benchmarkCurrency = event.target.value || defaultTarget();
    localStorage.setItem('poe2-account-benchmark', state.account.benchmarkCurrency);
    renderCabinet();
  });
  byId('fiat-rub-enabled')?.addEventListener('change', event => {
    saveAccountPreferences({ fiat_rub_enabled: Boolean(event.target.checked) });
  });
  byId('save-default-seller')?.addEventListener('click', saveDefaultSellerFromProfile);
  byId('save-lot-default-seller')?.addEventListener('click', saveDefaultSellerFromSearch);
  byId('refresh-rub-market')?.addEventListener('click', () => loadRubMarket({ refresh: true }));
  byId('cabinet-panel')?.addEventListener('click', event => {
    const tab = event.target.closest('[data-account-tab]');
    if (!tab) return;
    event.preventDefault();
    setAccountTab(tab.dataset.accountTab || 'tracking');
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
    const userId = Number(button.dataset.userId || 0);
    if (action === 'start-trade') startTradeFromPin(pinId);
    if (action === 'remove-pin') deletePin(pinId);
    if (action === 'close-trade') closeTrade(tradeId);
    if (action === 'remove-trade') deleteTrade(tradeId);
    if (action === 'remove-notification') deleteNotification(ruleId);
    if (action === 'toggle-notification') toggleNotification(ruleId);
    if (action === 'test-notification') testNotification(ruleId);
    if (action === 'save-user-permissions') saveAdminUserPermissions(userId);
  });
}

function normalizeAccountTab() {
  if (!state.account.authenticated || (state.accountActiveTab === 'rub' && !accountFiatRubEnabled())) {
    state.accountActiveTab = 'tracking';
  }
  if (!['tracking', 'bases', 'rub'].includes(state.accountActiveTab)) {
    state.accountActiveTab = 'tracking';
  }
}

function setAccountTab(tab) {
  if (tab === 'rub' && !accountFiatRubEnabled()) return;
  state.accountActiveTab = ['tracking', 'bases', 'rub'].includes(tab) ? tab : 'tracking';
  localStorage.setItem('poe2-account-tab', state.accountActiveTab);
  renderCabinet();
  if (state.accountActiveTab === 'rub') {
    loadRubMarket().catch(() => {});
  }
}

function renderAccountTabs() {
  normalizeAccountTab();
  document.querySelectorAll('[data-account-tab]').forEach(button => {
    const tab = button.dataset.accountTab || 'tracking';
    button.classList.toggle('active', tab === state.accountActiveTab);
    button.classList.toggle('is-hidden', tab === 'rub' && !accountFiatRubEnabled());
  });
  document.querySelectorAll('[data-account-tab-panel]').forEach(panel => {
    if (panel.id === 'rub-market-panel') return;
    panel.classList.toggle('d-none', (panel.dataset.accountTabPanel || 'tracking') !== state.accountActiveTab);
  });
}

function priceWithCurrency(value, currency) {
  return value === null || value === undefined || value === '' ? t('priceUnknown') : `${formatPriceAmount(value)} ${currencyLabel(currency)}`;
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
    ${rubEquivalentMeta(market.price, target)}
  `;
}

function renderAccountChart(item) {
  const market = accountMarketForItem(item);
  const request = accountChartRequest(item);
  const cachedSeries = accountChartCachedSeries(item);
  const visibleCachedSeries = hourlyTimedSeries(visibleTimedSeries(cachedSeries));
  const cachedValues = visibleCachedSeries.map(point => point.value);
  const sparklineValues = limitedChartValues(chartValuesForCurrent(market.sparkline || [], market.price, market.change));
  const hasHistory = cachedValues.length >= 2;
  const historyCoversSelection = timedSeriesCoversDays(visibleCachedSeries, selectedChartDays());
  const usesHistory = hasHistory && (
    isBaseMarketPin(item)
    || historyCoversSelection
    || !sparklineValues.length
    || cachedValues.length > sparklineValues.length
  );
  const values = usesHistory ? cachedValues : sparklineValues;
  if (values.length < 2) {
    if (request.itemId && state.accountChartSeriesLoading[request.key]) {
      return `<div class="account-market-chart empty">${loadingMarkup(t('loading'), 'inline')}</div>`;
    }
    return `<div class="account-market-chart empty">${t('chartNoData')}</div>`;
  }
  const historyCurrent = usesHistory ? values[values.length - 1] : market.price;
  const historyDays = usesHistory ? Math.max(1, Math.ceil(timedSeriesSpanDays(visibleCachedSeries))) : values.length;
  return `<div class="account-market-chart">${miniSignalChart(values, usesHistory ? chartBasisText(historyDays) : chartBasisText(values.length), historyCurrent, market.change, {
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

function currencyBucketText(bucket, emptyText = '0') {
  const entries = Object.entries(bucket || {})
    .filter(([, value]) => Number.isFinite(Number(value)) && Number(value) !== 0)
    .sort((left, right) => Math.abs(Number(right[1])) - Math.abs(Number(left[1])));
  if (!entries.length) return emptyText;
  return entries.map(([currency, value]) => priceWithCurrency(value, currency)).join(' · ');
}

function renderStrategyReport(item) {
  return `
    <article>
      <strong>${escapeHtml(item.strategy_tag || t('tradeReportNoStrategy'))}</strong>
      <span>${t('closedTradesCount')}: ${formatAmount(item.closed || 0)} · ${t('tradeReportWinRate')}: ${item.win_rate === null || item.win_rate === undefined ? '-' : formatChange(item.win_rate)}</span>
      <small>${t('tradeReportNominal')}: ${currencyBucketText(item.nominal_by_currency, '-')}</small>
      <small>${t('tradeReportReal')}: ${currencyBucketText(item.real_by_currency, '-')}</small>
    </article>
  `;
}

function renderTradeReportSummary() {
  const container = byId('trade-report-summary');
  if (!container) return;
  const report = state.account.tradeReport;
  if (!report || !report.total) {
    container.innerHTML = '';
    return;
  }
  const strategies = (report.by_strategy || []).slice(0, 4);
  container.innerHTML = `
    <section class="trade-report-panel">
      <div class="cabinet-section-head">
        <div>
          <h3>${t('tradeReportTitle')}</h3>
          <p class="panel-hint">${t('tradeReportHint')}</p>
        </div>
      </div>
      <div class="trade-report-grid">
        <div>
          <span class="summary-label">${t('tradeReportNominal')}</span>
          <strong>${currencyBucketText(report.nominal_closed_by_currency)}</strong>
        </div>
        <div>
          <span class="summary-label">${t('tradeReportReal')}</span>
          <strong>${currencyBucketText(report.real_closed_by_currency)}</strong>
        </div>
        <div>
          <span class="summary-label">${t('tradeReportOpenNow')}</span>
          <strong>${currencyBucketText(report.open_current_by_currency)}</strong>
        </div>
        <div>
          <span class="summary-label">${t('tradeReportFees')}</span>
          <strong>${currencyBucketText(report.fees_by_currency)}</strong>
        </div>
        <div>
          <span class="summary-label">${t('tradeReportWinRate')}</span>
          <strong>${report.win_rate === null || report.win_rate === undefined ? '-' : formatChange(report.win_rate)}</strong>
        </div>
      </div>
      ${strategies.length ? `<div class="trade-report-strategies">${strategies.map(renderStrategyReport).join('')}</div>` : ''}
    </section>
  `;
}

function openTradeCurrentPnl(trade, market) {
  if (trade.current_pnl_available) {
    return {
      available: true,
      amount: trade.current_pnl_amount,
      percent: trade.current_pnl_percent,
      currency: trade.current_pnl_currency,
    };
  }
  const entryPrice = Number(trade.entry_price);
  const quantity = Number(trade.quantity);
  const currentPrice = Number(market?.price);
  const entryCurrency = trade.entry_currency;
  const currentCurrency = market?.target_currency || trade.entry_currency;
  if (!Number.isFinite(entryPrice) || entryPrice <= 0 || !Number.isFinite(quantity) || !Number.isFinite(currentPrice) || currentPrice <= 0 || !entryCurrency || currentCurrency !== entryCurrency) {
    return {
      available: false,
      amount: trade.current_pnl_amount,
      percent: trade.current_pnl_percent,
      currency: trade.current_pnl_currency || entryCurrency,
    };
  }
  return {
    available: true,
    amount: (currentPrice - entryPrice) * quantity,
    percent: ((currentPrice - entryPrice) / entryPrice) * 100,
    currency: entryCurrency,
  };
}

function openTradeRealCurrentPnl(trade, market) {
  if (trade.current_real_pnl_available) {
    return {
      available: true,
      amount: trade.current_real_pnl_amount,
      percent: trade.current_real_pnl_percent,
      currency: trade.current_real_pnl_currency,
    };
  }
  const entryPrice = Number(trade.entry_price);
  const quantity = Number(trade.quantity);
  const currentPrice = Number(market?.price);
  const benchmarkCurrency = trade.benchmark_currency || state.account.benchmarkCurrency || 'divine';
  const isBenchmarkItem = trade.item_id && trade.item_id === benchmarkCurrency;
  const entryBenchmark = isBenchmarkItem ? 1 : Number(trade.entry_benchmark_price);
  const currentBenchmark = isBenchmarkItem ? 1 : Number(trade.current_benchmark_price);
  const entryCurrency = trade.entry_currency;
  const currentCurrency = market?.target_currency || trade.entry_currency;
  if (
    !Number.isFinite(entryPrice) || entryPrice <= 0
    || !Number.isFinite(quantity)
    || !Number.isFinite(currentPrice) || currentPrice <= 0
    || !Number.isFinite(entryBenchmark) || entryBenchmark <= 0
    || !Number.isFinite(currentBenchmark) || currentBenchmark <= 0
    || !entryCurrency
    || currentCurrency !== entryCurrency
  ) {
    return {
      available: false,
      amount: trade.current_real_pnl_amount,
      percent: trade.current_real_pnl_percent,
      currency: trade.current_real_pnl_currency || entryCurrency,
    };
  }
  const nominalRatio = currentPrice / entryPrice;
  const benchmarkRatio = currentBenchmark / entryBenchmark;
  const entryTotal = entryPrice * quantity;
  const currentTotal = currentPrice * quantity;
  const realCurrentTotal = currentTotal / benchmarkRatio;
  return {
    available: true,
    amount: realCurrentTotal - entryTotal,
    percent: (nominalRatio / benchmarkRatio - 1) * 100,
    currency: entryCurrency,
  };
}

function benchmarkSummary(trade, mode) {
  const benchmark = trade.benchmark_currency || 'divine';
  const isBenchmarkItem = trade.item_id && trade.item_id === benchmark;
  const entryBenchmark = isBenchmarkItem ? 1 : trade.entry_benchmark_price;
  const currentBenchmark = isBenchmarkItem ? 1 : (mode === 'closed' ? trade.exit_benchmark_price : trade.current_benchmark_price);
  const change = mode === 'closed' ? trade.benchmark_change_percent : trade.current_benchmark_change_percent;
  const currentLabel = mode === 'closed' ? t('benchmarkExit') : t('benchmarkCurrent');
  if (!entryBenchmark || !currentBenchmark) {
    return `<span>${t('benchmarkBasis')}: ${currencyLabel(benchmark)} · ${t('benchmarkMissing')}</span>`;
  }
  return `
    <span>${t('benchmarkBasis')}: ${currencyLabel(benchmark)}</span>
    <span>${t('benchmarkEntry')}: ${priceWithCurrency(entryBenchmark, trade.entry_currency)}</span>
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
          <input class="form-control form-control-sm" type="number" min="0" step="any" value="${escapeHtml(priceInputValue(priceValue))}" data-pin-entry-price="${pin.id}">
        </label>
        <label class="compact-field">
          <span>${t('quantity')}</span>
          <input class="form-control form-control-sm" type="number" min="0.0001" step="any" value="1" data-pin-quantity="${pin.id}">
        </label>
        <label class="compact-field">
          <span>${t('tradeFee')}</span>
          <input class="form-control form-control-sm" type="number" min="0" step="any" value="" data-pin-fee-amount="${pin.id}">
        </label>
        <label class="compact-field">
          <span>${t('strategyTag')}</span>
          <input class="form-control form-control-sm" value="" data-pin-strategy="${pin.id}" placeholder="${t('strategyTagPlaceholder')}">
        </label>
        <button class="btn btn-primary btn-sm" type="button" data-account-action="start-trade" data-pin-id="${pin.id}">${t('markEntry')}</button>
        <button class="btn btn-outline-light btn-sm" type="button" data-account-action="remove-pin" data-pin-id="${pin.id}">${t('unpinPosition')}</button>
      </div>
      <input class="form-control form-control-sm trade-note-input" value="" data-pin-entry-reason="${pin.id}" placeholder="${t('entryReasonPlaceholder')}">
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
  const currentPnl = openTradeCurrentPnl(trade, market);
  const realCurrentPnl = openTradeRealCurrentPnl(trade, market);
  return `
    <div class="trade-metric-grid">
      <div>
        <span class="summary-label">${t('currentMarketPrice')}</span>
        <strong>${priceWithCurrency(market.price, market.target_currency || trade.entry_currency)}</strong>
      </div>
      <div>
        <span class="summary-label">${t('currentMargin')}</span>
        ${pnlBadge(currentPnl.available, currentPnl.amount, currentPnl.percent, currentPnl.currency, t('currentPnlUnavailable'))}
      </div>
      <div>
        <span class="summary-label">${t('realCurrentMargin')}</span>
        ${pnlBadge(realCurrentPnl.available, realCurrentPnl.amount, realCurrentPnl.percent, realCurrentPnl.currency, t('realPnlUnavailable'))}
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
        ${trade.fee_amount ? `<span>${t('tradeFee')}: ${priceWithCurrency(trade.fee_amount, trade.fee_currency || trade.entry_currency)}</span>` : ''}
        ${trade.strategy_tag ? `<span>${t('strategyTag')}: ${escapeHtml(trade.strategy_tag)}</span>` : ''}
        ${trade.entry_reason ? `<span>${t('entryReason')}: ${escapeHtml(trade.entry_reason)}</span>` : ''}
        ${trade.exit_reason ? `<span>${t('exitReason')}: ${escapeHtml(trade.exit_reason)}</span>` : ''}
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
            <input class="form-control form-control-sm" type="number" min="0" step="any" value="${escapeHtml(priceInputValue(exitPriceValue))}" data-trade-exit-price="${trade.id}">
          </label>
          <label class="compact-field">
            <span>${t('tradeFee')}</span>
            <input class="form-control form-control-sm" type="number" min="0" step="any" value="${escapeHtml(trade.fee_amount || '')}" data-trade-fee-amount="${trade.id}">
          </label>
          <button class="btn btn-primary btn-sm" type="button" data-account-action="close-trade" data-trade-id="${trade.id}">${t('markExit')}</button>
          <button class="btn btn-outline-light btn-sm" type="button" data-account-action="remove-trade" data-trade-id="${trade.id}">${t('deleteTrade')}</button>
        </div>
        <input class="form-control form-control-sm trade-note-input" value="" data-trade-exit-reason="${trade.id}" placeholder="${t('exitReasonPlaceholder')}">
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

function adminFeatureLabel(feature) {
  if (feature === 'market_context') return t('aiFeatureMarketContext');
  if (feature === 'market_analysis') return t('aiTab');
  if (feature === 'currency_analysis') return t('aiFeatureCurrencyAnalysis');
  return feature;
}

function adminQuotaValue(value) {
  return value === null || value === undefined ? t('quotaUnlimited') : formatAmount(value);
}

function renderAdminMetric(label, value, hint = '') {
  return `
    <div>
      <span class="summary-label">${escapeHtml(label)}</span>
      <strong>${escapeHtml(value)}</strong>
      ${hint ? `<small>${escapeHtml(hint)}</small>` : ''}
    </div>
  `;
}

function renderAdminMetrics(metrics) {
  const container = byId('admin-metrics');
  if (!container) return;
  if (!metrics) {
    container.innerHTML = `<p class="text-secondary">${t('adminMetricsEmpty')}</p>`;
    return;
  }
  const quota = metrics.ai_quota || {};
  const usage = metrics.ai_usage || {};
  const users = metrics.users || {};
  container.innerHTML = `
    <div class="admin-summary">
      ${renderAdminMetric(t('aiQuotaRemaining'), adminQuotaValue(quota.remaining), t('aiQuotaRemainingHint'))}
      ${renderAdminMetric(t('aiQuotaUsedToday'), formatAmount(quota.used_today || 0), t('aiQuotaUsedTodayHint'))}
      ${renderAdminMetric(t('aiQuotaDailyLimit'), adminQuotaValue(quota.daily_limit), t('aiQuotaDailyLimitHint'))}
      ${renderAdminMetric(t('aiFailuresToday'), formatAmount(usage.failures_today || 0), t('aiFailuresTodayHint'))}
      ${renderAdminMetric(t('adminUsersTotal'), formatAmount(users.total || 0), t('adminUsersTotalHint'))}
      ${renderAdminMetric(t('adminAiUsers'), formatAmount(users.ai_enabled || 0), t('adminAiUsersHint'))}
    </div>
    <div class="admin-metrics-grid">
      <section class="admin-metric-panel">
        <h3>${t('adminUsageByDay')}</h3>
        <div class="admin-usage-bars">
          ${(usage.daily || []).map(day => {
            const requests = Number(day.requests || 0);
            const max = Math.max(1, ...(usage.daily || []).map(item => Number(item.requests || 0)));
            const height = Math.max(4, Math.round((requests / max) * 56));
            return `
              <div class="admin-usage-day">
                <span class="admin-usage-bar" style="height:${height}px"></span>
                <strong>${formatAmount(requests)}</strong>
                <small>${escapeHtml(day.date || '')}</small>
              </div>
            `;
          }).join('')}
        </div>
      </section>
      <section class="admin-metric-panel">
        <h3>${t('adminTopAiUsers')}</h3>
        ${(usage.top_users_today || []).length
          ? `<div class="admin-activity-list">${usage.top_users_today.map(item => `
            <div class="admin-activity-row">
              <span>${escapeHtml(item.display_name || item.username || '-')}</span>
              <strong>${formatAmount(item.requests || 0)}</strong>
            </div>
          `).join('')}</div>`
          : `<p class="text-secondary">${t('adminNoAiActivity')}</p>`}
      </section>
      <section class="admin-metric-panel admin-recent-panel">
        <h3>${t('adminRecentAiActivity')}</h3>
        ${(usage.recent || []).length
          ? `<div class="admin-activity-list">${usage.recent.map(item => `
            <div class="admin-activity-row">
              <span>${escapeHtml(item.display_name || item.username || '-')} / ${escapeHtml(adminFeatureLabel(item.feature || ''))}</span>
              <strong>${item.success ? t('statusOk') : t('statusFailed')}</strong>
              <small>${formatDateTime(item.created_at)}${item.duration_ms !== null && item.duration_ms !== undefined ? ` / ${formatAmount(item.duration_ms)} ms` : ''}</small>
            </div>
          `).join('')}</div>`
          : `<p class="text-secondary">${t('adminNoAiActivity')}</p>`}
      </section>
    </div>
  `;
}

function renderAdminUserCard(user) {
  const isSelf = Number(user.id) === Number(state.account.user?.id);
  const adminDisabled = isSelf ? 'disabled' : '';
  const aiNote = user.effective_can_use_ai && !user.can_use_ai ? `<span>${t('adminAiImplicit')}</span>` : '';
  return `
    <article class="admin-user-card" data-admin-user-card="${user.id}">
      <div class="admin-user-main">
        <div>
          <strong>${escapeHtml(user.display_name || user.username || '-')}</strong>
          <small>${escapeHtml(user.username || '')}${user.email ? ` / ${escapeHtml(user.email)}` : ''}</small>
        </div>
        <div class="admin-user-badges">
          ${user.is_admin ? `<span>${t('adminBadge')}</span>` : ''}
          ${user.effective_can_use_ai ? `<span>${t('aiAccessBadge')}</span>` : ''}
          ${user.email_verified ? `<span>${t('emailVerifiedBadge')}</span>` : `<span>${t('emailNotVerifiedBadge')}</span>`}
        </div>
      </div>
      <div class="admin-permissions-row">
        <label class="permission-toggle">
          <input type="checkbox" data-admin-permission="is_admin" ${user.is_admin ? 'checked' : ''} ${adminDisabled}>
          <span>${t('adminPermission')}</span>
        </label>
        <label class="permission-toggle">
          <input type="checkbox" data-admin-permission="can_use_ai" ${user.can_use_ai ? 'checked' : ''}>
          <span>${t('aiPermission')}</span>
        </label>
        ${aiNote}
        <button class="btn btn-outline-light btn-sm" type="button" data-account-action="save-user-permissions" data-user-id="${user.id}">${t('savePermissions')}</button>
      </div>
    </article>
  `;
}

function renderAdminPanel() {
  const panel = byId('admin-panel');
  if (!panel) return;
  const isAdmin = Boolean(state.account.user?.is_admin);
  panel.classList.toggle('d-none', !isAdmin);
  renderAdminMetrics(isAdmin ? state.account.adminMetrics : null);
  const list = byId('admin-users-list');
  if (!list) return;
  if (!isAdmin) {
    list.innerHTML = '';
    return;
  }
  list.innerHTML = state.account.adminUsers.length
    ? state.account.adminUsers.map(renderAdminUserCard).join('')
    : `<p class="text-secondary">${t('adminUsersEmpty')}</p>`;
}

function renderAdminNavigation() {
  const isAdmin = Boolean(state.account.user?.is_admin);
  byId('admin-nav-tab')?.classList.toggle('d-none', !isAdmin);
  if (!isAdmin && state.mainView === 'admin') {
    switchMainView('market');
  }
}

function aiActionLabel(action) {
  const key = {
    buy_candidate: 'aiActionBuyCandidate',
    sell_candidate: 'aiActionSellCandidate',
    hold: 'aiActionHold',
    watch: 'aiActionWatch',
    avoid: 'aiActionAvoid',
    insufficient_data: 'aiActionInsufficientData',
  }[action];
  return key ? t(key) : action;
}

function riskLevelLabel(value) {
  const key = {
    low: 'riskLow',
    medium: 'riskMedium',
    high: 'riskHigh',
  }[value || ''];
  return key ? t(key) : (value || '-');
}

function phaseLabel(value) {
  const key = {
    day_0_1: 'phaseDay01',
    day_2_7: 'phaseDay27',
    day_8_21: 'phaseDay821',
    late_league: 'phaseLateLeague',
    unknown: 'phaseUnknown',
  }[value || 'unknown'];
  return t(key || 'phaseUnknown');
}

function renderAiNavigation() {
  const canUseAi = accountCanUseAi();
  byId('ai-nav-tab')?.classList.toggle('d-none', !canUseAi);
  if (!canUseAi && state.mainView === 'ai') {
    switchMainView('market');
  }
}

function renderMainViewHeader() {
  const mapping = {
    market: ['market', 'marketHint'],
    signals: ['detailedSignals', 'marketSignalsHint'],
    ai: ['aiPanelTitle', 'aiPanelHint'],
    lots: ['sellerLotsTitle', 'sellerLotsHint'],
    cabinet: ['cabinetTitle', 'cabinetHint'],
    admin: ['adminPanelTitle', 'adminPanelHint'],
  };
  const [titleKey, hintKey] = mapping[state.mainView] || mapping.market;
  setText('main-view-title', t(titleKey));
  setText('main-view-hint', t(hintKey));
}

function renderAiContextStrip() {
  setText('ai-context-league', byId('live-league')?.value || '-');
  setText('ai-context-category', categoryName(state.categoryMeta.find(item => item.id === state.selectedCategory) || { label: state.selectedCategory }));
  setText('ai-context-target', currencyLabel(selectedTarget()));
  setText('ai-context-status', t(byId('live-status')?.value === 'online' ? 'statusOnline' : 'statusAny'));
}

function renderAiListPanel(title, items, emptyText) {
  const list = Array.isArray(items) ? items.filter(Boolean) : [];
  return `
    <section class="ai-list-panel">
      <h3>${escapeHtml(title)}</h3>
      ${list.length
        ? `<div class="ai-list-tags">${list.map(item => `<span>${escapeHtml(riskFlagLabel(item))}</span>`).join('')}</div>`
        : `<p class="text-secondary">${escapeHtml(emptyText)}</p>`}
    </section>
  `;
}

function renderAiSummary(assessment) {
  const summary = assessment?.summary || {};
  return `
    <section class="ai-summary-card">
      <h3>${t('aiSummary')}</h3>
      <div class="ai-summary-grid">
        <div><span class="summary-label">${t('aiMarketRead')}</span><strong>${escapeHtml(summary.market_read || '-')}</strong></div>
        <div><span class="summary-label">${t('aiOverallRisk')}</span><strong>${escapeHtml(riskLevelLabel(summary.overall_risk))}</strong></div>
        <div><span class="summary-label">${t('aiDataQuality')}</span><strong>${escapeHtml(dataQualityLabel(summary.data_quality))}</strong></div>
        <div><span class="summary-label">${t('aiTimeHorizon')}</span><strong>${escapeHtml(phaseLabel(summary.phase))}</strong></div>
      </div>
    </section>
  `;
}

function aiEvidenceValue(evidence, key) {
  return escapeHtml(evidence?.[key] || '-');
}

function renderAiSignal(signal) {
  const evidence = signal.evidence || {};
  const risks = Array.isArray(signal.risks) ? signal.risks : [];
  const checks = Array.isArray(signal.suggested_checks) ? signal.suggested_checks : [];
  const invalidation = Array.isArray(signal.invalidation) ? signal.invalidation : [];
  return `
    <article class="ai-signal-card ${escapeHtml(signal.action || '')}">
      <div class="ai-signal-head">
        <div>
          <strong>${escapeHtml(signal.item_name || signal.item_id || '-')}</strong>
          <small>${escapeHtml(signal.category || '')}${signal.item_id ? ` / ${escapeHtml(signal.item_id)}` : ''}</small>
        </div>
        <div class="ai-signal-badges">
          <span>${escapeHtml(aiActionLabel(signal.action))}</span>
          <span>${escapeHtml(t('confidence'))}: ${escapeHtml(confidenceLabel(signal.confidence))}</span>
        </div>
      </div>
      <div class="ai-signal-meta">
        ${signal.time_horizon ? `<span>${t('aiTimeHorizon')}: ${escapeHtml(signal.time_horizon)}</span>` : ''}
      </div>
      <p class="ai-signal-body"><strong>${t('aiThesis')}:</strong> ${escapeHtml(signal.thesis || '-')}</p>
      <div class="ai-evidence-grid">
        <div><span>${t('aiEvidencePriceAction')}</span><p>${aiEvidenceValue(evidence, 'price_action')}</p></div>
        <div><span>${t('aiEvidenceLiquidity')}</span><p>${aiEvidenceValue(evidence, 'liquidity')}</p></div>
        <div><span>${t('aiEvidenceDemandDriver')}</span><p>${aiEvidenceValue(evidence, 'demand_driver')}</p></div>
        <div><span>${t('aiEvidenceBenchmarkView')}</span><p>${aiEvidenceValue(evidence, 'benchmark_view')}</p></div>
      </div>
      ${renderAiListPanel(t('aiRisks'), risks, '-')}
      ${renderAiListPanel(t('aiSuggestedChecks'), checks, '-')}
      ${renderAiListPanel(t('aiInvalidation'), invalidation, '-')}
    </article>
  `;
}

function renderAiAssessmentContent(job, emptyText = t('aiAnalysisEmpty')) {
  const assessment = job?.assessment;
  if (!assessment) {
    return `<p class="text-secondary">${escapeHtml(emptyText)}</p>`;
  }
  const signals = Array.isArray(assessment.signals) ? assessment.signals : [];
  const doNotTrade = (assessment.do_not_trade || []).map(item => `${item.item_id || '-'}: ${item.reason || '-'}`);
  return `
    ${renderAiSummary(assessment)}
    <section class="ai-list-panel">
      <h3>${t('aiSignals')}</h3>
      ${signals.length ? `<div class="ai-signals-grid">${signals.map(renderAiSignal).join('')}</div>` : `<p class="text-secondary">${t('aiNoSignals')}</p>`}
    </section>
    ${renderAiListPanel(t('aiMissingData'), assessment.missing_data || [], t('aiNoMissingData'))}
    ${renderAiListPanel(t('aiDoNotTrade'), doNotTrade, '-')}
    ${job.analysis_path ? `<div class="ai-audit-path">${t('aiAuditPath')}: ${escapeHtml(job.analysis_path)}</div>` : ''}
  `;
}

function renderAiAssessment(job) {
  const result = byId('ai-analysis-result');
  if (!result) return;
  result.innerHTML = renderAiAssessmentContent(job);
}

function renderAiPanel() {
  renderAiContextStrip();
  const status = byId('ai-analysis-status');
  const button = byId('run-ai-analysis');
  if (button) button.disabled = Boolean(state.aiAnalysis.isRunning) || !accountCanUseAi();
  if (!accountCanUseAi()) {
    if (status) status.textContent = t('aiAnalysisNoAccess');
    const result = byId('ai-analysis-result');
    if (result) result.innerHTML = `<p class="text-secondary">${t('aiAnalysisNoAccess')}</p>`;
    return;
  }
  const job = state.aiAnalysis.job;
  if (status) {
    if (state.aiAnalysis.isRunning) {
      status.innerHTML = loadingMarkup(t('aiAnalysisRunning'), 'inline');
    } else if (job?.status === 'completed') {
      status.textContent = t('aiAnalysisComplete');
    } else if (job?.status === 'failed') {
      status.textContent = job.error || t('aiAnalysisFailed');
    } else {
      status.textContent = '';
    }
  }
  if (job?.status === 'completed') {
    renderAiAssessment(job);
  } else if (job?.status === 'failed') {
    const result = byId('ai-analysis-result');
    if (result) result.innerHTML = `<p class="text-secondary">${escapeHtml(job.error || t('aiAnalysisFailed'))}</p>`;
  } else if (!job) {
    const result = byId('ai-analysis-result');
    if (result) result.innerHTML = `<p class="text-secondary">${t('aiAnalysisEmpty')}</p>`;
  }
  renderCurrencyAnalysisPanel();
  renderAiHistory();
}

function renderAiHistory() {
  const list = byId('ai-history-list');
  if (!list) return;
  if (!accountCanUseAi()) {
    list.innerHTML = '';
    return;
  }
  if (state.aiHistory.isLoading) {
    list.innerHTML = loadingMarkup(t('aiHistoryLoading'));
    return;
  }
  if (state.aiHistory.error) {
    list.innerHTML = `<p class="text-secondary">${escapeHtml(state.aiHistory.error)}</p>`;
    return;
  }
  if (!state.aiHistory.loaded) {
    list.innerHTML = `<p class="text-secondary">${t('aiHistoryEmpty')}</p>`;
    return;
  }
  if (!state.aiHistory.items.length) {
    list.innerHTML = `<p class="text-secondary">${t('aiHistoryEmpty')}</p>`;
    return;
  }
  list.innerHTML = state.aiHistory.items.map(item => `
    <article class="ai-history-card">
      <div>
        <strong>${escapeHtml([item.league, item.category || item.item, item.target].filter(Boolean).join(' / ') || item.file)}</strong>
        <small>${formatDateTime(item.created_at)} · ${escapeHtml(item.file || '')}</small>
      </div>
      <p>${escapeHtml(item.market_read || t('aiNoSignals'))}</p>
      <div class="pin-meta">
        <span>${t('aiOverallRisk')}: ${escapeHtml(riskLevelLabel(item.overall_risk))}</span>
        <span>${t('aiDataQuality')}: ${escapeHtml(dataQualityLabel(item.data_quality))}</span>
        <span>${t('aiSignals')}: ${formatAmount(item.signals_count || 0)}</span>
      </div>
      ${item.path ? `<div class="ai-audit-path">${t('aiAuditPath')}: ${escapeHtml(item.path)}</div>` : ''}
    </article>
  `).join('');
}

async function loadAiHistory() {
  if (!accountCanUseAi() || state.aiHistory.isLoading) return;
  state.aiHistory.isLoading = true;
  state.aiHistory.error = '';
  renderAiHistory();
  try {
    const data = await fetchAccountJson('/api/ai/history?limit=20');
    state.aiHistory.items = data.analyses || [];
    state.aiHistory.loaded = true;
  } catch (error) {
    state.aiHistory.error = error.message || String(error);
  } finally {
    state.aiHistory.isLoading = false;
    renderAiHistory();
  }
}

function clearAiPollTimer() {
  if (state.aiAnalysis.pollTimer) {
    clearTimeout(state.aiAnalysis.pollTimer);
    state.aiAnalysis.pollTimer = null;
  }
}

async function pollAiAnalysis(jobId) {
  try {
    const job = await fetchAccountJson(`/api/ai/market-analysis/${encodeURIComponent(jobId)}`);
    state.aiAnalysis.job = job;
    state.aiAnalysis.isRunning = ['queued', 'running'].includes(job.status);
    renderAiPanel();
    if (state.aiAnalysis.isRunning) {
      state.aiAnalysis.pollTimer = setTimeout(() => pollAiAnalysis(jobId), 2500);
    }
  } catch (error) {
    state.aiAnalysis.isRunning = false;
    state.aiAnalysis.job = { status: 'failed', error: error.message || String(error) };
    renderAiPanel();
  }
}

async function runAiAnalysis() {
  if (!accountCanUseAi() || state.aiAnalysis.isRunning) return;
  clearAiPollTimer();
  const payload = {
    league: byId('live-league')?.value || '',
    category: state.selectedCategory,
    target: selectedTarget(),
    status: byId('live-status')?.value || 'any',
    league_day: byId('ai-league-day')?.value || null,
    limit: Number(byId('ai-row-limit')?.value || 80),
    max_candidates: Number(byId('ai-max-candidates')?.value || 10),
    refresh: Boolean(byId('ai-refresh-before-analysis')?.checked),
  };
  state.aiAnalysis.isRunning = true;
  state.aiAnalysis.job = { status: 'queued', params: payload };
  renderAiPanel();
  try {
    const job = await sendAccountJson('/api/ai/market-analysis', payload);
    state.aiAnalysis.job = job;
    state.aiAnalysis.isRunning = ['queued', 'running'].includes(job.status);
    renderAiPanel();
    if (job.job_id && state.aiAnalysis.isRunning) {
      state.aiAnalysis.pollTimer = setTimeout(() => pollAiAnalysis(job.job_id), 1200);
    }
  } catch (error) {
    state.aiAnalysis.isRunning = false;
    state.aiAnalysis.job = { status: 'failed', error: error.message || String(error) };
    renderAiPanel();
  }
}

function fillCurrencyAnalysisSelect() {
  const select = byId('currency-analysis-id');
  if (!select) return;
  const entries = state.categories.Currency || [];
  const current = select.value || (state.selectedCategory === 'Currency' && state.selectedItemId) || (hasTarget('divine') ? 'divine' : entries[0]?.id);
  fillSelect(select, entries.map(entry => ({ id: entry.id, text: entryName(entry) })), current);
}

function currencyTrendLabel(value) {
  const key = {
    strengthening: 'currencyTrendStrengthening',
    weakening: 'currencyTrendWeakening',
    sideways: 'currencyTrendSideways',
    unknown: 'currencyTrendUnknown',
  }[value || 'unknown'];
  return t(key || 'currencyTrendUnknown');
}

function volatilityLabel(value) {
  const key = {
    high: 'volatilityHigh',
    medium: 'volatilityMedium',
    low: 'volatilityLow',
    unknown: 'volatilityUnknown',
  }[value || 'unknown'];
  return t(key || 'volatilityUnknown');
}

function dataQualityLabel(value) {
  if (!value) return '-';
  const key = {
    full: 'dataQualityFull',
    good: 'dataQualityGood',
    partial: 'dataQualityPartial',
    poor: 'dataQualityPoor',
    unknown: 'dataQualityUnknown',
  }[value];
  return key ? t(key) : String(value).replaceAll('_', ' ');
}

function currencyChangeCards(changes = {}) {
  const windows = [
    ['1h', 'currencyChange1h'],
    ['6h', 'currencyChange6h'],
    ['24h', 'currencyChange24h'],
    ['72h', 'currencyChange72h'],
    ['7d', 'currencyChange7d'],
  ];
  return `
    <div class="currency-change-grid" aria-label="${t('currencyChangeWindows')}">
      ${windows.map(([key, labelKey]) => {
        const value = optionalFiniteNumber(changes[key]);
        const className = value > 0 ? 'change-up' : value < 0 ? 'change-down' : '';
        return `<div><span class="summary-label">${t(labelKey)}</span><strong class="${className}">${value === null ? '-' : formatChange(value)}</strong></div>`;
      }).join('')}
    </div>
  `;
}

function currencyAnalysisPayload() {
  return {
    league: byId('live-league')?.value || '',
    currency_id: byId('currency-analysis-id')?.value || '',
    target: selectedTarget(),
    status: byId('live-status')?.value || 'any',
    league_day: byId('ai-league-day')?.value || null,
    history_limit: Number(byId('currency-history-limit')?.value || 1500),
    horizon_hours: Number(byId('currency-horizon-hours')?.value || 24),
    forecast_points: Number(byId('currency-forecast-points')?.value || 12),
    refresh: Boolean(byId('currency-refresh-before-analysis')?.checked),
  };
}

function optionalFiniteNumber(value) {
  if (value === null || value === undefined || value === '') return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function renderCurrencyAnalysisContext(context) {
  const result = byId('currency-analysis-result');
  if (!result) return;
  if (!context) {
    result.innerHTML = `<p class="text-secondary">${t('currencyAnalysisEmpty')}</p>`;
    return;
  }
  const currency = context.currency || {};
  const trend = context.trend || {};
  const forecast = context.forecast || {};
  const changes = trend.change_pct || {};
  const history = (context.price_history || [])
    .map(point => ({ ts: Number(point.created_ts || 0), value: Number(point.value) }))
    .filter(point => Number.isFinite(point.ts) && point.ts > 0 && Number.isFinite(point.value) && point.value > 0);
  const forecastPoints = (forecast.points || [])
    .map(point => ({ ts: Number(point.created_ts || 0), value: Number(point.value) }))
    .filter(point => Number.isFinite(point.ts) && point.ts > 0 && Number.isFinite(point.value) && point.value > 0);
  const latestPoint = history[history.length - 1];
  const forecastSeries = latestPoint ? [latestPoint, ...forecastPoints] : forecastPoints;
  const risks = Array.isArray(trend.risk_flags) ? trend.risk_flags : [];
  const change24h = optionalFiniteNumber(trend.change_pct?.['24h']);
  const forecastChange = optionalFiniteNumber(forecast.expected_change_pct);
  result.innerHTML = `
    <section class="ai-summary-card">
      <h3>${t('currencyTrendSummary')}</h3>
      <div class="currency-summary-grid">
        <div><span class="summary-label">${t('currencyLatestPrice')}</span><strong>${currency.latest_price ? `${formatPriceAmount(currency.latest_price)} ${currencyLabel(currency.target)}` : '-'}</strong></div>
        <div><span class="summary-label">${t('currencyTrendDirection')}</span><strong>${escapeHtml(currencyTrendLabel(trend.direction))}</strong></div>
        <div><span class="summary-label">${t('currencyVolatility')}</span><strong>${escapeHtml(volatilityLabel(trend.volatility))}</strong></div>
        <div><span class="summary-label">${t('currencyDataQuality')}</span><strong>${escapeHtml(dataQualityLabel(trend.data_quality))}</strong></div>
        <div><span class="summary-label">${t('currencyHistoryPoints')}</span><strong>${formatAmount(trend.history_points || 0)}</strong></div>
      </div>
      ${currencyChangeCards(changes)}
    </section>
    <section class="currency-analysis-charts">
      <article class="currency-chart-card">
        <h3>${t('currencyTrendChart')}</h3>
        ${miniSignalChart(history.map(point => point.value), t('currencyTrendBasis'), null, change24h, { series: history, changeLabel: t('currencyChange24h') })}
      </article>
      <article class="currency-chart-card">
        <h3>${t('currencyForecastChart')} · ${t('currencyExpectedChange')}: ${Number.isFinite(forecastChange) ? formatChange(forecastChange) : '-'}</h3>
        ${miniSignalChart(forecastSeries.map(point => point.value), t('currencyForecastBasis'), null, forecastChange, { series: forecastSeries, changeLabel: t('currencyExpectedChange') })}
        <p class="currency-forecast-note">${t('currencyForecastDisclaimer')} ${t('currencyForecastConfidence')}: ${escapeHtml(confidenceLabel(forecast.confidence))}.</p>
      </article>
    </section>
    <section class="ai-list-panel">
      <h3>${t('currencyRiskFlags')}</h3>
      ${risks.length ? `<div class="currency-risk-list">${risks.map(item => `<span>${escapeHtml(riskFlagLabel(item))}</span>`).join('')}</div>` : `<p class="text-secondary">${t('currencyNoRisks')}</p>`}
    </section>
  `;
}

function renderCurrencyAiResult() {
  const result = byId('currency-ai-result');
  if (!result) return;
  const job = state.currencyAnalysis.aiJob;
  if (state.currencyAnalysis.aiRunning) {
    result.innerHTML = `<section class="ai-list-panel">${loadingMarkup(t('currencyAiRunning'))}</section>`;
    return;
  }
  if (job?.status === 'completed') {
    result.innerHTML = `<section><h3>${t('currencyAiAdvice')}</h3>${renderAiAssessmentContent(job, '')}</section>`;
  } else if (job?.status === 'failed') {
    result.innerHTML = `<p class="text-secondary">${escapeHtml(job.error || t('aiAnalysisFailed'))}</p>`;
  } else {
    result.innerHTML = '';
  }
}

function renderCurrencyAnalysisPanel() {
  fillCurrencyAnalysisSelect();
  const status = byId('currency-analysis-status');
  const runButton = byId('run-currency-analysis');
  const aiButton = byId('run-ai-currency-analysis');
  if (runButton) runButton.disabled = Boolean(state.currencyAnalysis.isLoading);
  if (aiButton) aiButton.disabled = Boolean(state.currencyAnalysis.aiRunning) || !accountCanUseAi();
  if (status) {
    if (state.currencyAnalysis.isLoading) {
      status.innerHTML = loadingMarkup(t('currencyAnalysisLoading'), 'inline');
    } else if (state.currencyAnalysis.aiRunning) {
      status.innerHTML = loadingMarkup(t('currencyAiRunning'), 'inline');
    } else if (state.currencyAnalysis.error) {
      status.textContent = t('currencyAnalysisFailed');
    } else if (state.currencyAnalysis.context) {
      status.textContent = t('currencyAnalysisReady');
    } else {
      status.textContent = '';
    }
  }
  if (state.currencyAnalysis.error && !state.currencyAnalysis.context) {
    const result = byId('currency-analysis-result');
    if (result) result.innerHTML = `<p class="text-secondary">${escapeHtml(state.currencyAnalysis.error)}</p>`;
  } else {
    renderCurrencyAnalysisContext(state.currencyAnalysis.context);
  }
  renderCurrencyAiResult();
}

function clearCurrencyAiPollTimer() {
  if (state.currencyAnalysis.pollTimer) {
    clearTimeout(state.currencyAnalysis.pollTimer);
    state.currencyAnalysis.pollTimer = null;
  }
}

async function runCurrencyAnalysis() {
  if (state.currencyAnalysis.isLoading) return null;
  clearCurrencyAiPollTimer();
  const payload = currencyAnalysisPayload();
  state.currencyAnalysis.isLoading = true;
  state.currencyAnalysis.aiJob = null;
  state.currencyAnalysis.error = '';
  renderCurrencyAnalysisPanel();
  try {
    const params = new URLSearchParams();
    Object.entries(payload).forEach(([key, value]) => {
      if (value !== null && value !== undefined && value !== '') params.set(key, String(value));
    });
    const response = await fetch(`/api/trade/currency-analysis?${params.toString()}`);
    const context = await response.json();
    if (!response.ok || context.error) {
      const message = response.status === 404
        ? t('currencyAnalysisBackendMissing')
        : (context.error || context.detail || t('currencyAnalysisFailed'));
      throw new Error(message);
    }
    state.currencyAnalysis.context = context;
    return context;
  } catch (error) {
    state.currencyAnalysis.context = null;
    state.currencyAnalysis.error = error.message || String(error);
    return null;
  } finally {
    state.currencyAnalysis.isLoading = false;
    renderCurrencyAnalysisPanel();
  }
}

async function pollAiCurrencyAnalysis(jobId) {
  try {
    const job = await fetchAccountJson(`/api/ai/currency-analysis/${encodeURIComponent(jobId)}`);
    state.currencyAnalysis.aiJob = job;
    if (job.context) state.currencyAnalysis.context = job.context;
    state.currencyAnalysis.aiRunning = ['queued', 'running'].includes(job.status);
    renderCurrencyAnalysisPanel();
    if (state.currencyAnalysis.aiRunning) {
      state.currencyAnalysis.pollTimer = setTimeout(() => pollAiCurrencyAnalysis(jobId), 2500);
    }
  } catch (error) {
    state.currencyAnalysis.aiRunning = false;
    state.currencyAnalysis.aiJob = { status: 'failed', error: error.message || String(error) };
    renderCurrencyAnalysisPanel();
  }
}

async function runAiCurrencyAnalysis() {
  if (!accountCanUseAi() || state.currencyAnalysis.aiRunning) return;
  clearCurrencyAiPollTimer();
  const payload = currencyAnalysisPayload();
  state.currencyAnalysis.aiRunning = true;
  state.currencyAnalysis.aiJob = { status: 'queued', params: payload };
  state.currencyAnalysis.error = '';
  renderCurrencyAnalysisPanel();
  try {
    const job = await sendAccountJson('/api/ai/currency-analysis', payload);
    state.currencyAnalysis.aiJob = job;
    if (job.context) state.currencyAnalysis.context = job.context;
    state.currencyAnalysis.aiRunning = ['queued', 'running'].includes(job.status);
    renderCurrencyAnalysisPanel();
    if (job.job_id && state.currencyAnalysis.aiRunning) {
      state.currencyAnalysis.pollTimer = setTimeout(() => pollAiCurrencyAnalysis(job.job_id), 1200);
    }
  } catch (error) {
    state.currencyAnalysis.aiRunning = false;
    state.currencyAnalysis.aiJob = { status: 'failed', error: error.message || String(error) };
    renderCurrencyAnalysisPanel();
  }
}

function rubMarketTarget() {
  if (hasTarget('divine')) return 'divine';
  return state.account.benchmarkCurrency || selectedTarget() || defaultTarget();
}

function rubMarketKey() {
  return `${byId('live-league')?.value || ''}|${rubMarketTarget()}`;
}

function formatRub(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return '-';
  return new Intl.NumberFormat(state.lang === 'ru' ? 'ru-RU' : 'en-US', {
    style: 'currency',
    currency: 'RUB',
    maximumFractionDigits: number < 1 ? 4 : 2,
  }).format(number);
}

function rubMarketPrice(row) {
  const value = Number(row?.market_price ?? row?.trimmed_median ?? row?.median);
  return Number.isFinite(value) && value > 0 ? value : null;
}

function rubRateFor(currencyId) {
  if (!accountFiatRubEnabled()) return null;
  const row = state.rubMarket.context?.by_currency?.[currencyId];
  return rubMarketPrice(row);
}

function rubEquivalent(value, currencyId) {
  const amount = Number(value);
  const rate = rubRateFor(currencyId);
  if (!Number.isFinite(amount) || amount <= 0 || !rate) return null;
  return amount * rate;
}

function rubEquivalentMeta(value, currencyId) {
  const rubValue = rubEquivalent(value, currencyId);
  if (rubValue === null) return '';
  return `<span>${t('rubEquivalent')}: ${formatRub(rubValue)}</span>`;
}

function rubHistorySeries() {
  return (state.rubMarket.context?.focus_hourly_history || state.rubMarket.context?.focus_history || [])
    .map(point => ({ ts: Number(point.hour_ts || point.created_ts || 0), value: rubMarketPrice(point) }))
    .filter(point => Number.isFinite(point.ts) && point.ts > 0 && Number.isFinite(point.value) && point.value > 0);
}

async function loadRubMarket(options = {}) {
  if (!accountFiatRubEnabled() || state.rubMarket.isLoading) return;
  const key = rubMarketKey();
  if (!options.refresh && state.rubMarket.context && state.rubMarket.loadedKey === key) return;
  state.rubMarket.isLoading = true;
  state.rubMarket.error = '';
  renderRubMarketPanel();
  try {
    const params = new URLSearchParams({
      league: byId('live-league')?.value || '',
      target: rubMarketTarget(),
      refresh: options.refresh ? 'true' : 'false',
      history_days: '30',
    });
    const data = await fetchAccountJson(`/api/account/funpay-rub?${params.toString()}`);
    state.rubMarket.context = data;
    state.rubMarket.loadedKey = key;
  } catch (error) {
    state.rubMarket.error = error.message || String(error);
  } finally {
    state.rubMarket.isLoading = false;
    renderRubMarketPanel();
    renderCabinet();
  }
}

function rubFlowLabel(row) {
  const stockDelta = optionalFiniteNumber(row.listed_stock_delta_last);
  const offersDelta = optionalFiniteNumber(row.offers_delta_last);
  const parts = [];
  if (stockDelta !== null) {
    const label = stockDelta > 0 ? t('rubSupplyAdded') : stockDelta < 0 ? t('rubSupplyReduced') : t('rubSupplyFlat');
    parts.push(`${label}: ${formatAmount(Math.abs(stockDelta))}`);
  }
  if (offersDelta !== null) {
    const label = offersDelta > 0 ? t('rubOffersAdded') : offersDelta < 0 ? t('rubOffersRemoved') : t('rubOffersFlat');
    parts.push(`${label}: ${formatAmount(Math.abs(offersDelta))}`);
  }
  return parts.join(' · ') || '-';
}

function rubSignalText(row) {
  const change = optionalFiniteNumber(row.change_24h_pct);
  const stockDelta = optionalFiniteNumber(row.listed_stock_delta_last);
  const offersDelta = optionalFiniteNumber(row.offers_delta_last);
  if (change === null) return t('rubSignalNeedHistory');
  if (change >= 5 && (stockDelta !== null && stockDelta < 0 || offersDelta !== null && offersDelta < 0)) {
    return t('rubSignalSellWindow');
  }
  if (change <= -5 && (stockDelta !== null && stockDelta > 0 || offersDelta !== null && offersDelta > 0)) {
    return t('rubSignalBuyWindow');
  }
  if (change >= 5) return t('rubSignalRising');
  if (change <= -5) return t('rubSignalFalling');
  return t('rubSignalNeutral');
}

function rubLowMarketBasis(row) {
  const lowOffers = optionalFiniteNumber(row.low_market_offers);
  const totalOffers = optionalFiniteNumber(row.offers);
  const ignored = optionalFiniteNumber(row.ignored_high_offers);
  const lowStock = optionalFiniteNumber(row.low_market_stock);
  const ceiling = optionalFiniteNumber(row.low_market_ceiling);
  const parts = [];
  if (lowOffers !== null && totalOffers !== null) parts.push(`${t('rubLowMarketOffers')}: ${formatAmount(lowOffers)} / ${formatAmount(totalOffers)}`);
  if (lowStock !== null) parts.push(`${t('rubLowMarketStock')}: ${formatAmount(lowStock)}`);
  if (ignored !== null && ignored > 0) parts.push(`${t('rubIgnoredHighOffers')}: ${formatAmount(ignored)}`);
  if (ceiling !== null) parts.push(`${t('rubLowMarketCeiling')}: ${formatRub(ceiling)}`);
  return parts.join(' · ') || t('rubLowMarketFallback');
}

function rubWeekdayLabel(weekday) {
  const index = Number(weekday);
  const keys = ['weekdayMon', 'weekdayTue', 'weekdayWed', 'weekdayThu', 'weekdayFri', 'weekdaySat', 'weekdaySun'];
  return keys[index] ? t(keys[index]) : '-';
}

function rubHourRangeLabel(interval) {
  const rawStart = Number(interval?.start_hour ?? 0);
  const start = Math.max(0, Math.min(23, Number.isFinite(rawStart) ? rawStart : 0));
  const rawEnd = Number(interval?.end_hour ?? start + 1);
  const endRaw = Math.max(1, Math.min(24, Number.isFinite(rawEnd) ? rawEnd : start + 1));
  const end = Math.max(start + 1, endRaw);
  const fmt = hour => `${String(hour).padStart(2, '0')}:00`;
  return `${fmt(start)}-${fmt(end)}`;
}

function rubCalendarConfidenceLabel(value) {
  const key = {
    ok: 'rubCalendarConfidenceOk',
    partial: 'rubCalendarConfidencePartial',
    insufficient: 'rubCalendarConfidenceInsufficient',
  }[value || 'insufficient'];
  return t(key || 'rubCalendarConfidenceInsufficient');
}

function rubCalendarRecommendationCard(kind, data, calendar) {
  if (!data) {
    return `
      <article class="rub-analysis-card rub-calendar-card ${kind}">
        <span class="summary-label">${t(kind === 'sell' ? 'rubSellWindowTitle' : 'rubBuyWindowTitle')}</span>
        <strong>${t('rubCalendarNeedData')}</strong>
        <small>${t('rubCalendarNeedDataHint')}</small>
      </article>
    `;
  }
  const intervals = Array.isArray(data.hour_intervals) ? data.hour_intervals : [];
  const intervalText = intervals.length ? intervals.map(rubHourRangeLabel).join(', ') : t('rubCalendarNoIntervals');
  const avgPrice = optionalFiniteNumber(data.avg_price);
  const sourceText = data.hour_source === 'all_days' ? t('rubCalendarAllDaysHours') : t('rubCalendarWeekdayHours');
  return `
    <article class="rub-analysis-card rub-calendar-card ${kind}">
      <span class="summary-label">${t(kind === 'sell' ? 'rubSellWindowTitle' : 'rubBuyWindowTitle')}</span>
      <strong>${rubWeekdayLabel(data.weekday)} · ${escapeHtml(intervalText)}</strong>
      <small>${t('rubCalendarAvg')}: ${avgPrice === null ? '-' : formatRub(avgPrice)} · ${t('rubCalendarPoints')}: ${formatAmount(data.points || 0)}</small>
      <small>${sourceText} · ${rubCalendarConfidenceLabel(calendar?.confidence)}</small>
    </article>
  `;
}

function renderRubMarketPanel() {
  const panel = byId('rub-market-panel');
  const toggle = byId('fiat-rub-enabled');
  if (toggle) toggle.checked = accountFiatRubEnabled();
  if (!panel) return;
  const shouldShow = accountFiatRubEnabled() && state.accountActiveTab === 'rub';
  panel.classList.toggle('d-none', !shouldShow);
  if (!shouldShow) return;
  const status = byId('rub-market-status');
  if (status) {
    if (state.rubMarket.isLoading) {
      status.innerHTML = loadingMarkup(t('rubMarketLoading'), 'inline');
    } else {
      status.textContent = state.rubMarket.error || '';
    }
  }
  if (!state.rubMarket.context && !state.rubMarket.isLoading && !state.rubMarket.error) {
    loadRubMarket().catch(() => {});
    return;
  }
  const context = state.rubMarket.context || {};
  const focus = context.focus || {};
  const focusPrice = rubMarketPrice(focus);
  const summary = byId('rub-market-summary');
  if (summary) {
    const snapshot = context.snapshot || {};
    summary.innerHTML = `
      <div>
        <span class="summary-label">${t('rubLowMarketRate')}</span>
        <strong>${focusPrice ? formatRub(focusPrice) : '-'}</strong>
      </div>
      <div>
        <span class="summary-label">${t('rubChange24h')}</span>
        <strong class="${Number(focus.change_24h_pct) > 0 ? 'change-up' : Number(focus.change_24h_pct) < 0 ? 'change-down' : ''}">${focus.change_24h_pct === null || focus.change_24h_pct === undefined ? '-' : formatChange(focus.change_24h_pct)}</strong>
      </div>
      <div>
        <span class="summary-label">${t('rubListedStock')}</span>
        <strong>${formatAmount(focus.listed_stock)}</strong>
      </div>
      <div>
        <span class="summary-label">${t('rubSellers')}</span>
        <strong>${formatAmount(focus.seller_count || 0)}</strong>
      </div>
      <div>
        <span class="summary-label">${t('marketSnapshot')}</span>
        <strong>${snapshot.created_at ? formatDateTime(snapshot.created_at) : '-'}</strong>
      </div>
    `;
  }
  const chart = byId('rub-market-chart');
  if (chart) {
    const history = rubHistorySeries();
    chart.innerHTML = history.length >= 2
      ? miniSignalChart(history.map(point => point.value), t('rubHourlyLowMarket'), focusPrice, focus.change_24h_pct, { series: history, changeLabel: t('rubChange24h') })
      : `<div class="account-market-chart empty">${t('rubHistoryNoData')}</div>`;
  }
  const analytics = byId('rub-market-analytics');
  if (analytics) {
    analytics.innerHTML = focusPrice
      ? `
        <article class="rub-analysis-card">
          <span class="summary-label">${t('rubPriceBasis')}</span>
          <strong>${formatRub(focus.best)} - ${formatRub(focus.low_market_ceiling || focusPrice)}</strong>
          <small>${escapeHtml(rubLowMarketBasis(focus))}</small>
        </article>
        <article class="rub-analysis-card">
          <span class="summary-label">${t('rubFlow')}</span>
          <strong>${escapeHtml(rubFlowLabel(focus))}</strong>
          <small>${t('rubFlowProxyHint')}</small>
        </article>
        <article class="rub-analysis-card">
          <span class="summary-label">${t('rubMarketSignal')}</span>
          <strong>${escapeHtml(rubSignalText(focus))}</strong>
          <small>${t('rubMarketSignalHint')}</small>
        </article>
        <article class="rub-analysis-card">
          <span class="summary-label">${t('rubDepth')}</span>
          <strong>${formatAmount(focus.low_market_sellers || focus.seller_count || 0)} / ${formatAmount(focus.online_sellers || 0)}</strong>
          <small>${t('rubDepthHint')}</small>
        </article>
      `
      : `<p class="text-secondary">${t('rubMarketNoData')}</p>`;
  }
  const calendarEl = byId('rub-market-calendar');
  if (calendarEl) {
    const calendar = context.calendar_recommendations || {};
    calendarEl.innerHTML = focusPrice
      ? `
        ${rubCalendarRecommendationCard('buy', calendar.buy, calendar)}
        ${rubCalendarRecommendationCard('sell', calendar.sell, calendar)}
      `
      : '';
  }
  const sourceLink = byId('rub-market-source-link');
  if (sourceLink) {
    sourceLink.href = context.source_url || 'https://funpay.com/chips/209/';
  }
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
    renderTradeReportSummary();
    renderAccountTabs();
    renderRubMarketPanel();
    return;
  }
  fillAccountTargetCurrencySelect();
  fillBenchmarkCurrencySelect();
  renderAccountTabs();
  renderRubMarketPanel();
  setText('account-user-label', state.account.user?.display_name || state.account.user?.username || '');
  const defaultSellerInput = byId('default-seller-account');
  if (defaultSellerInput && document.activeElement !== defaultSellerInput) {
    defaultSellerInput.value = accountDefaultSeller();
  }
  const openTrades = state.account.trades.filter(trade => trade.status !== 'closed');
  const closedTrades = state.account.trades.filter(trade => trade.status === 'closed');
  const basePins = state.account.pins.filter(isBaseMarketPin);
  const regularPins = state.account.pins.filter(pin => !isBaseMarketPin(pin));
  setText('pinned-count', state.account.pins.length);
  setText('open-trades-count', openTrades.length);
  setText('closed-trades-count', closedTrades.length);
  renderTradeReportSummary();
  const pinsList = byId('pins-list');
  if (pinsList) {
    pinsList.innerHTML = regularPins.length
      ? regularPins.map(renderPinCard).join('')
      : `<p class="text-secondary">${t('noPinnedPositions')}</p>`;
  }
  const basePinsList = byId('base-pins-list');
  if (basePinsList) {
    basePinsList.innerHTML = basePins.length
      ? basePins.map(renderPinCard).join('')
      : `<p class="text-secondary">${t('noTrackedBases')}</p>`;
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
  renderAdminPanel();
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
  if (String(target || '').startsWith('basket:')) return t('marketBasketBenchmark');
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

function accountTargetCurrency() {
  const fallback = defaultTarget();
  if (!hasTarget(state.account.targetCurrency)) {
    state.account.targetCurrency = fallback;
    localStorage.setItem('poe2-account-target', state.account.targetCurrency);
  }
  return state.account.targetCurrency || fallback;
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

function benchmarkOptions() {
  return [
    { id: 'basket:liquid-core', text: t('marketBasketBenchmark') },
    ...targetOptions(false),
  ];
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
    { id: '30000', text: t('autoRefresh30s') },
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
  const fallback = 'basket:liquid-core';
  const selected = state.account.benchmarkCurrency && (state.account.benchmarkCurrency.startsWith('basket:') || hasTarget(state.account.benchmarkCurrency))
    ? state.account.benchmarkCurrency
    : fallback;
  state.account.benchmarkCurrency = selected;
  fillSelect(select, benchmarkOptions(), selected);
}

function fillAccountTargetCurrencySelect() {
  const select = byId('account-target-currency');
  if (!select) return;
  fillSelect(select, targetOptions(false), accountTargetCurrency());
}

function fillAutoRefreshSelect() {
  const select = byId('auto-refresh-interval');
  if (!select) return;
  fillSelect(select, autoRefreshOptions(), String(state.autoRefreshMs || 0));
}

function renderCategories() {
  const list = byId('category-list');
  if (!list) return;
  const sidebarOpen = isCategorySidebarOpen();
  list.innerHTML = '';
  state.categoryMeta.forEach(category => {
    const button = document.createElement('button');
    button.type = 'button';
    button.tabIndex = sidebarOpen ? 0 : -1;
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
      state.crossDealsMeta = null;
      state.crossDealsKey = '';
      state.activeTrades = [];
      state.activeTradesKey = '';
      state.historyTrends = [];
      state.historyTrendsKey = '';
      state.isLoadingHistoryTrends = false;
      state.detailDemandCache = {};
      state.detailSeriesCache = {};
      setText('category-title', categoryName(category));
      byId('item-detail-panel')?.classList.add('d-none');
      if (!categorySidebarPinned()) {
        switchMainView('market');
      }
      renderCategories();
      renderMarket();
      renderAdvice((state.rates[state.selectedCategory] || {}).advice || []);
      renderAiPanel();
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
  setText('last-snapshot', formatSnapshotStamp(categoryRates));
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
      <td>${formatPriceAmount(priced.best)}</td>
      <td>${formatPriceAmount(priced.median)}</td>
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
  return `${formatPriceAmount(lot.price_amount)} ${currencyLabel(lot.price_currency)}`;
}

function lotTargetPrice(value, target = selectedTarget()) {
  return value === null || value === undefined ? '-' : `${formatPriceAmount(value)} ${currencyLabel(target)}`;
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
  if (mode === 'base-only') return t('comparisonBaseOnly');
  if (mode === 'type-level-stat-ids') return t('comparisonExactStats');
  if (mode === 'type-level-stat-ids-minus-one') return t('comparisonStatsMinusOne');
  if (mode === 'type-level-loose-stats') return t('comparisonLooseStats');
  return t('comparisonTypeOnly');
}

function sellerLotProfileKey(lot) {
  return lot?.id || [lot?.seller, lot?.base_type, lot?.item_level, lot?.price_amount, lot?.price_currency].filter(Boolean).join(':');
}

function sellerLotProfile(lot) {
  const key = sellerLotProfileKey(lot);
  const profile = key ? state.sellerLotProfiles[key] : null;
  const ranges = profile?.ranges && typeof profile.ranges === 'object' ? profile.ranges : {};
  return {
    important: Array.isArray(profile?.important) ? profile.important : [],
    ignored: Array.isArray(profile?.ignored) ? profile.ignored : [],
    tier: Array.isArray(profile?.tier) ? profile.tier : [],
    ranges,
    baseOnly: Boolean(profile?.baseOnly),
    baseMode: ['required', 'ignored'].includes(profile?.baseMode) ? profile.baseMode : 'default',
  };
}

function persistSellerLotProfiles() {
  localStorage.setItem('poe2-seller-lot-profiles', JSON.stringify(state.sellerLotProfiles));
}

function sellerLotProfileParams(lot) {
  const profile = sellerLotProfile(lot);
  const params = {
    important_stats: profile.important.join(','),
    ignored_stats: profile.ignored.join(','),
    base_mode: profile.baseMode,
  };
  if (profile.baseOnly) {
    params.base_only = 'true';
  }
  if (profile.tier.length) {
    params.tier_stats = profile.tier.join(',');
  }
  const numericRanges = {};
  Object.entries(profile.ranges || {}).forEach(([statId, range]) => {
    const min = String(range?.min ?? '').trim();
    const max = String(range?.max ?? '').trim();
    const payload = {};
    if (min !== '' && Number.isFinite(Number(min))) payload.min = Number(min);
    if (max !== '' && Number.isFinite(Number(max))) payload.max = Number(max);
    if (Object.keys(payload).length) numericRanges[statId] = payload;
  });
  if (Object.keys(numericRanges).length) {
    params.stat_ranges = JSON.stringify(numericRanges);
  }
  return params;
}

function focusedSellerLot() {
  const lots = filteredSellerLots();
  return lots.find(item => item.id === state.focusedSellerLotId) || lots[0] || null;
}

function sellerLotFilterText() {
  return (byId('lot-query')?.value || '').trim().toLowerCase();
}

function sellerLotDisplayLimit() {
  const value = Number(byId('lot-limit')?.value || 200);
  return Number.isFinite(value) && value > 0 ? Math.min(value, 200) : 200;
}

function sellerLotMatchesFilter(lot, filterText) {
  if (!filterText) return true;
  const text = [
    lot.display_name,
    lot.name,
    lot.type_line,
    lot.base_type,
    lot.rarity,
    lot.stash,
    ...(lot.explicit_mods || []),
  ].filter(Boolean).join(' ').toLowerCase();
  return text.includes(filterText);
}

function filteredSellerLots() {
  const lots = state.sellerLots?.lots || [];
  const filterText = sellerLotFilterText();
  return filterText ? lots.filter(lot => sellerLotMatchesFilter(lot, filterText)) : lots;
}

function renderLotSubtabs() {
  const activeTab = state.lotSubtab === 'bases' ? 'bases' : 'seller';
  document.querySelectorAll('[data-lot-tab]').forEach(button => {
    const active = button.dataset.lotTab === activeTab;
    button.classList.toggle('active', active);
    button.setAttribute('aria-pressed', active ? 'true' : 'false');
  });
  document.querySelectorAll('[data-lot-panel]').forEach(panel => {
    panel.classList.toggle('d-none', panel.dataset.lotPanel !== activeTab);
  });
}

function switchLotSubtab(tab) {
  state.lotSubtab = tab === 'bases' ? 'bases' : 'seller';
  localStorage.setItem('poe2-lot-subtab', state.lotSubtab);
  renderLotSubtabs();
  if (state.lotSubtab === 'bases') {
    renderBaseMarket();
    if (!state.baseMarket && !state.isLoadingBaseMarket) {
      refreshBaseMarket(false);
    }
  } else {
    renderSellerLots();
  }
}

function baseMarketRequestParams(forceRefresh = false) {
  const minIlvl = Number(byId('base-market-min-ilvl')?.value || 0);
  const params = {
    league: byId('live-league')?.value || '',
    target: selectedTarget(),
    status: byId('live-status')?.value || 'any',
    q: (byId('base-market-query')?.value || '').trim(),
    limit: byId('base-market-limit')?.value || '40',
  };
  if (Number.isFinite(minIlvl) && minIlvl > 0) params.min_ilvl = String(Math.round(minIlvl));
  if (forceRefresh) params.refresh = 'true';
  return params;
}

function baseMarketLowPrice(row) {
  const value = Number(row?.low ?? row?.best ?? row?.median);
  return Number.isFinite(value) && value > 0 ? value : null;
}

function baseMarketMedianPrice(row) {
  const value = Number(row?.market_median ?? row?.p25 ?? row?.median);
  return Number.isFinite(value) && value > 0 ? value : null;
}

function baseMarketWarning() {
  const errors = state.baseMarket?.errors || [];
  if (errors.some(error => String(error?.error || '').toLowerCase().includes('rate limited'))) {
    return t('baseMarketRateLimited');
  }
  return errors.length ? t('baseMarketPartialError') : '';
}

function baseMarketRowName(row) {
  return state.lang === 'ru' ? (row?.text_ru || row?.text || row?.query_type || '-') : (row?.text || row?.text_ru || row?.query_type || '-');
}

function baseMarketGroupLabel(row) {
  return state.lang === 'ru'
    ? (row?.category_label_ru || t('baseMarketUnknownGroup'))
    : (row?.category_label || row?.category_label_ru || t('baseMarketUnknownGroup'));
}

function baseMarketIconMarkup(row, extraClass = '') {
  const image = row?.image || row?.icon_url || '';
  if (image) {
    return `<span class="base-market-icon ${extraClass}"><img src="${escapeHtml(image)}" alt=""></span>`;
  }
  const key = String(row?.icon_key || 'base').replace(/[^a-z0-9_-]/gi, '').toLowerCase() || 'base';
  return `<span class="base-market-icon base-market-icon-fallback base-market-icon-${escapeHtml(key)} ${extraClass}" aria-hidden="true"></span>`;
}

function baseMarketPriceText(value, target) {
  return value ? lotTargetPrice(value, target) : t('baseMarketNoPrice');
}

function baseMarketRangeText(row, target) {
  const low = Number(row?.p25);
  const high = Number(row?.p75);
  if (Number.isFinite(low) && low > 0 && Number.isFinite(high) && high > 0) {
    return `${lotTargetPrice(low, target)} - ${lotTargetPrice(high, target)}`;
  }
  if (Number.isFinite(low) && low > 0) return lotTargetPrice(low, target);
  if (Number.isFinite(high) && high > 0) return lotTargetPrice(high, target);
  return t('baseMarketNoPrice');
}

function baseMarketErrorLabel(errorText) {
  const text = String(errorText || '').toLowerCase();
  if (!text) return '';
  if (text.includes('rate limited')) return t('baseMarketPricesPending');
  return t('baseMarketPartialError');
}

function baseMarketRowState(row) {
  if (baseMarketLowPrice(row)) return t('baseMarketHasPriceData');
  return baseMarketErrorLabel(row?.error) || t('baseMarketPricesPending');
}

function baseMarketHistoryKey(row) {
  const data = state.baseMarket || {};
  return `${data.league || ''}|${data.target || ''}|${data.status || ''}|${row?.id || ''}`;
}

async function loadBaseMarketHistory(row) {
  const key = baseMarketHistoryKey(row);
  if (!row?.id || state.baseMarketHistoryCache[key] || state.baseMarketHistoryLoading[key]) return;
  state.baseMarketHistoryLoading[key] = true;
  try {
    const params = new URLSearchParams({
      limit: String(HISTORY_SERIES_LIMIT),
      league: state.baseMarket?.league || byId('live-league')?.value || '',
      category: 'ItemBases',
      item_id: row.id,
      target: state.baseMarket?.target || selectedTarget(),
      status: state.baseMarket?.status || byId('live-status')?.value || 'any',
      metric: 'price',
    });
    const response = await fetch(`/api/trade/history/item?${params.toString()}`);
    const data = await response.json();
    if (!response.ok || data.error) throw new Error(data.error || t('cacheLoadError'));
    const seen = new Set();
    const series = (data.series || [])
      .sort((left, right) => Number(left.created_ts || 0) - Number(right.created_ts || 0))
      .map(point => {
        const ts = Number(point.created_ts || 0);
        const value = Number(point.value);
        if (!ts || seen.has(ts) || !Number.isFinite(value) || value <= 0) return null;
        seen.add(ts);
        return { ts, value };
      })
      .filter(Boolean);
    const current = baseMarketLowPrice(row);
    const currentTs = Number(state.baseMarket?.created_ts || 0);
    if (current && currentTs && !seen.has(currentTs)) {
      series.push({ ts: currentTs, value: current });
    }
    state.baseMarketHistoryCache[key] = series;
  } catch {
    state.baseMarketHistoryCache[key] = [];
  } finally {
    delete state.baseMarketHistoryLoading[key];
    renderBaseMarketDetail();
  }
}

function renderBaseMarketSamples(row) {
  const target = state.baseMarket?.target || selectedTarget();
  const lots = row?.sample_lots || [];
  if (!lots.length) return `<p class="text-secondary">${t('baseMarketNoSamples')}</p>`;
  return `
    <div class="base-market-samples">
      ${lots.map(lot => `
        <div class="base-market-sample">
          <strong>${lotTargetPrice(lot.price_target, target)}</strong>
          <small>${escapeHtml([lot.seller, lot.item_level ? `ilvl ${lot.item_level}` : '', lot.stash].filter(Boolean).join(' · '))}</small>
        </div>
      `).join('')}
    </div>
  `;
}

function isBaseMarketPin(pin) {
  return pin?.category === 'ItemBases';
}

function renderBaseMarketDetail() {
  const panel = byId('base-market-detail');
  if (!panel) return;
  const rows = state.baseMarket?.rows || [];
  const row = rows.find(item => item.id === state.focusedBaseMarketId) || rows[0] || null;
  if (!state.baseMarket || !row) {
    panel.innerHTML = '';
    return;
  }
  state.focusedBaseMarketId = row.id || state.focusedBaseMarketId;
  const target = state.baseMarket.target || selectedTarget();
  const key = baseMarketHistoryKey(row);
  const history = state.baseMarketHistoryCache[key] || [];
  if (!state.baseMarketHistoryCache[key] && !state.baseMarketHistoryLoading[key]) {
    loadBaseMarketHistory(row);
  }
  const chart = history.length >= 2
    ? miniSignalChart(history.map(point => point.value), t('baseMarketLowChartBasis'), baseMarketLowPrice(row), null, { series: history, changeLabel: t('baseMarketLowChange') })
    : miniSignalChart(row.sparkline || [], t('baseMarketLowChartBasis'), baseMarketLowPrice(row));
  const rowState = baseMarketRowState(row);
  panel.innerHTML = `
    <article class="base-market-detail-card">
      <div class="base-market-detail-head">
        <div class="base-market-detail-title">
          ${baseMarketIconMarkup(row, 'base-market-icon-lg')}
          <div>
            <strong>${escapeHtml(baseMarketRowName(row))}</strong>
            <small>${escapeHtml([baseMarketGroupLabel(row), row.min_ilvl ? `ilvl >= ${row.min_ilvl}` : ''].filter(Boolean).join(' / '))}</small>
            <small>${escapeHtml(rowState)}</small>
          </div>
        </div>
        <span class="advice-badge">${t('baseMarketPureBasis')}</span>
      </div>
      <div class="base-market-summary">
        <div><span>${t('baseMarketLowPrice')}</span><strong>${baseMarketPriceText(baseMarketLowPrice(row), target)}</strong></div>
        <div><span>${t('baseMarketMedianPrice')}</span><strong>${baseMarketPriceText(baseMarketMedianPrice(row), target)}</strong></div>
        <div><span>${t('marketRange')}</span><strong>${baseMarketRangeText(row, target)}</strong></div>
        <div><span>${t('marketLots')}</span><strong>${formatAmount(row.count || 0)} / ${formatAmount(row.raw_count || row.total || 0)}</strong></div>
      </div>
      ${chart}
      <div class="lot-profile-similar">
        <strong>${t('nearestPrices')}</strong>
        ${renderBaseMarketSamples(row)}
      </div>
      <div class="pin-trade-row">
        <button class="btn btn-outline-light btn-sm" type="button" data-base-track="${escapeHtml(row.id || '')}">${t('trackBaseMarket')}</button>
      </div>
    </article>
  `;
}

async function trackFocusedBaseMarket() {
  const status = byId('base-market-status');
  if (!state.account.authenticated) {
    switchMainView('cabinet');
    setAccountStatus(t('loginRequiredForPin'));
    if (status) status.textContent = t('loginRequiredForPin');
    return;
  }
  const rows = state.baseMarket?.rows || [];
  const row = rows.find(item => item.id === state.focusedBaseMarketId) || rows[0] || null;
  if (!row) return;
  const target = state.baseMarket?.target || selectedTarget();
  try {
    await sendAccountJson('/api/account/pins', {
      league: state.baseMarket?.league || byId('live-league')?.value || '',
      category: 'ItemBases',
      item_id: row.id,
      item_name: row.text || baseMarketRowName(row),
      item_name_ru: row.text_ru || row.text || baseMarketRowName(row),
      icon_url: row.image || '',
      target_currency: target,
      last_price: baseMarketLowPrice(row),
      last_source: state.baseMarket?.source || '',
      note: t('baseMarketPureBasis'),
    });
    state.accountActiveTab = 'bases';
    localStorage.setItem('poe2-account-tab', state.accountActiveTab);
    await refreshAccountData(t('baseTrackSaved'));
    if (status) status.textContent = t('baseTrackSaved');
  } catch (error) {
    if (status) status.textContent = error.message || String(error);
  }
}

function renderBaseMarketRow(row) {
  const target = state.baseMarket?.target || selectedTarget();
  const active = row.id && row.id === state.focusedBaseMarketId;
  const low = baseMarketLowPrice(row);
  const median = baseMarketMedianPrice(row);
  return `
    <button class="base-market-row ${active ? 'active' : ''}" type="button" data-base-market-focus="${escapeHtml(row.id || '')}">
      <div class="base-market-main">
        <div class="base-market-title-line">
          ${baseMarketIconMarkup(row)}
          <strong>${escapeHtml(baseMarketRowName(row))}</strong>
        </div>
        <small>${escapeHtml([baseMarketGroupLabel(row), row.min_ilvl ? `ilvl >= ${row.min_ilvl}` : '', t('baseMarketPureBasis')].filter(Boolean).join(' · '))}</small>
        <small>${escapeHtml(baseMarketRowState(row))}</small>
      </div>
      <div><small class="base-market-label">${t('baseMarketLowPrice')}</small><span>${baseMarketPriceText(low, target)}</span></div>
      <div><small class="base-market-label">${t('baseMarketMedianPrice')}</small><span>${baseMarketPriceText(median, target)}</span></div>
      <div><small class="base-market-label">${t('marketLots')}</small><span>${formatAmount(row.count || 0)}</span></div>
      <div><small class="base-market-label">${t('confidence')}</small><span>${confidenceLabel(row.confidence)}</span></div>
    </button>
  `;
}

function renderBaseMarket() {
  const list = byId('base-market-results');
  const status = byId('base-market-status');
  if (!list) return;
  renderLotSubtabs();
  if (state.isLoadingBaseMarket) {
    list.innerHTML = '';
    renderBaseMarketDetail();
    if (status) status.innerHTML = loadingMarkup(t('baseMarketLoading'), 'inline');
    return;
  }
  if (!state.baseMarket) {
    list.innerHTML = `<p class="text-secondary">${t('baseMarketEmpty')}</p>`;
    renderBaseMarketDetail();
    if (status) status.textContent = state.baseMarketError || '';
    return;
  }
  const rows = state.baseMarket.rows || [];
  if (status) {
    const cached = state.baseMarket.cached || state.baseMarket.stored ? ` · ${t('cacheLabel')}` : '';
    const priced = state.baseMarket.priced_total ?? rows.filter(row => baseMarketLowPrice(row)).length;
    const warning = baseMarketWarning();
    const pending = !priced && warning ? ` · ${t('baseMarketPricesPending')}` : '';
    status.textContent = state.baseMarketError || `${t('baseMarketShown')}: ${formatAmount(rows.length)} / ${formatAmount(state.baseMarket.matched_total || rows.length)} · ${t('baseMarketPriced')}: ${formatAmount(priced)}${cached}${warning ? ` · ${warning}` : ''}${pending}`;
  }
  if (!rows.length) {
    const emptyKey = state.baseMarket.stored === false ? 'baseMarketEmpty' : 'baseMarketNoResults';
    list.innerHTML = `<p class="text-secondary">${t(emptyKey)}</p>`;
    renderBaseMarketDetail();
    return;
  }
  if (!state.focusedBaseMarketId || !rows.some(row => row.id === state.focusedBaseMarketId)) {
    state.focusedBaseMarketId = rows[0]?.id || '';
  }
  list.innerHTML = rows.map(renderBaseMarketRow).join('');
  renderBaseMarketDetail();
}

async function refreshBaseMarket(forceRefresh = true) {
  const status = byId('base-market-status');
  const button = byId('refresh-base-market');
  const params = baseMarketRequestParams(forceRefresh);
  if (!params.league) {
    if (status) status.textContent = t('leaguesLoadError');
    return;
  }
  const searchParams = new URLSearchParams(params);
  const cacheKey = searchParams.toString();
  if (!forceRefresh && state.baseMarketCache[cacheKey] && state.baseMarketCache[cacheKey].stored !== false) {
    state.baseMarket = state.baseMarketCache[cacheKey];
    renderBaseMarket();
    return;
  }
  if (state.baseMarketAbortController) {
    state.baseMarketAbortController.abort();
  }
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), 120000);
  state.baseMarketAbortController = controller;
  state.baseMarketParams = params;
  state.isLoadingBaseMarket = true;
  state.baseMarketError = '';
  if (button) button.disabled = true;
  renderBaseMarket();
  try {
    const response = await fetch(`/api/trade/item-base-market?${searchParams.toString()}`, { signal: controller.signal });
    const data = await response.json();
    if (!response.ok || data.error) throw new Error(data.error || t('tradeError'));
    state.baseMarket = data;
    state.focusedBaseMarketId = data.rows?.[0]?.id || '';
    if (forceRefresh || data.stored !== false || (data.rows || []).length) {
      state.baseMarketCache[cacheKey] = data;
    }
  } catch (error) {
    const isAbort = error?.name === 'AbortError';
    state.baseMarketError = isAbort ? t('baseMarketTimeout') : (error.message || String(error));
    if (status) status.textContent = state.baseMarketError;
    state.baseMarket = state.baseMarket || { rows: [] };
  } finally {
    window.clearTimeout(timeoutId);
    state.isLoadingBaseMarket = false;
    state.baseMarketAbortController = null;
    if (button) button.disabled = false;
    renderBaseMarket();
  }
}

function focusBaseMarketRow(baseId) {
  if (!baseId) return;
  state.focusedBaseMarketId = baseId;
  renderBaseMarket();
}

function statModValueText(mod) {
  const min = Number(mod?.min);
  const max = Number(mod?.max);
  const hasMin = Number.isFinite(min);
  const hasMax = Number.isFinite(max);
  if (hasMin && hasMax && min !== max) return `${formatAmount(min)} - ${formatAmount(max)}`;
  if (hasMax) return formatAmount(max);
  if (hasMin) return formatAmount(min);
  return '-';
}

function statModTierText(mod) {
  const parts = [];
  if (mod?.tier) parts.push(`${t('affixTier')}: ${cleanPoeText(mod.tier)}`);
  if (mod?.level) parts.push(`${t('affixLevel')}: ${formatAmount(mod.level)}`);
  return parts.join(' · ') || '-';
}

function renderFocusedSimilarLots(lot, target) {
  const sampleLots = (lot.similar_lots || []).slice(0, 6);
  if (!sampleLots.length) {
    return `<p class="text-secondary">${t('noSimilarLots')}</p>`;
  }
  return `
    <div class="lot-profile-samples">
      ${sampleLots.map(item => `
        <div class="lot-profile-sample">
          <span>${escapeHtml(cleanPoeText(item.display_name || item.type_line || '-'))}</span>
          <strong>${lotTargetPrice(item.price_target, target)}</strong>
          <small>${escapeHtml([item.seller, item.item_level ? `ilvl ${item.item_level}` : '', item.stash].filter(Boolean).join(' · '))}</small>
        </div>
      `).join('')}
    </div>
  `;
}

function renderSellerLotProfilePanel() {
  const panel = byId('seller-lot-profile-panel');
  if (!panel) return;
  const lot = focusedSellerLot();
  if (!state.sellerLots || !lot) {
    panel.innerHTML = '';
    return;
  }
  state.focusedSellerLotId = lot.id || state.focusedSellerLotId;
  const profile = sellerLotProfile(lot);
  const statMods = (lot.stat_mods || [])
    .filter(mod => mod.id && ['explicit', 'fractured', 'implicit', 'rune', 'desecrated'].includes(mod.type))
    .slice(0, 12);
  const lotName = cleanPoeText(lot.display_name);
  const lotBase = cleanPoeText(lot.base_type || lot.type_line || '');
  const target = lot.target || selectedTarget();
  const market = lot.market || {};
  panel.innerHTML = `
    <div class="lot-stat-profile">
      <div class="lot-stat-profile-head">
        <div>
          <span>${t('sellerStatProfile')}</span>
          <strong>${escapeHtml(lotName)}</strong>
          <small>${escapeHtml([rarityLabel(lot.rarity), lotBase, lot.item_level ? `ilvl ${lot.item_level}` : ''].filter(Boolean).join(' / '))}</small>
        </div>
        <div class="lot-profile-price-strip">
          <span>${t('sellerPrice')}: <strong>${lotNativePrice(lot)}</strong></span>
          <span>${t('currentMarketPrice')}: <strong>${market.pending ? t('marketEvaluating') : lotTargetPrice(market.current, target)}</strong></span>
          <span>${t('marketRange')}: <strong>${lotTargetPrice(market.min, target)} - ${lotTargetPrice(market.p75, target)}</strong></span>
        </div>
      </div>
      <div class="lot-stat-row base-row">
        <div class="lot-stat-main">
          <strong>${t('sellerBaseProperty')}</strong>
          <span>${escapeHtml(lotBase || '-')}</span>
        </div>
        <div class="lot-stat-actions">
          <label class="lot-stat-check">
            <input type="checkbox" data-lot-profile-base="required" data-lot-id="${escapeHtml(lot.id || '')}" ${profile.baseMode !== 'ignored' || profile.baseOnly ? 'checked' : ''}>
            <span>${t('sellerBaseImportant')}</span>
          </label>
          <label class="lot-stat-check">
            <input type="checkbox" data-lot-profile-base-only="true" data-lot-id="${escapeHtml(lot.id || '')}" ${profile.baseOnly ? 'checked' : ''}>
            <span>${t('sellerBaseOnly')}</span>
          </label>
        </div>
      </div>
      ${statMods.length ? statMods.map(mod => {
        const statId = String(mod.id);
        const label = cleanPoeText(mod.text || mod.name || statId);
        const range = profile.ranges[statId] || {};
        return `
          <div class="lot-stat-row">
            <div class="lot-stat-main">
              <span>${escapeHtml(label)}</span>
              <small>${escapeHtml(statModTierText(mod))} · ${t('affixValue')}: ${escapeHtml(statModValueText(mod))}</small>
            </div>
            <div class="lot-stat-actions">
              <label class="lot-stat-check">
                <input type="checkbox" data-lot-profile="important" data-lot-id="${escapeHtml(lot.id || '')}" data-stat-id="${escapeHtml(statId)}" ${profile.important.includes(statId) ? 'checked' : ''}>
                <span>${t('sellerStatImportantShort')}</span>
              </label>
              <label class="lot-stat-check">
                <input type="checkbox" data-lot-profile="ignored" data-lot-id="${escapeHtml(lot.id || '')}" data-stat-id="${escapeHtml(statId)}" ${profile.ignored.includes(statId) ? 'checked' : ''}>
                <span>${t('sellerStatIgnoredShort')}</span>
              </label>
              <label class="lot-stat-check">
                <input type="checkbox" data-lot-profile="tier" data-lot-id="${escapeHtml(lot.id || '')}" data-stat-id="${escapeHtml(statId)}" ${profile.tier.includes(statId) ? 'checked' : ''}>
                <span>${t('sellerStatTierShort')}</span>
              </label>
              <span class="lot-stat-range">
                <input type="number" inputmode="decimal" step="any" data-lot-range="min" data-lot-id="${escapeHtml(lot.id || '')}" data-stat-id="${escapeHtml(statId)}" value="${escapeHtml(range.min ?? '')}" placeholder="${t('affixMin')}">
                <input type="number" inputmode="decimal" step="any" data-lot-range="max" data-lot-id="${escapeHtml(lot.id || '')}" data-stat-id="${escapeHtml(statId)}" value="${escapeHtml(range.max ?? '')}" placeholder="${t('affixMax')}">
              </span>
            </div>
          </div>
        `;
      }).join('') : `<p class="text-secondary">${t('sellerNoStatProperties')}</p>`}
      <div class="lot-profile-similar">
        <strong>${t('nearestPrices')}</strong>
        ${renderFocusedSimilarLots(lot, target)}
      </div>
    </div>
  `;
}

function sellerLotProfilePatch(lot, nextProfile) {
  const key = sellerLotProfileKey(lot);
  const ranges = nextProfile.ranges || {};
  const normalizedRanges = {};
  Object.entries(ranges).forEach(([statId, range]) => {
    const min = String(range?.min ?? '').trim();
    const max = String(range?.max ?? '').trim();
    if (min || max) normalizedRanges[statId] = { min, max };
  });
  const normalized = {
    important: nextProfile.important || [],
    ignored: nextProfile.ignored || [],
    tier: nextProfile.tier || [],
    ranges: normalizedRanges,
    baseOnly: Boolean(nextProfile.baseOnly),
    baseMode: nextProfile.baseMode || 'default',
  };
  if (
    normalized.important.length
    || normalized.ignored.length
    || normalized.tier.length
    || Object.keys(normalized.ranges).length
    || normalized.baseOnly
    || normalized.baseMode !== 'default'
  ) {
    state.sellerLotProfiles[key] = normalized;
  } else {
    delete state.sellerLotProfiles[key];
  }
}

async function recalculateFocusedSellerLot(lot) {
  persistSellerLotProfiles();
  lot.market = { ...(lot.market || {}), pending: true };
  renderSellerLotProfilePanel();
  renderSellerLots();
  const params = state.sellerLotsParams;
  if (params) {
    await fetchSellerLotMarket(lot, params, state.sellerLotsRequestId || Date.now());
  }
}

async function updateSellerLotBaseProfile(lotId, checked) {
  const lot = (state.sellerLots?.lots || []).find(item => item.id === lotId);
  if (!lot) return;
  const current = sellerLotProfile(lot);
  current.baseMode = checked ? 'required' : 'ignored';
  if (!checked) current.baseOnly = false;
  sellerLotProfilePatch(lot, current);
  await recalculateFocusedSellerLot(lot);
}

async function updateSellerLotBaseOnlyProfile(lotId, checked) {
  const lot = (state.sellerLots?.lots || []).find(item => item.id === lotId);
  if (!lot) return;
  const current = sellerLotProfile(lot);
  sellerLotProfilePatch(lot, { ...current, baseOnly: checked, baseMode: checked ? 'required' : current.baseMode });
  await recalculateFocusedSellerLot(lot);
}

async function updateSellerLotPropertyProfile(lotId, statId, mode, checked) {
  const lot = (state.sellerLots?.lots || []).find(item => item.id === lotId);
  if (!lot || !statId) return;
  const current = sellerLotProfile(lot);
  const important = new Set(current.important);
  const ignored = new Set(current.ignored);
  const tier = new Set(current.tier);
  const ranges = { ...(current.ranges || {}) };
  if (mode === 'important') {
    if (checked) {
      important.add(statId);
      ignored.delete(statId);
    } else {
      important.delete(statId);
    }
  } else if (mode === 'ignored') {
    if (checked) {
      ignored.add(statId);
      important.delete(statId);
      tier.delete(statId);
      delete ranges[statId];
    } else {
      ignored.delete(statId);
    }
  } else if (mode === 'tier') {
    if (checked) {
      tier.add(statId);
      important.add(statId);
      ignored.delete(statId);
    } else {
      tier.delete(statId);
    }
  }
  sellerLotProfilePatch(lot, { ...current, important: [...important], ignored: [...ignored], tier: [...tier], ranges });
  await recalculateFocusedSellerLot(lot);
}

async function updateSellerLotRangeProfile(lotId, statId, bound, value) {
  const lot = (state.sellerLots?.lots || []).find(item => item.id === lotId);
  if (!lot || !statId || !['min', 'max'].includes(bound)) return;
  const current = sellerLotProfile(lot);
  const ranges = { ...(current.ranges || {}) };
  const range = { ...(ranges[statId] || {}) };
  const normalizedValue = String(value || '').trim();
  if (normalizedValue) range[bound] = normalizedValue;
  else delete range[bound];
  if (range.min || range.max) {
    ranges[statId] = range;
  } else {
    delete ranges[statId];
  }
  const important = new Set(current.important);
  const ignored = new Set(current.ignored);
  if (ranges[statId]) {
    important.add(statId);
    ignored.delete(statId);
  }
  sellerLotProfilePatch(lot, { ...current, important: [...important], ignored: [...ignored], ranges });
  await recalculateFocusedSellerLot(lot);
}

async function focusSellerLot(lotId) {
  if (!lotId) return;
  state.focusedSellerLotId = lotId;
  renderSellerLotProfilePanel();
  renderSellerLots();
  const lot = focusedSellerLot();
  if (lot?.market?.pending && state.sellerLotsParams) {
    await fetchSellerLotMarket(lot, state.sellerLotsParams, state.sellerLotsRequestId || Date.now());
  }
}

function renderSellerLotPropertySummary(lot) {
  const profile = sellerLotProfile(lot);
  const parts = [];
  if (profile.baseMode === 'required') parts.push(t('sellerBaseImportant'));
  if (profile.baseMode === 'ignored') parts.push(t('sellerBaseIgnored'));
  if (profile.baseOnly) parts.push(t('sellerBaseOnly'));
  if (profile.important.length) parts.push(`${t('sellerStatImportant')}: ${formatAmount(profile.important.length)}`);
  if (profile.ignored.length) parts.push(`${t('sellerStatIgnored')}: ${formatAmount(profile.ignored.length)}`);
  if (profile.tier.length) parts.push(`${t('sellerStatTierFocus')}: ${formatAmount(profile.tier.length)}`);
  if (Object.keys(profile.ranges || {}).length) parts.push(`${t('affixValueRange')}: ${formatAmount(Object.keys(profile.ranges).length)}`);
  return parts.length ? `<span class="lot-card-note">${t('manualProfile')}: ${escapeHtml(parts.join(' · '))}</span>` : '';
}

function renderSellerBaseSummary() {
  const panel = byId('seller-base-summary-panel');
  if (!panel) return;
  const rows = state.sellerLots?.base_summary || [];
  if (!state.sellerLots || !rows.length) {
    panel.innerHTML = '';
    return;
  }
  const target = state.sellerLots.target || selectedTarget();
  panel.innerHTML = `
    <div class="seller-base-summary">
      <div class="seller-base-summary-head">
        <strong>${t('topSellerBases')}</strong>
        <span>${t('topSellerBasesHint')}</span>
      </div>
      <div class="seller-base-grid">
        ${rows.slice(0, 8).map(row => `
          <button class="seller-base-card" type="button" data-base-filter="${escapeHtml(row.base_type || '')}">
            <span>${escapeHtml(cleanPoeText(row.base_type || '-'))}</span>
            <small>${escapeHtml([rarityLabel(row.rarity), row.item_level ? `ilvl ${row.item_level}` : ''].filter(Boolean).join(' / '))}</small>
            <strong>${lotTargetPrice(row.median, target)}</strong>
            <small>${t('averagePrice')}: ${lotTargetPrice(row.avg, target)} · ${t('marketLots')}: ${formatAmount(row.count || 0)}</small>
          </button>
        `).join('')}
      </div>
    </div>
  `;
}

function renderSellerLotStatProfile(lot) {
  const statMods = (lot.stat_mods || [])
    .filter(mod => mod.id && ['explicit', 'fractured', 'implicit', 'rune', 'desecrated'].includes(mod.type))
    .slice(0, 8);
  if (!statMods.length) return '';
  return `<span class="lot-card-note">${t('propertyCount')}: ${formatAmount(statMods.length)}</span>`;
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
  const manualProfile = market.comparison?.manual_profile ? ` · ${t('manualProfile')}` : '';
  const active = lot.id && lot.id === state.focusedSellerLotId;
  return `
    <article class="lot-card ${escapeHtml(verdict.kind || 'unknown')} ${active ? 'active' : ''}" data-lot-focus data-lot-id="${escapeHtml(lot.id || '')}" tabindex="0">
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
          ${renderSellerLotStatProfile(lot)}
          ${renderSellerLotPropertySummary(lot)}
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
            <span class="lot-card-note">${t('confidence')}: ${confidenceLabel(market.confidence)} · ${comparisonLabel(market.comparison?.mode)}${manualProfile}</span>
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
          <button class="lot-focus-button" type="button" data-lot-focus data-lot-id="${escapeHtml(lot.id || '')}">${t('openLotDetails')}</button>
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
    renderSellerBaseSummary();
    renderSellerLotProfilePanel();
    return;
  }
  if (!state.sellerLots) {
    list.innerHTML = `<p class="text-secondary">${t('sellerLotsEmpty')}</p>`;
    renderSellerBaseSummary();
    renderSellerLotProfilePanel();
    return;
  }
  const filteredLots = filteredSellerLots();
  const lots = filteredLots.slice(0, sellerLotDisplayLimit());
  const status = byId('lot-search-status');
  if (status) {
    const total = state.sellerLots.matched_total ?? state.sellerLots.total ?? state.sellerLots.lots?.length ?? 0;
    const shown = Math.min(filteredLots.length, sellerLotDisplayLimit());
    status.textContent = `${t('marketLots')}: ${formatAmount(shown)} / ${formatAmount(total)} · ${t('sellerLocalFilterHint')} · ${t('autoMarketLimit')}: ${formatAmount(Math.min(SELLER_LOT_AUTO_MARKET_LIMIT, state.sellerLots.lots?.length || 0))}`;
  }
  if (!filteredLots.length) {
    list.innerHTML = `<p class="text-secondary">${t('sellerLotsNoResults')}</p>`;
    renderSellerBaseSummary();
    renderSellerLotProfilePanel();
    return;
  }
  if (!state.focusedSellerLotId || !filteredLots.some(lot => lot.id === state.focusedSellerLotId)) {
    state.focusedSellerLotId = lots[0]?.id || '';
  }
  list.innerHTML = lots.map(renderSellerLotCard).join('');
  renderSellerBaseSummary();
  renderSellerLotProfilePanel();
}

function renderItemParser() {
  const result = byId('item-parser-result');
  const status = byId('item-parser-status');
  if (!result) return;
  if (status) {
    if (state.itemParser.isLoading) {
      status.innerHTML = loadingMarkup(t(state.itemParser.loadingKey || 'itemParserLoading'), 'inline');
    } else {
      status.textContent = state.itemParser.error || '';
    }
  }
  const payload = state.itemParser.result;
  const parsed = payload?.parsed || payload;
  if (!parsed) {
    result.innerHTML = '';
    return;
  }
  const hint = parsed.pricing_hint || {};
  const market = payload?.market || null;
  const sampleLots = payload?.sample_lots || [];
  const target = payload?.target || selectedTarget();
  result.innerHTML = `
    <article class="item-parser-card">
      <div class="pin-title">
        <span class="category-placeholder"></span>
        <div>
          <strong>${escapeHtml(parsed.display_name || '-')}</strong>
          <small>${escapeHtml([parsed.rarity, parsed.item_level ? `ilvl ${parsed.item_level}` : ''].filter(Boolean).join(' / '))}</small>
        </div>
      </div>
      <div class="pin-meta">
        <span>${t('parserPricingMode')}: ${escapeHtml(hint.mode || '-')}</span>
        <span>${t('confidence')}: ${confidenceLabel(hint.confidence)}</span>
        <span>${t('affixes')}: ${formatAmount(parsed.mod_count || 0)}</span>
      </div>
      ${(parsed.mods || []).length ? `<div class="item-parser-mods">${parsed.mods.slice(0, 8).map(mod => `<span>${escapeHtml(mod)}</span>`).join('')}</div>` : ''}
      ${market ? `
        <div class="item-parser-market">
          <div>
            <span class="summary-label">${t('itemMarketEstimate')}</span>
            <strong>${lotTargetPrice(market.current, target)}</strong>
          </div>
          <div>
            <span class="summary-label">${t('marketRange')}</span>
            <strong>${lotTargetPrice(market.min, target)} - ${lotTargetPrice(market.p75, target)}</strong>
          </div>
          <div>
            <span class="summary-label">${t('marketLots')}</span>
            <strong>${formatAmount(market.count || 0)} / ${formatAmount(market.candidate_count || market.total || 0)}</strong>
          </div>
          <div>
            <span class="summary-label">${t('confidence')}</span>
            <strong>${confidenceLabel(market.confidence)}</strong>
          </div>
        </div>
        <p class="text-secondary">${comparisonLabel(market.comparison?.mode)} · ${t('itemMarketEstimateHint')}</p>
        ${sampleLots.length ? `<div class="item-parser-samples">${sampleLots.slice(0, 5).map(lot => `
          <span>${escapeHtml(lot.display_name || lot.type_line || '-')} · ${lotTargetPrice(lot.price_target, target)}</span>
        `).join('')}</div>` : ''}
      ` : `<p class="text-secondary">${t('itemParserResultHint')}</p>`}
    </article>
  `;
}

async function parsePastedItem() {
  const text = byId('item-parser-text')?.value || '';
  if (!text.trim()) {
    state.itemParser.error = t('itemParserTextRequired');
    renderItemParser();
    return;
  }
  state.itemParser.isLoading = true;
  state.itemParser.error = '';
  state.itemParser.loadingKey = 'itemParserLoading';
  renderItemParser();
  try {
    const data = await sendJson('/api/trade/item-text/parse', { text });
    state.itemParser.result = data;
  } catch (error) {
    state.itemParser.error = error.message || String(error);
    state.itemParser.result = null;
  } finally {
    state.itemParser.isLoading = false;
    state.itemParser.loadingKey = '';
    renderItemParser();
  }
}

async function pricePastedItem() {
  const text = byId('item-parser-text')?.value || '';
  if (!text.trim()) {
    state.itemParser.error = t('itemParserTextRequired');
    renderItemParser();
    return;
  }
  state.itemParser.isLoading = true;
  state.itemParser.error = '';
  state.itemParser.loadingKey = 'itemPricingLoading';
  renderItemParser();
  try {
    const data = await sendJson('/api/trade/item-text/price', {
      text,
      league: byId('live-league')?.value || '',
      target: selectedTarget(),
      status: byId('live-status')?.value || 'any',
    });
    state.itemParser.result = data;
  } catch (error) {
    state.itemParser.error = error.message || String(error);
    state.itemParser.result = null;
  } finally {
    state.itemParser.isLoading = false;
    state.itemParser.loadingKey = '';
    renderItemParser();
  }
}

async function fetchSellerLotMarket(lot, params, requestId) {
  if (!lot.id || state.sellerLotsRequestId !== requestId) return;
  const profileParams = sellerLotProfileParams(lot);
  const marketParams = new URLSearchParams({
    league: params.league,
    seller: params.seller,
    lot_id: lot.id,
    target: params.target,
    status: params.status,
    ...profileParams,
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
    targetLot.similar_lots = data.sample_lots || targetLot.similar_lots || [];
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
  const queue = lots.filter(lot => lot.id).slice(0, SELLER_LOT_AUTO_MARKET_LIMIT);
  const workers = [0, 1].map(async () => {
    while (queue.length && state.sellerLotsRequestId === requestId) {
      const lot = queue.shift();
      await fetchSellerLotMarket(lot, params, requestId);
    }
  });
  await Promise.allSettled(workers);
  const status = byId('lot-search-status');
  if (state.sellerLotsRequestId === requestId && status && state.sellerLots) {
    const total = state.sellerLots.matched_total ?? state.sellerLots.total ?? state.sellerLots.lots?.length ?? 0;
    status.textContent = `${t('marketLots')}: ${formatAmount(total)} · ${t('autoMarketLimit')}: ${formatAmount(Math.min(SELLER_LOT_AUTO_MARKET_LIMIT, lots.length))}`;
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
  const limit = '200';
  const params = { league, seller, target, status: liveStatus, limit };
  state.sellerLotsParams = params;
  const searchParams = new URLSearchParams({ ...params, analyze: 'false' });
  const cacheKey = searchParams.toString();
  if (state.sellerLotsCache[cacheKey]) {
    state.sellerLots = state.sellerLotsCache[cacheKey];
    state.focusedSellerLotId = filteredSellerLots()[0]?.id || state.sellerLots.lots?.[0]?.id || '';
    if (status) status.textContent = `${t('marketLots')}: ${formatAmount(state.sellerLots.matched_total ?? state.sellerLots.total ?? state.sellerLots.lots?.length ?? 0)} · ${t('cacheLabel')} · ${t('sellerLocalFilterHint')}`;
    renderSellerLots();
    state.sellerLotsRequestId = Date.now();
    loadSellerLotMarkets(params, state.sellerLotsRequestId);
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
    state.focusedSellerLotId = data.lots?.[0]?.id || '';
    state.sellerLotsCache[cacheKey] = data;
    if (status) {
      const cacheLabel = data.cached ? ` · ${t('cacheLabel')}` : '';
      const timeoutLabel = data.analysis_timed_out ? ` · ${t('partialResults')}` : '';
      const fetchedLabel = data.fetched_total && data.total && data.fetched_total < data.total ? ` · ${t('sellerFetched')}: ${formatAmount(data.fetched_total)} / ${formatAmount(data.total)}` : '';
      status.textContent = `${t('marketLots')}: ${formatAmount(data.matched_total ?? data.total ?? data.lots?.length ?? 0)}${fetchedLabel}${cacheLabel}${timeoutLabel} · ${t('sellerLocalFilterHint')}`;
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

function adviceEntryName(itemId, preferredName = '') {
  const normalizedName = String(preferredName || '');
  const isMissingName = !normalizedName || normalizedName.toLowerCase() === 'none' || normalizedName === itemId;
  if (!itemId) return isMissingName ? '' : normalizedName;
  const entry = findAnyEntry(itemId);
  if (entry && isMissingName) return entryName(entry);
  return normalizedName || itemId;
}

function entryIcon(entry) {
  return entry?.image || '';
}

function itemTitleMarkup(name, icon) {
  return `<span class="advice-item-title">${icon ? `<img src="${escapeHtml(icon)}" alt="">` : ''}<span>${escapeHtml(name)}</span></span>`;
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
  const league = byId('live-league').value;
  const status = byId('live-status').value;
  const cached = state.detailRates[key];
  let stored = null;
  try {
    stored = await fetchLatestStoredRates({
      league,
      category: state.selectedCategory,
      target,
      status,
      sinceTs: Number(cached?.created_ts || 0),
    });
  } catch {
    stored = null;
  }
  if (stored) {
    state.detailRates[key] = stored;
    return stored;
  }
  if (cached) return cached;

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
      limit: String(HISTORY_SERIES_LIMIT),
      league: request.league,
      category: request.category,
      item_id: request.itemId,
      target: request.target,
      status: request.status,
      metric: 'price',
    });
    const response = await fetch(`/api/trade/history/item?${params.toString()}`);
    const data = await response.json();
    if (!response.ok || data.error) throw new Error(data.error || t('cacheLoadError'));
    const seen = new Set();
    const series = (data.series || [])
      .filter(point => point && Number(point.created_ts || 0) > 0)
      .sort((left, right) => Number(left.created_ts || 0) - Number(right.created_ts || 0))
      .map(point => {
        const createdTs = Number(point.created_ts || 0);
        if (seen.has(createdTs)) return null;
        seen.add(createdTs);
        const value = Number(point.value);
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
    limit: String(HISTORY_SERIES_LIMIT),
    league: currentData.league || byId('live-league')?.value || '',
    category: currentData.category || state.selectedCategory,
    item_id: itemId,
    target: currentData.target || selectedTarget(),
    status: currentData.status || byId('live-status')?.value || 'any',
    metric,
  });
  const response = await fetch(`/api/trade/history/item?${params.toString()}`);
  const data = await response.json();
  if (!response.ok || data.error) throw new Error(data.error || t('cacheLoadError'));
  const currentRow = rowsById(currentData).get(itemId);
  const currentValue = metric === 'demand' ? Number(currentRow?.volume) : rateValue(currentRow);
  const points = [...(data.series || [])];
  if (currentValue > 0 && Number(currentData?.created_ts || 0) > 0) {
    points.push({ created_ts: currentData.created_ts, value: currentValue });
  }
  const sortedPoints = points
    .filter(point => point && Number(point.created_ts || 0) > 0)
    .sort((left, right) => Number(left.created_ts || 0) - Number(right.created_ts || 0));
  const seen = new Set();
  const series = sortedPoints
    .map(point => {
      const createdTs = Number(point.created_ts || 0);
      if (seen.has(createdTs)) return null;
      seen.add(createdTs);
      const value = Number(point.value);
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
  const yValueFormatter = chartAmountFormatter(min, max, gridY.length - 1);
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
      ${gridY.map(y => `<text class="detail-chart-y-label" x="${leftPad - 8}" y="${(y + 4).toFixed(2)}" text-anchor="end">${yValueFormatter(valueAtY(y))}</text>`).join('')}
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
  const yValueFormatter = chartAmountFormatter(scale ? min * scale : min, scale ? max * scale : max, gridY.length - 1);
  const valueLabels = canScaleValues ? [gridY[0], gridY[2], gridY[4]].map(y => (
    `<text class="advice-chart-y-label" x="${leftPad - 7}" y="${(y + 3).toFixed(2)}" text-anchor="end">${yValueFormatter(valueAtY(y) * scale)}</text>`
  )).join('') : '';
  const displayCurrent = Number.isFinite(absoluteCurrent) && absoluteCurrent > 0 ? absoluteCurrent : data[data.length - 1];
  const firstValue = data[0];
  const numericChange = Number(changeValue);
  const change = Number.isFinite(numericChange) ? numericChange : (firstValue ? ((data[data.length - 1] - firstValue) / firstValue) * 100 : null);
  const changeLabel = options.changeLabel || t('sevenDayChange');
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
      <div class="advice-chart-label"><span>${t('currentPoint')}: ${yValueFormatter(displayCurrent)}</span><span>${escapeHtml(changeLabel)}: ${formatChange(change)}</span></div>
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
    setText('detail-value', `${formatPriceAmount(row.best)} ${currencyLabel(target)}`);
    setText('detail-median', `${formatPriceAmount(row.median)} ${currencyLabel(target)}`);
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

function allowedMainViews() {
  const views = [...PUBLIC_MAIN_VIEWS];
  if (state.account.user?.is_admin) views.push('admin');
  if (accountCanUseAi()) views.push('ai');
  return views;
}

function categorySidebarPinned() {
  return state.mainView === 'market' || state.mainView === 'signals';
}

function isCategorySidebarOpen() {
  return categorySidebarPinned() || state.categorySidebarOpen;
}

function renderCategorySidebar() {
  const shell = document.querySelector('.app-shell');
  if (!shell) return;
  const pinned = categorySidebarPinned();
  const open = isCategorySidebarOpen();
  shell.classList.toggle('categories-drawer-pinned', pinned);
  shell.classList.toggle('categories-drawer-open', open);
  shell.classList.toggle('categories-drawer-collapsed', !open);
  const toggle = byId('category-sidebar-toggle');
  if (toggle) {
    toggle.setAttribute('aria-expanded', String(open));
    toggle.setAttribute('aria-label', open ? t('collapseCategories') : t('expandCategories'));
    toggle.title = open ? t('collapseCategories') : t('expandCategories');
    const icon = toggle.querySelector('.category-sidebar-toggle-icon');
    if (icon) icon.textContent = open ? '‹' : '›';
  }
  const list = byId('category-list');
  if (list) {
    list.setAttribute('aria-hidden', String(!open));
    if ('inert' in list) {
      list.inert = !open;
    }
    list.querySelectorAll('button').forEach(button => {
      button.tabIndex = open ? 0 : -1;
    });
  }
}

function renderMainControls() {
  document.querySelectorAll('[data-main-control-views]').forEach(element => {
    const views = String(element.dataset.mainControlViews || '')
      .split(/\s+/)
      .filter(Boolean);
    element.classList.toggle('view-hidden', !views.includes(state.mainView));
  });
}

function switchMainView(view) {
  state.mainView = allowedMainViews().includes(view) ? view : 'market';
  if (!categorySidebarPinned()) {
    state.categorySidebarOpen = false;
  }
  document.querySelectorAll('.main-view-tab').forEach(button => {
    button.classList.toggle('active', button.dataset.mainTab === state.mainView);
  });
  document.querySelectorAll('[data-main-view]').forEach(element => {
    element.classList.toggle('view-hidden', element.dataset.mainView !== state.mainView);
  });
  renderMainControls();
  if (state.mainView === 'signals' && state.activeAdviceTab === 'cross') loadCrossCurrencyDeals();
  if (state.mainView === 'lots') {
    renderLotSubtabs();
    if (state.lotSubtab === 'bases') {
      renderBaseMarket();
      if (!state.baseMarket && !state.isLoadingBaseMarket) {
        refreshBaseMarket(false);
      }
    } else {
      renderSellerLots();
    }
  }
  if (state.mainView === 'cabinet') renderCabinet();
  if (state.mainView === 'admin') renderAdminPanel();
  if (state.mainView === 'ai') {
    renderAiPanel();
    if (accountCanUseAi() && !state.aiHistory.loaded && !state.aiHistory.isLoading) {
      loadAiHistory().catch(() => {});
    }
  }
  renderCategorySidebar();
  renderMainViewHeader();
  if (window.location.pathname === '/') {
    const params = new URLSearchParams(window.location.search);
    if (state.mainView === 'market' || state.mainView === 'cabinet') {
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
    ${renderRecipeSignalSection()}
    ${renderHistoryTrendSection()}
    <div class="market-signal-board">
      ${renderMarketSignalGroup(t('marketDrops'), drops, 'drop', t('noMarketDrops'))}
      ${renderMarketSignalGroup(t('marketRises'), rises, 'rise', t('noMarketRises'))}
      ${renderMarketSignalGroup(t('marketLowLiquidity'), lowLiquidity, 'risk', t('noMarketLowLiquidity'))}
    </div>
  `;
}

function renderRecipeSignalSection() {
  const recipes = (state.rates[state.selectedCategory] || {}).recipes || {};
  const opportunities = recipes.opportunities || [];
  const setCosts = recipes.set_costs || [];
  if (!opportunities.length && !setCosts.length && !recipes.known_recipes && !recipes.known_sets) return '';
  return `
    <section class="recipe-signal-section">
      <h3>${t('recipeSignals')}</h3>
      ${opportunities.length
        ? `<div class="recipe-signal-list">${opportunities.slice(0, 8).map(renderRecipeSignal).join('')}</div>`
        : `<p class="text-secondary">${t('noRecipeSignals')}</p>`}
      ${setCosts.length
        ? `<div class="recipe-signal-list">${setCosts.slice(0, 6).map(renderRecipeSetCost).join('')}</div>`
        : ''}
    </section>
  `;
}

function renderRecipeSignal(item) {
  const severity = item.severity || 'watch';
  const rawSourceName = state.lang === 'ru' ? item.source_name_ru : item.source_name_en;
  const rawResultName = state.lang === 'ru' ? item.result_name_ru : item.result_name_en;
  const sourceName = adviceEntryName(item.source, rawSourceName);
  const resultName = adviceEntryName(item.result, rawResultName);
  return `
    <article class="advice-card ${severity}">
      <div class="advice-card-layout">
        <div class="advice-card-content">
          <div class="advice-title-row"><span class="advice-badge">${t('recipeSignal')}</span><strong>${escapeHtml(sourceName || item.source)} → ${escapeHtml(resultName || item.result)}</strong></div>
          <p>${item.input_count} × ${escapeHtml(sourceName || item.source)} → ${escapeHtml(resultName || item.result)} · ${t('profit')}: ${formatPriceAmount(item.profit)} ${currencyLabel(item.target)} (${formatChange(Number(item.margin || 0) * 100)})</p>
          <div class="deal-meta">
            <span>${t('executionQuality')}: ${escapeHtml(executionQualityLabel(item.execution?.quality))}</span>
            <span>${t('minVolume')}: ${formatAmount(item.execution?.volume || 0)}</span>
          </div>
        </div>
      </div>
    </article>
  `;
}

function renderRecipeSetCost(item) {
  const label = state.lang === 'ru' ? item.label_ru : item.label_en;
  const components = (item.components || []).map(component => {
    const rawName = state.lang === 'ru' ? component.source_name_ru : component.source_name_en;
    const name = adviceEntryName(component.source, rawName);
    return `${component.input_count} × ${name || component.source}`;
  });
  return `
    <article class="advice-card watch">
      <div class="advice-card-layout">
        <div class="advice-card-content">
          <div class="advice-title-row"><span class="advice-badge">${t('recipeEntrySet')}</span><strong>${escapeHtml(label || item.set_id || '-')}</strong></div>
          <p>${t('entrySetCost')}: ${formatPriceAmount(item.set_cost)} ${currencyLabel(item.target)} · ${escapeHtml(components.join(' + '))}</p>
          <div class="deal-meta">
            <span>${t('executionQuality')}: ${escapeHtml(executionQualityLabel(item.execution?.quality))}</span>
            <span>${t('minVolume')}: ${formatAmount(item.execution?.volume || 0)}</span>
          </div>
        </div>
      </div>
    </article>
  `;
}

function renderMarketHealthSection(rows) {
  const total = (state.categories[state.selectedCategory] || []).length;
  const priced = rows.length;
  const high = rows.filter(item => liquidityKind(item.volume) === 'high').length;
  const medium = rows.filter(item => liquidityKind(item.volume) === 'medium').length;
  const low = rows.filter(item => item.volume > 0 && liquidityKind(item.volume) === 'low').length;
  const strong = rows.filter(item => Math.abs(item.change) >= MARKET_SIGNAL_STRONG_CHANGE).length;
  const executable = rows.filter(item => item.execution?.executable).length;
  const risky = rows.filter(item => (item.execution?.risk_flags || []).length).length;
  return `
    <section class="market-health-grid">
      <div>
        <span class="summary-label">${t('marketCoverage')}</span>
        <strong>${formatAmount(priced)} / ${formatAmount(total)}</strong>
      </div>
      <div>
        <span class="summary-label">${t('executableSignals')}</span>
        <strong>${formatAmount(executable)}</strong>
      </div>
      <div>
        <span class="summary-label">${t('riskyRows')}</span>
        <strong>${formatAmount(risky)}</strong>
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
      <small>${formatPriceAmount(item.previousValue)} → ${formatPriceAmount(item.currentValue)} ${currencyLabel(item.target)}</small>
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
            <span>${t('value')}: ${formatPriceAmount(item.value)} ${currencyLabel(item.target)}</span>
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
          <p>${formatPriceAmount(item.value)} ${currencyLabel(item.target)} · <span class="${changeClass}">${formatChange(item.change)}</span></p>
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
      <p>${action}: ${formatPriceAmount(item.value)} ${currencyLabel(item.target)} (${formatChange(item.change)})</p>
      <div class="deal-meta"><span>${t('volume')}: ${formatAmount(item.volume)}</span><span>${t('offers')}: ${formatAmount(item.row.offers || 0)}</span></div>
    `, miniSignalChart(item.row.sparkline || [], t('priceChartBasis'), item.value, item.change));
    list.appendChild(card);
  });
}

function renderOperationSignals() {
  const list = byId('advice-list-ops');
  if (!list) return;
  const maxSteps = Number(byId('chain-max-steps')?.value || 5);
  const operations = state.advice.filter(item => Number(item.path_steps || 1) <= maxSteps && Number(item.profit || 0) > 0);
  if (operations.length) {
    renderAdviceList(list, operations, t('noAdvice'));
    return;
  }
  list.innerHTML = '';
  list.innerHTML = `<p class="text-secondary">${t('noMarketChains')}</p>`;
}

function renderActiveTradeOperation(item) {
  return `
    <article class="advice-card watch">
      <div class="advice-card-layout">
        <div class="advice-card-content">
          <div class="advice-title-row"><span class="advice-badge">${t('watchLabel')}</span><strong>${itemTitleMarkup(item.name, item.image)}</strong></div>
          <p>${t('buyFor')} ${formatPriceAmount(item.buy.value)} ${currencyLabel(item.buy.target)} → ${t('sellFor')} ${formatPriceAmount(item.sell.value)} ${currencyLabel(item.sell.target)}</p>
          <div class="deal-meta">
            <span>${t('spread')}: ${formatPriceAmount(item.profit)} ${currencyLabel(selectedTarget())} (${formatChange(item.margin * 100)})</span>
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
    const rawSourceName = state.lang === 'ru' ? item.source_name_ru : item.source_name_en;
    const rawResultName = state.lang === 'ru' ? item.result_name_ru : item.result_name_en;
    const sourceName = adviceEntryName(item.source, rawSourceName);
    const resultName = adviceEntryName(item.result, rawResultName);
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
        ${entryIcon(sourceEntry) ? `<img src="${escapeHtml(entryIcon(sourceEntry))}" alt="">` : ''}
        <span>${escapeHtml(sourceName)}</span>
        <span class="advice-arrow">→</span>
        ${entryIcon(resultEntry) ? `<img src="${escapeHtml(entryIcon(resultEntry))}" alt="">` : ''}
        <span>${escapeHtml(resultName)}</span>
      </span>
    `;
  }
  return itemTitleMarkup(sourceName || resultName || '', entryIcon(sourceEntry) || entryIcon(resultEntry));
}

function executionQualityLabel(quality) {
  if (quality === 'good') return t('executionGood');
  if (quality === 'partial') return t('executionPartial');
  if (quality === 'poor') return t('executionPoor');
  return quality || '-';
}

function riskFlagLabel(flag) {
  const labels = {
    missing_price: t('riskMissingPrice'),
    missing_volume: t('riskMissingVolume'),
    missing_listing_count: t('riskMissingListingCount'),
    low_volume: t('riskLowVolume'),
    thin_listings: t('riskThinListings'),
    wide_spread: t('riskWideSpread'),
    large_move_low_volume: t('riskLargeMoveLowVolume'),
    price_fixing_risk: t('riskPriceFixing'),
    sparkline_not_price: t('riskSparklineNotPrice'),
    stale_snapshot: t('riskStaleSnapshot'),
    short_history: t('riskShortHistory'),
    high_volatility: t('riskHighVolatility'),
  };
  return labels[flag] || String(flag || '-').replaceAll('_', ' ');
}

function emotionRiskText(item) {
  if (item.execution?.risk_flags?.length) {
    const flags = item.execution.risk_flags.slice(0, 3).map(riskFlagLabel).join('; ');
    return state.lang === 'ru'
      ? `Исполнимость: ${executionQualityLabel(item.execution.quality)}. Риски: ${flags}.`
      : `Execution: ${executionQualityLabel(item.execution.quality)}. Risks: ${flags}.`;
  }
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
      return `${item.input_count} × ${sourceName} → ${resultName} (${item.path_steps} шаг.): прибыль ${formatPriceAmount(item.profit)} ${target}, маржа ${formatChange(item.margin * 100)}, минимальный объем ${formatAmount(item.min_volume)}. ${emotionRiskText(item)}`;
    }
    const stepLabel = item.path_steps === 1 ? 'step' : 'steps';
    return `${item.input_count} x ${sourceName} -> ${resultName} (${item.path_steps} ${stepLabel}): profit ${formatPriceAmount(item.profit)} ${target}, margin ${formatChange(item.margin * 100)}, minimum volume ${formatAmount(item.min_volume)}. ${emotionRiskText(item)}`;
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
    const meta = state.crossDealsMeta || {};
    const errors = Array.isArray(meta.errors) && meta.errors.length
      ? `<p class="text-secondary">${t('cycleErrors')}: ${formatAmount(meta.errors.length)}</p>`
      : '';
    list.innerHTML = `<p class="text-secondary">${t('noCrossDeals')}</p>${errors}`;
    return;
  }
  if (state.crossDealsMeta) {
    const meta = state.crossDealsMeta;
    list.innerHTML = `
      <p class="text-secondary">
        ${t('currencyCycleBasis')}: ${formatAmount(meta.edge_count || 0)} / ${formatAmount(meta.pair_count || 0)} ${t('scannedPairs')},
        ${t('afterBuffer')}: ${formatAmount((meta.fee_pct || 0) * 100)}%
      </p>
    `;
  }
  state.crossDeals.forEach(cycle => {
    const card = document.createElement('article');
    card.className = `advice-card ${cycle.severity || 'weak'}`;
    const badge = cycle.severity === 'signal' ? t('signalLabel') : t('weakSignalLabel');
    const route = (cycle.route || []).map(currencyMarkup).join('<span class="advice-arrow">→</span>');
    const stepRows = (cycle.steps || []).map((step, index) => `
      <div class="chain-step">
        <strong>${t('step')} ${index + 1}</strong>
        <span>${currencyMarkup(step.from)} → ${currencyMarkup(step.to)} · ${t('exchangeRate')}: ${formatPriceAmount(step.effective_rate || step.rate)}</span>
        <small>${t('volume')}: ${formatAmount(step.available_from || 0)} ${currencyLabel(step.from)} · ${t('offers')}: ${formatAmount(step.offer_count || 0)}</small>
      </div>
    `).join('');
    renderAdviceCard(card, `
      <div class="advice-title-row"><span class="advice-badge">${badge}</span><strong class="advice-path">${route}</strong></div>
      <div class="deal-meta">
        <span>${t('start')}: ${formatPriceAmount(cycle.start_amount)} ${currencyLabel(cycle.route?.[0] || selectedTarget())}</span>
        <span>${t('finish')}: ${formatPriceAmount(cycle.finish_amount)} ${currencyLabel(cycle.route?.[0] || selectedTarget())}</span>
        <span>${t('profit')}: ${formatPriceAmount(cycle.profit)} ${currencyLabel(cycle.route?.[0] || selectedTarget())} (${formatChange(cycle.margin * 100)})</span>
        <span>${t('minVolume')}: ${formatAmount(cycle.min_volume || 0)}</span>
      </div>
      <div class="chain-steps">${stepRows}</div>
    `);
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
  const maxSteps = Math.max(2, Number(byId('chain-max-steps')?.value || 5));
  return `${league}|currency-cycles|${selectedTarget()}|${status}|${maxSteps}|${availableTargetIds().join(',')}`;
}

function multiTargetDealsKey() {
  const league = byId('live-league')?.value || '';
  const status = byId('live-status')?.value || '';
  return `${league}|${state.selectedCategory}|${selectedTarget()}|${status}|${availableTargetIds().join(',')}`;
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
              <td>${formatPriceAmount(item.buy.value)} ${currencyLabel(item.buy.target)}</td>
              <td>${formatPriceAmount(item.sell.value)} ${currencyLabel(item.sell.target)}</td>
              <td>${renderMarketBasis(item)}</td>
              <td class="${item.profit > 0 ? 'change-up' : ''}">${formatPriceAmount(item.profit)} ${currencyLabel(selectedTarget())} (${formatChange(item.margin * 100)})</td>
              <td>${item.prices.map(price => `${formatPriceAmount(price.value)} ${currencyLabel(price.target)}`).join(' / ')}</td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    </div>
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
    state.activeTradesKey = key;
  } catch {
    state.activeTrades = [];
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
    state.crossDealsMeta = null;
    state.crossDealsKey = key;
    renderCrossDeals();
    return;
  }
  state.isLoadingCrossDeals = true;
  renderCrossDeals();
  try {
    const params = new URLSearchParams({
      league: byId('live-league')?.value || '',
      base: selectedTarget(),
      targets: targets.join(','),
      status: 'online',
      max_steps: String(Math.max(2, Number(byId('chain-max-steps')?.value || 5))),
      min_margin: '0.001',
      fee_pct: '0.003',
      min_volume: '1',
      limit: '30',
    });
    const response = await fetch(`/api/trade/currency-cycles?${params.toString()}`);
    const data = await response.json();
    if (!response.ok || data.error) throw new Error(data.error || t('tradeError'));
    state.crossDeals = data.cycles || [];
    state.crossDealsMeta = data;
    state.crossDealsKey = key;
  } catch {
    state.crossDeals = [];
    state.crossDealsMeta = null;
    state.crossDealsKey = key;
  } finally {
    state.isLoadingCrossDeals = false;
    renderCrossDeals();
  }
}

// Data loading

function currentRatesContext(category = state.selectedCategory, target = selectedTarget()) {
  return {
    league: byId('live-league')?.value || '',
    category,
    target,
    status: byId('live-status')?.value || 'any',
  };
}

function ratesContextMatches(data, context) {
  return (
    (!data.league || data.league === context.league)
    && (!data.category || data.category === context.category)
    && (!data.target || data.target === context.target)
    && (!data.status || data.status === context.status)
  );
}

async function fetchLatestStoredRates({ league, category, target, status, sinceTs = 0 }) {
  if (!league || !category || !target || !status) return null;
  const params = new URLSearchParams({ league, category, target, status });
  if (Number(sinceTs) > 0) params.set('since_ts', String(Number(sinceTs)));
  const response = await fetch(`/api/trade/category-rates/latest?${params.toString()}`);
  const data = await response.json();
  if (!response.ok || data.error) throw new Error(data.error || t('cacheLoadError'));
  if (data.unchanged) return null;
  if ((!data.stored && !data.cached) || !Array.isArray(data.rows) || !data.rows.length) return null;
  return data;
}

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
  const category = data.category || state.selectedCategory;
  const previousTs = Number((state.rates[category] || {}).created_ts || 0);
  const currentTs = Number(data.created_ts || 0);
  state.rates[category] = data;
  if (currentTs > previousTs) {
    state.crossDealsKey = '';
    state.activeTradesKey = '';
    state.account.benchmarkRates = {};
  }
  const contextPrefix = `${data.league || byId('live-league')?.value || ''}|${category}|`;
  Object.keys(state.detailRates).forEach(key => {
    if (key.startsWith(contextPrefix) && state.detailRates[key]?.target === data.target) {
      delete state.detailRates[key];
    }
  });
  setText('rate-source', data.source || '-');
  renderMarket();
  renderAdvice(data.advice || []);
  renderSelectedItemDetail();
  loadHistoryTrends(data);
  if (state.account.authenticated) {
    refreshAccountData().catch(() => {});
  }
}

async function loadLatestCachedRates(options = {}) {
  if (state.isCheckingLatest || (options.onlyIfNew && state.isRefreshing)) return false;
  const category = state.selectedCategory;
  const context = currentRatesContext(category);
  if (!context.league || !context.target || !context.status) return false;
  const currentTs = Number((state.rates[category] || {}).created_ts || 0);
  state.isCheckingLatest = true;
  try {
    const data = await fetchLatestStoredRates({ ...context, sinceTs: options.onlyIfNew ? currentTs : 0 });
    if (!data || category !== state.selectedCategory || !ratesContextMatches(data, context)) {
      return false;
    }
    if (options.onlyIfNew && currentTs > 0 && Number(data.created_ts || 0) <= currentTs) return false;
    applyRatesData(data);
    if (!options.silent) {
      const statusEl = byId('rate-status');
      if (statusEl) statusEl.textContent = t('savedSnapshotLoaded');
    }
    return true;
  } catch {
    return false;
  } finally {
    state.isCheckingLatest = false;
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
      if (state.mainView === 'lots' && state.lotSubtab === 'bases') {
        refreshBaseMarket(false);
      } else {
        loadLatestCachedRates({ onlyIfNew: true, silent: true });
      }
    }
  }, state.autoRefreshMs);
}

async function fetchJsonWithTimeout(url, timeoutMs = 0) {
  const controller = timeoutMs > 0 ? new AbortController() : null;
  const timer = controller ? setTimeout(() => controller.abort(), timeoutMs) : null;
  try {
    const response = await fetch(url, controller ? { signal: controller.signal } : undefined);
    const data = await response.json().catch(() => ({}));
    return { response, data };
  } finally {
    if (timer) clearTimeout(timer);
  }
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
    setText('last-snapshot', formatSnapshotStamp(data));
    applyRatesData(data);
    statusEl.textContent = snapshotLabel(data);
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
    const [leaguesResult, staticResult] = await Promise.all([
      fetchJsonWithTimeout('/api/trade/leagues', LEAGUES_REFERENCE_TIMEOUT_MS).catch(error => ({ error })),
      fetchJsonWithTimeout('/api/trade/static', STATIC_REFERENCE_TIMEOUT_MS).catch(error => ({ error })),
    ]);
    const leaguesResponse = leaguesResult.response;
    const leaguesData = leaguesResult.data || {};
    const staticResponse = staticResult.response;
    const staticData = staticResult.data || {};
    const leaguesLoadFailed = Boolean(leaguesResult.error) || !leaguesResponse?.ok || leaguesData.error;
    const staticLoadFailed = Boolean(staticResult.error) || !staticResponse?.ok || staticData.error;
    state.leagues = leaguesLoadFailed ? fallbackTradeLeagues() : (leaguesData.leagues || []);
    if (!state.leagues.length) state.leagues = fallbackTradeLeagues();
    state.categories = staticLoadFailed ? fallbackStaticCategories() : (staticData.categories || {});
    state.categoryMeta = staticLoadFailed ? fallbackStaticCategoryMeta(state.categories) : (staticData.category_meta || []);
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
    byId('category-sidebar-toggle')?.addEventListener('click', () => {
      state.categorySidebarOpen = !isCategorySidebarOpen();
      renderCategorySidebar();
    });
    byId('market-search').addEventListener('input', renderMarket);
    byId('search-lots')?.addEventListener('click', searchSellerLots);
    document.querySelectorAll('[data-lot-tab]').forEach(button => {
      button.addEventListener('click', () => switchLotSubtab(button.dataset.lotTab));
    });
    byId('refresh-base-market')?.addEventListener('click', () => refreshBaseMarket(true));
    byId('base-market-results')?.addEventListener('click', event => {
      const target = event.target.closest('[data-base-market-focus]');
      if (!target) return;
      event.preventDefault();
      focusBaseMarketRow(target.dataset.baseMarketFocus || '');
    });
    byId('base-market-detail')?.addEventListener('click', event => {
      const target = event.target.closest('[data-base-track]');
      if (!target) return;
      event.preventDefault();
      trackFocusedBaseMarket();
    });
    byId('lot-results')?.addEventListener('click', event => {
      const target = event.target.closest('[data-lot-focus]');
      if (!target) return;
      event.preventDefault();
      focusSellerLot(target.dataset.lotId || '');
    });
    byId('lot-results')?.addEventListener('keydown', event => {
      if (!['Enter', ' '].includes(event.key)) return;
      const target = event.target.closest('[data-lot-focus]');
      if (!target) return;
      event.preventDefault();
      focusSellerLot(target.dataset.lotId || '');
    });
    byId('seller-lot-profile-panel')?.addEventListener('change', event => {
      const control = event.target.closest('[data-lot-profile], [data-lot-profile-base], [data-lot-profile-base-only], [data-lot-range]');
      if (!control) return;
      const lotId = control.dataset.lotId || '';
      const statId = control.dataset.statId || '';
      if (control.dataset.lotProfileBaseOnly) {
        updateSellerLotBaseOnlyProfile(lotId, control.checked);
      } else if (control.dataset.lotProfileBase) {
        updateSellerLotBaseProfile(lotId, control.checked);
      } else if (control.dataset.lotProfile) {
        updateSellerLotPropertyProfile(lotId, statId, control.dataset.lotProfile, control.checked);
      } else if (control.dataset.lotRange) {
        updateSellerLotRangeProfile(lotId, statId, control.dataset.lotRange, control.value);
      }
    });
    byId('seller-base-summary-panel')?.addEventListener('click', event => {
      const button = event.target.closest('[data-base-filter]');
      if (!button) return;
      event.preventDefault();
      const input = byId('lot-query');
      if (input) input.value = button.dataset.baseFilter || '';
      state.focusedSellerLotId = '';
      renderSellerLots();
    });
    byId('parse-item-text')?.addEventListener('click', parsePastedItem);
    byId('price-item-text')?.addEventListener('click', pricePastedItem);
    byId('run-ai-analysis')?.addEventListener('click', runAiAnalysis);
    byId('load-ai-history')?.addEventListener('click', loadAiHistory);
    byId('run-currency-analysis')?.addEventListener('click', runCurrencyAnalysis);
    byId('run-ai-currency-analysis')?.addEventListener('click', runAiCurrencyAnalysis);
    byId('currency-analysis-id')?.addEventListener('change', () => {
      state.currencyAnalysis.context = null;
      state.currencyAnalysis.error = '';
      state.currencyAnalysis.aiJob = null;
      renderCurrencyAnalysisPanel();
    });
    ['currency-horizon-hours', 'currency-forecast-points', 'currency-history-limit', 'currency-refresh-before-analysis'].forEach(id => {
      byId(id)?.addEventListener('change', () => {
        state.currencyAnalysis.error = '';
        state.currencyAnalysis.aiJob = null;
        renderCurrencyAnalysisPanel();
      });
    });
    bindAccountEvents();
    byId('lot-query')?.addEventListener('input', () => {
      state.focusedSellerLotId = '';
      renderSellerLots();
    });
    byId('lot-limit')?.addEventListener('change', renderSellerLots);
    ['lot-seller'].forEach(id => {
      byId(id)?.addEventListener('keydown', event => {
        if (event.key === 'Enter') searchSellerLots();
      });
    });
    byId('base-market-query')?.addEventListener('input', () => {
      if (state.baseMarketFilterTimer) window.clearTimeout(state.baseMarketFilterTimer);
      state.baseMarketFilterTimer = window.setTimeout(() => refreshBaseMarket(false), 350);
    });
    ['base-market-query', 'base-market-min-ilvl'].forEach(id => {
      byId(id)?.addEventListener('keydown', event => {
        if (event.key === 'Enter') refreshBaseMarket(false);
      });
    });
    byId('base-market-limit')?.addEventListener('change', () => refreshBaseMarket(false));
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
      if (state.activeAdviceTab === 'cross') {
        state.crossDealsKey = '';
        loadCrossCurrencyDeals();
      } else if (state.activeAdviceTab === 'active') {
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
        state.crossDealsMeta = null;
        state.crossDealsKey = '';
        state.activeTrades = [];
        state.activeTradesKey = '';
        state.historyTrends = [];
        state.historyTrendsKey = '';
        state.isLoadingHistoryTrends = false;
        state.currencyAnalysis.context = null;
        state.currencyAnalysis.error = '';
        state.currencyAnalysis.aiJob = null;
        state.rubMarket.context = null;
        state.rubMarket.error = '';
        state.rubMarket.loadedKey = '';
        state.detailDemandCache = {};
        state.detailSeriesCache = {};
        state.sellerLots = null;
        state.sellerLotsParams = null;
        state.baseMarket = null;
        state.baseMarketParams = null;
        state.baseMarketCache = {};
        state.baseMarketHistoryCache = {};
        state.baseMarketHistoryLoading = {};
        state.baseMarketError = '';
        state.focusedBaseMarketId = '';
        setText('last-snapshot', '-');
        setText('rate-source', '-');
        renderTargetCurrencyInfo();
        renderAiPanel();
        renderMarket();
        renderAdvice([]);
        renderBaseMarket();
        renderSelectedItemDetail();
        loadLatestCachedRates();
      });
    });
    const requestedView = new URLSearchParams(window.location.search).get('view');
    const requestedAdminView = requestedView === 'admin';
    const requestedAiView = requestedView === 'ai';
    const deferredMainView = requestedAdminView || requestedAiView ? requestedView : '';
    localStorage.removeItem(MAIN_VIEW_STORAGE_KEY);
    if (PUBLIC_MAIN_VIEWS.includes(requestedView)) {
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
    if (leaguesLoadFailed || staticLoadFailed) {
      setLiveError(t('staticFallbackNotice'));
    }
    loadLatestCachedRates();
    loadAccountState().then(() => {
      showVerificationQueryStatus();
      if (deferredMainView) {
        switchMainView(deferredMainView);
      }
    });
    scheduleAutoRefresh();
  } catch (error) {
    setLiveError(error.message || String(error));
  }
}

window.initLiveTrade = initLiveTrade;
