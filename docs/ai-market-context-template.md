# Шаблон контекста для ИИ-анализа рынка PoE2

Дата подготовки: 2026-05-15.

Этот файл описывает, что отправлять в ИИ вместе с актуальными метриками рынка и какой ответ ожидать обратно. Общие правила экономики лежат в `docs/league-start-market-notes.md`; этот документ нужен как рабочий шаблон для будущей интеграции.

## Цель

ИИ должен не "угадывать цены", а помогать разбирать рынок по данным:

- объяснять, какие позиции выглядят переоцененными или недооцененными;
- отделять сильные сигналы от шума ранней лиги;
- учитывать фазу лиги, ликвидность, спред, объем и внешний спрос;
- возвращать проверяемые гипотезы и список недостающих метрик.

ИИ не должен выдавать уверенный торговый совет, если данных мало, рынок неликвиден или сигнал держится на одном лоте.

## Текущий инструмент в проекте

Первый рабочий слой уже есть: он собирает JSON-контекст по последнему сохраненному снимку категории или по свежему live-запросу.

API:

```text
GET /api/ai/market-context?league=<league>&category=<category>&target=exalted&status=any&league_day=1&limit=80
```

Параметры:

- `league` - название PoE2-лиги из `trade2/data/leagues`.
- `category` - категория static data, например `Currency`, `Delirium`, `Fragments`, `Runes`.
- `target` - валюта оценки, обычно `exalted`, `divine` или `chaos`.
- `status` - `any` или `online`.
- `league_day` - день лиги для фазовой модели; если не указан, фаза будет `unknown`.
- `limit` - максимум строк в `market_rows`.
- `refresh=true` - сначала обновить категорию через live endpoint, затем собрать контекст. Использовать осторожно, с учетом rate limits.

CLI:

```powershell
python -m app.cli ai-context --league "Runes of Aldur" --category Currency --target exalted --status any --league-day 1
```

Команда печатает JSON-контекст в stdout. Если добавить `--refresh`, она сначала запросит свежие цены категории через текущий торговый слой.

Codex CLI-анализатор:

```powershell
python -m app.cli market-analyze --league "Runes of Aldur" --category Currency --target exalted --status any --league-day 1
```

Команда строит тот же JSON-контекст, передает его в `codex exec` в read-only режиме, валидирует ответ по разрешенным `action/confidence` и сохраняет аудит в `data/ai_market_analyses`.

## Компактный системный промпт

```text
Ты рыночный аналитик для Path of Exile 2. Анализируй только предоставленные данные и не выдумывай цены, объемы, патчноуты, популярность билдов или новости.

Учитывай фазу лиги:
- day_0_1: дефицит, случайные цены, важнее скорость прогресса.
- day_2_7: рынок насыщается, появляются первые мета-сигналы.
- day_8_21: растет спрос на эндгейм-крафт, фрагменты, проходки, boss-entry, meta-bases и build-enabling uniques.
- late_league: спрос падает, массовые позиции насыщены, важна ликвидность и фиксация прибыли.

Для stackable-позиций опирайся на агрегаты Currency Exchange/poe.ninja, если они есть. Для rare/unique/equipment требуй сравнение похожих trade2 listings по базе, item level, rarity и official stat ids/hash.

Перед рекомендацией проверь: price_action, volume, listing_count, spread_percent, freshness, source, demand_driver, benchmark_view и risk_flags. Если данных недостаточно, верни insufficient_data.

Формат ответа строго JSON. Для каждого сигнала укажи action, confidence, thesis, evidence, risks, suggested_checks и invalidation.
```

## Входной JSON

Минимальный пакет, который стоит передавать модели:

```json
{
  "schema_version": "poe2-market-ai-context/v1",
  "generated_at": "2026-05-29T21:15:00+03:00",
  "league": {
    "id": "Runes of Aldur",
    "day": 1,
    "phase": "day_0_1",
    "status": "fresh_economy",
    "notes": [
      "Fresh league economy; old league characters/items are not part of this trade economy."
    ]
  },
  "sources": {
    "trade2": {
      "enabled": true,
      "checked_at": "2026-05-29T21:14:30+03:00",
      "notes": "Public trade2 listings and exchange endpoint. Asking prices, not guaranteed executed trades."
    },
    "poe_ninja": {
      "enabled": true,
      "checked_at": "2026-05-29T21:14:40+03:00",
      "notes": "PoE2 Currency Exchange overview for supported stackable categories."
    },
    "external_context": {
      "enabled": true,
      "checked_at": "2026-05-29T21:00:00+03:00",
      "notes": "Patch notes, hotfixes, streamer/build observations, manual notes."
    }
  },
  "benchmarks": {
    "target_currency": "exalted",
    "available": ["chaos", "exalted", "divine"],
    "basket": {
      "enabled": false,
      "notes": "Future composite benchmark; do not infer if not provided."
    }
  },
  "market_rows": [],
  "category_summaries": [],
  "chain_opportunities": [],
  "seller_lot_checks": [],
  "external_context": {
    "patch_notes": [],
    "hotfixes": [],
    "popular_builds": [],
    "streamer_mentions": [],
    "news": [],
    "known_risks": []
  },
  "request": {
    "task": "find_watchlist_and_trade_candidates",
    "risk_profile": "conservative",
    "max_candidates": 10,
    "language": "ru"
  }
}
```

