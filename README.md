# PoE2 Trade Helper

Локальный помощник для торговли в Path of Exile 2. Текущий фокус - работать без OAuth через публичную торговую площадку `trade2` и агрегированные данные poe.ninja, выбирать текущую лигу и смотреть live-обмен валют.

## Что уже есть

- Live web UI на FastAPI: `/`
  - загружает текущие PoE2-лиги из `trade2/data/leagues`;
  - дает выбрать лигу;
  - показывает все актуальные trade2-категории и позиции из `trade2/data/static`;
  - поддерживает RU/EN-переключатель интерфейса;
  - умеет сортировать таблицу по названию, id, цене, медиане, изменению за 7 дней, лотам и объему;
  - обновляет цены выбранной категории через poe.ninja PoE2 exchange overview, если категория поддерживается, иначе откатывается к `trade2/exchange`;
  - ведет локальный JSONL-лог снимков цен в `data/trade_rate_history.jsonl`;
  - содержит первый анализатор цепочки жидких эмоций 3-в-1.
- Заготовка poe.ninja economy collector: `/economy`
  - discovery через Playwright;
  - синхронизация лиг/категорий poe.ninja в SQLite;
  - экспорт CSV/JSONL.
- `mcp_server.py` - отдельная MCP-заготовка для trade2 и будущего официального API.

## Ключи и доступы

Для ближайшего MVP OAuth/API-заявка GGG не нужна.

Публичные запросы, которые используются сейчас:

- `https://www.pathofexile.com/api/trade2/data/leagues`
- `https://www.pathofexile.com/api/trade2/data/static`
- `https://www.pathofexile.com/api/trade2/exchange/poe2/<league>`
- `https://poe.ninja/poe2/api/economy/exchange/current/overview?league=<league>&type=<type>`

Нужен только корректный `USER_AGENT`.

poe.ninja endpoint используется как агрегированный источник для категорий, где он есть: `Currency`, `Fragments`, `Delirium` / Liquid Emotions, `Breach`, `Essences`, `Ritual`, `Expedition`, `Runes`, `Abyss`, `UncutGems`, `LineageSupportGems`, `SoulCores`, `Idols`. Он лучше подходит для цепочек эмоций и проходок, потому что возвращает нормализованные значения, объем и 7-дневное изменение.

OAuth пригодится позже только для официального `https://api.pathofexile.com`, например:

- `service:cxapi` - официальная историческая Currency Exchange API;
- `account:characters` - персонажи и инвентарь аккаунта.

Официальные stash endpoints в текущей документации помечены как PoE1 only, поэтому для PoE2 stash/listed-items анализа пока нельзя обещать рабочий официальный путь.

## Установка

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Эти команды создают локальное Python-окружение и ставят зависимости проекта.

Для poe.ninja discovery дополнительно нужен Chromium Playwright:

```powershell
.\.venv\Scripts\python.exe -m playwright install chromium
```

Эта команда ставит браузер, который нужен только для discovery/fallback-сбора poe.ninja.

## Запуск

```powershell
.\.venv\Scripts\python.exe -m app.cli run
```

Команда запускает локальный веб-интерфейс на `http://127.0.0.1:8000`.

## CLI

```powershell
.\.venv\Scripts\python.exe -m app.cli discover --league vaal --category runes
.\.venv\Scripts\python.exe -m app.cli sync --league vaal --category runes
.\.venv\Scripts\python.exe -m app.cli sync --all
```

Команды выше относятся к poe.ninja collector: найти endpoint, синхронизировать одну пару лига/категория или синхронизировать все найденные пары.

## Проверка

```powershell
python -m pytest -q
python -m py_compile app.py mcp_server.py
```

Первая команда запускает тесты, вторая проверяет синтаксис legacy/MCP-файлов.
