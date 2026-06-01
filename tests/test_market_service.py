from __future__ import annotations

import asyncio

from app.market_service import (
    DEFAULT_SERVICE_CATEGORIES,
    MarketSnapshotService,
    MarketSnapshotServiceSettings,
    known_league_start_ts,
    select_market_league,
)


def test_select_market_league_prefers_first_trade_challenge_league():
    leagues = [
        {"id": "Standard", "text": "Standard", "realm": "poe2"},
        {"id": "Hardcore Runes of Aldur", "text": "Hardcore Runes of Aldur", "realm": "poe2"},
        {"id": "Runes of Aldur", "text": "Runes of Aldur", "realm": "poe2"},
        {"id": "Fate of the Vaal", "text": "Fate of the Vaal", "realm": "poe2"},
    ]

    selected = select_market_league(leagues)

    assert selected["id"] == "Runes of Aldur"


def test_select_market_league_ignores_stale_preferred_league():
    leagues = [
        {"id": "Runes of Aldur", "text": "Runes of Aldur", "realm": "poe2"},
        {"id": "Fate of the Vaal", "text": "Fate of the Vaal", "realm": "poe2"},
    ]

    selected = select_market_league(leagues, preferred_league="Fate of the Vaal")

    assert selected["id"] == "Runes of Aldur"


def test_select_market_league_does_not_collect_standard_only():
    leagues = [
        {"id": "Standard", "text": "Standard", "realm": "poe2"},
        {"id": "Hardcore", "text": "Hardcore", "realm": "poe2"},
    ]

    selected = select_market_league(leagues)

    assert selected is None


def test_known_league_start_ts_knows_runes_of_aldur():
    start = known_league_start_ts("Runes of Aldur", "Runes of Aldur")

    assert start == 1780081200.0


def test_market_snapshot_service_status_includes_funpay_rub_settings():
    service = MarketSnapshotService(MarketSnapshotServiceSettings(funpay_rub_enabled=True, funpay_rub_target="divine"))

    status = service.status()

    assert status["funpay_rub"]["enabled"] is True
    assert status["funpay_rub"]["target_currency"] == "divine"
    assert status["funpay_rub"]["last_collection_ts"] is None


def test_market_snapshot_service_default_categories_skip_heavy_trade2_scans():
    service = MarketSnapshotService(MarketSnapshotServiceSettings())

    assert service.settings.categories == DEFAULT_SERVICE_CATEGORIES
    assert "ItemBases" not in service.settings.categories
    assert service.status()["item_base_market"]["enabled"] is True


def test_market_snapshot_service_collects_item_base_market_micro_batch(monkeypatch):
    captured = {}

    async def fake_job():
        return {
            "created_ts": 1000.0,
            "league": "Runes of Aldur",
            "source": "trade2/search+fetch:rough",
            "rows": [
                {"id": "base:a", "low": 1.0, "best_native": {"amount": 1.0, "currency": "exalted"}},
                {"id": "base:b", "high_demand": True},
            ],
            "refresh_job": {
                "status": "done",
                "processed_count": 2,
                "base_total": 12,
                "scan_batch_size": 60,
                "fast_scan_limit": 840,
                "priority_recheck_count": 1,
                "fetched_count": 2,
                "clean_count": 1,
            },
        }

    def fake_start_item_base_market_refresh_job(**kwargs):
        captured.update(kwargs)
        return {"status": "queued"}, fake_job()

    monkeypatch.setattr(
        "app.market_service.start_item_base_market_refresh_job",
        fake_start_item_base_market_refresh_job,
    )
    service = MarketSnapshotService(MarketSnapshotServiceSettings(item_base_market_sample_limit=100))
    service.current_league = "Runes of Aldur"

    summary = asyncio.run(service._collect_item_base_market_snapshot())

    assert captured["league"] == "Runes of Aldur"
    assert captured["q"] == ""
    assert captured["status"] == "securable"
    assert summary["processed_count"] == 2
    assert summary["scan_batch_size"] == 60
    assert summary["fast_scan_limit"] == 840
    assert summary["priority_recheck_count"] == 1
    assert summary["priced_rows"] == 1
    assert summary["high_demand_rows"] == 1
    assert service.last_item_base_market_collection_ts == 1000.0


def test_market_snapshot_service_does_not_guess_league_when_refresh_fails(monkeypatch):
    async def fake_leagues():
        raise RuntimeError("league endpoint unavailable")

    monkeypatch.setattr("app.market_service.get_trade_leagues", fake_leagues)
    service = MarketSnapshotService(MarketSnapshotServiceSettings(preferred_league=""))

    asyncio.run(service._refresh_league())

    assert service.current_league == ""
    assert service.current_league_text == ""
