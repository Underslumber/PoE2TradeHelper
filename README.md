# PoE2 Trade Helper

Черновик помощника для торговли в Path of Exile 2.

## Что сейчас полезно

- `mcp_server.py` - заготовка MCP-инструментов для поиска предметов, получения деталей лотов и обмена валют через `https://www.pathofexile.com/api/trade2`.
- `app.py` и `templates/index.html` - старая Flask-страница с курсами. Она оставлена как legacy, но сейчас содержит дублирующуюся логику, заглушки и старые PoE1 endpoint'ы. Для развития проекта лучше опираться на `mcp_server.py`, а UI писать заново поверх нормального API-слоя.

## Ключи и доступы

Для обычного поиска сделок через `trade2/search`, `trade2/fetch` и `trade2/exchange` отдельный ключ обычно не нужен. Нужен корректный `USER_AGENT`.

OAuth-токен Path of Exile нужен, если используем официальный API `https://api.pathofexile.com`, например:

- `service:cxapi` - исторические часовые сводки Currency Exchange;
- `account:characters` - персонажи аккаунта;
- `account:stashes` - в официальной документации помечен как PoE1 only, поэтому для анализа личных ящиков PoE2 на него пока нельзя надежно рассчитывать.

Клиент создается на странице:

```text
https://www.pathofexile.com/my-account/clients
```

Для локального десктопного помощника нужен Public Client с Authorization Code + PKCE. Для сервисных scope вроде `service:cxapi` нужен Confidential Client и client credentials.

## Локальный запуск MCP-сервера

```powershell
Copy-Item .env.example .env
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe mcp_server.py
```

Команды выше создают локальное окружение, ставят зависимости и запускают MCP-сервер с торговыми инструментами.
