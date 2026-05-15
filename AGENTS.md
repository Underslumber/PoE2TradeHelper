# AGENTS.md

## Назначение проекта

PoE2 Trade Helper - черновик помощника для торговли в Path of Exile 2.
Цель: искать потенциально выгодные сделки на рынке PoE2, сравнивать цены, находить возможные арбитражные/обменные действия и позже добавить анализ выставленных игроком товаров.

## Рабочая база

- Главная полезная основа сейчас: `mcp_server.py`.
- `mcp_server.py` содержит слой доступа к PoE2 `trade2`: `trade_leagues`, `trade_static_data`, `trade_search`, `trade_fetch`, `trade_exchange`.
- Активный локальный UI живет в `app/web`, торговый слой - в `app/trade2.py`.
- `README.md` хранит краткое состояние проекта для человека; при изменении API-подхода обновляй и README, и этот файл.
- `.env` содержит секреты/локальные значения. Не выводи его содержимое в ответы и не коммить.
- `.env.example` - публичный шаблон переменных.

## Критичные API-факты

- Для обычного поиска сделок через `https://www.pathofexile.com/api/trade2/search`, `trade2/fetch`, `trade2/exchange` отдельный API-ключ обычно не нужен. Нужен корректный `USER_AGENT`.
- `trade2` - веб-API официального сайта торговли PoE2, но он не является полноценным стабильным официальным developer API. Перед крупными изменениями проверяй живые endpoints.
- Для агрегированных цен PoE2 можно использовать poe.ninja endpoint `https://poe.ninja/poe2/api/economy/exchange/current/overview?league=<league>&type=<type>`. Он сейчас полезнее для Liquid Emotions и Fragment/Boss-entry анализа, потому что возвращает нормализованную цену, объем и 7-дневное изменение.
- В `poe.ninja` exchange overview `sparkline.data` для PoE2 нельзя показывать как абсолютную цену: это процентный ряд. Для графика цены переводить его в положительный ценовой ряд, привязанный к текущей `primaryValue`/нормализованной цене.
- В live UI `get_category_rates` должен сначала пробовать poe.ninja для поддерживаемых категорий, затем откатываться на `trade2/exchange`.
- Официальный API живет на `https://api.pathofexile.com` и требует OAuth Bearer token.
- Для `get_currency_exchange` нужен scope `service:cxapi`; это исторические часовые сводки, не текущий стакан заявок.
- Для персонажей нужен scope `account:characters`.
- Официальные `Account Stashes` и `Public Stashes` в документации помечены как PoE1 only. Для анализа личных ящиков PoE2 не обещай рабочий официальный путь, пока он не проверен заново.
- OAuth-клиенты создаются на `https://www.pathofexile.com/my-account/clients`.
- Для локального десктопного помощника обычно нужен Public Client с Authorization Code + PKCE. Для `service:*` scope нужен Confidential Client и client credentials.

## Подход к разработке