## Market Row

Форма одной позиции из live-таблицы/категории. Поля согласованы с текущим `app/trade2.py` и UI.

```json
{
  "id": "divine",
  "name_en": "Divine Orb",
  "name_ru": "Божественная сфера",
  "category": "Currency",
  "source": "poe.ninja",
  "target": "exalted",
  "best": 55.0,
  "median": 56.5,
  "offers": 120,
  "volume": 450.0,
  "change_7d_percent": 18.4,
  "sparkline_kind": "price",
  "sparkline": [45.1, 47.0, 49.8, 52.4, 55.2, 56.5],
  "snapshot_ts": "2026-05-29T21:15:00+03:00",
  "freshness_seconds": 30,
  "spread_percent": 2.7,
  "listing_count": 120,
  "depth_near_market": 35,
  "stale_listing_share": 0.08,
  "risk_flags": []
}
```

Пояснения:

- `best` и `median` должны быть в `target`.
- `change_7d_percent` соответствует текущему `row.change`, если источник дает 7-дневное изменение.
- `sparkline_kind=price` означает, что ряд уже переведен в цены, а не является процентным рядом poe.ninja.
- `spread_percent`, `depth_near_market`, `stale_listing_share` можно не передавать, если они еще не рассчитаны; тогда ИИ обязан снижать уверенность.

## Category Summary

Агрегат по категории нужен, чтобы модель не переоценивала одиночные позиции.

```json
{
  "category": "Delirium",
  "source": "poe.ninja",
  "target": "exalted",
  "rows_count": 10,
  "priced_count": 10,
  "high_liquidity_count": 3,
  "medium_liquidity_count": 4,
  "low_liquidity_count": 3,
  "strong_movers_count": 2,
  "top_volume_items": [
    {"id": "simulacrum-splinter", "name_ru": "Осколок Симулякра", "volume": 900.0}
  ],
  "notes": []
}
```

## Chain Opportunity

Для цепочек вроде Liquid Emotions:

```json
{
  "kind": "emotion_path",
  "source_id": "diluted-liquid-ire",
  "source_name_ru": "Разбавленный жидкий гнев",
  "result_id": "liquid-paranoia",
  "result_name_ru": "Жидкая паранойя",
  "input_count": 9,
  "path_steps": 2,
  "target": "exalted",
  "source_value": 0.2,
  "result_value": 2.4,
  "craft_cost": 1.8,
  "profit": 0.6,
  "margin": 0.3333,
  "source_volume": 120.0,
  "result_volume": 15.0,
  "min_volume": 15.0,
  "risk": "medium",
  "source": "poe.ninja",
  "snapshot_ts": "2026-05-29T21:15:00+03:00"
}
```

ИИ должен считать такую сделку слабой, если `min_volume` низкий, `result_volume` низкий или нет подтверждения реальной исполнимости.

## Seller Lot Check

Для анализа публичных лотов продавца:

```json
{
  "seller": "AccountName#1234",
  "league": "Runes of Aldur",
  "lot": {
    "item_id": "opaque_trade2_item_id",
    "name": "Example Rare Boots",
    "rarity": "rare",
    "base_type": "Boots",
    "item_level": 78,
    "price": 10.0,
    "currency": "exalted",
    "stack_size": 1,
    "official_stat_ids": ["explicit.stat_123", "explicit.stat_456"]
  },
  "market": {
    "source": "trade2/search+fetch",
    "current": 14.0,
    "median": 15.0,
    "count": 8,
    "confidence": "medium",
    "comparison_mode": "stat_ids_minus_one",
    "unit_priced": false
  },
  "verdict": "cheap",
  "risk_flags": ["low_comparable_count"]
}
```

ИИ не должен повышать уверенность по rare/equipment, если сравнение сделано только по названию или слабому текстовому совпадению.

## External Context

Внешний контекст лучше давать короткими фактами, а не длинными статьями.

