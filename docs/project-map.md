# Карта PoE2 Trade Helper

Проверено по рабочей копии 2026-10-09, база `8c89b219`, с незакоммиченными изменениями. Это карта кода; она не подтверждает состояние развёрнутого сервера.

## Основной поток

```text
Браузер: live.html + app.js + i18n.js
    |
    v
FastAPI: app/web/main.py -> app/web/routes.py
    |                         |
    | latest / history        | явное обновление / поиск
    v                         v
SQLite market_history <--- app/trade2.py + app/trade/
    ^                         |             |
    |                         v             v
market_service           poe.ninja       trade2
    |                    агрегаты     search/fetch/exchange
    +-> market_snapshots -> нормализация -> запись истории
    +-> фоновые ItemBases -> каталог PoB -> порционный поиск
    +-> notification_worker -> правила пользователя -> Telegram
    +-> history_compaction -> raw -> hourly -> daily

Сохранённые данные -> diagnostics / currency_analyzer / recipes
                  -> profitability / benchmark / журнал сделок
                  -> ai_context -> Codex read-only -> проверенный ответ
```

## Компоненты

| Узел | Файлы / точки входа | Что делает и где граница |
|---|---|---|
| Запуск | `app/cli.py`, `app/web/main.py` | `python -m app.cli web` поднимает Uvicorn; lifespan запускает миграции и один фоновый сервис на процесс |
| Интерфейс | `app/web/templates/live.html`, `app/web/static/app.js`, `i18n.js`, `app.css` | Отображение рынков, фильтров, кабинета, графиков; RU/EN через словарь |
| HTTP API | `app/web/routes.py` | Публичные справочники и рынки, аккаунт, сделки, админка и задачи ИИ; проверяет права на закрытых маршрутах |
| Доступ к рынку | `app/trade2.py`, `app/trade/api_client.py` | Категории, похожие предметы, публичные лоты продавца, основы; API-ключ для веб-trade2 обычно не требуется, но это не стабильный developer API |
| Сеть и лимиты | `app/http_client.py`, `app/trade/rate_limit.py` | Proxy/failover, `Retry-After` и заголовки лимитов; отдельное состояние маршрутов |
| Периодический сбор | `app/market_service.py`, `app/market_snapshots.py` | Выбор первой подходящей challenge-лиги, проверка лиг каждые 10 минут, список категорий, интервал 5/15 минут по возрасту лиги |
| История | `app/trade/history.py`, `app/history_compaction.py`, `app/db/` | SQLite, разделение по лиге/категории/валюте/status; raw/hourly/daily; JSONL — legacy/migration |
| Основы | `app/resources/item_base_catalog_seed.json`, `scripts/build_item_base_catalog_seed_from_pob.py` | Каталог PoB, RU-названия, локальные иконки; грубый фоновый проход, точный поиск по явному фильтру |
| Рецепты и циклы | `app/recipes.py`, `app/currency_cycles.py` | Цепочки эмоций, рецепты и стоимость комплектов; направленные обменные циклы с затратами на каждом шаге |
| Аналитика | `app/profitability.py`, `app/market_diagnostics.py`, `app/currency_analyzer.py` | Качество/свежесть, история сигналов, тренд и осторожный прогноз; не гарантия исполнения |
| Кабинет | `app/account.py`, модели и маршруты | Пароли, сессии, email, pinned items, сделки, P/L, права; отдельная локальная учётная запись, не OAuth PoE |
| Benchmark | `app/benchmark.py` | Divine/Exalted/Chaos и `basket:liquid-core`; реальные результаты отделены от номинальных и сгруппированы по валютам |
| Уведомления | `app/notifications.py`, `app/notification_worker.py` | Проверка правил после снимков и CLI `notifications-check`; не зависит от открытого браузера |
| ИИ | `app/ai_context.py`, `app/ai_history.py`, `app/codex_market_analyzer.py` | Подготовка данных, квота, фоновый анализ; CLI read-only, ответ валидируется, автопокупок нет |
| RUB | `app/funpay_market.py` | Только публичная витрина, отдельные офферы/агрегаты, отображение по opt-in; stock не означает продажи |
| MCP | `mcp_server.py` | Отдельный сервер: leagues/static/search/fetch/exchange; не оболочка всего веб-приложения |
| Старый сборщик | `app/collector/`, `app/export/` | Discovery через Playwright, XHR/DOM-снимки, экспорт; сохраняется для совместимости, не основной путь нового сезона |
| Доставка | `.github/workflows/ci-cd.yml`, `scripts/deploy_server.sh` | Compile + pytest, затем условный deploy `main`; `/health` подтверждает только жизнь процесса |

## Ключевые сценарии

1. **Открытие рынка:** UI получает leagues/static, затем `/api/trade/category-rates/latest`. Последующие проверки `created_ts` читают сохранённые данные; обновление внешнего рынка выполняет сборщик или явное действие.
2. **Проверка вещи:** pasted text → `item_parser` → поиск похожих priced listings → сравнение базы/уровня/official stats → оценка с уверенностью. Агрегированная цена валюты не заменяет оценку редкого предмета.
3. **Смена сезона:** сервис перечитывает trade-лиги, меняет `current_league`; новые строки пишутся с новым league key. Старые сделки и историю удалять не нужно. Дата раннего сбора требует отдельной проверки — см. runbook.
4. **ИИ:** пользователь с правом запускает backend job; модель получает вычисленные цены и риски, результат сохраняется отдельно. Доступность установленного Codex и его авторизация не доказаны unit-тестами.

## Ограничения архитектуры

Один процесс приложения запускает один сборщик. Несколько Uvicorn workers без межпроцессного lease размножат сбор и лимитеры. Для текущей схемы использовать один worker; отдельный collector/очередь — следующий шаг только при реальном росте нагрузки.

`app/trade2.py` и `app/web/routes.py` велики; разделение на адаптеры источников, market services и routers полезно делать постепенно под регрессиями, а не общим рефакторингом перед сезоном.

HTTP `200` от источника, зелёные unit-тесты, `/health` и успешный деплой доказывают разные вещи. Сезонная приёмка требует новых снимков нужной лиги и проверки их в браузере.
