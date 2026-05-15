import asyncio
import json

import app.trade2 as trade2
from app.trade2 import build_trade_advice, normalize_exchange_result, normalize_poe_ninja_overview, normalize_static_entries


def test_normalize_static_entries_skips_separators_and_expands_images():
    payload = {
        "result": [
            {
                "id": "Currency",
                "entries": [
                    {"id": "sep", "text": "Currency"},
                    {"id": "divine", "text": "Divine Orb", "image": "/image.png"},
                ],
            }
        ]
    }

    categories = normalize_static_entries(payload)

    assert categories["Currency"] == [
        {
            "id": "divine",
            "text": "Divine Orb",
            "text_ru": "Божественная сфера",
            "image": "https://www.pathofexile.com/image.png",
        }
    ]


def test_normalize_static_entries_prefers_official_russian_payload():
    payload = {
        "result": [
            {
                "id": "Currency",
                "entries": [
                    {"id": "transmute", "text": "Orb of Transmutation", "image": "/image.png"},
                ],
            }
        ]
    }
    localized_payload = {
        "result": [
            {
                "id": "Currency",
                "entries": [
                    {"id": "transmute", "text": "Сфера превращения"},
                ],
            }
        ]
    }

    categories = normalize_static_entries(payload, localized_payload)

    assert categories["Currency"][0]["text_ru"] == "Сфера превращения"


def test_normalize_exchange_result_flattens_offers():
    payload = {
        "id": "query123",
        "total": 1,
        "result": {
            "abc": {
                "listing": {
                    "indexed": "2026-05-12T10:00:00+00:00",
                    "account": {"name": "Seller#1234", "online": {"league": "Fate"}},
                    "offers": [
                        {
                            "exchange": {"currency": "exalted", "amount": 10},
                            "item": {"currency": "divine", "amount": 1, "stock": 4},
                        }
                    ],
                }
            }
        },
    }

    result = normalize_exchange_result(payload)

    assert result["query_id"] == "query123"
    assert result["total"] == 1
    assert result["rows"][0]["seller"] == "Seller#1234"
    assert result["rows"][0]["ratio"] == 0.1


def test_normalize_item_listing_requires_stash_buyout_price():
    payload = {
        "id": "item1",
        "listing": {
            "indexed": "2026-05-12T10:00:00Z",
            "stash": {"name": "Buyout", "x": 1, "y": 2},
            "price": {"type": "~price", "amount": 2, "currency": "divine"},
            "account": {"name": "Seller#1234", "online": False},
        },
        "item": {
            "icon": "icon.png",
            "name": "",
            "typeLine": "Expert Waxed Jacket",
            "baseType": "Waxed Jacket",
            "rarity": "Rare",
            "ilvl": 82,
            "explicitMods": ["+10 to Strength"],
            "extended": {
                "mods": {
                    "explicit": [
                        {
                            "name": "+10 to Strength",
                            "magnitudes": [{"hash": "explicit.stat_3299347043"}],
                        }
                    ]
                }
            },
        },
    }

    lot = trade2._normalize_item_listing(payload)

    assert lot["seller"] == "Seller#1234"
    assert lot["stash"] == "Buyout"
    assert lot["display_name"] == "Expert Waxed Jacket"
    assert lot["price_amount"] == 2
    assert lot["price_currency"] == "divine"
    assert lot["stat_mods"][0]["id"] == "explicit.stat_3299347043"
    assert lot["stat_mods"][0]["type"] == "explicit"
    assert lot["stat_mods"][0]["text"] == "+10 to Strength"


def test_normalize_item_listing_skips_unpriced_or_non_stash_listing():
    assert trade2._normalize_item_listing({"listing": {"price": {"amount": 1, "currency": "exalted"}}, "item": {}}) is None
    assert trade2._normalize_item_listing({"listing": {"stash": {"name": "Tab"}}, "item": {}}) is None


