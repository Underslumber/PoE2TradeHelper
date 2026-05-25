import asyncio
import json
import time
from datetime import datetime, timedelta, timezone

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


def test_get_trade_static_uses_module_cache(monkeypatch):
    calls = []

    class FakeResponse:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, url, *args, **kwargs):
            calls.append(url)
            if "ru.pathofexile.com" in url:
                return FakeResponse({"result": [{"id": "Currency", "entries": [{"id": "chaos", "text": "Сфера хаоса"}]}]})
            return FakeResponse({"result": [{"id": "Currency", "entries": [{"id": "chaos", "text": "Chaos Orb"}]}]})

    monkeypatch.setattr(trade2, "TRADE_STATIC_CACHE", {"created_ts": 0.0, "data": None})
    monkeypatch.setattr(trade2.httpx, "AsyncClient", FakeAsyncClient)

    first = asyncio.run(trade2.get_trade_static())
    second = asyncio.run(trade2.get_trade_static())

    assert len(calls) == 2
    assert first == second
    assert first["Currency"][0]["text"] == "Chaos Orb"
    assert first["Currency"][0]["text_ru"] == "Сфера хаоса"


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


def test_normalize_item_listing_tracks_listing_age(monkeypatch):
    now = datetime(2026, 5, 25, 12, 0, tzinfo=timezone.utc)
    indexed = now - timedelta(days=3, hours=6)
    monkeypatch.setattr(trade2.time, "time", lambda: now.timestamp())
    payload = {
        "id": "item1",
        "listing": {
            "indexed": indexed.isoformat().replace("+00:00", "Z"),
            "stash": {"name": "Buyout", "x": 1, "y": 2},
            "price": {"type": "~price", "amount": 2, "currency": "divine"},
            "account": {"name": "Seller#1234", "online": False},
        },
        "item": {"typeLine": "Crimson Amulet", "baseType": "Crimson Amulet", "rarity": "Normal"},
    }

    lot = trade2._normalize_item_listing(payload)

    assert lot["indexed_ts"] == indexed.timestamp()
    assert lot["listed_age_seconds"] == 3 * 86400 + 6 * 3600
    assert lot["listed_age_days"] == 3.25
    assert lot["stale"] is False
    assert lot["high_demand_age"] is False


def test_normalize_item_listing_skips_unpriced_or_non_stash_listing():
    assert trade2._normalize_item_listing({"listing": {"price": {"amount": 1, "currency": "exalted"}}, "item": {}}) is None
    assert trade2._normalize_item_listing({"listing": {"stash": {"name": "Tab"}}, "item": {}}) is None
    assert (
        trade2._normalize_item_listing(
            {
                "listing": {
                    "stash": {"name": "Tab"},
                    "price": {"type": "~c/o", "amount": 1, "currency": "exalted"},
                },
                "item": {},
            }
        )
        is None
    )


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
    assert strict[0]["similarity"]["matched_stat_ids"] == ["explicit.stat_evasion", "explicit.stat_spirit"]


def test_market_confidence_requires_multiple_official_stats_for_high_confidence():
    comparison = {
        "mode": "type-level-stat-ids",
        "official_stat_count": 1,
    }
    stronger_comparison = {
        "mode": "type-level-stat-ids",
        "official_stat_count": 2,
    }
    stats = {"avg_similarity": 90}

    assert trade2._market_confidence(10, comparison, stats) == "medium"
    assert trade2._market_confidence(10, stronger_comparison, stats) == "high"


def test_manual_seller_lot_profile_requires_selected_stats():
    target = {
        "base_type": "Waxed Jacket",
        "rarity": "Rare",
        "item_level": 82,
        "stat_mods": [
            {"id": "explicit.stat_life", "type": "explicit", "text": "+50 to maximum Life"},
            {"id": "explicit.stat_res", "type": "explicit", "text": "+30% to Fire Resistance"},
        ],
    }
    lots = [
        {
            "seller": "Other#1",
            "base_type": "Waxed Jacket",
            "rarity": "Rare",
            "item_level": 83,
            "stat_mods": [{"id": "explicit.stat_life", "type": "explicit", "text": "+55 to maximum Life"}],
            "price_target": 10.0,
        },
        {
            "seller": "Other#2",
            "base_type": "Waxed Jacket",
            "rarity": "Rare",
            "item_level": 83,
            "stat_mods": [{"id": "explicit.stat_res", "type": "explicit", "text": "+35% to Fire Resistance"}],
            "price_target": 20.0,
        },
    ]
    profile = trade2._manual_stat_profile(
        preferred_stat_ids="explicit.stat_life",
        ignored_stat_ids="explicit.stat_res",
    )

    query = trade2._similar_lots_query(target, "any", looseness=0, profile=profile)
    strict = trade2._filter_comparable_lots(target, lots, looseness=0, profile=profile)
    comparison = trade2._comparable_lot_profile(target, looseness=0, profile=profile)

    assert [item["id"] for item in query["stats"][0]["filters"]] == ["explicit.stat_life"]
    assert [lot["price_target"] for lot in strict] == [10.0]
    assert comparison["manual_profile"] is True
    assert comparison["preferred_stat_ids"] == ["explicit.stat_life"]
    assert comparison["ignored_stat_ids"] == ["explicit.stat_res"]


def test_manual_seller_lot_profile_can_ignore_base_type():
    target = {
        "base_type": "Waxed Jacket",
        "rarity": "Rare",
        "item_level": 82,
        "stat_mods": [{"id": "explicit.stat_life", "type": "explicit", "text": "+50 to maximum Life"}],
    }
    lots = [
        {
            "base_type": "Silk Robe",
            "rarity": "Rare",
            "item_level": 82,
            "stat_mods": [{"id": "explicit.stat_life", "type": "explicit", "text": "+55 to maximum Life"}],
            "price_target": 10.0,
        },
        {
            "base_type": "Silk Robe",
            "rarity": "Rare",
            "item_level": 82,
            "stat_mods": [{"id": "explicit.stat_res", "type": "explicit", "text": "+35% to Fire Resistance"}],
            "price_target": 20.0,
        },
    ]
    profile = trade2._manual_stat_profile(preferred_stat_ids="explicit.stat_life", base_mode="ignored")

    query = trade2._similar_lots_query(target, "any", looseness=0, profile=profile)
    strict = trade2._filter_comparable_lots(target, lots, looseness=0, profile=profile)

    assert "type" not in query
    assert [lot["price_target"] for lot in strict] == [10.0]


def test_manual_seller_lot_profile_can_focus_affix_tier():
    target = {
        "base_type": "Waxed Jacket",
        "rarity": "Rare",
        "item_level": 82,
        "stat_mods": [
            {"id": "explicit.stat_life", "type": "explicit", "text": "+50 to maximum Life", "tier": "T3", "level": 55},
        ],
    }
    lots = [
        {
            "base_type": "Waxed Jacket",
            "rarity": "Rare",
            "item_level": 82,
            "stat_mods": [
                {"id": "explicit.stat_life", "type": "explicit", "text": "+52 to maximum Life", "tier": "T3", "level": 55},
            ],
            "price_target": 10.0,
        },
        {
            "base_type": "Waxed Jacket",
            "rarity": "Rare",
            "item_level": 82,
            "stat_mods": [
                {"id": "explicit.stat_life", "type": "explicit", "text": "+70 to maximum Life", "tier": "T2", "level": 62},
            ],
            "price_target": 20.0,
        },
    ]
    profile = trade2._manual_stat_profile(tier_stat_ids="explicit.stat_life")

    strict = trade2._filter_comparable_lots(target, lots, looseness=0, profile=profile)
    comparison = trade2._comparable_lot_profile(target, looseness=0, profile=profile)

    assert [lot["price_target"] for lot in strict] == [10.0]
    assert comparison["tier_stat_ids"] == ["explicit.stat_life"]


def test_manual_seller_lot_profile_can_limit_affix_value_range():
    target = {
        "base_type": "Waxed Jacket",
        "rarity": "Rare",
        "item_level": 82,
        "stat_mods": [
            {"id": "explicit.stat_life", "type": "explicit", "text": "+50 to maximum Life", "min": 50.0, "max": 50.0},
        ],
    }
    lots = [
        {
            "base_type": "Waxed Jacket",
            "rarity": "Rare",
            "item_level": 82,
            "stat_mods": [
                {"id": "explicit.stat_life", "type": "explicit", "text": "+55 to maximum Life", "min": 55.0, "max": 55.0},
            ],
            "price_target": 10.0,
        },
        {
            "base_type": "Waxed Jacket",
            "rarity": "Rare",
            "item_level": 82,
            "stat_mods": [
                {"id": "explicit.stat_life", "type": "explicit", "text": "+70 to maximum Life", "min": 70.0, "max": 70.0},
            ],
            "price_target": 20.0,
        },
    ]
    profile = trade2._manual_stat_profile(stat_value_ranges='{"explicit.stat_life":{"min":45,"max":60}}')

    query = trade2._similar_lots_query(target, "any", looseness=0, profile=profile)
    strict = trade2._filter_comparable_lots(target, lots, looseness=0, profile=profile)

    assert query["stats"][0]["filters"][0]["value"] == {"min": 45.0, "max": 60.0}
    assert [lot["price_target"] for lot in strict] == [10.0]


def test_manual_seller_lot_profile_can_match_base_without_properties():
    target = {
        "base_type": "Waxed Jacket",
        "rarity": "Rare",
        "item_level": 82,
        "stat_mods": [
            {"id": "explicit.stat_life", "type": "explicit", "text": "+50 to maximum Life"},
        ],
    }
    lots = [
        {
            "base_type": "Waxed Jacket",
            "rarity": "Rare",
            "item_level": 83,
            "stat_mods": [{"id": "explicit.stat_res", "type": "explicit", "text": "+35% to Fire Resistance"}],
            "price_target": 10.0,
        },
        {
            "base_type": "Silk Robe",
            "rarity": "Rare",
            "item_level": 83,
            "stat_mods": [{"id": "explicit.stat_life", "type": "explicit", "text": "+55 to maximum Life"}],
            "price_target": 20.0,
        },
    ]
    profile = trade2._manual_stat_profile(base_only=True, base_mode="ignored")

    query = trade2._similar_lots_query(target, "any", looseness=0, profile=profile)
    strict = trade2._filter_comparable_lots(target, lots, looseness=0, profile=profile)
    comparison = trade2._comparable_lot_profile(target, looseness=0, profile=profile)

    assert query["type"] == "Waxed Jacket"
    assert query["stats"][0]["filters"] == []
    assert [lot["price_target"] for lot in strict] == [10.0]
    assert comparison["mode"] == "base-only"
    assert comparison["base_only"] is True


