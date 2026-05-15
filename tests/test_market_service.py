from __future__ import annotations

from app.market_service import known_league_start_ts, select_market_league


def test_select_market_league_prefers_first_trade_challenge_league():
    leagues = [
        {"id": "Standard", "text": "Standard", "realm": "poe2"},
        {"id": "Hardcore Runes of Aldur", "text": "Hardcore Runes of Aldur", "realm": "poe2"},
        {"id": "Runes of Aldur", "text": "Runes of Aldur", "realm": "poe2"},
        {"id": "Fate of the Vaal", "text": "Fate of the Vaal", "realm": "poe2"},
    ]

    selected = select_market_league(leagues)

    assert selected["id"] == "Runes of Aldur"


def test_select_market_league_allows_explicit_preferred_league():
    leagues = [
        {"id": "Runes of Aldur", "text": "Runes of Aldur", "realm": "poe2"},
        {"id": "Fate of the Vaal", "text": "Fate of the Vaal", "realm": "poe2"},
    ]

    selected = select_market_league(leagues, preferred_league="Fate of the Vaal")

    assert selected["id"] == "Fate of the Vaal"


def test_known_league_start_ts_knows_runes_of_aldur():
    start = known_league_start_ts("Runes of Aldur", "Runes of Aldur")

    assert start == 1780081200.0
