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
  const league = document.getElementById('league').value;
  const category = document.getElementById('category').value;
  const search = document.getElementById('search').value;
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
      const header = document.getElementById('columns-header');
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
    const el = document.getElementById(id);
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

const i18n = {
  ru: {
    navLive: 'Рынок',
    all: 'Все',
    category: 'Категория',
    categories: 'Категории',
    market: 'Рынок',
    marketHint: 'Публичная торговая и валютная площадка без OAuth. Сначала выводим все позиции, цены обновляем аккуратно для выбранной категории.',
    league: 'Лига',
    targetCurrency: 'Валюта оценки',
    pricedIn: 'Цены в валюте',
    status: 'Статус',
    statusAny: 'Любой',
    statusOnline: 'В сети',
    autoRefresh: 'Автообновление',
    autoRefreshOff: 'Выкл',
    autoRefresh1m: '1 мин',
    autoRefresh5m: '5 мин',
    autoRefresh30m: '30 мин',
    autoRefresh1h: '1 час',
    search: 'Поиск',
    searchPlaceholder: 'Название или id',
    refreshRates: 'Обновить цены категории',
    refreshLists: 'Обновить списки',
    items: 'Позиций',
    priced: 'С ценой',
    lastSnapshot: 'Последний снимок',
    tradeAdvice: 'Советы по торгам',
    item: 'Предмет',
    name: 'Название',
    value: 'Цена',
    median: 'Медиана',
    offers: 'Лотов',
    volume: 'Объем',
    last7days: '7 дней',
    source: 'Источник',
    detailTarget: 'Цена относительно',
    history: 'Лог изменений курса',
    loading: 'Загрузка...',
    noItems: 'Нет позиций',
    noAdvice: 'Пока нет рекомендаций для выбранной категории',
    noHistory: 'Истории пока нет',
    autoTarget: 'Авто',
    cacheLabel: 'кэш',
    chartNoData: 'Для этой позиции пока нет графика изменения цены.',
    detailSourceNote: 'График строится по 7-дневным данным poe.ninja, когда они доступны.',
    tradeError: 'Ошибка торгового API',
    cacheLoadError: 'Не удалось загрузить сохраненный снимок',
    leaguesLoadError: 'Не удалось загрузить лиги',
    staticLoadError: 'Не удалось загрузить справочник валют',
    priceChartLabel: 'график цены',
    snapshot: 'Снимок',
    columns: 'Колонки',
    rawData: 'Сырые данные',
    updateLong: 'Обновляю цены. Для больших категорий это может занять время из-за rate limit...',
  },
  en: {
    navLive: 'Market',
    all: 'All',
    category: 'Category',
    categories: 'Categories',
    market: 'Market',
    marketHint: 'Public trade and exchange data without OAuth. All items are listed first; prices are refreshed carefully for the selected category.',
    league: 'League',
    targetCurrency: 'Value currency',
    pricedIn: 'Prices in',
    status: 'Status',
    statusAny: 'Any',
    statusOnline: 'Online',
    autoRefresh: 'Auto refresh',
    autoRefreshOff: 'Off',
    autoRefresh1m: '1 min',
    autoRefresh5m: '5 min',
    autoRefresh30m: '30 min',
    autoRefresh1h: '1 hour',
    search: 'Search',
    searchPlaceholder: 'Name or id',
    refreshRates: 'Refresh category prices',
    refreshLists: 'Refresh lists',
    items: 'Items',
    priced: 'Priced',
    lastSnapshot: 'Last snapshot',
    tradeAdvice: 'Trade advice',
    item: 'Item',
    name: 'Name',
    value: 'Value',
    median: 'Median',
    offers: 'Offers',
    volume: 'Volume',
    last7days: '7 days',
    source: 'Source',
    detailTarget: 'Value currency',
    history: 'Rate history log',
    loading: 'Loading...',
    noItems: 'No items',
    noAdvice: 'No recommendations for the selected category yet',
    noHistory: 'No history yet',
    autoTarget: 'Auto',
    cacheLabel: 'cache',
    chartNoData: 'No price change chart is available for this item yet.',
    detailSourceNote: 'The chart uses 7-day poe.ninja data when available.',
    tradeError: 'Trade API error',
    cacheLoadError: 'Failed to load saved snapshot',
    leaguesLoadError: 'Failed to load leagues',
    staticLoadError: 'Failed to load currency data',
    priceChartLabel: 'price chart',
    snapshot: 'Snapshot',
    columns: 'Columns',
    rawData: 'Raw data',
    updateLong: 'Refreshing prices. Large categories can take time because of rate limits...',
  },
};

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
  autoRefreshMs: Number(localStorage.getItem('poe2-auto-refresh-ms') ?? 60000),
  autoRefreshTimer: null,
  isRefreshing: false,
  sort: { key: 'name', direction: 'asc' },
};

const preferredTargets = ['exalted', 'divine', 'chaos'];

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
  document.getElementById('lang-ru')?.classList.toggle('active', state.lang === 'ru');
  document.getElementById('lang-en')?.classList.toggle('active', state.lang === 'en');
  fillStatusSelect();
  fillTargetCurrencySelect();
  fillAutoRefreshSelect();
  renderTargetCurrencyInfo();
  renderCategories();
  renderMarket();
  renderAdvice((state.rates[state.selectedCategory] || {}).advice || []);
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

