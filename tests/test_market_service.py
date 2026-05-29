from __future__ import annotations

import asyncio

from app.market_service import MarketSnapshotService, MarketSnapshotServiceSettings, known_league_start_ts, select_market_league


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


def test_market_snapshot_service_status_includes_funpay_rub_settings():
    service = MarketSnapshotService(MarketSnapshotServiceSettings(funpay_rub_enabled=True, funpay_rub_target="divine"))

    status = service.status()

    assert status["funpay_rub"]["enabled"] is True
    assert status["funpay_rub"]["target_currency"] == "divine"
    assert status["funpay_rub"]["last_collection_ts"] is None


def test_market_snapshot_service_uses_fallback_league_when_refresh_fails(monkeypatch):
    async def fake_leagues():
        raise RuntimeError("league endpoint unavailable")

    monkeypatch.setattr("app.market_service.get_trade_leagues", fake_leagues)
    service = MarketSnapshotService(MarketSnapshotServiceSettings(preferred_league=""))

    asyncio.run(service._refresh_league())

    assert service.current_league == "Runes of Aldur"
    assert service.current_league_text == "Runes of Aldur"
