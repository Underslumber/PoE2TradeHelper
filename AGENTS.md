# AGENTS.md

## Назначение проекта

PoE2 Trade Helper - черновик помощника для торговли в Path of Exile 2.
Цель: искать потенциально выгодные сделки на рынке PoE2, сравнивать цены, находить возможные арбитражные/обменные действия и позже добавить анализ выставленных игроком товаров.

## Рабочая база

- Главная полезная основа сейчас: `mcp_server.py`.
- `mcp_server.py` содержит слой доступа к PoE2 `trade2`: `trade_leagues`, `trade_static_data`, `trade_search`, `trade_fetch`, `trade_exchange`.
- `app.py` и `templates/index.html` считать legacy-прототипом Flask UI. Там есть заглушки, дублирующиеся кэши, старые PoE1 endpoint'ы и недостижимый код. Не развивать их как основную архитектуру без отдельного решения.
- `README.md` хранит краткое состояние проекта для человека; при изменении API-подхода обновляй и README, и этот файл.
- `.env` содержит секреты/локальные значения. Не выводи его содержимое в ответы и не коммить.
- `.env.example` - публичный шаблон переменных.

## Критичные API-факты

- Для обычного поиска сделок через `https://www.pathofexile.com/api/trade2/search`, `trade2/fetch`, `trade2/exchange` отдельный API-ключ обычно не нужен. Нужен корректный `USER_AGENT`.
- `trade2` - веб-API официального сайта торговли PoE2, но он не является полноценным стабильным официальным developer API. Перед крупными изменениями проверяй живые endpoints.
- Для агрегированных цен PoE2 можно использовать poe.ninja endpoint `https://poe.ninja/poe2/api/economy/exchange/current/overview?league=<league>&type=<type>`. Он сейчас полезнее для Liquid Emotions и Fragment/Boss-entry анализа, потому что возвращает нормализованную цену, объем и 7-дневное изменение.
- В live UI `get_category_rates` должен сначала пробовать poe.ninja для поддерживаемых категорий, затем откатываться на `trade2/exchange`.
- Официальный API живет на `https://api.pathofexile.com` и требует OAuth Bearer token.
- Для `get_currency_exchange` нужен scope `service:cxapi`; это исторические часовые сводки, не текущий стакан заявок.
- Для персонажей нужен scope `account:characters`.
- Официальные `Account Stashes` и `Public Stashes` в документации помечены как PoE1 only. Для анализа личных ящиков PoE2 не обещай рабочий официальный путь, пока он не проверен заново.
- OAuth-клиенты создаются на `https://www.pathofexile.com/my-account/clients`.
- Для локального десктопного помощника обычно нужен Public Client с Authorization Code + PKCE. Для `service:*` scope нужен Confidential Client и client credentials.

## Подход к разработке

- Предпочитай минимальные, небьющие изменения. Не добавляй абстракции, пока они не убирают реальную сложность.
- Не строи новую логику на догадках о JSON-структуре. Сначала получи справочник через `trade_static_data` или живой endpoint, затем кодируй по фактической форме данных.
- Сохраняй rate limit дисциплину: явный `USER_AGENT`, короткие батчи, пауза через `RATE_COOLDOWN_MS`, без агрессивного сканирования рынка.
- Для poe.ninja не запускай Playwright discovery, если известный JSON endpoint отвечает живым запросом; прямой JSON дешевле и надежнее.
- Любые торговые выводы должны учитывать spread, малый объем, устаревшие/фейковые listings, комиссии/практическую исполнимость и риск price fixing.
- Для прибыльности разделяй данные: raw listings, нормализованные цены, агрегаты/медианы, выводы/сигналы. Не смешивай это в одном неявном словаре.
- Если добавляешь анализ предметов, сначала сделай parser/normalizer для pasted item text или fetched listing, затем отдельный pricing engine.
- Для будущего UI лучше строить тонкий интерфейс поверх отдельного API/service слоя, а не расширять текущий `app.py`.

## Команды проверки

Запускай после изменений в Python-коде:

```powershell
python -m py_compile app.py mcp_server.py
```

Эта команда проверяет синтаксис Python-файлов без запуска приложения и без сетевых запросов.

Для проверки публичных PoE2 trade2 справочников можно выполнить:

```powershell
@'
import asyncio
import mcp_server

async def main():
    leagues = await mcp_server.trade_leagues()
    static = await mcp_server.trade_static_data()
    print("leagues", len(leagues.get("result", [])))
    print("static categories", len(static.get("result", [])))

asyncio.run(main())
'@ | python -
```

Эта команда проверяет, что `trade2/data/leagues` и `trade2/data/static` отвечают через текущий `mcp_server.py`.

Для установки зависимостей в локальное окружение:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Эта команда ставит зависимости проекта в уже созданный `.venv`.

## Работа с файлами

- Не удаляй legacy-файлы только потому, что они плохие. Если нет git-истории или явного запроса, сначала зафиксируй в документации, что они legacy.
- Можно удалять сгенерированные артефакты: `__pycache__`, `*.pyc`, `*.log`, `Answer_API.txt`, сохраненные HTML-снимки.
- При добавлении секретов используй `.env`; при добавлении новых переменных обновляй `.env.example`.
- Если проект станет git-репозиторием, перед правками проверяй `git status --short --branch`.

## Коммуникация

- Отвечай по-русски, если пользователь пишет по-русски.
- Предлагая команду, всегда поясняй, для чего она нужна и что должна сделать.
- Для вопросов "нужен ли API-ключ" отвечай конкретно: для `trade2` обычно нет, для официального `api.pathofexile.com` нужен OAuth и конкретный scope.
- Если API мог измениться, проверяй актуальное состояние live-запросом или по официальной документации, а не опирайся на старые логи.
