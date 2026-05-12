function buildColumns(data) {
  const cols = [
    { data: 'name', title: 'Item', render: (data, type, row) => {
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
    categories: 'Категории',
    market: 'Рынок',
    marketHint: 'Публичная торговая и валютная площадка без OAuth. Сначала выводим все позиции, цены обновляем аккуратно для выбранной категории.',
    league: 'Лига',
    targetCurrency: 'Валюта оценки',
    status: 'Статус',
    search: 'Поиск',
    refreshRates: 'Обновить цены категории',
    refreshLists: 'Обновить списки',
    items: 'Позиций',
    priced: 'С ценой',
    lastSnapshot: 'Последний снимок',
    tradeAdvice: 'Советы по торгам',
    name: 'Название',
    value: 'Цена',
    median: 'Медиана',
    offers: 'Лотов',
    volume: 'Объем',
    last7days: '7 дней',
    source: 'Источник',
    history: 'Лог изменений курса',
    loading: 'Загрузка...',
    noItems: 'Нет позиций',
    noAdvice: 'Пока нет рекомендаций для выбранной категории',
    noHistory: 'Истории пока нет',
    updateLong: 'Обновляю цены. Для больших категорий это может занять время из-за rate limit...',
  },
  en: {
    categories: 'Categories',
    market: 'Market',
    marketHint: 'Public trade and exchange data without OAuth. All items are listed first; prices are refreshed carefully for the selected category.',
    league: 'League',
    targetCurrency: 'Value currency',
    status: 'Status',
    search: 'Search',
    refreshRates: 'Refresh category prices',
    refreshLists: 'Refresh lists',
    items: 'Items',
    priced: 'Priced',
    lastSnapshot: 'Last snapshot',
    tradeAdvice: 'Trade advice',
    name: 'Name',
    value: 'Value',
    median: 'Median',
    offers: 'Offers',
    volume: 'Volume',
    last7days: '7 days',
    source: 'Source',
    history: 'Rate history log',
    loading: 'Loading...',
    noItems: 'No items',
    noAdvice: 'No recommendations for the selected category yet',
    noHistory: 'No history yet',
    updateLong: 'Refreshing prices. Large categories can take time because of rate limits...',
  },
};

const state = {
  lang: localStorage.getItem('poe2-lang') || 'ru',
  leagues: [],
  categories: {},
  categoryMeta: [],
  selectedCategory: 'Currency',
  rates: {},
  sort: { key: 'name', direction: 'asc' },
};

const preferredTargets = ['divine', 'exalted', 'chaos'];

function t(key) {
  return (i18n[state.lang] && i18n[state.lang][key]) || i18n.ru[key] || key;
}

function applyLanguage() {
  document.documentElement.lang = state.lang;
  document.querySelectorAll('[data-i18n]').forEach(el => {
    el.textContent = t(el.dataset.i18n);
  });
  document.getElementById('lang-ru')?.classList.toggle('active', state.lang === 'ru');
  document.getElementById('lang-en')?.classList.toggle('active', state.lang === 'en');
  renderCategories();
  renderMarket();
  renderAdvice((state.rates[state.selectedCategory] || {}).advice || []);
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
      document.getElementById('category-title').textContent = categoryName(category);
      renderCategories();
      renderMarket();
      renderAdvice((state.rates[state.selectedCategory] || {}).advice || []);
    });
    list.appendChild(button);
  });
}

function renderMarket() {
  const body = document.getElementById('market-results');
  if (!body) return;
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
    ? `${new Date(categoryRates.created_ts * 1000).toLocaleTimeString(state.lang === 'ru' ? 'ru-RU' : 'en-US')}${categoryRates.cached ? ' cache' : ''}`
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
    tr.innerHTML = `
      <td class="name-cell">${entry.image ? `<img src="${entry.image}" alt="">` : ''}<span>${entryName(entry)}</span></td>
      <td class="muted-id">${entry.id}</td>
      <td>${formatAmount(priced.best)}</td>
      <td>${formatAmount(priced.median)}</td>
      <td class="${changeClass}">${formatChange(priced.change)}</td>
      <td>${formatAmount(priced.offers || 0)}</td>
      <td>${formatAmount(priced.volume || 0)}</td>
    `;
    body.appendChild(tr);
  });
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

async function refreshRates() {
  const league = document.getElementById('live-league').value;
  const target = document.getElementById('target-currency').value;
  const status = document.getElementById('live-status').value;
  const statusEl = document.getElementById('rate-status');
  setLiveError('');
  statusEl.textContent = t('updateLong');
  const params = new URLSearchParams({ league, category: state.selectedCategory, target, status });
  try {
    const response = await fetch(`/api/trade/category-rates?${params.toString()}`);
    const data = await response.json();
    if (!response.ok || data.error) throw new Error(data.error || 'trade2 error');
    state.rates[state.selectedCategory] = data;
    const stamp = new Date(data.created_ts * 1000).toLocaleTimeString(state.lang === 'ru' ? 'ru-RU' : 'en-US');
    document.getElementById('last-snapshot').textContent = data.cached ? `${stamp} cache` : stamp;
    document.getElementById('rate-source').textContent = data.source || '-';
    renderMarket();
    renderAdvice(data.advice || []);
    renderHistory();
    statusEl.textContent = data.cached ? 'cache' : '';
  } catch (error) {
    setLiveError(error.message || String(error));
    statusEl.textContent = '';
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
    if (!leaguesResponse.ok || leaguesData.error) throw new Error(leaguesData.error || 'Не удалось загрузить лиги');
    if (!staticResponse.ok || staticData.error) throw new Error(staticData.error || 'Не удалось загрузить справочник валют');
    state.leagues = leaguesData.leagues || [];
    state.categories = staticData.categories || {};
    state.categoryMeta = staticData.category_meta || [];
    if (!state.categories[state.selectedCategory]) state.selectedCategory = state.categoryMeta[0]?.id || 'Currency';

    fillSelect(leagueSelect, state.leagues.map(league => ({ id: league.id, text: league.text })), state.leagues[0]?.id);
    const currencyEntries = state.categories.Currency || [];
    const targetEntries = preferredTargets
      .map(id => currencyEntries.find(entry => entry.id === id))
      .filter(Boolean)
      .map(entry => ({ id: entry.id, text: `${entry.text} (${entry.id})` }));
    fillSelect(document.getElementById('target-currency'), targetEntries, 'divine');

    document.getElementById('category-title').textContent = categoryName(state.categoryMeta.find(c => c.id === state.selectedCategory) || { label: state.selectedCategory });
    document.getElementById('refresh-rates').addEventListener('click', refreshRates);
    document.getElementById('refresh-static').addEventListener('click', () => window.location.reload());
    document.getElementById('market-search').addEventListener('input', renderMarket);
    ['live-league', 'target-currency', 'live-status'].forEach(id => {
      document.getElementById(id).addEventListener('change', () => {
        state.rates = {};
        document.getElementById('last-snapshot').textContent = '-';
        document.getElementById('rate-source').textContent = '-';
        renderMarket();
        renderAdvice([]);
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
    renderHistory();
  } catch (error) {
    setLiveError(error.message || String(error));
  }
}

window.initLiveTrade = initLiveTrade;