def test_market_price_stats_excludes_same_seller_and_marks_verdict():
    lots = [
        {"seller": "Seller#1234", "price_target": 1.0},
        {"seller": "Other#1", "price_target": 8.0},
        {"seller": "Other#2", "price_target": 10.0},
        {"seller": "Other#3", "price_target": 12.0},
    ]

    market = trade2._market_price_stats(lots, "Seller#1234")
    verdict = trade2._verdict_for_lot({"price_target": 7.0}, market)

    assert market["count"] == 3
    assert market["raw_count"] == 3
    assert market["outliers"] == 0
    assert market["median"] == 10.0
    assert verdict["kind"] == "cheap"
    assert verdict["delta_pct"] == -30.0


def test_market_price_stats_trims_outliers():
    lots = [
        {"seller": f"Other#{index}", "price_target": value}
        for index, value in enumerate([8.0, 9.0, 10.0, 11.0, 12.0, 100.0], start=1)
    ]

    market = trade2._market_price_stats(lots, "Seller#1234")

    assert market["raw_count"] == 6
    assert market["count"] == 5
    assert market["outliers"] == 1
    assert market["median"] == 10.0


def test_stackable_market_payload_uses_poe_ninja_unit_price():
    categories = {
        "Fragments": [
            {
                "id": "simulacrum-splinter",
                "text": "Simulacrum Splinter",
                "text_ru": "Осколок Симулякра",
                "image": None,
            }
        ]
    }
    lookup = trade2._static_entry_lookup(categories)
    lot = {
        "base_type": "Simulacrum Splinter",
        "price_amount": 20,
        "price_currency": "exalted",
        "stack_size": 2,
    }
    trade2._apply_target_price(lot, {"exalted": 1.0}, "exalted")
    category_cache = {
        "Fragments": {
            "rows": [
                {
                    "id": "simulacrum-splinter",
                    "median": 12.0,
                    "volume": 100,
                    "change": -5,
                }
            ],
            "cached": True,
        }
    }

    market = asyncio.run(
        trade2._stackable_market_payload("Fate", lot, "exalted", "any", lookup, category_cache)
    )
    verdict = trade2._verdict_for_lot(lot, market["stats"])

    assert market["stats"]["source"] == "poe.ninja"
    assert market["stats"]["unit_priced"] is True
    assert market["stats"]["current"] == 12.0
    assert lot["price_unit_target"] == 10.0
    assert verdict["kind"] == "cheap"


def test_seller_lots_text_query_uses_type_before_term():
    type_query = trade2._seller_lots_query("Seller#1234", "Waxed Jacket", "any")
    term_query = trade2._seller_lots_query("Seller#1234", "Vengeance Veil", "any", text_field="term")

    assert type_query["filters"]["trade_filters"]["filters"]["account"]["input"] == "Seller#1234"
    assert type_query["filters"]["trade_filters"]["filters"]["sale_type"]["option"] == "priced"
    assert type_query["type"] == "Waxed Jacket"
    assert "term" not in type_query
    assert term_query["term"] == "Vengeance Veil"


def test_similar_lots_query_starts_with_ilvl_window_for_non_unique():
    lot = {
        "base_type": "Waxed Jacket",
        "rarity": "Rare",
        "item_level": 82,
        "stat_mods": [{"id": "explicit.stat_123", "type": "explicit", "text": "+10 to Strength"}],
    }

    strict = trade2._similar_lots_query(lot, "any", looseness=0)
    wider = trade2._similar_lots_query(lot, "any", looseness=1)

    strict_filters = strict["filters"]["type_filters"]["filters"]
    wider_filters = wider["filters"]["type_filters"]["filters"]
    assert strict["type"] == "Waxed Jacket"
    assert strict_filters["rarity"]["option"] == "rare"
    assert strict_filters["ilvl"] == {"min": 77, "max": 87}
    assert strict["stats"][0]["filters"][0]["id"] == "explicit.stat_123"
    assert wider_filters["ilvl"] == {"min": 72, "max": 92}


