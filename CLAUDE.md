# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Language

`AGENTS.md`, `README.md`, and most code comments are in Russian. Reply in Russian when the user writes in Russian. `AGENTS.md` is the canonical contributor guide and carries detailed API facts and trading rules — read it before non-trivial changes.

## Commands

The project targets Python 3.10+ and a local `.venv`. The `.env` file holds secrets and config (`.env.example` is the public template).

```bash
pip install -r requirements.txt

python -m app.cli run                    # FastAPI UI on http://localhost:8000
python -m app.cli market-snapshots --league "<league>" --once   # one market snapshot
python -m app.cli funpay-rub-snapshots --league "<league>" --once
python -m app.cli market-analyze --league "<league>" --category Currency   # Codex CLI analysis
python -m app.cli currency-analyze --league "<league>" --currency divine
python -m app.cli ai-context --league "<league>" --category Currency
python -m app.cli discover --league "<league>" --category <cat>  # legacy poe.ninja collector
python -m app.cli sync --all

python -m pytest -q                      # full test suite
python -m pytest tests/test_trade2.py -q # single test file
python -m pytest tests/test_trade2.py::test_name -q  # single test

python -m py_compile mcp_server.py app/*.py app/web/*.py app/db/*.py app/trade/*.py  # syntax check
```

Run `py_compile` + `pytest` after Python changes. `tests/conftest.py` puts the repo root on `sys.path`, so run pytest from the repo root.

## Versioning (required on every meaningful change)

`app/version.py` (`APP_VERSION`) is the single source of truth, surfaced in the UI and used for static-file cache-busting. Bump it by SemVer in the *same* change whenever code, UI, API behavior, data schema, config, or user docs change: patch for fixes/internal edits, minor for new compatible features, major for breaking changes or migrations needing manual action.

## Architecture

This is a local Path of Exile 2 trading assistant. It has no single backend — it aggregates several external sources and stores history locally in SQLite.

### Data sources
- **`trade2` web API** (`pathofexile.com/api/trade2`, and `ru.pathofexile.com` for Russian terms) — leagues, static data, search, fetch, exchange. No API key needed; a correct `USER_AGENT` is required. Not a stable official API — verify live endpoints before large changes.
- **poe.ninja** PoE2 economy endpoints — normalized aggregate prices/volume for supported categories. `get_category_rates` tries poe.ninja first, then falls back to `trade2/exchange`. poe.ninja `sparkline.data` is a *percent* series, not absolute prices.
- **FunPay** (`funpay.com/chips/209/` public listing only) — optional, profile-gated RUB-fiat layer.
- **Official `api.pathofexile.com`** — OAuth Bearer only; not used for trade2 flows. Personal stash analysis has no confirmed PoE2 path yet.

### Layers
- `mcp_server.py` — MCP server exposing `trade2` tools (`trade_leagues`, `trade_static_data`, `trade_search`, `trade_fetch`, `trade_exchange`). Standalone entrypoint; uses `app/trade/api_client.py`.
- `app/trade2.py` + `app/trade/` — the trading layer. `app/trade2.py` is the main module (~1.6k lines): it calls the `trade2` web API and poe.ninja and normalizes `trade2`/poe.ninja/static data into a common row format. It reuses `app/trade/cache.py` (SQLite response cache) and `app/trade/history.py` (`market_history` read/write). `app/trade/api_client.py` (`PoeTradeClient`) is a separate `trade2` client used only by `mcp_server.py`. Keep these two clients from drifting — or fold one into the other.
- `app/web/` — FastAPI app (`main.py` builds the app, `routes.py` holds all `~50` endpoints). Server-rendered Jinja templates + static JS/CSS live UI.
- `app/db/` — SQLAlchemy models (`models.py`) over SQLite. `migrate.py` runs `create_all` plus hand-written `ALTER TABLE` column adds and admin bootstrap; it is the schema-evolution mechanism (no Alembic). `migrate_jsonl_to_sqlite.py` migrates the legacy `data/trade_rate_history.jsonl` into the `market_history` table.
- `app/cli.py` — argparse dispatcher for all subcommands above; runs `migrate()` before non-`run` commands.
- `app/collector/`, `app/export/` — legacy poe.ninja collector (Playwright discovery, sync, icons) feeding the `/economy` page; kept for the `discover`/`sync` commands.