function setLiveError(message) {
  const error = document.getElementById('live-error');
  if (!error) return;
  if (!message) {
    error.classList.add('d-none');
    error.textContent = '';
    return;
  }
  error.textContent = message;
  error.classList.remove('d-none');
}

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
  return `${icon ? `<img src="${icon}" alt="">` : ''}<span>${label}</span><span class="currency-code">(${target})</span>`;
}

function selectedTarget() {
  return document.getElementById('target-currency')?.value || defaultTarget();
}

function renderCurrencyElement(element, target) {
  if (!element) return;
  element.innerHTML = currencyMarkup(target);
}

function renderTargetCurrencyInfo(target = selectedTarget()) {
  renderCurrencyElement(document.getElementById('target-currency-preview'), target);
  renderCurrencyElement(document.getElementById('summary-target-currency'), target);
  const shortLabel = target ? `(${currencyLabel(target)})` : '';
  const bestLabel = document.getElementById('best-target-label');
  const medianLabel = document.getElementById('median-target-label');
  if (bestLabel) bestLabel.textContent = shortLabel;
  if (medianLabel) medianLabel.textContent = shortLabel;
}

function targetOptions(includeAuto = false) {
  const currencyEntries = state.categories.Currency || [];
  const ordered = preferredTargets
    .map(id => currencyEntries.find(entry => entry.id === id))
    .filter(Boolean)
    .map(entry => ({ id: entry.id, text: `${entryName(entry)} (${entry.id})` }));
  if (!includeAuto) return ordered;
  return [{ id: 'auto', text: t('autoTarget') }, ...ordered];
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
  const select = document.getElementById('live-status');
  if (!select) return;
  const selected = select.value || 'any';
  fillSelect(select, statusOptions(), selected);
}

function fillTargetCurrencySelect() {
  const select = document.getElementById('target-currency');
  if (!select) return;
  const selected = select.value || defaultTarget();
  fillSelect(select, targetOptions(false), selected);
}

function fillAutoRefreshSelect() {
  const select = document.getElementById('auto-refresh-interval');
  if (!select) return;
  fillSelect(select, autoRefreshOptions(), String(state.autoRefreshMs || 0));
}

function renderCategories() {
  const list = document.getElementById('category-list');
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
      document.getElementById('category-title').textContent = categoryName(category);
      document.getElementById('item-detail-panel')?.classList.add('d-none');
      renderCategories();
      renderMarket();
      renderAdvice((state.rates[state.selectedCategory] || {}).advice || []);
      loadLatestCachedRates();
    });
    list.appendChild(button);
  });
}