def test_similar_lots_query_relaxes_stats_with_count_group():
    lot = {
        "base_type": "Waxed Jacket",
        "rarity": "Rare",
        "item_level": 82,
        "stat_mods": [
            {"id": "explicit.stat_life", "type": "explicit", "text": "+50 to maximum Life"},
            {"id": "explicit.stat_res", "type": "explicit", "text": "+30% to Fire Resistance"},
        ],
    }

    query = trade2._similar_lots_query(lot, "any", looseness=1)

    assert query["stats"][0]["type"] == "count"
    assert query["stats"][0]["value"] == {"min": 1}
    assert {item["id"] for item in query["stats"][0]["filters"]} == {"explicit.stat_life", "explicit.stat_res"}


def test_affix_keys_ignore_roll_values_and_trade_markup():
    lot = {
        "explicit_mods": [
            "+35 к духу",
            "[PhysicalDamage|26% увеличение уклонения]",
        ]
    }

    assert trade2._lot_affix_keys(lot) == ("# к духу", "#% увеличение уклонения")


def test_filter_comparable_lots_relaxes_by_one_affix_only_after_strict_step():
    target = {
        "base_type": "Одеяние аскета",
        "rarity": "Magic",
        "item_level": 52,
        "explicit_mods": ["+35 к духу", "26% увеличение уклонения"],
        "stat_mods": [
            {"id": "explicit.stat_spirit", "type": "explicit", "text": "+35 к духу"},
            {"id": "explicit.stat_evasion", "type": "explicit", "text": "26% увеличение уклонения"},
        ],
    }
    lots = [
        {
            "seller": "Other#1",
            "base_type": "Одеяние аскета",
            "rarity": "Magic",
            "item_level": 50,
            "explicit_mods": ["+40 к духу", "30% увеличение уклонения"],
            "stat_mods": [
                {"id": "explicit.stat_spirit", "type": "explicit", "text": "+40 к духу"},
                {"id": "explicit.stat_evasion", "type": "explicit", "text": "30% увеличение уклонения"},
            ],
            "price_target": 1.0,
        },
        {
            "seller": "Other#2",
            "base_type": "Одеяние аскета",
            "rarity": "Magic",
            "item_level": 54,
            "explicit_mods": ["+30 к духу", "+10 к максимуму здоровья"],
            "stat_mods": [
                {"id": "explicit.stat_spirit", "type": "explicit", "text": "+30 к духу"},
                {"id": "explicit.stat_life", "type": "explicit", "text": "+10 к максимуму здоровья"},
            ],
            "price_target": 2.0,
        },
        {
            "seller": "Other#3",
            "base_type": "Треуголка корсара",
            "rarity": "Magic",
            "item_level": 52,
            "explicit_mods": ["+35 к духу", "26% увеличение уклонения"],
            "stat_mods": [
                {"id": "explicit.stat_spirit", "type": "explicit", "text": "+35 к духу"},
                {"id": "explicit.stat_evasion", "type": "explicit", "text": "26% увеличение уклонения"},
            ],
            "price_target": 3.0,
        },
    ]

    strict = trade2._filter_comparable_lots(target, lots, looseness=0)
    relaxed = trade2._filter_comparable_lots(target, lots, looseness=1)

    assert [lot["price_target"] for lot in strict] == [1.0]
    assert [lot["price_target"] for lot in relaxed] == [1.0, 2.0]


def test_seller_lots_snapshot_uses_cache(monkeypatch):
    calls = {"search": 0, "fetch": 0}

    async def fake_post_search(league, query, sort=None):
        calls["search"] += 1
        return {"id": "query1", "total": 1, "result": ["item1"]}

    async def fake_fetch(ids, query_id, limit=60):
        calls["fetch"] += 1
        return [
            {
                "id": "item1",
                "listing": {
                    "stash": {"name": "Buyout"},
                    "price": {"amount": 1, "currency": "exalted"},
                    "account": {"name": "Seller#1234"},
                },
                "item": {"typeLine": "Waxed Jacket", "baseType": "Waxed Jacket", "rarity": "Rare"},
            }
        ]

    monkeypatch.setattr(trade2, "SELLER_LOTS_CACHE", {})
    monkeypatch.setattr(trade2, "_post_search", fake_post_search)
    monkeypatch.setattr(trade2, "_fetch_trade_items", fake_fetch)

    first = asyncio.run(trade2._get_seller_lots_snapshot("Fate", "Seller#1234", "any"))
    second = asyncio.run(trade2._get_seller_lots_snapshot("Fate", "Seller#1234", "any"))

    assert first["cached"] is False
    assert second["cached"] is True
    assert second["lots"][0]["display_name"] == "Waxed Jacket"
    assert calls == {"search": 1, "fetch": 1}