- Предпочитай минимальные, небьющие изменения. Не добавляй абстракции, пока они не убирают реальную сложность.
- Строго разделяй русскую и английскую локализации UI: весь видимый текст должен идти через `app/web/static/i18n.js` или шаблонные `data-i18n`-ключи. Не смешивай русские fallback-строки в английском интерфейсе и английские fallback-строки в русском интерфейсе.
- Для русских названий валют, фрагментов и других trade2-позиций сначала опирайся на официальный локализованный справочник `https://ru.pathofexile.com/api/trade2/data/static`. Ручные переводы допустимы только как временный fallback, когда официального термина нет.
- В русской версии видимого UI не показывай английские названия предметов, валют и категорий. Технические id можно оставлять только в диагностике или явно технических местах.
- Не строи новую логику на догадках о JSON-структуре. Сначала получи справочник через `trade_static_data` или живой endpoint, затем кодируй по фактической форме данных.
- Сохраняй rate limit дисциплину: явный `USER_AGENT`, короткие батчи, пауза через `RATE_COOLDOWN_MS`, без агрессивного сканирования рынка.
- Для poe.ninja не запускай Playwright discovery, если известный JSON endpoint отвечает живым запросом; прямой JSON дешевле и надежнее.
- Ошибки внешних HTTP-вызовов в `mcp_server.py` возвращай с понятным `error` и фактическим `status_code`, если он доступен; не логируй тела запросов с потенциально чувствительными данными.
- Для поиска публичных лотов продавца через `trade2/search` используй `trade_filters.account.input` и `sale_type=priced`; `trade2/fetch` батчить максимум по 10 id; в анализ допускай только fetched listings с `listing.price` и `listing.stash`; полный снимок продавца кэшируй по `league/seller/status`.
- Для оценки предметов продавца сравнивай не только название: учитывай тип базы, редкость, item level и официальные stat id из `item.extended.hashes` / `item.extended.mods`; нормализованный текст аффиксов используй только как fallback. Если полностью аналогичных лотов мало, ослабляй сравнение до stat-группы `count` с "аффиксы минус один"; только после этого используй запасной ориентир по типу, уровню и слабому пересечению статов.
- Для stackable-лотов продавца, которые точно совпали со static entry из поддерживаемой poe.ninja категории, можно использовать агрегированную poe.ninja цену как быстрый market estimate; для rare/unique/equipment не подменяй сравнение похожих `trade2` listings агрегатом.
- Любые торговые выводы должны учитывать spread, малый объем, устаревшие/фейковые listings, комиссии/практическую исполнимость и риск price fixing.
- Для прибыльности разделяй данные: raw listings, нормализованные цены, агрегаты/медианы, выводы/сигналы. Не смешивай это в одном неявном словаре.
- Регулярные слепки stackable-рынка собирай через `app.market_snapshots` / `python -m app.cli market-snapshots`: по умолчанию `status=any`, основной target `exalted`, 5 минут первые 48 часов при заданном `--league-start`, затем 15 минут. История слепков хранится в SQLite `data/poe2_ninja.sqlite` / `market_history`; старый `data/trade_rate_history.jsonl` используй только как источник миграции или legacy fallback. Пока FastAPI-приложение активно, `app.market_service` запускает сбор по умолчанию и раз в 10 минут проверяет новые PoE2 trade-лиги. Не трактуй `volume` как точное количество закрытых сделок; это прокси спроса/активности.
- Личный кабинет - локальная функция поверх SQLite: пользователи, сессии, закрепленные позиции, Telegram-уведомления, админские права, локальные метрики ИИ и журнал сделок не требуют OAuth PoE. Новая регистрация требует подтверждения email; SMTP настраивается через `.env`, а без SMTP допустима локальная dev-ссылка подтверждения. Telegram bot token хранится в `.env`, пользователь указывает chat id и правила по закрепленным позициям. Админский bootstrap идет через `ADMIN_USERNAME`/`ADMIN_PASSWORD`; если в базе нет админов, первый существующий или первый зарегистрированный пользователь получает админку. Веб-ИИ ограничивается локальной дневной квотой `AI_DAILY_QUOTA`; это не фактическая квота внешнего провайдера.
- Сделки разделяй на отслеживание, открытый вход и закрытый выход. Номинальная маржа считается в валюте входа. Реальная маржа считается через benchmark: `(current_value / entry_value) / (current_benchmark / entry_benchmark) - 1`. На старте сезона не зашивай Divine Orb как единственный смысловой эталон: UI должен позволять выбрать Divine/Exalted/Chaos, а будущая корзина ликвидных валют/предметов должна идти отдельной моделью.
- Для ИИ-анализа рынка сначала собирай контекст через `app.ai_context` / `/api/ai/market-context`: передавай снимки, агрегаты, внешние новости и риски как данные, но не позволяй ИИ выдумывать цены или автоматически покупать.
- Валютный анализ держи в `app.currency_analyzer` / `/api/trade/currency-analysis` / `python -m app.cli currency-analyze`: локально считай историю, тренд, волатильность и осторожный прогноз по сохраненным снимкам Currency. ИИ передавай этот контекст через `/api/ai/currency-analysis`, но не позволяй ему заменять расчет цен или прогнозов.
- В live UI вкладка ИИ должна показываться только пользователям с `can_use_ai` или админкой. Из браузера запускай анализ через backend-задачу `/api/ai/market-analysis`, а не прямым вызовом Codex CLI.
- Codex CLI-анализатор рынка должен идти через `app.codex_market_analyzer` / `python -m app.cli market-analyze`: запускать `codex exec` только в read-only режиме, сохранять входной payload и ответ в `data/ai_market_analyses`, валидировать `action/confidence` и не превращать сигнал в автопокупку.
- Если добавляешь анализ предметов, сначала сделай parser/normalizer для pasted item text или fetched listing, затем отдельный pricing engine.
- Для будущего UI лучше строить тонкий интерфейс поверх отдельного API/service слоя в `app/`.

## Команды проверки

Запускай после изменений в Python-коде:

```powershell
python -m py_compile mcp_server.py app\account.py app\ai_context.py app\codex_market_analyzer.py app\currency_analyzer.py app\market_service.py app\market_snapshots.py app\trade2.py app\cli.py app\web\main.py app\web\routes.py app\db\migrate_jsonl_to_sqlite.py app\trade\api_client.py app\trade\cache.py app\trade\history.py app\trade\logic.py app\trade\market.py app\trade\math_utils.py
```

Эта команда проверяет синтаксис ключевых Python-файлов без запуска приложения и без сетевых запросов.

Для проверки публичных PoE2 trade2 справочников можно выполнить:

```powershell
@'
import asyncio
import mcp_server

async def main():
    leagues = await mcp_server.trade_leagues()
    static = await mcp_server.trade_static_data()
    static_ru = await mcp_server.trade_static_data(locale="ru")
    print("leagues", len(leagues.get("result", [])))
    print("static categories", len(static.get("result", [])))
    print("static ru categories", len(static_ru.get("result", [])))

asyncio.run(main())
'@ | python -
```

Эта команда проверяет, что `trade2/data/leagues`, английский `trade2/data/static` и русский `ru.pathofexile.com/api/trade2/data/static` отвечают через текущий `mcp_server.py`.

Для установки зависимостей в локальное окружение:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Эта команда ставит зависимости проекта в уже созданный `.venv`.

## Работа с файлами

- Не удаляй legacy-файлы только потому, что они плохие. Если нет git-истории или явного запроса, сначала зафиксируй в документации, что они legacy.
- Можно удалять сгенерированные артефакты: `__pycache__`, `*.pyc`, `*.log`, `Answer_API.txt`, сохраненные HTML-снимки.
- При добавлении секретов используй `.env`; при добавлении новых переменных обновляй `.env.example`.
- SMTP-пароли, Telegram bot token, отправители и реальные почтовые настройки не выводи в ответы и не коммить.
- Если проект станет git-репозиторием, перед правками проверяй `git status --short --branch`.

## Коммуникация

- Отвечай по-русски, если пользователь пишет по-русски.
- Предлагая команду, всегда поясняй, для чего она нужна и что должна сделать.
- Для вопросов "нужен ли API-ключ" отвечай конкретно: для `trade2` обычно нет, для официального `api.pathofexile.com` нужен OAuth и конкретный scope.
- Если API мог измениться, проверяй актуальное состояние live-запросом или по официальной документации, а не опирайся на старые логи.
