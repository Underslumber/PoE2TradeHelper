import app.ai_context as ai_context


def test_league_phase_boundaries():
    assert ai_context.league_phase(None) == "unknown"
    assert ai_context.league_phase(1) == "day_0_1"
    assert ai_context.league_phase(7) == "day_2_7"
    assert ai_context.league_phase(21) == "day_8_21"
    assert ai_context.league_phase(22) == "late_league"


def test_build_ai_market_context_maps_snapshot_rows_and_summary():
    snapshot = {
        "created_ts": 1760000000,
        "league": "Runes of Aldur",
        "category": "Currency",
        "target": "exalted",
        "status": "any",
        "source": "poe.ninja",
        "rows": [
            {
                "id": "divine",
                "text": "Divine Orb",
                "text_ru": "Божественная сфера",
                "best": 55.0,
                "median": 56.0,
                "offers": 40,
                "volume": 120,
                "change": 12.5,
                "sparkline_kind": "price",
                "sparkline": [50, 53, 56],
            },
            {
                "id": "thin-item",
                "text": "Thin Item",
                "best": 1.0,
                "offers": 1,
                "volume": 2,
                "change": 30,
            },
        ],
    }

    payload = ai_context.build_ai_market_context(
        snapshot,
        league="Runes of Aldur",
        category="Currency",
        target="exalted",
        league_day=3,
    )

    assert payload["schema_version"] == "poe2-market-ai-context/v1"
    assert payload["league"]["phase"] == "day_2_7"
    assert payload["market_rows"][0]["name_ru"] == "Божественная сфера"
    assert payload["market_rows"][0]["change_7d_percent"] == 12.5
    assert payload["market_rows"][1]["risk_flags"] == ["low_volume", "thin_listings", "large_move_low_volume"]
    assert payload["category_summaries"][0]["priced_count"] == 2
    assert payload["category_summaries"][0]["high_liquidity_count"] == 1