def test_read_history_filters_without_changing_newest_first_order(tmp_path, monkeypatch):
    history_path = tmp_path / "history.jsonl"
    history_path.write_text(
        "\n".join(
            [
                json.dumps({"created_ts": 1, "league": "A", "category": "Currency", "target": "exalted", "status": "any"}),
                json.dumps({"created_ts": 2, "league": "B", "category": "Currency", "target": "exalted", "status": "any"}),
                json.dumps({"created_ts": 3, "league": "A", "category": "Currency", "target": "exalted", "status": "any"}),
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(trade2, "HISTORY_PATH", history_path)

    history = trade2.read_history(limit=2, league="A", category="Currency", target="exalted", status="any")

    assert [item["created_ts"] for item in history] == [3, 1]


def test_normalize_poe_ninja_overview_converts_primary_value_to_target():
    payload = {
        "core": {"primary": "divine", "rates": {"exalted": 175, "chaos": 30}},
        "lines": [
            {
                "id": "liquid-paranoia",
                "primaryValue": 0.02,
                "volumePrimaryValue": 4,
                "sparkline": {"totalChange": 12.5, "data": [1, 2, 3]},
            }
        ],
    }

    result = normalize_poe_ninja_overview(payload, "exalted")

    assert result["target_supported"] is True
    assert result["rows"][0]["id"] == "liquid-paranoia"
    assert result["rows"][0]["best"] == 3.5
    assert result["rows"][0]["median"] == 3.5
    assert result["rows"][0]["volume"] == 700
    assert result["rows"][0]["change"] == 12.5
    assert [round(value, 4) for value in result["rows"][0]["sparkline"]] == [3.432, 3.466, 3.5]


def test_build_trade_advice_marks_low_volume_emotion_upgrade():
    rows = [
        {
            "id": "diluted-liquid-ire",
            "text": "Diluted Liquid Ire",
            "text_ru": "Разбавленный жидкий гнев",
            "median": 1,
            "volume": 3,
        },
        {
            "id": "diluted-liquid-guilt",
            "text": "Diluted Liquid Guilt",
            "text_ru": "Разбавленная жидкая вина",
            "median": 4,
            "volume": 20,
        },
    ]

    advice = build_trade_advice("Delirium", rows, "divine")

    assert len(advice) == 1
    assert advice[0]["profit"] == 1
    assert advice[0]["margin"] == 1 / 3
    assert advice[0]["severity"] == "weak"
    assert advice[0]["min_volume"] == 3
    assert advice[0]["low_volume"] is True
    assert "Объем низкий" in advice[0]["message_ru"]


def test_build_trade_advice_classifies_signal_and_watch():
    rows = [
        {
            "id": "diluted-liquid-ire",
            "text": "Diluted Liquid Ire",
            "text_ru": "Разбавленный жидкий гнев",
            "median": 1,
            "volume": 30,
        },
        {
            "id": "diluted-liquid-guilt",
            "text": "Diluted Liquid Guilt",
            "text_ru": "Разбавленная жидкая вина",
            "median": 3.5,
            "volume": 30,
        },
        {
            "id": "diluted-liquid-greed",
            "text": "Diluted Liquid Greed",
            "text_ru": "Разбавленная жидкая жадность",
            "median": 9,
            "volume": 30,
        },
    ]

    advice = build_trade_advice("Delirium", rows, "divine")

    assert [item["severity"] for item in advice] == ["signal", "watch", "watch"]
    assert advice[0]["source"] == "diluted-liquid-ire"
    assert advice[0]["result"] == "diluted-liquid-guilt"
    assert advice[0]["path_steps"] == 1
    assert advice[0]["input_count"] == 3
    assert advice[0]["profit"] == 3.5 - 1 * 3
    assert "Объем достаточный" in advice[0]["message_ru"]


def test_build_trade_advice_finds_best_full_emotion_path():
    rows = [
        {
            "id": "diluted-liquid-ire",
            "text": "Diluted Liquid Ire",
            "text_ru": "Разбавленный жидкий гнев",
            "median": 1,
            "volume": 30,
        },
        {
            "id": "diluted-liquid-guilt",
            "text": "Diluted Liquid Guilt",
            "text_ru": "Разбавленная жидкая вина",
            "median": 4,
            "volume": 30,
        },
        {
            "id": "diluted-liquid-greed",
            "text": "Diluted Liquid Greed",
            "text_ru": "Разбавленная жидкая жадность",
            "median": 20,
            "volume": 30,
            "sparkline": [10, 15, 20],
        },
    ]

    advice = build_trade_advice("Delirium", rows, "divine")

    assert advice[0]["source"] == "diluted-liquid-ire"
    assert advice[0]["result"] == "diluted-liquid-greed"
    assert advice[0]["path_steps"] == 2
    assert advice[0]["input_count"] == 9
    assert advice[0]["profit"] == 11
    assert advice[0]["result_sparkline"] == [10, 15, 20]
    assert "9 x" in advice[0]["message_ru"]


def test_read_latest_rates_returns_newest_matching_snapshot(tmp_path, monkeypatch):
    history = tmp_path / "history.jsonl"
    snapshots = [
        {
            "created_ts": 1,
            "league": "Fate",
            "category": "Currency",
            "target": "divine",
            "status": "any",
            "source": "poe.ninja",
            "rows": [{"id": "exalted", "median": 0.01}],
        },
        {
            "created_ts": 2,
            "league": "Fate",
            "category": "Currency",
            "target": "divine",
            "status": "online",
            "source": "trade2",
            "rows": [{"id": "exalted", "median": 0.02}],
        },
    ]
    history.write_text("\n".join(json.dumps(item) for item in snapshots), encoding="utf-8")
    monkeypatch.setattr(trade2, "HISTORY_PATH", history)

    latest = trade2.read_latest_rates("Fate", "Currency", target="divine", status="online")

    assert latest["cached"] is True
    assert latest["created_ts"] == 2
    assert latest["source"] == "trade2"
    assert latest["rows"][0]["median"] == 0.02


def test_read_item_history_returns_metric_series(tmp_path, monkeypatch):
    history = tmp_path / "history.jsonl"
    snapshots = [
        {
            "created_ts": 1,
            "league": "Fate",
            "category": "Currency",
            "target": "exalted",
            "status": "any",
            "source": "poe.ninja",
            "rows": [{"id": "chaos", "median": 4, "volume": 100, "offers": 0}],
        },
        {
            "created_ts": 2,
            "league": "Fate",
            "category": "Currency",
            "target": "exalted",
            "status": "any",
            "source": "poe.ninja",
            "rows": [{"id": "chaos", "median": 5, "volume": 120, "offers": 0}],
        },
    ]
    history.write_text("\n".join(json.dumps(item) for item in snapshots), encoding="utf-8")
    monkeypatch.setattr(trade2, "HISTORY_PATH", history)

    price = trade2.read_item_history(
        league="Fate",
        category="Currency",
        target="exalted",
        status="any",
        item_id="chaos",
        metric="price",
    )
    demand = trade2.read_item_history(
        league="Fate",
        category="Currency",
        target="exalted",
        status="any",
        item_id="chaos",
        metric="demand",
    )

    assert [item["value"] for item in price] == [4, 5]
    assert [item["value"] for item in demand] == [100, 120]