```json
{
  "patch_notes": [
    {
      "date": "2026-05-29",
      "title": "Patch 0.5.0 notable balance change",
      "summary": "Short factual summary.",
      "affected_tags": ["runic_ward", "minion", "bow"],
      "source_url": "https://example.invalid/patch-notes"
    }
  ],
  "popular_builds": [
    {
      "build": "Spirit Walker projectile setup",
      "class": "Huntress",
      "confidence": "medium",
      "evidence": "3 large streamers and build guide imports observed.",
      "likely_item_demand": ["projectile bases", "specific support gems", "runes"],
      "source_urls": []
    }
  ],
  "streamer_mentions": [
    {
      "name": "StreamerName",
      "date": "2026-05-29",
      "topic": "League starter build",
      "mentioned_items": ["item_or_category_id"],
      "estimated_impact": "watch_only"
    }
  ],
  "known_risks": [
    {
      "risk": "possible_hotfix",
      "summary": "New mechanic reward appears overtuned; avoid long holds until hotfix window passes."
    }
  ]
}
```

## Ожидаемый JSON-ответ

```json
{
  "schema_version": "poe2-market-ai-assessment/v1",
  "summary": {
    "phase": "day_0_1",
    "market_read": "short Russian summary",
    "overall_risk": "high",
    "data_quality": "partial"
  },
  "signals": [
    {
      "item_id": "divine",
      "item_name": "Божественная сфера",
      "category": "Currency",
      "action": "watch",
      "confidence": "low",
      "time_horizon": "1-3 days",
      "thesis": "Price is moving, but early league data is too thin for a heavy entry.",
      "evidence": {
        "price_action": "7d/short trend if provided",
        "liquidity": "volume/listing/depth summary",
        "demand_driver": "known or unknown",
        "benchmark_view": "view across chaos/exalted/divine if provided"
      },
      "risks": [
        "early scarcity",
        "wide spread",
        "missing execution data"
      ],
      "suggested_checks": [
        "Recheck volume and spread in 2 hours.",
        "Compare against chaos and divine benchmark."
      ],
      "invalidation": [
        "Volume falls while price keeps rising.",
        "Hotfix changes the relevant farming source."
      ]
    }
  ],
  "missing_data": [
    "spread_percent is missing for several rows",
    "no current build popularity data"
  ],
  "do_not_trade": [
    {
      "item_id": "example",
      "reason": "single listing, no volume, likely price fixing"
    }
  ]
}
```

Разрешенные `action`:

- `buy_candidate` - можно проверять вход, но не означает автоматическую покупку.
- `sell_candidate` - стоит проверить фиксацию прибыли или продажу переоцененного лота.
- `hold` - держать, если позиция уже есть; новый вход не обязателен.
- `watch` - наблюдать, нужны новые снимки.
- `avoid` - риск выше потенциальной пользы.
- `insufficient_data` - данных мало для вывода.

Разрешенные `confidence`: `low`, `medium`, `high`.

## Рабочий промпт с подстановкой данных

```text
Ниже будет JSON с актуальным снимком рынка PoE2. Проанализируй его как торговый помощник, но не выдумывай отсутствующие данные.

Контекст:
- Общая памятка рынка: рынок новой лиги проходит фазы дефицита, насыщения, эндгейм-спроса и позднего снижения активности.
- На старте не считать одну валюту абсолютным эталоном; если есть данные, сравнивать в chaos/exalted/divine и будущей basket-модели.
- Stackable-позиции анализировать по агрегатам, rare/equipment - только по похожим trade2 listings.
- Любой вывод обязан учитывать ликвидность, spread, свежесть, объем, источник и риск price fixing.

Задача:
1. Дай короткую оценку состояния рынка.
2. Верни до {max_candidates} сигналов с action/confidence.
3. Отдельно перечисли missing_data.
4. Не советуй покупку, если сигнал держится только на одном лоте или нет объема.
5. Ответ строго JSON по схеме poe2-market-ai-assessment/v1.

JSON:
{market_context_json}
```

## Минимальные правила валидации

Перед отправкой в ИИ:

- `generated_at`, `league.id`, `league.day`, `league.phase` заполнены.
- Для каждой market row есть `id`, `category`, `source`, `target`.
- Хотя бы одно из `best` или `median` заполнено для priced-позиции.
- Если `sparkline_kind` отсутствует, не считать `sparkline` абсолютным ценовым рядом.
- Для stackable-позиций желательно иметь `volume`; без него confidence не выше `low`.
- Для rare/equipment не отправлять verdict без `market.count` и `market.confidence`.
- Секреты, токены, email, Telegram bot token и содержимое `.env` не отправлять.

После ответа ИИ:

- Отбрасывать сигналы с неизвестным `action` или `confidence`.
- Показывать пользователю причину и риски рядом с сигналом.
- Не превращать `buy_candidate` в автопокупку.
- Логировать входной payload и ответ без секретов, чтобы можно было проверить ошибочные выводы.