function renderMarket() {
  const body = document.getElementById('market-results');
  if (!body) return;
  renderTargetCurrencyInfo((state.rates[state.selectedCategory] || {}).target || selectedTarget());
  const search = (document.getElementById('market-search').value || '').toLowerCase();
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
  document.getElementById('items-total').textContent = entries.length;
  document.getElementById('priced-total').textContent = [...rateRows.values()].filter(row => row.best !== null && row.best !== undefined).length;
  document.getElementById('rate-source').textContent = categoryRates.source || '-';
  document.getElementById('last-snapshot').textContent = categoryRates.created_ts
    ? `${new Date(categoryRates.created_ts * 1000).toLocaleTimeString(state.lang === 'ru' ? 'ru-RU' : 'en-US')}${categoryRates.cached ? ` ${t('cacheLabel')}` : ''}`
    : '-';
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

function fillDetailTargetSelect() {
  const select = document.getElementById('detail-target-currency');
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

function ratesCacheKey(target) {
  const league = document.getElementById('live-league')?.value || '';
  const status = document.getElementById('live-status')?.value || 'any';
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
  const currentTarget = (state.rates[state.selectedCategory] || {}).target || document.getElementById('target-currency')?.value || defaultTarget();
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

  const league = document.getElementById('live-league').value;
  const status = document.getElementById('live-status').value;
  const params = new URLSearchParams({ league, category: state.selectedCategory, target, status });
  const response = await fetch(`/api/trade/category-rates?${params.toString()}`);
  const data = await response.json();
  if (!response.ok || data.error) throw new Error(data.error || t('tradeError'));
  state.detailRates[key] = data;
  return data;
}

function renderSparkline(values) {
  const chart = document.getElementById('detail-chart');
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

async function renderSelectedItemDetail() {
  const panel = document.getElementById('item-detail-panel');
  if (!panel || !state.selectedItemId) return;
  const entry = findEntry(state.selectedItemId);
  if (!entry) {
    panel.classList.add('d-none');
    return;
  }
  panel.classList.remove('d-none');
  document.getElementById('detail-name').textContent = entryName(entry);
  document.getElementById('detail-id').textContent = entry.id;
  const detailIcon = document.getElementById('detail-icon');
  if (entry.image) {
    detailIcon.src = entry.image;
  } else {
    detailIcon.removeAttribute('src');
  }

  const select = document.getElementById('detail-target-currency');
  state.detailTarget = select?.value || 'auto';
  const baseRow = currentRowFor(entry.id);
  const target = state.detailTarget === 'auto' ? autoTargetFor(baseRow) : state.detailTarget;
  renderCurrencyElement(document.getElementById('detail-target-currency-preview'), target);
  document.getElementById('detail-value-target-label').textContent = `(${currencyLabel(target)})`;
  document.getElementById('detail-median-target-label').textContent = `(${currencyLabel(target)})`;
  document.getElementById('detail-note').textContent = t('loading');
  try {
    const data = await ensureRatesForTarget(target);
    const row = rowsById(data).get(entry.id) || entry;
    document.getElementById('detail-value').textContent = `${formatAmount(row.best)} ${currencyLabel(target)}`;
    document.getElementById('detail-median').textContent = `${formatAmount(row.median)} ${currencyLabel(target)}`;
    document.getElementById('detail-volume').textContent = formatAmount(row.volume || 0);
    document.getElementById('detail-change').textContent = formatChange(row.change);
    document.getElementById('detail-change').className = Number(row.change) > 0 ? 'change-up' : Number(row.change) < 0 ? 'change-down' : '';
    renderSparkline(row.sparkline || []);
    document.getElementById('detail-note').textContent = `${t('detailSourceNote')} ${t('source')}: ${data.source || '-'}.`;
  } catch (error) {
    document.getElementById('detail-note').textContent = error.message || String(error);
    renderSparkline([]);
  }
}

function openItemDetail(itemId) {
  state.selectedItemId = itemId;
  fillDetailTargetSelect();
  renderMarket();
  renderSelectedItemDetail();
}

function renderAdvice(advice) {
  const panel = document.getElementById('advice-panel');
  const list = document.getElementById('advice-list');
  if (!panel || !list) return;
  list.innerHTML = '';
  if (!advice || !advice.length) {
    panel.classList.add('d-none');
    return;
  }
  panel.classList.remove('d-none');
  advice.forEach(item => {
    const card = document.createElement('article');
    card.className = `advice-card ${item.kind || ''}`;
    const title = state.lang === 'ru' ? item.title_ru : item.title_en;
    const message = state.lang === 'ru' ? item.message_ru : item.message_en;
    card.innerHTML = `<strong>${title}</strong><p>${message}</p>`;
    list.appendChild(card);
  });
}

async function renderHistory() {
  const list = document.getElementById('history-list');
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
  document.getElementById('rate-source').textContent = data.source || '-';
  renderMarket();
  renderAdvice(data.advice || []);
  renderSelectedItemDetail();
  renderHistory();
}

async function loadLatestCachedRates() {
  const league = document.getElementById('live-league')?.value;
  const target = document.getElementById('target-currency')?.value;
  const status = document.getElementById('live-status')?.value;
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
  const league = document.getElementById('live-league').value;
  const target = document.getElementById('target-currency').value;
  const status = document.getElementById('live-status').value;
  const statusEl = document.getElementById('rate-status');
  setLiveError('');
  if (!options.silent) statusEl.textContent = t('updateLong');
  const params = new URLSearchParams({ league, category: state.selectedCategory, target, status });
  try {
    const response = await fetch(`/api/trade/category-rates?${params.toString()}`);
    const data = await response.json();
    if (!response.ok || data.error) throw new Error(data.error || t('tradeError'));
    const stamp = new Date(data.created_ts * 1000).toLocaleTimeString(state.lang === 'ru' ? 'ru-RU' : 'en-US');
    document.getElementById('last-snapshot').textContent = data.cached ? `${stamp} ${t('cacheLabel')}` : stamp;
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
  const leagueSelect = document.getElementById('live-league');
  if (!leagueSelect) return;
  try {
    setLiveError('');
    document.getElementById('lang-ru').addEventListener('click', () => {
      state.lang = 'ru';
      localStorage.setItem('poe2-lang', state.lang);
      applyLanguage();
    });
    document.getElementById('lang-en').addEventListener('click', () => {
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

    document.getElementById('category-title').textContent = categoryName(state.categoryMeta.find(c => c.id === state.selectedCategory) || { label: state.selectedCategory });
    document.getElementById('refresh-rates').addEventListener('click', refreshRates);
    document.getElementById('refresh-static').addEventListener('click', () => window.location.reload());
    document.getElementById('market-search').addEventListener('input', renderMarket);
    document.getElementById('detail-target-currency').addEventListener('change', event => {
      state.detailTarget = event.target.value;
      renderSelectedItemDetail();
    });
    document.getElementById('auto-refresh-interval').addEventListener('change', event => {
      state.autoRefreshMs = Number(event.target.value || 0);
      localStorage.setItem('poe2-auto-refresh-ms', String(state.autoRefreshMs));
      scheduleAutoRefresh();
    });
    ['live-league', 'target-currency', 'live-status'].forEach(id => {
      document.getElementById(id).addEventListener('change', () => {
        state.rates = {};
        state.detailRates = {};
        document.getElementById('last-snapshot').textContent = '-';
        document.getElementById('rate-source').textContent = '-';
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