def test_seller_base_summaries_rank_by_median_buyout_price():
    lots = [
        {"base_type": "Waxed Jacket", "rarity": "Rare", "item_level": 82, "price_target": 10.0, "id": "a"},
        {"base_type": "Waxed Jacket", "rarity": "Rare", "item_level": 82, "price_target": 12.0, "id": "b"},
        {"base_type": "Silk Robe", "rarity": "Rare", "item_level": 82, "price_target": 30.0, "id": "c"},
    ]

    summaries = trade2._seller_base_summaries(lots, "exalted", top=2)

    assert summaries[0]["base_type"] == "Silk Robe"
    assert summaries[0]["median"] == 30.0
    assert summaries[1]["base_type"] == "Waxed Jacket"
    assert summaries[1]["avg"] == 11.0
    assert summaries[1]["count"] == 2


def test_normalize_item_base_catalog_prefers_localized_query_text():
    payload = {
        "result": [
            {
                "id": "armour",
                "label": "Armour",
                "entries": [
                    {"type": "Waxed Jacket", "text": "Waxed Jacket"},
                    {"type": "Silk Robe", "text": "Silk Robe"},
                    {"type": "[DNT-UNUSED] Hand Wraps", "text": "[DNT-UNUSED] Hand Wraps"},
                ],
            },
            {
                "id": "currency",
                "label": "Currency",
                "entries": [{"type": "Chaos Orb", "text": "Chaos Orb"}],
            },
            {
                "id": "jewel",
                "label": "Jewels",
                "entries": [{"type": "Ruby", "text": "Ruby"}],
            },
        ]
    }
    localized_payload = {
        "result": [
            {
                "id": "armour",
                "label": "Броня",
                "entries": [
                    {"type": "Вощеная куртка", "text": "Вощеная куртка"},
                    {"type": "Шелковая роба", "text": "Шелковая роба"},
                    {"type": "[DNT-UNUSED] Hand Wraps", "text": "[DNT-UNUSED] Hand Wraps"},
                ],
            }
        ]
    }

    bases = trade2.normalize_item_base_catalog(payload, localized_payload)

    assert [base["type"] for base in bases] == ["Silk Robe", "Waxed Jacket"]
    assert bases[0]["type_ru"] == "Шелковая роба"
    assert bases[0]["query_type"] == "Шелковая роба"
    assert all(base["category"] == "armour" for base in bases)


def test_item_base_fallback_catalog_is_russian_and_has_icons():
    bases = trade2._item_base_fallback_catalog()

    first = bases[0]
    assert first["type"] == "Waxed Jacket"
    assert first["type_ru"] == "Вощеная куртка"
    assert first["category_label_ru"] == "Нательная броня"
    assert first["image"].startswith("/icons/item-bases/generated/")
    assert first["icon_key"] == "armour"
    assert all(base["category_label_ru"] != "Fallback" for base in bases)


def test_item_base_catalog_icons_are_local_files(tmp_path, monkeypatch):
    monkeypatch.setattr(trade2, "ITEM_BASE_ICON_DIR", tmp_path / "icons")
    monkeypatch.setattr(trade2, "ITEM_BASE_BUNDLED_ICON_DIR", tmp_path / "bundled-icons")

    bases = trade2._ensure_item_base_catalog_icons(
        [{"id": "base:amber-amulet", "type": "Amber Amulet", "icon_key": "amulet", "image": "data:image/svg+xml;utf8,old"}]
    )

    assert bases[0]["image"] == "/icons/item-bases/generated/amulet.svg"
    assert (tmp_path / "icons" / "generated" / "amulet.svg").exists()


def test_item_base_catalog_recreates_generated_icon_from_seed_path(tmp_path, monkeypatch):
    monkeypatch.setattr(trade2, "ITEM_BASE_ICON_DIR", tmp_path / "icons")
    monkeypatch.setattr(trade2, "ITEM_BASE_BUNDLED_ICON_DIR", tmp_path / "bundled-icons")

    bases = trade2._ensure_item_base_catalog_icons(
        [{"id": "base:unknown", "type": "Unknown", "icon_key": "base", "image": "/icons/item-bases/generated/base.svg"}]
    )

    assert bases[0]["image"] == "/icons/item-bases/generated/base.svg"
    assert (tmp_path / "icons" / "generated" / "base.svg").exists()
    assert "width='64' height='64'" in (tmp_path / "icons" / "generated" / "base.svg").read_text(encoding="utf-8")


def test_item_base_generated_icon_rewrites_legacy_svg(tmp_path, monkeypatch):
    monkeypatch.setattr(trade2, "ITEM_BASE_ICON_DIR", tmp_path / "icons")
    icon_path = tmp_path / "icons" / "generated" / "base.svg"
    icon_path.parent.mkdir(parents=True)
    icon_path.write_text("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'></svg>", encoding="utf-8")

    assert trade2._item_base_generated_icon_url("base") == "/icons/item-bases/generated/base.svg"
    assert "width='64' height='64'" in icon_path.read_text(encoding="utf-8")


def test_item_base_catalog_prefers_existing_local_icon(tmp_path, monkeypatch):
    icon_dir = tmp_path / "icons"
    icon_dir.mkdir()
    (icon_dir / "amber-amulet.png").write_bytes(b"png")
    monkeypatch.setattr(trade2, "ITEM_BASE_ICON_DIR", icon_dir)

    bases = trade2._ensure_item_base_catalog_icons(
        [{"id": "base:amber-amulet", "type": "Amber Amulet", "icon_key": "amulet", "image": "/icons/item-bases/generated/amulet.svg"}]
    )

    assert bases[0]["image"] == "/icons/item-bases/amber-amulet.png"


def test_item_base_catalog_prefers_bundled_icon_when_storage_is_empty(tmp_path, monkeypatch):
    storage_icon_dir = tmp_path / "storage-icons"
    bundled_icon_dir = tmp_path / "bundled-icons"
    storage_icon_dir.mkdir()
    bundled_icon_dir.mkdir()
    (bundled_icon_dir / "amber-amulet.png").write_bytes(b"png")
    monkeypatch.setattr(trade2, "ITEM_BASE_ICON_DIR", storage_icon_dir)
    monkeypatch.setattr(trade2, "ITEM_BASE_BUNDLED_ICON_DIR", bundled_icon_dir)

    bases = trade2._ensure_item_base_catalog_icons(
        [{"id": "base:amber-amulet", "type": "Amber Amulet", "icon_key": "amulet", "image": "/icons/item-bases/generated/amulet.svg"}]
    )

    assert bases[0]["image"] == "/static/item-base-icons/amber-amulet.png"


def test_poe2db_item_class_links_keep_equipment_and_skip_non_bases():
    html = """
    <div class="itemList">
      <span class="disabled">Одноручное оружие</span>
      <a class="ItemClasses" href="Claws">Когти</a>
      <a class="ItemClasses" href="Skill_Gems">Камни умений</a>
      <a class="ItemClasses" href="Fishing_Rods">Удочки</a>
      <a class="ItemClasses" href="Jewels">Самоцветы</a>
    </div>
    <div class="itemList">
      <span class="disabled">Доспехи</span>
      <a class="ItemClasses" href="Body_Armours">Нательные доспехи</a>
    </div>
    <div class="itemList">
      <span class="disabled">Валюта</span>
      <a class="ItemClasses" href="Augment">Усилители</a>
    </div>
    <div class="itemList">
      <span class="disabled">Прочее</span>
      <a class="ItemClasses" href="Vault_Keys">Ключи от хранилищ</a>
    </div>
    """

    classes = trade2._poe2db_item_class_links(html)

    assert classes == [
        {"slug": "Claws", "label_ru": "Когти", "group_label_ru": "Одноручное оружие"},
        {"slug": "Body_Armours", "label_ru": "Нательные доспехи", "group_label_ru": "Доспехи"},
    ]


def test_parse_poe2db_item_class_bases_extracts_names_and_icons():
    html = """
    <div class="d-flex border-top rounded">
      <img class="panel-item-icon" src="https://cdn.poe2db.tw/image/Art/2DItems/Weapons/Claws/Claw01.webp">
      <a class="whiteitem Claw" href="Crude_Claw">Грубый кастет</a>
    </div>
    <div class="d-flex border-top rounded">
      <a class="magicitem" href="Ignored">Не база</a>
    </div>
    <div class="d-flex border-top rounded">
      <a class="whiteitem Claw" href="Unused_Hand_Wraps">[DNT-UNUSED] Hand Wraps</a>
    </div>
    """

    bases = trade2._parse_poe2db_item_class_bases(
        html,
        {"slug": "Claws", "label_ru": "Когти", "group_label_ru": "Одноручное оружие"},
    )

    assert bases == [
        {
            "id": "base:грубый-кастет",
            "type": "Грубый кастет",
            "type_ru": "Грубый кастет",
            "query_type": "Грубый кастет",
            "category": "Claws",
            "category_label": "Когти",
            "category_label_ru": "Когти",
            "group_label_ru": "Одноручное оружие",
            "poe2db_slug": "Crude_Claw",
            "icon_key": "base",
            "image": "https://cdn.poe2db.tw/image/Art/2DItems/Weapons/Claws/Claw01.webp",
        }
    ]


def test_item_base_catalog_snapshot_roundtrip(tmp_path):
    payload = {
        "created_ts": 123.0,
        "source": "trade2/data/items",
        "bases": [{"id": "base:amber-amulet", "type": "Amber Amulet", "type_ru": "Амулет с янтарём"}],
        "errors": [],
    }
    path = tmp_path / "item_base_catalog.json"

    trade2.save_item_base_catalog_snapshot(payload, path=path)
    loaded = trade2.load_item_base_catalog_snapshot(path=path)

    assert loaded is not None
    assert loaded["schema_version"] == trade2.ITEM_BASE_CATALOG_SCHEMA_VERSION
    assert loaded["created_ts"] == 123.0
    assert loaded["bases"][0]["type_ru"] == "Амулет с янтарём"


def test_bundled_item_base_seed_is_built_from_pob_catalog():
    payload = json.loads(trade2.ITEM_BASE_BUNDLED_CATALOG_PATH.read_text(encoding="utf-8"))
    bases = {base["type"]: base for base in payload["bases"]}

    assert payload["source"] == "PathOfBuilding-PoE2/Data/Bases+poe2db/ru"
    assert payload["total"] == len(payload["bases"]) >= 900
    assert bases["Cutlass"]["type_ru"] == "Абордажная сабля"
    assert bases["Cutlass"]["base_class_label_ru"] == "Мечи"
    assert bases["Rawhide Boots"]["type_ru"] == "Сыромятные сапоги"
    assert bases["Rawhide Boots"]["base_class_label_ru"] == "Обувь"
    assert bases["Shortbow"]["type_ru"] == "Короткий лук"
    assert bases["Crude Claw"]["type_ru"] == "Грубый кастет"
    assert "Shrine Sceptre (Purity of Fire)" not in bases
    assert "Golden Hoop" not in bases
    assert "Fishing Rod" not in bases
    assert "Ruby" not in bases
    assert all(base["type_ru"] and not base["type_ru"].isascii() for base in payload["bases"])