### Background market service
When the FastAPI app runs, `app/market_service.py` (`market_snapshot_service`, started in `main.py`'s lifespan) auto-collects market snapshots: it picks the current PoE2 challenge league, snapshots all stackable categories, re-checks for a new league every ~10 min, and optionally collects the FunPay RUB base on the same cycle. Cadence is 5 min for the first 48 h after league start, then 15 min. Status is exposed at `/api/trade/market-snapshot-service`. The same loop logic is reusable from the CLI via `market-snapshots` / `funpay-rub-snapshots`.

### AI analysis
AI is advisory only — it must never invent prices or trigger purchases. `app/ai_context.py` builds a JSON market context; `app/codex_market_analyzer.py` runs `codex exec` in read-only mode and saves the input/output audit to `data/ai_market_analyses`. `app/currency_analyzer.py` computes local trend/volatility/forecast for a single currency. Web AI endpoints require login with `can_use_ai` (or admin) and are rate-limited by the local `AI_DAILY_QUOTA`.

### Local account system
Users, sessions, pinned positions, trade journal, Telegram rules, AI usage metrics — all local SQLite, no PoE OAuth. Registration requires email verification (SMTP from `.env`, or a dev link when SMTP is unset). Admin is bootstrapped via `ADMIN_USERNAME`/`ADMIN_PASSWORD`; if no admin exists, the first user becomes admin. Trade P/L uses both nominal margin and a benchmark-adjusted margin: `(current_value / entry_value) / (current_benchmark / entry_benchmark) - 1`.

### Storage
SQLite at `data/poe2_ninja.sqlite` (override via `SQLITE_PATH`). Key tables: `market_history` (price snapshots), `users`/`user_sessions`, `pinned_positions`, `trade_journal_entries`, `telegram_notification_rules`, `funpay_rub_snapshots`/`funpay_rub_offers`, `cache_entries`, and the legacy `snapshots`/`rows`/`artifacts`. `data/` and `storage/` are gitignored.

## Conventions

- **i18n is strict.** All visible UI text goes through `app/web/static/i18n.js` or template `data-i18n` keys. Never mix Russian fallback strings into the English UI or vice versa. In the Russian UI do not show English item/currency/category names — prefer the official localized reference at `ru.pathofexile.com/api/trade2/data/static`; technical ids are allowed only in diagnostics.
- **Don't guess JSON shapes.** Fetch the live `trade_static_data` / endpoint response first, then code against the actual structure.
- **Rate-limit discipline.** Explicit `USER_AGENT`, small batches (`trade2/fetch` ≤ 10 ids), pause via `RATE_COOLDOWN_MS`, no aggressive market scanning. Don't run Playwright discovery if a known JSON endpoint already answers.
- **External HTTP errors** return a dict with a clear `error` and the real `status_code`; never log request bodies with potential secrets.
- **Trading conclusions** must account for spread, low volume, stale/fake listings, fees, and price-fixing risk. Keep raw listings, normalized prices, aggregates, and signals as separate data, not one implicit dict.
- Prefer minimal, non-breaking changes; don't add abstractions until they remove real complexity. Don't delete legacy files without git history or an explicit request — document them as legacy first. Generated artifacts (`__pycache__`, `*.pyc`, `*.log`, saved HTML snapshots) may be removed.
- New secrets go in `.env`; update `.env.example` when adding env vars. Never print or commit `.env`, SMTP passwords, or the Telegram bot token.
