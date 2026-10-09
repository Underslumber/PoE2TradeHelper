from __future__ import annotations

import asyncio
import threading

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


def test_select_market_league_ignores_hc_only_results():
    leagues = [
        {"id": "HC Forbidden Rites", "text": "HC Forbidden Rites", "realm": "poe2"},
        {"id": "Hardcore", "text": "Hardcore", "realm": "poe2"},
    ]

    assert select_market_league(leagues) is None


def test_select_market_league_skips_hc_prefix_before_softcore():
    leagues = [
        {"id": "HC Forbidden Rites", "text": "HC Forbidden Rites", "realm": "poe2"},
        {"id": "Forbidden Rites", "text": "Forbidden Rites", "realm": "poe2"},
    ]

    assert select_market_league(leagues)["id"] == "Forbidden Rites"


def test_select_market_league_detects_hc_id_with_localized_text():
    leagues = [
        {"id": "hC Forbidden Rites", "text": "Запретные обряды", "realm": "poe2"},
        {"id": "Forbidden Rites", "text": "Запретные обряды", "realm": "poe2"},
    ]

    assert select_market_league(leagues)["id"] == "Forbidden Rites"


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


def test_market_service_uses_one_item_base_collection_route_when_dedicated_enabled(monkeypatch):
    import app.market_service as market_service_module

    async def run_service(*, dedicated_enabled):
        calls = []
        service = MarketSnapshotService(
            MarketSnapshotServiceSettings(
                categories=["ItemBases"],
                item_base_market_enabled=dedicated_enabled,
                pause_seconds=0,
                funpay_rub_enabled=False,
                notification_worker_enabled=False,
                history_compaction_enabled=False,
            )
        )
        service.current_league = "Runes of Aldur"
        service._stop_event = asyncio.Event()

        async def fake_refresh_league():
            service.current_league = "Runes of Aldur"

        async def fake_collect(**kwargs):
            calls.append(("generic", kwargs["categories"]))
            service._stop_event.set()
            return {
                "created_ts": 1000.0,
                "league": "Runes of Aldur",
                "jobs_total": 1,
                "jobs_ok": 1,
                "jobs_failed": 0,
                "results": [],
            }

        async def fake_item_base_collect():
            calls.append(("dedicated", None))
            service._stop_event.set()
            return {"ok": True, "category": "ItemBases"}

        monkeypatch.setattr(service, "_refresh_league", fake_refresh_league)
        monkeypatch.setattr(service, "_collect_item_base_market_snapshot", fake_item_base_collect)
        monkeypatch.setattr(market_service_module, "collect_market_snapshots", fake_collect)
        await service._run()
        return service, calls

    dedicated_service, dedicated_calls = asyncio.run(run_service(dedicated_enabled=True))
    assert dedicated_calls == [("dedicated", None)]
    assert dedicated_service.last_summary["jobs_total"] == 0
    assert dedicated_service.last_summary["item_base_market"]["category"] == "ItemBases"

    generic_service, generic_calls = asyncio.run(run_service(dedicated_enabled=False))
    assert generic_calls == [("generic", ["ItemBases"])]
    assert generic_service.last_summary["jobs_total"] == 1
    assert "item_base_market" not in generic_service.last_summary


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


def test_history_compaction_runs_outside_event_loop(monkeypatch):
    import app.market_service as market_service_module

    worker_started = threading.Event()
    release_worker = threading.Event()
    worker_thread_ids = []

    def slow_compaction(*, now_ts):
        worker_thread_ids.append(threading.get_ident())
        worker_started.set()
        if not release_worker.wait(timeout=1.0):
            raise TimeoutError("event loop did not release compaction worker")
        return {"ok": True}

    monkeypatch.setattr(market_service_module, "compact_market_history", slow_compaction)
    service = MarketSnapshotService(
        MarketSnapshotServiceSettings(history_compaction_enabled=True, history_compaction_interval_minutes=60)
    )

    async def run_with_ticker():
        loop_thread_id = threading.get_ident()
        ticker_progress = []

        async def ticker():
            deadline = asyncio.get_running_loop().time() + 1.0
            while not worker_started.is_set() and asyncio.get_running_loop().time() < deadline:
                await asyncio.sleep(0.005)
            ticker_progress.append(worker_started.is_set())
            release_worker.set()

        tick = asyncio.create_task(ticker())
        summary = await asyncio.wait_for(service._compact_history_if_due(), timeout=2.0)
        await tick
        return summary, ticker_progress, loop_thread_id

    summary, ticker_progress, loop_thread_id = asyncio.run(run_with_ticker())

    assert summary == {"ok": True}
    assert ticker_progress == [True]
    assert worker_thread_ids[0] != loop_thread_id
