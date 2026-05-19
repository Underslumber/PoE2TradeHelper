from __future__ import annotations

from app.benchmark import DEFAULT_BASKET_ID, basket_price_from_snapshot
from app.item_parser import parse_item_text
from app.profitability import build_profitability_snapshot, execution_quality
from app.recipes import analyze_recipes


def test_execution_quality_uses_volume_when_listing_count_is_missing():
    quality = execution_quality({"id": "divine", "median": 10, "volume": 80, "offers": 0, "change": 5})

    assert quality["quality"] == "good"
    assert "missing_listing_count" not in quality["risk_flags"]


def test_profitability_snapshot_splits_executable_and_risky_rows():
    payload = build_profitability_snapshot(
        {
            "league": "Fate",
            "category": "Currency",
            "target": "exalted",
            "created_ts": 1,
            "rows": [
                {"id": "divine", "text_ru": "Божественная сфера", "median": 100, "volume": 100, "change": 4},
                {"id": "thin", "text_ru": "Тонкий рынок", "median": 1, "volume": 1, "offers": 1, "change": 50},
            ],
        }
    )

    assert payload["summary"]["priced"] == 2
    assert payload["executable_candidates"][0]["id"] == "divine"
    assert payload["risky_candidates"][0]["id"] == "thin"


def test_basket_price_uses_weighted_currency_snapshot():
    snapshot = {
        "source": "test",
        "created_ts": 10,
        "rows": [
            {"id": "divine", "median": 100},
            {"id": "chaos", "median": 0.1},
        ],
    }

    basket = basket_price_from_snapshot(snapshot, "exalted", DEFAULT_BASKET_ID)

    assert round(basket["value"], 4) == round((1 * 0.45 + 100 * 0.35 + 0.1 * 0.2), 4)
    assert basket["missing"] == []


def test_parse_item_text_extracts_affixes_and_item_level():
    parsed = parse_item_text(
        """Rarity: Rare
Vengeance Veil
Waxed Jacket
--------
Item Level: 72
--------
+55 to maximum Life
+20% to Fire Resistance
"""
    )

    assert parsed["rarity"] == "Rare"
    assert parsed["name"] == "Vengeance Veil"
    assert parsed["type_line"] == "Waxed Jacket"
    assert parsed["item_level"] == 72
    assert "# to maximum life" in parsed["normalized_mods"]


def test_recipe_analysis_returns_known_fragment_recipe():
    payload = analyze_recipes(
        "Fragments",
        [
            {"id": "simulacrum-splinter", "text_ru": "Осколок Симулякра", "median": 1, "volume": 500},
            {"id": "simulacrum", "text_ru": "Симулякр", "median": 400, "volume": 20},
        ],
        "exalted",
        snapshot_ts=1,
    )

    assert payload["opportunities"][0]["source"] == "simulacrum-splinter"
    assert payload["opportunities"][0]["profit"] == 100


def test_recipe_analysis_returns_adjacent_delirium_recipe():
    payload = analyze_recipes(
        "Delirium",
        [
            {"id": "diluted-liquid-ire", "text_ru": "Разбавленный жидкий гнев", "median": 1, "volume": 100},
            {"id": "diluted-liquid-guilt", "text_ru": "Разбавленная жидкая вина", "median": 4, "volume": 100},
        ],
        "exalted",
        snapshot_ts=1,
    )

    assert payload["known_recipes"] > 1
    assert payload["opportunities"][0]["source"] == "diluted-liquid-ire"
    assert payload["opportunities"][0]["result"] == "diluted-liquid-guilt"
    assert payload["opportunities"][0]["profit"] == 1


def test_recipe_analysis_finds_best_full_emotion_path():
    payload = analyze_recipes(
        "Delirium",
        [
            {"id": "diluted-liquid-ire", "text_ru": "Разбавленный жидкий гнев", "median": 1, "volume": 100},
            {"id": "diluted-liquid-guilt", "text_ru": "Разбавленная жидкая вина", "median": 4, "volume": 100},
            {"id": "diluted-liquid-greed", "text_ru": "Разбавленная жидкая жадность", "median": 20, "volume": 100},
        ],
        "exalted",
        snapshot_ts=1,
    )

    best = payload["opportunities"][0]
    assert best["kind"] == "emotion_path"
    assert best["source"] == "diluted-liquid-ire"
    assert best["result"] == "diluted-liquid-greed"
    assert best["path_steps"] == 2
    assert best["input_count"] == 9
    assert best["profit"] == 11


def test_recipe_analysis_ranks_by_profit_liquidity_and_success():
    payload = analyze_recipes(
        "Delirium",
        [
            {"id": "diluted-liquid-ire", "text_ru": "Разбавленный жидкий гнев", "median": 1, "volume": 3},
            {"id": "diluted-liquid-guilt", "text_ru": "Разбавленная жидкая вина", "median": 12, "volume": 3},
            {"id": "liquid-paranoia", "text_ru": "Жидкая паранойя", "median": 10, "volume": 200},
            {"id": "liquid-envy", "text_ru": "Жидкая зависть", "median": 37, "volume": 200},
        ],
        "exalted",
        snapshot_ts=1,
    )

    best = payload["opportunities"][0]
    second = payload["opportunities"][1]

    assert best["source"] == "liquid-paranoia"
    assert best["result"] == "liquid-envy"
    assert best["profit"] == 7
    assert best["min_volume"] == 200
    assert best["rank_score"] > second["rank_score"]
    assert second["profit"] == 9
    assert second["min_volume"] == 3


def test_recipe_analysis_hides_dominated_emotion_extension():
    payload = analyze_recipes(
        "Delirium",
        [
            {"id": "concentrated-liquid-fear", "text_ru": "Концентрированный жидкий страх", "median": 100, "volume": 200},
            {"id": "concentrated-liquid-suffering", "text_ru": "Концентрированное жидкое страдание", "median": 950, "volume": 200},
            {"id": "concentrated-liquid-isolation", "text_ru": "Концентрированное жидкое отчуждение", "median": 1200, "volume": 200},
        ],
        "exalted",
        snapshot_ts=1,
    )

    source_results = [
        item["result"]
        for item in payload["opportunities"]
        if item["source"] == "concentrated-liquid-fear"
    ]

    assert source_results == ["concentrated-liquid-suffering"]