def test_item_base_catalog_prefers_pob_seed_over_old_stored_trade2_catalog(tmp_path, monkeypatch):
    old_runtime_path = tmp_path / "item_base_catalog.json"
    old_runtime_path.write_text(
        json.dumps(
            {
                "schema_version": trade2.ITEM_BASE_CATALOG_SCHEMA_VERSION,
                "created_ts": 100.0,
                "source": "trade2/data/items",
                "total": 1,
                "bases": [
                    {
                        "id": "base:rawhide-boots",
                        "type": "Rawhide Boots",
                        "type_ru": "Золочёное облачение",
                        "query_type": "Золочёное облачение",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    bundled_path = tmp_path / "item_base_catalog_seed.json"
    bundled_path.write_text(
        json.dumps(
            {
                "schema_version": trade2.ITEM_BASE_CATALOG_SCHEMA_VERSION,
                "created_ts": 200.0,
                "source": "PathOfBuilding-PoE2/Data/Bases+poe2db/ru",
                "total": 1,
                "bases": [
                    {
                        "id": "base:rawhide-boots",
                        "type": "Rawhide Boots",
                        "type_ru": "Сыромятные сапоги",
                        "query_type": "Сыромятные сапоги",
                        "category": "armour",
                        "category_label": "Armour",
                        "category_label_ru": "Броня",
                        "icon_key": "boots",
                        "image": "/icons/item-bases/generated/boots.svg",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    async def unexpected_fetch(_locale="en"):
        raise AssertionError("trade2 catalog should not be fetched when PoB seed exists")

    monkeypatch.setattr(trade2, "_fetch_item_base_catalog_payload", unexpected_fetch)
    monkeypatch.setattr(trade2, "ITEM_BASE_CATALOG_PATH", old_runtime_path)
    monkeypatch.setattr(trade2, "ITEM_BASE_BUNDLED_CATALOG_PATH", bundled_path)
    monkeypatch.setattr(trade2, "ITEM_BASE_ICON_DIR", tmp_path / "storage-icons")
    monkeypatch.setattr(trade2, "ITEM_BASE_BUNDLED_ICON_DIR", tmp_path / "bundled-icons")
    monkeypatch.setattr(trade2, "ITEM_BASES_CACHE", {"created_ts": 0.0, "data": None, "errors": []})

    result = asyncio.run(trade2.get_item_base_catalog())

    assert result["source"] == "bundled:item_base_catalog_seed"
    assert result["total"] == 1
    assert result["bases"][0]["type_ru"] == "Сыромятные сапоги"


def test_item_base_catalog_filters_by_pob_base_class(tmp_path, monkeypatch):
    catalog_path = tmp_path / "item_base_catalog.json"
    catalog_path.write_text(
        json.dumps(
            {
                "schema_version": trade2.ITEM_BASE_CATALOG_SCHEMA_VERSION,
                "created_ts": 200.0,
                "source": "PathOfBuilding-PoE2/Data/Bases+poe2db/ru",
                "total": 2,
                "bases": [
                    {
                        "id": "base:scimitar",
                        "type": "Scimitar",
                        "type_ru": "Скимитар",
                        "query_type": "Скимитар",
                        "category": "weapon",
                        "category_label": "Weapons",
                        "category_label_ru": "Оружие",
                        "base_class": "sword",
                        "base_class_label": "Swords",
                        "base_class_label_ru": "Мечи",
                        "icon_key": "base",
                        "image": "/icons/item-bases/generated/base.svg",
                    },
                    {
                        "id": "base:hammer",
                        "type": "Hammer",
                        "type_ru": "Молот",
                        "query_type": "Молот",
                        "category": "weapon",
                        "category_label": "Weapons",
                        "category_label_ru": "Оружие",
                        "base_class": "mace",
                        "base_class_label": "Maces",
                        "base_class_label_ru": "Булавы",
                        "icon_key": "base",
                        "image": "/icons/item-bases/generated/base.svg",
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(trade2, "ITEM_BASE_CATALOG_PATH", catalog_path)
    monkeypatch.setattr(trade2, "ITEM_BASE_BUNDLED_CATALOG_PATH", tmp_path / "missing_seed.json")
    monkeypatch.setattr(trade2, "ITEM_BASE_ICON_DIR", tmp_path / "storage-icons")
    monkeypatch.setattr(trade2, "ITEM_BASE_BUNDLED_ICON_DIR", tmp_path / "bundled-icons")
    monkeypatch.setattr(trade2, "ITEM_BASES_CACHE", {"created_ts": 0.0, "data": None, "errors": []})

    result = asyncio.run(trade2.get_item_base_catalog(q="меч"))

    assert result["matched_total"] == 1
    assert result["bases"][0]["type_ru"] == "Скимитар"
    assert result["bases"][0]["base_class_label_ru"] == "Мечи"


def test_item_base_catalog_uses_bundled_seed_when_trade2_is_limited(tmp_path, monkeypatch):
    async def fake_fetch(_locale="en"):
        raise RuntimeError("trade2 item catalog rate limited")

    async def fake_poe2db_catalog():
        return []

    bundled_path = tmp_path / "item_base_catalog_seed.json"
    bundled_path.write_text(
        json.dumps(
            {
                "schema_version": trade2.ITEM_BASE_CATALOG_SCHEMA_VERSION,
                "created_ts": 456.0,
                "source": "trade2/data/items",
                "total": 1,
                "bases": [
                    {
                        "id": "base:amber-amulet",
                        "type": "Amber Amulet",
                        "type_ru": "Амулет с янтарём",
                        "query_type": "Амулет с янтарём",
                        "icon_key": "amulet",
                        "image": "/icons/item-bases/generated/amulet.svg",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    storage_icon_dir = tmp_path / "storage-icons"
    bundled_icon_dir = tmp_path / "bundled-icons"
    storage_icon_dir.mkdir()
    bundled_icon_dir.mkdir()
    (bundled_icon_dir / "amber-amulet.png").write_bytes(b"png")
    monkeypatch.setattr(trade2, "_fetch_item_base_catalog_payload", fake_fetch)
    monkeypatch.setattr(trade2, "_fetch_poe2db_item_base_catalog", fake_poe2db_catalog)
    monkeypatch.setattr(trade2, "ITEM_BASE_CATALOG_PATH", tmp_path / "missing_runtime_catalog.json")
    monkeypatch.setattr(trade2, "ITEM_BASE_BUNDLED_CATALOG_PATH", bundled_path)
    monkeypatch.setattr(trade2, "ITEM_BASE_ICON_DIR", storage_icon_dir)
    monkeypatch.setattr(trade2, "ITEM_BASE_BUNDLED_ICON_DIR", bundled_icon_dir)
    monkeypatch.setattr(trade2, "ITEM_BASES_CACHE", {"created_ts": 0.0, "data": None, "errors": []})

    result = asyncio.run(trade2.get_item_base_catalog())

    assert result["source"] == "bundled:item_base_catalog_seed"
    assert result["total"] == 1
    assert result["bases"][0]["type_ru"] == "Амулет с янтарём"
    assert result["bases"][0]["image"] == "/static/item-base-icons/amber-amulet.png"


def test_item_base_catalog_uses_bundled_seed_without_runtime_poe2db_merge(tmp_path, monkeypatch):
    async def fake_fetch(_locale="en"):
        raise RuntimeError("trade2 item catalog rate limited")

    async def fake_poe2db_catalog():
        return [
            {
                "id": "base:amber-amulet",
                "type": "Амулет с янтарём",
                "type_ru": "Амулет с янтарём",
                "query_type": "Амулет с янтарём",
                "category": "Amulets",
                "category_label": "Амулеты",
                "category_label_ru": "Амулеты",
                "group_label_ru": "Бижутерия",
                "icon_key": "amulet",
                "image": "https://cdn.poe2db.tw/image/amber.webp",
            },
            {
                "id": "base:грубый-кастет",
                "type": "Грубый кастет",
                "type_ru": "Грубый кастет",
                "query_type": "Грубый кастет",
                "category": "Claws",
                "category_label": "Когти",
                "category_label_ru": "Когти",
                "icon_key": "base",
                "image": "https://cdn.poe2db.tw/image/claw.webp",
            },
        ]

    bundled_path = tmp_path / "item_base_catalog_seed.json"
    bundled_path.write_text(
        json.dumps(
            {
                "schema_version": trade2.ITEM_BASE_CATALOG_SCHEMA_VERSION,
                "created_ts": 456.0,
                "source": "trade2/data/items",
                "total": 1,
                "bases": [
                    {
                        "id": "base:amber-amulet",
                        "type": "Amber Amulet",
                        "type_ru": "Амулет с янтарём",
                        "query_type": "Амулет с янтарём",
                        "category": "accessory",
                        "category_label": "Accessories",
                        "category_label_ru": "Бижутерия",
                        "icon_key": "amulet",
                        "image": "/icons/item-bases/generated/amulet.svg",
                    },
                    {
                        "id": "base:ruby",
                        "type": "Ruby",
                        "type_ru": "Рубин",
                        "query_type": "Рубин",
                        "category": "jewel",
                        "category_label": "Jewels",
                        "category_label_ru": "Самоцветы",
                        "icon_key": "base",
                        "image": "/icons/item-bases/generated/base.svg",
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(trade2, "_fetch_item_base_catalog_payload", fake_fetch)
    monkeypatch.setattr(trade2, "_fetch_poe2db_item_base_catalog", fake_poe2db_catalog)
    monkeypatch.setattr(trade2, "ITEM_BASE_CATALOG_PATH", tmp_path / "missing_runtime_catalog.json")
    monkeypatch.setattr(trade2, "ITEM_BASE_BUNDLED_CATALOG_PATH", bundled_path)
    monkeypatch.setattr(trade2, "ITEM_BASE_ICON_DIR", tmp_path / "storage-icons")
    monkeypatch.setattr(trade2, "ITEM_BASE_BUNDLED_ICON_DIR", tmp_path / "bundled-icons")
    monkeypatch.setattr(trade2, "ITEM_BASES_CACHE", {"created_ts": 0.0, "data": None, "errors": []})

    result = asyncio.run(trade2.get_item_base_catalog())

    assert result["source"] == "bundled:item_base_catalog_seed"
    assert result["total"] == 1
    assert result["bases"][0]["type_ru"] == "Амулет с янтарём"
    assert result["bases"][0]["image"] == "/icons/item-bases/generated/amulet.svg"


def test_item_base_catalog_uses_poe2db_when_trade2_is_limited(tmp_path, monkeypatch):
    async def fake_fetch(_locale="en"):
        raise RuntimeError("trade2 item catalog rate limited")

    async def fake_poe2db_catalog():
        return [
            {
                "id": "base:грубый-кастет",
                "type": "Грубый кастет",
                "type_ru": "Грубый кастет",
                "query_type": "Грубый кастет",
                "category": "Claws",
                "category_label": "Когти",
                "category_label_ru": "Когти",
                "icon_key": "claws",
                "image": "https://cdn.poe2db.tw/image/Art/2DItems/Weapons/Claws/Claw01.webp",
            }
        ]

    monkeypatch.setattr(trade2, "_fetch_item_base_catalog_payload", fake_fetch)
    monkeypatch.setattr(trade2, "_fetch_poe2db_item_base_catalog", fake_poe2db_catalog)
    monkeypatch.setattr(trade2, "ITEM_BASE_CATALOG_PATH", tmp_path / "item_base_catalog.json")
    monkeypatch.setattr(trade2, "ITEM_BASE_BUNDLED_CATALOG_PATH", tmp_path / "missing_seed.json")
    monkeypatch.setattr(trade2, "ITEM_BASE_ICON_DIR", tmp_path / "storage-icons")
    monkeypatch.setattr(trade2, "ITEM_BASE_BUNDLED_ICON_DIR", tmp_path / "bundled-icons")
    monkeypatch.setattr(trade2, "ITEM_BASES_CACHE", {"created_ts": 0.0, "data": None, "errors": []})

    result = asyncio.run(trade2.get_item_base_catalog())

    assert result["source"] == "poe2db/ru/Items"
    assert result["total"] == 1
    assert result["bases"][0]["type_ru"] == "Грубый кастет"
    assert result["bases"][0]["category_label_ru"] == "Когти"


def test_poe2db_catalog_enriches_official_bases_without_appending_unmatched():
    trade_bases = [
        {
            "id": "base:amber-amulet",
            "type": "Amber Amulet",
            "type_ru": "Амулет с янтарём",
            "query_type": "Амулет с янтарём",
            "category": "accessory",
            "category_label": "Accessories",
            "category_label_ru": "Бижутерия",
            "icon_key": "amulet",
            "image": "/icons/item-bases/generated/amulet.svg",
        }
    ]
    poe2db_bases = [
        {
            "id": "base:amber-amulet",
            "type": "Амулет с янтарём",
            "type_ru": "Амулет с янтарём",
            "query_type": "Амулет с янтарём",
            "category": "Amulets",
            "category_label_ru": "Амулеты",
            "group_label_ru": "Бижутерия",
            "poe2db_slug": "Amber_Amulet",
            "image": "https://cdn.poe2db.tw/image/amber.webp",
        },
        {
            "id": "base:грубый-кастет",
            "type": "Грубый кастет",
            "type_ru": "Грубый кастет",
            "query_type": "Грубый кастет",
            "category": "Claws",
            "image": "https://cdn.poe2db.tw/image/claw.webp",
        },
    ]

    bases = trade2._merge_poe2db_item_base_catalog(trade_bases, poe2db_bases)

    assert len(bases) == 1
    assert bases[0]["id"] == "base:amber-amulet"
    assert bases[0]["image"] == "https://cdn.poe2db.tw/image/amber.webp"
    assert bases[0]["poe2db_slug"] == "Amber_Amulet"


def test_item_base_market_query_uses_normal_rarity_and_priced_buyout():
    query = trade2._item_base_market_query("Вощеная куртка", "any", min_ilvl=82)

    assert query["type"] == "Вощеная куртка"
    assert query["stats"][0]["filters"] == []
    assert query["filters"]["trade_filters"]["filters"]["sale_type"]["option"] == "priced"
    assert query["filters"]["type_filters"]["filters"]["rarity"]["option"] == "normal"
    assert query["filters"]["type_filters"]["filters"]["ilvl"] == {"min": 82}


def test_item_base_market_overview_query_does_not_pin_single_base():
    query = trade2._item_base_market_overview_query("online", min_ilvl=70)

    assert "type" not in query
    assert query["status"]["option"] == "online"
    assert query["stats"][0]["filters"] == []
    assert query["filters"]["trade_filters"]["filters"]["sale_type"]["option"] == "priced"
    assert query["filters"]["type_filters"]["filters"]["rarity"]["option"] == "normal"
    assert query["filters"]["type_filters"]["filters"]["ilvl"] == {"min": 70}


def test_clean_item_base_lot_requires_normal_item_without_affixes():
    clean = {
        "rarity": "Normal",
        "implicit_mods": ["10% increased Charm Effect Duration"],
        "explicit_mods": [],
        "rune_mods": [],
        "desecrated_mods": [],
        "stat_mods": [{"type": "implicit", "id": "implicit.stat_1"}],
    }
    rare = {**clean, "rarity": "Rare"}
    explicit = {**clean, "explicit_mods": ["+10 to maximum Life"]}
    fractured = {**clean, "stat_mods": [{"type": "fractured", "id": "explicit.stat_1"}]}

    assert trade2._is_clean_item_base_lot(clean) is True
    assert trade2._is_clean_item_base_lot(rare) is False
    assert trade2._is_clean_item_base_lot(explicit) is False
    assert trade2._is_clean_item_base_lot(fractured) is False


def test_fresh_clean_item_base_lots_exclude_stale_and_mark_high_demand(monkeypatch):
    now = datetime(2026, 5, 25, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(trade2.time, "time", lambda: now.timestamp())

    def clean_lot(lot_id: str, seconds_old: int) -> dict[str, object]:
        return {
            "id": lot_id,
            "indexed": (now - timedelta(seconds=seconds_old)).isoformat().replace("+00:00", "Z"),
            "listed_age_seconds": seconds_old,
            "rarity": "Normal",
            "corrupted": False,
            "explicit_mods": [],
            "rune_mods": [],
            "desecrated_mods": [],
            "stat_mods": [],
            "price_amount": 2.0,
            "price_currency": "exalted",
        }

    clean_lots, stale_count = trade2._fresh_clean_item_base_lots(
        [
            clean_lot("recent-1", 10 * 60),
            clean_lot("recent-2", 20 * 60),
            clean_lot("recent-3", 50 * 60),
            clean_lot("fresh", 2 * 86400),
            clean_lot("old", 30 * 86400),
        ],
        {"exalted": 1.0},
        "exalted",
    )
    stats = trade2._base_market_stats(clean_lots, raw_count=5, stale_count=stale_count)

    assert [lot["id"] for lot in clean_lots] == ["recent-1", "recent-2", "recent-3", "fresh"]
    assert clean_lots[0]["price_target"] == 2.0
    assert stale_count == 1
    assert stats["clean_count"] == 4
    assert stats["stale_count"] == 1
    assert stats["recent_listing_count"] == 3
    assert stats["high_demand"] is True


def test_base_market_stats_store_low_market_as_chart_price():
    lots = [
        {"price_target": 5.0, "price_amount": 1.0, "price_currency": "transmutation"},
        {"price_target": 10.0, "price_amount": 2.0, "price_currency": "transmutation"},
        {"price_target": 30.0, "price_amount": 1.0, "price_currency": "exalted"},
    ]

    stats = trade2._base_market_stats(lots, raw_count=5)

    assert stats["low"] == 5.0
    assert stats["best"] == 5.0
    assert stats["median"] == 5.0
    assert stats["market_median"] == 10.0
    assert stats["raw_count"] == 5
    assert stats["clean_count"] == 3
    assert stats["best_native"] == {"amount": 1.0, "currency": "transmutation", "price_target": 5.0}
    assert stats["optimal"] == 10.0
    assert stats["optimal_native"] == {"amount": 2.0, "currency": "transmutation", "price_target": 10.0}
    assert stats["price_currency_groups"][0]["currency"] == "transmutation"
    assert stats["price_currency_groups"][0]["count"] == 2
    assert stats["price_currency_groups"][0]["low_amount"] == 1.0


def test_currency_rates_by_id_convert_from_stored_exalted_snapshot():
    snapshot = {
        "target": "exalted",
        "rows": [
            {"id": "alch", "best": 1.2, "median": 1.5},
            {"id": "regal", "best": 0.13},
            {"id": "divine", "best": 170.0},
        ],
    }

    exalted_rates = trade2._currency_rates_by_id(snapshot, "exalted")
    divine_rates = trade2._currency_rates_by_id(snapshot, "divine")

    assert exalted_rates["alch"] == 1.2
    assert exalted_rates["regal"] == 0.13
    assert exalted_rates["exalted"] == 1.0
    assert divine_rates["alch"] == 1.2 / 170.0
    assert divine_rates["divine"] == 1.0


def test_apply_target_price_uses_currency_aliases():
    lot = {"price_amount": 1.0, "price_currency": "alchemy"}

    priced = trade2._apply_target_price(lot, {"alch": 1.2, "exalted": 1.0}, "exalted")

    assert priced["price_target"] == 1.2


def test_base_market_stats_keep_native_prices_without_target_conversion():
    lots = [
        {"price_amount": 1.0, "price_currency": "transmutation", "price_target": None},
        {"price_amount": 2.0, "price_currency": "transmutation", "price_target": None},
    ]

    stats = trade2._base_market_stats(lots, raw_count=2)

    assert stats["low"] is None
    assert stats["best_native"] == {"amount": 1.0, "currency": "transmutation", "price_target": None}
    assert stats["optimal_native"] is None
    assert stats["price_currency_groups"] == [
        {
            "currency": "transmutation",
            "count": 2,
            "low_amount": 1.0,
            "median_amount": 1.5,
            "low_target": None,
            "median_target": None,
        }
    ]


def test_base_market_row_uses_english_type_for_trade_query() -> None:
    row = trade2._base_market_row_from_base(
        {
            "type": "Elegant Plate",
            "type_ru": "Элегантный доспех",
            "query_type": "Элегантный доспех",
        }
    )

    assert row["query_type"] == "Elegant Plate"
    assert row["text_ru"] == "Элегантный доспех"


def test_item_base_market_scan_prioritizes_high_demand_rows(monkeypatch):
    monkeypatch.setattr(trade2, "ITEM_BASE_MARKET_SCAN_BATCH_SIZE", 3)
    trade2.ITEM_BASE_MARKET_SCAN_CURSORS.clear()
    bases = [
        {"id": f"base:test-{index}", "type": f"Test Base {index}", "type_ru": f"Тестовая основа {index}"}
        for index in range(6)
    ]
    previous_rows = [
        {
            "id": "base:test-4",
            "text": "Test Base 4",
            "text_ru": "Тестовая основа 4",
            "recent_listing_count": 5,
            "high_demand": True,
        }
    ]

    priority_bases = trade2._item_base_market_priority_bases(bases, previous_rows)
    selected, start, next_position, priority_count, normal_count = trade2._item_base_market_scan_batch(
        bases,
        ("PoE2 - Test", "exalted", "securable", None),
        priority_bases=priority_bases,
    )

    assert [base["type"] for base in selected] == ["Test Base 4", "Test Base 0", "Test Base 1"]
    assert start == 0
    assert next_position == 2
    assert priority_count == 1
    assert normal_count == 2


def test_item_base_market_text_filter_uses_exact_base_search(monkeypatch):
    trade2.ITEM_BASE_MARKET_CACHE.clear()
    trade2.ITEM_BASE_MARKET_JOBS.clear()
    calls = {"search": 0, "fetch": 0, "overview": 0}

    async def fake_catalog(q="", limit=500):
        assert q == "Жемчужное кольцо"
        return {
            "source": "fake",
            "total": 1,
            "matched_total": 1,
            "errors": [],
            "bases": [
                {
                    "id": "base:pearl-ring",
                    "type": "Pearl Ring",
                    "type_ru": "Жемчужное кольцо",
                    "query_type": "Жемчужное кольцо",
                    "category": "accessory",
                    "category_label": "Jewellery",
                    "category_label_ru": "Бижутерия",
                }
            ],
        }

    async def fake_rates(**kwargs):
        return {"rows": [{"id": "transmutation", "median": 0.005}]}

    async def fake_search(league, query, sort=None, api_base=None):
        calls["search"] += 1
        assert api_base == trade2.ITEM_BASE_MARKET_TRADE2_BASE
        assert query["type"] == "Pearl Ring"
        assert query["filters"]["trade_filters"]["filters"]["sale_type"]["option"] == "priced"
        return {"id": "exact-query", "total": 100, "result": ["lot1"]}

    async def fake_fetch_from_search(base, market_search, target, rates, min_ilvl=None, fetch_limit=None):
        calls["fetch"] += 1
        assert fetch_limit == trade2.ITEM_BASE_MARKET_DEFAULT_SAMPLE_LIMIT
        assert fetch_limit == 100
        row = trade2._base_market_row_from_base(base, min_ilvl=min_ilvl)
        stats = trade2._base_market_stats(
            [{"price_amount": 1.0, "price_currency": "transmutation", "price_target": 0.005}],
            raw_count=100,
        )
        return {**row, **stats, "query_id": "exact-query", "total": 100, "total_scope": "exact", "sample_lots": []}

    async def fake_overview(*args, **kwargs):
        calls["overview"] += 1
        return {"rows_by_key": {}}

    monkeypatch.setattr(trade2, "get_item_base_catalog", fake_catalog)
    monkeypatch.setattr(trade2, "get_category_rates", fake_rates)
    monkeypatch.setattr(trade2, "_post_search", fake_search)
    monkeypatch.setattr(trade2, "_fetch_item_base_market_row_from_search", fake_fetch_from_search)
    monkeypatch.setattr(trade2, "_fetch_item_base_market_overview", fake_overview)
    monkeypatch.setattr(trade2, "log_market_history", lambda *args, **kwargs: None)

    result = asyncio.run(
        trade2.get_item_base_market(
            league="PoE2 - Test",
            target="exalted",
            status="any",
            q="Жемчужное кольцо",
            limit=40,
            force_refresh=True,
        )
    )

    assert calls == {"search": 1, "fetch": 1, "overview": 0}
    assert result["source"] == "trade2/search+fetch:exact"
    assert result["rows"][0]["text_ru"] == "Жемчужное кольцо"
    assert result["rows"][0]["best_native"]["currency"] == "transmutation"
    assert result["rows"][0]["total_scope"] == "exact"


def test_item_base_market_background_job_collects_limited_exact_sample(monkeypatch):
    trade2.ITEM_BASE_MARKET_CACHE.clear()
    trade2.ITEM_BASE_MARKET_JOBS.clear()
    calls = {"exact": 0}

    async def fake_catalog(q="", limit=500):
        return {
            "source": "fake",
            "total": 1,
            "bases": [
                {
                    "id": "base:amber-amulet",
                    "type": "Amber Amulet",
                    "type_ru": "Амулет с янтарём",
                    "query_type": "Амулет с янтарём",
                    "category": "amulet",
                    "category_label": "Accessories",
                    "category_label_ru": "Бижутерия",
                }
            ],
        }

    async def fake_rates(**kwargs):
        return {"rows": [{"id": "regal", "median": 0.17}]}

    async def fake_search(league, query, sort=None, api_base=None):
        assert api_base == trade2.ITEM_BASE_MARKET_TRADE2_BASE
        return {"id": "exact-query", "total": 9484, "result": ["item1"]}

    async def fake_fetch_from_search(base, market_search, target, rates, min_ilvl=None, fetch_limit=None):
        calls["exact"] += 1
        assert fetch_limit == 100
        row = trade2._base_market_row_from_base(base, min_ilvl=min_ilvl)
        stats = trade2._base_market_stats(
            [{"price_amount": 1.0, "price_currency": "regal", "price_target": 0.17}],
            raw_count=100,
        )
        return {
            **row,
            **stats,
            "query_id": "exact-query",
            "total": 9484,
            "total_scope": "exact",
            "fetched_count": 100,
            "sample_lots": [],
        }

    monkeypatch.setattr(trade2, "get_item_base_catalog", fake_catalog)
    monkeypatch.setattr(trade2, "get_category_rates", fake_rates)
    monkeypatch.setattr(trade2, "_post_search", fake_search)
    monkeypatch.setattr(trade2, "_fetch_item_base_market_row_from_search", fake_fetch_from_search)
    monkeypatch.setattr(trade2, "log_market_history", lambda *args, **kwargs: None)

    job, coroutine = trade2.start_item_base_market_refresh_job(
        league="PoE2 - Test",
        target="exalted",
        status="any",
        q="Амулет с янтарём",
        limit=40,
        sample_limit=100,
    )
    trade2.ITEM_BASE_MARKET_CACHE[("PoE2 - Test", "exalted", "any", "", trade2.ITEM_BASE_MARKET_MAX_BASES, None)] = {
        "created_ts": 9999999999,
        "data": {"source": "trade2/search+fetch:overview", "rows": [{"id": "base:other", "text": "Other"}]},
    }
    pending = asyncio.run(
        trade2.get_item_base_market(
            league="PoE2 - Test",
            target="exalted",
            status="any",
            q="Амулет с янтарём",
            limit=40,
            force_refresh=False,
            sample_limit=100,
        )
    )
    result = asyncio.run(coroutine)
    cached = asyncio.run(
        trade2.get_item_base_market(
            league="PoE2 - Test",
            target="exalted",
            status="any",
            q="Амулет с янтарём",
            limit=40,
            force_refresh=False,
            sample_limit=100,
        )
    )

    assert pending["refresh_job"]["status"] == "queued"
    assert job["status"] == "done"
    assert calls == {"exact": 1}
    assert result["rows"][0]["total"] == 9484
    assert result["rows"][0]["fetched_count"] == 100
    assert cached["rows"][0]["total"] == 9484
    assert cached["cached"] is True


def test_item_base_market_blank_refresh_scans_catalog_in_rough_batches(monkeypatch):
    trade2.ITEM_BASE_MARKET_CACHE.clear()
    trade2.ITEM_BASE_MARKET_JOBS.clear()
    trade2.ITEM_BASE_MARKET_SCAN_CURSORS.clear()
    calls = {"search": 0, "fetch": 0}
    searched_types = []
    batch_size = trade2.ITEM_BASE_MARKET_SCAN_BATCH_SIZE
    base_count = batch_size + 5
    bases = [
        {
            "id": f"base:test-base-{index}",
            "type": f"Test Base {index}",
            "type_ru": f"Тестовая основа {index}",
            "query_type": f"Тестовая основа {index}",
        }
        for index in range(base_count)
    ]

    async def fake_catalog(q="", limit=500):
        assert q == ""
        return {
            "source": "stored:item_base_catalog",
            "total": base_count,
            "bases": bases,
            "errors": [],
        }

    async def fake_rates(**kwargs):
        return {"rows": [{"id": "regal", "median": 0.25}]}

    async def fake_search(league, query, sort=None, api_base=None):
        calls["search"] += 1
        assert api_base == trade2.ITEM_BASE_MARKET_TRADE2_BASE
        assert query["filters"]["trade_filters"]["filters"]["sale_type"]["option"] == "priced"
        searched_types.append(query["type"])
        return {"id": f"rough-query-{calls['search']}", "total": 5000, "result": [f"lot-{calls['search']}"]}

    async def fake_fetch_from_search(base, market_search, target, rates, min_ilvl=None, fetch_limit=None):
        calls["fetch"] += 1
        assert fetch_limit == trade2.ITEM_BASE_MARKET_ROUGH_SAMPLE_LIMIT
        row = trade2._base_market_row_from_base(base, min_ilvl=min_ilvl)
        clean_lots = []
        if row["text_ru"] in {"Тестовая основа 0", f"Тестовая основа {batch_size}"}:
            clean_lots = [
                {"price_amount": 1.0, "price_currency": "regal", "price_target": 0.25}
                for _ in range(trade2.ITEM_BASE_MARKET_MIN_GENERAL_LOTS)
            ]
        stats = trade2._base_market_stats(
            clean_lots,
            raw_count=trade2.ITEM_BASE_MARKET_ROUGH_SAMPLE_LIMIT,
        )
        return {
            **row,
            **stats,
            "query_id": market_search["id"],
            "total": 5000,
            "total_scope": "exact",
            "fetched_count": trade2.ITEM_BASE_MARKET_ROUGH_SAMPLE_LIMIT,
            "sample_lots": [],
        }

    monkeypatch.setattr(trade2, "get_item_base_catalog", fake_catalog)
    monkeypatch.setattr(trade2, "get_category_rates", fake_rates)
    monkeypatch.setattr(trade2, "_post_search", fake_search)
    monkeypatch.setattr(trade2, "_fetch_item_base_market_row_from_search", fake_fetch_from_search)
    monkeypatch.setattr(trade2, "log_market_history", lambda *args, **kwargs: None)
    monkeypatch.setattr(trade2, "DEFAULT_RATE_LIMIT_DELAY", 0)

    result = asyncio.run(
        trade2.get_item_base_market(
            league="PoE2 - Test",
            target="exalted",
            status="securable",
            q="",
            limit=1,
            force_refresh=True,
            sample_limit=100,
        )
    )

    assert calls == {"search": batch_size, "fetch": batch_size}
    assert searched_types[0] == "Test Base 0"
    assert searched_types[-1] == f"Test Base {batch_size - 1}"
    assert result["source"] == "trade2/search+fetch:rough"
    assert result["matched_total"] == 1
    assert result["catalog_total"] == base_count
    assert result["priced_total"] == 1
    assert len(result["rows"]) == 1
    assert result["refresh_job"]["processed_count"] == batch_size
    assert result["refresh_job"]["base_total"] == batch_size
    assert result["refresh_job"]["catalog_total"] == base_count
    assert result["refresh_job"]["fetched_count"] == batch_size * trade2.ITEM_BASE_MARKET_ROUGH_SAMPLE_LIMIT

    result = asyncio.run(
        trade2.get_item_base_market(
            league="PoE2 - Test",
            target="exalted",
            status="securable",
            q="",
            limit=80,
            force_refresh=True,
            sample_limit=100,
        )
    )

    assert searched_types[batch_size] == f"Test Base {batch_size}"
    assert result["matched_total"] == 2
    assert result["catalog_total"] == base_count
    assert result["priced_total"] == 2


def test_item_base_market_job_treats_generic_429_as_rate_limited(monkeypatch):
    trade2.ITEM_BASE_MARKET_CACHE.clear()
    trade2.ITEM_BASE_MARKET_JOBS.clear()

    async def fake_catalog(q="", limit=500):
        return {
            "source": "fake",
            "total": 1,
            "bases": [
                {
                    "id": "base:crossbow",
                    "type": "Crossbow",
                    "type_ru": "Арбалет",
                    "query_type": "Арбалет",
                }
            ],
        }

    async def fake_search(league, query, sort=None, api_base=None):
        assert api_base == trade2.ITEM_BASE_MARKET_TRADE2_BASE
        raise RuntimeError("Client error '429 Too Many Requests'")

    monkeypatch.setattr(trade2, "get_item_base_catalog", fake_catalog)
    monkeypatch.setattr(trade2, "_post_search", fake_search)
    monkeypatch.setattr(
        trade2,
        "_currency_rates_for_target",
        lambda *args, **kwargs: asyncio.sleep(0, result=({"rows": []}, {"exalted": 1.0})),
    )

    job, coroutine = trade2.start_item_base_market_refresh_job(
        league="PoE2 - Test",
        target="exalted",
        status="securable",
        q="Crossbow",
        limit=40,
        sample_limit=100,
    )
    result = asyncio.run(coroutine)

    assert job["status"] == "rate_limited"
    assert job["retry_after"] == 60
    assert result["rows"] == []
    assert result["matched_total"] == 0
    assert not trade2.ITEM_BASE_MARKET_CACHE


def test_item_base_market_refresh_restarts_stale_running_job():
    trade2.ITEM_BASE_MARKET_JOBS.clear()
    now = time.time()
    key = trade2._item_base_market_job_key("PoE2 - Test", "exalted", "securable", "", 82, 100)
    stale_job = {
        "id": "old",
        "status": "running",
        "created_ts": now - 300,
        "updated_ts": now - trade2.ITEM_BASE_MARKET_STALE_JOB_SECONDS - 1,
        "sample_limit": 100,
    }
    trade2.ITEM_BASE_MARKET_JOBS[key] = stale_job

    job, coroutine = trade2.start_item_base_market_refresh_job(
        league="PoE2 - Test",
        target="exalted",
        status="securable",
        q="",
        min_ilvl=82,
        sample_limit=100,
    )

    assert job is not stale_job
    assert job["status"] == "queued"
    assert coroutine is not None
    coroutine.close()


def test_item_base_market_fetch_rate_limit_preserves_search_total(monkeypatch):
    trade2.ITEM_BASE_MARKET_CACHE.clear()
    trade2.ITEM_BASE_MARKET_JOBS.clear()

    async def fake_catalog(q="", limit=500):
        return {
            "source": "fake",
            "total": 1,
            "bases": [
                {
                    "id": "base:amber-amulet",
                    "type": "Amber Amulet",
                    "type_ru": "Амулет с янтарём",
                    "query_type": "Амулет с янтарём",
                }
            ],
        }

    async def fake_search(league, query, sort=None, api_base=None):
        assert api_base == trade2.ITEM_BASE_MARKET_TRADE2_BASE
        return {"id": "search-id", "total": 3423, "result": ["a", "b"]}

    async def fake_fetch_from_search(base, market_search, target, rates, min_ilvl=None, fetch_limit=None):
        row = trade2._base_market_row_from_base(base, min_ilvl=min_ilvl)
        return {
            **row,
            **trade2._base_market_stats([], 0),
            "query_id": market_search["id"],
            "total": market_search["total"],
            "total_scope": "exact",
            "fetched_count": 0,
            "sample_lots": [],
            "error": "trade2 fetch rate limited; retry after 299s",
        }

    monkeypatch.setattr(trade2, "get_item_base_catalog", fake_catalog)
    monkeypatch.setattr(trade2, "_post_search", fake_search)
    monkeypatch.setattr(trade2, "_fetch_item_base_market_row_from_search", fake_fetch_from_search)
    monkeypatch.setattr(
        trade2,
        "_currency_rates_for_target",
        lambda *args, **kwargs: asyncio.sleep(0, result=({"rows": []}, {"exalted": 1.0})),
    )

    job, coroutine = trade2.start_item_base_market_refresh_job(
        league="PoE2 - Test",
        target="exalted",
        status="securable",
        q="Амулет с янтарём",
        limit=40,
        sample_limit=100,
    )
    result = asyncio.run(coroutine)

    assert job["status"] == "rate_limited"
    assert job["retry_after"] == 299
    assert job["total"] == 3423
    assert result["rows"] == []
    assert result["matched_total"] == 0
    assert not trade2.ITEM_BASE_MARKET_CACHE


def test_item_base_market_blank_query_skips_exact_snapshot(monkeypatch):
    trade2.ITEM_BASE_MARKET_CACHE.clear()
    trade2.ITEM_BASE_MARKET_JOBS.clear()

    def fake_read_latest_rates(**kwargs):
        return {
            "created_ts": 10.0,
            "source": "trade2/search+fetch:exact",
            "rows": [{"id": "base:crossbow", "text": "Crossbow", "text_ru": "Арбалет", "low": 1.0}],
        }

    async def fake_catalog(q="", limit=1000):
        return {
            "source": "fake",
            "total": 1,
            "bases": [
                {
                    "id": "base:crossbow",
                    "type": "Crossbow",
                    "type_ru": "Арбалет",
                    "query_type": "Арбалет",
                }
            ],
            "errors": [],
        }

    monkeypatch.setattr(trade2, "read_latest_rates", fake_read_latest_rates)
    monkeypatch.setattr(trade2, "get_item_base_catalog", fake_catalog)

    result = asyncio.run(
        trade2.get_item_base_market(
            league="PoE2 - Test",
            target="exalted",
            status="securable",
            q="",
            limit=40,
            force_refresh=False,
        )
    )

    assert result["stored"] is True
    assert result["source"] == "item-base-catalog"
    assert result["rows"] == []
    assert result["matched_total"] == 0
    assert result["catalog_total"] == 1


def test_item_base_market_zero_limit_returns_all_visible_rows(monkeypatch):
    trade2.ITEM_BASE_MARKET_CACHE.clear()
    trade2.ITEM_BASE_MARKET_JOBS.clear()
    bases = [
        {
            "id": f"base:test-{index}",
            "type": f"Test Base {index}",
            "type_ru": f"Тестовая основа {index}",
            "query_type": f"Тестовая основа {index}",
        }
        for index in range(3)
    ]

    async def fake_catalog(q="", limit=1000):
        return {
            "source": "fake",
            "total": len(bases),
            "bases": bases,
            "errors": [],
        }

    def native_group(price: float, count: int = trade2.ITEM_BASE_MARKET_MIN_GENERAL_LOTS):
        return [{"currency": "exalted", "count": count, "low_amount": price, "median_amount": price, "low_target": price, "median_target": price}]

    def fake_read_latest_rates(**kwargs):
        return {
            "created_ts": 10.0,
            "source": "trade2/search+fetch:rough",
            "rows": [
                {
                    "id": f"base:test-{index}",
                        "text_ru": f"Тестовая основа {index}",
                        "low": float(index + 1),
                        "offers": trade2.ITEM_BASE_MARKET_MIN_GENERAL_LOTS,
                        "price_currency_groups": native_group(float(index + 1)),
                    }
                    for index in range(3)
                ],
            }

    monkeypatch.setattr(trade2, "read_latest_rates", fake_read_latest_rates)
    monkeypatch.setattr(trade2, "get_item_base_catalog", fake_catalog)

    result = asyncio.run(
        trade2.get_item_base_market(
            league="PoE2 - Test",
            target="exalted",
            status="securable",
            q="",
            limit=0,
            force_refresh=False,
        )
    )

    assert result["matched_total"] == 3
    assert [row["id"] for row in result["rows"]] == ["base:test-0", "base:test-1", "base:test-2"]


def test_item_base_market_price_filter_uses_target_prices(monkeypatch):
    trade2.ITEM_BASE_MARKET_CACHE.clear()
    trade2.ITEM_BASE_MARKET_JOBS.clear()
    cache_key = ("PoE2 - Test", "exalted", "any", "", trade2.ITEM_BASE_MARKET_MAX_BASES, None)
    native_group = [{"currency": "exalted", "count": trade2.ITEM_BASE_MARKET_MIN_GENERAL_LOTS, "low_amount": 4.0, "median_amount": 4.0, "low_target": 4.0, "median_target": 4.0}]
    trade2.ITEM_BASE_MARKET_CACHE[cache_key] = {
        "created_ts": 9999999999,
        "data": {
            "source": "trade2/search+fetch:catalog-scan",
            "rows": [
                {
                    "id": "base:cheap",
                    "text_ru": "Дешевая основа",
                    "low": 4.0,
                    "offers": trade2.ITEM_BASE_MARKET_MIN_GENERAL_LOTS,
                    "price_currency_groups": native_group,
                },
                {
                    "id": "base:expensive",
                    "text_ru": "Дорогая основа",
                    "low": 12.0,
                    "offers": trade2.ITEM_BASE_MARKET_MIN_GENERAL_LOTS,
                    "price_currency_groups": [
                        {
                            "currency": "exalted",
                            "count": trade2.ITEM_BASE_MARKET_MIN_GENERAL_LOTS,
                            "low_amount": 12.0,
                            "median_amount": 12.0,
                            "low_target": 12.0,
                            "median_target": 12.0,
                        }
                    ],
                },
                {"id": "base:empty", "text_ru": "Пустая основа"},
            ],
        },
    }
    monkeypatch.setattr(trade2, "read_latest_rates", lambda **kwargs: None)

    result = asyncio.run(
        trade2.get_item_base_market(
            league="PoE2 - Test",
            target="exalted",
            status="any",
            q="",
            limit=0,
            force_refresh=False,
            price_trigger="below",
            price_value=10,
            price_currency="exalted",
        )
    )

    assert result["matched_total"] == 1
    assert result["priced_total"] == 1
    assert [row["id"] for row in result["rows"]] == ["base:cheap"]
    assert result["price_filter"]["target_value"] == 10


def test_item_base_market_price_filter_converts_threshold_currency(monkeypatch):
    trade2.ITEM_BASE_MARKET_CACHE.clear()
    trade2.ITEM_BASE_MARKET_JOBS.clear()
    cache_key = ("PoE2 - Test", "exalted", "any", "", trade2.ITEM_BASE_MARKET_MAX_BASES, None)
    trade2.ITEM_BASE_MARKET_CACHE[cache_key] = {
        "created_ts": 9999999999,
        "data": {
            "source": "trade2/search+fetch:catalog-scan",
            "rows": [
                {
                    "id": "base:below",
                    "text_ru": "Ниже порога",
                    "low": 9.0,
                    "offers": trade2.ITEM_BASE_MARKET_MIN_GENERAL_LOTS,
                    "price_currency_groups": [
                        {
                            "currency": "exalted",
                            "count": trade2.ITEM_BASE_MARKET_MIN_GENERAL_LOTS,
                            "low_amount": 9.0,
                            "median_amount": 9.0,
                            "low_target": 9.0,
                            "median_target": 9.0,
                        }
                    ],
                },
                {
                    "id": "base:above",
                    "text_ru": "Выше порога",
                    "low": 15.0,
                    "offers": trade2.ITEM_BASE_MARKET_MIN_GENERAL_LOTS,
                    "price_currency_groups": [
                        {
                            "currency": "exalted",
                            "count": trade2.ITEM_BASE_MARKET_MIN_GENERAL_LOTS,
                            "low_amount": 15.0,
                            "median_amount": 15.0,
                            "low_target": 15.0,
                            "median_target": 15.0,
                        }
                    ],
                },
            ],
        },
    }

    async def fake_currency_rates_for_target(*args, **kwargs):
        return {"rows": []}, {"exalted": 1.0, "divine": 10.0}

    monkeypatch.setattr(trade2, "_currency_rates_for_target", fake_currency_rates_for_target)

    result = asyncio.run(
        trade2.get_item_base_market(
            league="PoE2 - Test",
            target="exalted",
            status="any",
            q="",
            limit=0,
            force_refresh=False,
            price_trigger="above",
            price_value=1,
            price_currency="divine",
        )
    )

    assert result["matched_total"] == 1
    assert [row["id"] for row in result["rows"]] == ["base:above"]
    assert result["price_filter"]["target_value"] == 10


def test_item_base_market_hides_empty_catalog_rows(monkeypatch):
    trade2.ITEM_BASE_MARKET_CACHE.clear()
    trade2.ITEM_BASE_MARKET_JOBS.clear()

    async def fake_catalog(q="", limit=1000):
        return {
            "source": "fake",
            "total": 2,
            "bases": [
                {
                    "id": "base:future-sword",
                    "type": "Future Sword",
                    "type_ru": "Будущий меч",
                    "query_type": "Будущий меч",
                },
                {
                    "id": "base:future-axe",
                    "type": "Future Axe",
                    "type_ru": "Будущий топор",
                    "query_type": "Будущий топор",
                },
            ],
            "errors": [],
        }

    monkeypatch.setattr(trade2, "read_latest_rates", lambda **kwargs: None)
    monkeypatch.setattr(trade2, "get_item_base_catalog", fake_catalog)

    result = asyncio.run(
        trade2.get_item_base_market(
            league="PoE2 - Test",
            target="exalted",
            status="securable",
            q="",
            limit=0,
            force_refresh=False,
        )
    )

    assert result["catalog_total"] == 2
    assert result["matched_total"] == 0
    assert result["rows"] == []


def test_item_base_market_hides_price_only_rows_without_lots(monkeypatch):
    trade2.ITEM_BASE_MARKET_CACHE.clear()
    cache_key = ("PoE2 - Test", "exalted", "any", "", trade2.ITEM_BASE_MARKET_MAX_BASES, None)
    trade2.ITEM_BASE_MARKET_CACHE[cache_key] = {
        "created_ts": 9999999999,
        "data": {
            "source": "trade2/search+fetch:catalog-scan",
            "rows": [
                {"id": "base:ghost", "text_ru": "Пустая цена", "low": 12.0, "offers": 0},
                {
                    "id": "base:thin",
                    "text_ru": "Тонкая цена",
                    "low": 8.0,
                    "offers": trade2.ITEM_BASE_MARKET_MIN_GENERAL_LOTS - 1,
                },
                {
                    "id": "base:confirmed",
                    "text_ru": "Подтвержденная цена",
                    "low": 4.0,
                    "offers": trade2.ITEM_BASE_MARKET_MIN_GENERAL_LOTS,
                    "price_currency_groups": [
                        {
                            "currency": "exalted",
                            "count": trade2.ITEM_BASE_MARKET_MIN_GENERAL_LOTS,
                            "low_amount": 4.0,
                            "median_amount": 4.0,
                            "low_target": 4.0,
                            "median_target": 4.0,
                        }
                    ],
                },
            ],
        },
    }
    monkeypatch.setattr(trade2, "read_latest_rates", lambda **kwargs: None)

    result = asyncio.run(
        trade2.get_item_base_market(
            league="PoE2 - Test",
            target="exalted",
            status="any",
            q="",
            limit=0,
            force_refresh=False,
        )
    )

    assert result["matched_total"] == 1
    assert result["priced_total"] == 1
    assert [row["id"] for row in result["rows"]] == ["base:confirmed"]


def test_item_base_market_exact_refresh_hides_zero_result_base(monkeypatch):
    trade2.ITEM_BASE_MARKET_CACHE.clear()
    trade2.ITEM_BASE_MARKET_JOBS.clear()

    async def fake_catalog(q="", limit=500):
        return {
            "source": "fake",
            "total": 1,
            "bases": [
                {
                    "id": "base:future-sword",
                    "type": "Future Sword",
                    "type_ru": "Будущий меч",
                    "query_type": "Будущий меч",
                }
            ],
            "errors": [],
        }

    async def fake_search(league, query, sort=None, api_base=None):
        assert api_base == trade2.ITEM_BASE_MARKET_TRADE2_BASE
        return {"id": "search-id", "total": 0, "result": []}

    async def fake_fetch_from_search(base, market_search, target, rates, min_ilvl=None, fetch_limit=None):
        row = trade2._base_market_row_from_base(base, min_ilvl=min_ilvl)
        return {
            **row,
            **trade2._base_market_stats([], 0),
            "query_id": market_search["id"],
            "total": 0,
            "total_scope": "exact",
            "fetched_count": 0,
            "sample_lots": [],
        }

    monkeypatch.setattr(trade2, "get_item_base_catalog", fake_catalog)
    monkeypatch.setattr(trade2, "_post_search", fake_search)
    monkeypatch.setattr(trade2, "_fetch_item_base_market_row_from_search", fake_fetch_from_search)
    monkeypatch.setattr(
        trade2,
        "_currency_rates_for_target",
        lambda *args, **kwargs: asyncio.sleep(0, result=({"rows": []}, {"exalted": 1.0})),
    )
    monkeypatch.setattr(trade2, "DEFAULT_RATE_LIMIT_DELAY", 0)

    result = asyncio.run(
        trade2.get_item_base_market(
            league="PoE2 - Test",
            target="exalted",
            status="securable",
            q="Будущий меч",
            limit=0,
            force_refresh=True,
        )
    )

    assert result["catalog_total"] == 1
    assert result["matched_total"] == 0
    assert result["rows"] == []


def test_item_base_market_blank_query_skips_stored_overview_snapshot(monkeypatch):
    trade2.ITEM_BASE_MARKET_CACHE.clear()
    trade2.ITEM_BASE_MARKET_JOBS.clear()

    def fake_read_latest_rates(**kwargs):
        return {
            "created_ts": 10.0,
            "source": "trade2/search+fetch:overview",
            "rows": [{"id": "base:crossbow", "text": "Crossbow", "text_ru": "Арбалет", "low": 1.0}],
        }

    async def fake_catalog(q="", limit=1000):
        return {
            "source": "fake",
            "total": 1,
            "bases": [
                {
                    "id": "base:crossbow",
                    "type": "Crossbow",
                    "type_ru": "Арбалет",
                    "query_type": "Арбалет",
                }
            ],
            "errors": [],
        }

    monkeypatch.setattr(trade2, "read_latest_rates", fake_read_latest_rates)
    monkeypatch.setattr(trade2, "get_item_base_catalog", fake_catalog)

    result = asyncio.run(
        trade2.get_item_base_market(
            league="PoE2 - Test",
            target="exalted",
            status="securable",
            q="",
            limit=40,
            force_refresh=False,
        )
    )

    assert result["stored"] is True
    assert result["source"] == "item-base-catalog"
    assert result["rows"] == []
    assert result["matched_total"] == 0


def test_item_base_market_text_filter_can_use_cached_overview(monkeypatch):
    trade2.ITEM_BASE_MARKET_CACHE.clear()
    cache_key = ("PoE2 - Test", "exalted", "any", "", trade2.ITEM_BASE_MARKET_MAX_BASES, None)
    trade2.ITEM_BASE_MARKET_CACHE[cache_key] = {
        "created_ts": 9999999999,
        "data": {
            "rows": [
                {
                    "id": "base:pearl-ring",
                    "text": "Pearl Ring",
                    "text_ru": "Жемчужное кольцо",
                    "low": 0.01,
                    "offers": 1,
                    "price_currency_groups": [{"currency": "exalted", "count": 1, "low_amount": 0.01, "median_amount": 0.01}],
                },
                {
                    "id": "base:robe",
                    "text": "Silk Robe",
                    "text_ru": "Шелковая роба",
                    "low": 2.0,
                    "offers": 1,
                    "price_currency_groups": [{"currency": "exalted", "count": 1, "low_amount": 2.0, "median_amount": 2.0}],
                },
            ]
        },
    }
    monkeypatch.setattr(trade2, "read_latest_rates", lambda **kwargs: None)

    result = asyncio.run(
        trade2.get_item_base_market(
            league="PoE2 - Test",
            target="exalted",
            status="any",
            q="Жемчужное",
            limit=40,
            force_refresh=False,
        )
    )

    assert result["cached"] is True
    assert [row["id"] for row in result["rows"]] == ["base:pearl-ring"]


def test_item_base_market_min_ilvl_does_not_reuse_unfiltered_market(monkeypatch):
    trade2.ITEM_BASE_MARKET_CACHE.clear()
    trade2.ITEM_BASE_MARKET_JOBS.clear()
    default_cache_key = ("PoE2 - Test", "exalted", "any", "", trade2.ITEM_BASE_MARKET_MAX_BASES, None)
    trade2.ITEM_BASE_MARKET_CACHE[default_cache_key] = {
        "created_ts": 9999999999,
        "data": {
            "source": "trade2/search+fetch:catalog-scan",
            "rows": [{"id": "base:amber-amulet", "text_ru": "Амулет с янтарём", "low": 1.0, "min_ilvl": None}],
        },
    }
    history_calls = {"count": 0}

    def fake_read_latest_rates(**kwargs):
        history_calls["count"] += 1
        return {
            "created_ts": 10.0,
            "rows": [{"id": "base:amber-amulet", "text_ru": "Амулет с янтарём", "low": 1.0}],
        }

    async def fake_catalog(q="", limit=1000):
        return {
            "source": "fake",
            "total": 1,
            "bases": [
                {
                    "id": "base:amber-amulet",
                    "type": "Amber Amulet",
                    "type_ru": "Амулет с янтарём",
                    "query_type": "Амулет с янтарём",
                }
            ],
            "errors": [],
        }

    monkeypatch.setattr(trade2, "read_latest_rates", fake_read_latest_rates)
    monkeypatch.setattr(trade2, "get_item_base_catalog", fake_catalog)

    result = asyncio.run(
        trade2.get_item_base_market(
            league="PoE2 - Test",
            target="exalted",
            status="any",
            q="",
            limit=40,
            min_ilvl=82,
            force_refresh=False,
        )
    )

    assert history_calls == {"count": 0}
    assert result["source"] == "item-base-catalog"
    assert result["rows"] == []
    assert result["matched_total"] == 0
    assert result["catalog_total"] == 1


def test_item_base_market_ignores_error_only_cache_and_hides_stored_price_only_rows(monkeypatch):
    trade2.ITEM_BASE_MARKET_CACHE.clear()
    cache_key = ("PoE2 - Test", "exalted", "any", "", trade2.ITEM_BASE_MARKET_MAX_BASES, None)
    trade2.ITEM_BASE_MARKET_CACHE[cache_key] = {
        "created_ts": 9999999999,
        "data": {
            "rows": [
                {"id": "base:pearl-ring", "text": "Pearl Ring", "error": "trade2 search rate limited; retry after 600s"}
            ],
            "errors": [{"source": "trade2/search", "error": "rate limited"}],
        },
    }

    def fake_read_latest_rates(**kwargs):
        return {
            "created_ts": 10.0,
            "rows": [{"id": "base:pearl-ring", "text": "Pearl Ring", "text_ru": "Жемчужное кольцо", "low": 0.01, "offers": 1}],
        }

    async def fake_catalog(q="", limit=1000):
        return {"bases": []}

    monkeypatch.setattr(trade2, "read_latest_rates", fake_read_latest_rates)
    monkeypatch.setattr(trade2, "get_item_base_catalog", fake_catalog)

    result = asyncio.run(
        trade2.get_item_base_market(
            league="PoE2 - Test",
            target="exalted",
            status="any",
            q="Pearl",
            limit=40,
            force_refresh=False,
        )
    )

    assert result["stored"] is True
    assert result["rows"] == []
    assert result["matched_total"] == 0


def test_item_base_market_enriches_but_hides_stored_price_only_rows(monkeypatch):
    trade2.ITEM_BASE_MARKET_CACHE.clear()

    def fake_read_latest_rates(**kwargs):
        return {
            "created_ts": 10.0,
            "rows": [{"id": "base:pearl-ring", "median": 0.01, "best": 0.01, "offers": 1}],
        }

    async def fake_catalog(q="", limit=1000):
        return {
            "bases": [
                {
                    "id": "base:pearl-ring",
                    "type": "Pearl Ring",
                    "type_ru": "Жемчужное кольцо",
                    "query_type": "Жемчужное кольцо",
                    "category": "accessory",
                    "category_label": "Accessories",
                    "category_label_ru": "Бижутерия",
                }
            ]
        }

    monkeypatch.setattr(trade2, "read_latest_rates", fake_read_latest_rates)
    monkeypatch.setattr(trade2, "get_item_base_catalog", fake_catalog)

    result = asyncio.run(
        trade2.get_item_base_market(
            league="PoE2 - Test",
            target="exalted",
            status="any",
            q="Жемчужное",
            limit=40,
            force_refresh=False,
        )
    )

    assert result["stored"] is True
    assert result["rows"] == []
    assert result["matched_total"] == 0


def test_filter_comparable_lots_uses_text_affixes_for_pasted_items():
    parsed = {
        "display_name": "Vengeance Veil Waxed Jacket",
        "name": "Vengeance Veil",
        "type_line": "Waxed Jacket",
        "rarity": "Rare",
        "item_level": 72,
        "mods": ["+55 to maximum Life", "+20% to Fire Resistance"],
    }
    target = trade2._parsed_item_lot(parsed)
    lots = [
        {
            "seller": "Other#1",
            "base_type": "Waxed Jacket",
            "rarity": "Rare",
            "item_level": 74,
            "explicit_mods": ["+60 to maximum Life", "+22% to Fire Resistance"],
            "stat_mods": [
                {"id": "explicit.stat_life", "type": "explicit"},
                {"id": "explicit.stat_fire_res", "type": "explicit"},
            ],
            "price_target": 10.0,
        },
        {
            "seller": "Other#2",
            "base_type": "Waxed Jacket",
            "rarity": "Rare",
            "item_level": 74,
            "explicit_mods": ["+20 to Dexterity", "+22% to Fire Resistance"],
            "stat_mods": [
                {"id": "explicit.stat_dex", "type": "explicit"},
                {"id": "explicit.stat_fire_res", "type": "explicit"},
            ],
            "price_target": 15.0,
        },
    ]

    strict = trade2._filter_comparable_lots(target, lots, looseness=0)
    relaxed = trade2._filter_comparable_lots(target, lots, looseness=1)

    assert [lot["price_target"] for lot in strict] == [10.0]
    assert [lot["price_target"] for lot in relaxed] == [10.0, 15.0]


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

    assert [item["severity"] for item in advice] == ["signal", "watch"]
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

    full_path = next(item for item in advice if item["result"] == "diluted-liquid-greed")
    assert full_path["source"] == "diluted-liquid-ire"
    assert full_path["path_steps"] == 2
    assert full_path["input_count"] == 9
    assert full_path["profit"] == 11
    assert full_path["result_sparkline"] == [10, 15, 20]
    assert "9 x" in full_path["message_ru"]


def test_build_trade_advice_ranks_profit_by_liquidity_and_execution():
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
            "median": 12,
            "volume": 3,
        },
        {
            "id": "liquid-paranoia",
            "text": "Liquid Paranoia",
            "text_ru": "Жидкая паранойя",
            "median": 10,
            "volume": 200,
        },
        {
            "id": "liquid-envy",
            "text": "Liquid Envy",
            "text_ru": "Жидкая зависть",
            "median": 37,
            "volume": 200,
        },
    ]

    advice = build_trade_advice("Delirium", rows, "divine")

    assert advice[0]["source"] == "liquid-paranoia"
    assert advice[0]["result"] == "liquid-envy"
    assert advice[0]["profit"] == 7
    assert advice[0]["min_volume"] == 200
    assert advice[0]["rank_score"] > advice[1]["rank_score"]
    assert advice[1]["profit"] == 9
    assert advice[1]["min_volume"] == 3


def test_build_trade_advice_hides_dominated_emotion_extension():
    rows = [
        {
            "id": "concentrated-liquid-fear",
            "text": "Concentrated Liquid Fear",
            "text_ru": "Концентрированный жидкий страх",
            "median": 100,
            "volume": 200,
        },
        {
            "id": "concentrated-liquid-suffering",
            "text": "Concentrated Liquid Suffering",
            "text_ru": "Концентрированное жидкое страдание",
            "median": 950,
            "volume": 200,
        },
        {
            "id": "concentrated-liquid-isolation",
            "text": "Concentrated Liquid Isolation",
            "text_ru": "Концентрированное жидкое отчуждение",
            "median": 1200,
            "volume": 200,
        },
    ]

    advice = build_trade_advice("Delirium", rows, "divine")
    source_results = [item["result"] for item in advice if item["source"] == "concentrated-liquid-fear"]

    assert source_results == ["concentrated-liquid-suffering"]


def test_build_trade_advice_uses_ids_when_emotion_names_are_missing():
    rows = [
        {
            "id": "diluted-liquid-ire",
            "median": 1,
            "volume": 30,
        },
        {
            "id": "diluted-liquid-guilt",
            "median": 4,
            "volume": 30,
        },
    ]

    advice = build_trade_advice("Delirium", rows, "divine")

    assert advice[0]["source_name_ru"] == "diluted-liquid-ire"
    assert advice[0]["result_name_ru"] == "diluted-liquid-guilt"
    assert "None" not in advice[0]["message_ru"]
    assert "None" not in advice[0]["message_en"]
    assert "diluted-liquid-ire -> diluted-liquid-guilt" in advice[0]["message_ru"]


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


def test_read_item_history_keeps_target_and_status_defaults(tmp_path, monkeypatch):
    history = tmp_path / "history.jsonl"
    history.write_text(
        json.dumps(
            {
                "created_ts": 1,
                "league": "Fate",
                "category": "Currency",
                "target": "exalted",
                "status": "any",
                "source": "poe.ninja",
                "rows": [{"id": "chaos", "median": 4, "volume": 100, "offers": 0}],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(trade2, "HISTORY_PATH", history)

    series = trade2.read_item_history(league="Fate", category="Currency", item_id="chaos")

    assert [item["value"] for item in series] == [4]
