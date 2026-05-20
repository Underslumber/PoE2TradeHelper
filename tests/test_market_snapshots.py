from __future__ import annotations

import asyncio

from app import market_snapshots


def test_market_snapshot_interval_uses_early_window():
    assert market_snapshots.market_snapshot_interval_seconds(
        now_ts=120,
        league_start_ts=0,
        early_days=1,
        early_interval_minutes=5,
        interval_minutes=15,
    ) == 300
    assert market_snapshots.market_snapshot_interval_seconds(
        now_ts=3 * 24 * 60 * 60,
        league_start_ts=0,
        early_days=1,
        early_interval_minutes=5,
        interval_minutes=15,
    ) == 900


def test_build_market_snapshot_jobs_uses_all_static_categories(monkeypatch):
    async def fake_static():
        return {
            "Currency": [{"id": "exalted"}],
            "Delirium": [{"id": "liquid-paranoia"}],
            "Waystones": [{"id": "waystone"}],
            "Misc": [{"id": "skip-me"}],
            "Empty": [],
        }

    monkeypatch.setattr(market_snapshots, "get_trade_static", fake_static)

    jobs = asyncio.run(
        market_snapshots.build_market_snapshot_jobs(
            league="Fate",
            target="exalted",
            status="any",
            currency_targets=["divine", "chaos", "exalted"],
        )
    )

    assert [(job.category, job.target, job.status) for job in jobs] == [
        ("Currency", "exalted", "any"),
        ("Delirium", "exalted", "any"),
        ("Waystones", "exalted", "any"),
        ("ItemBases", "exalted", "any"),
        ("Currency", "divine", "any"),
        ("Currency", "chaos", "any"),
    ]


def test_build_market_snapshot_jobs_allows_explicit_item_bases(monkeypatch):
    async def fake_static():
        return {
            "Currency": [{"id": "exalted"}],
        }

    monkeypatch.setattr(market_snapshots, "get_trade_static", fake_static)

    jobs = asyncio.run(
        market_snapshots.build_market_snapshot_jobs(
            league="Fate",
            target="exalted",
            status="any",
            categories=["ItemBases"],
            include_unsupported=False,
        )
    )

    assert [(job.category, job.target, job.status) for job in jobs] == [("ItemBases", "exalted", "any")]


def test_build_market_snapshot_jobs_keeps_item_bases_when_static_fails(monkeypatch):
    async def fake_static():
        raise RuntimeError("static unavailable")

    monkeypatch.setattr(market_snapshots, "get_trade_static", fake_static)

    jobs = asyncio.run(
        market_snapshots.build_market_snapshot_jobs(
            league="Fate",
            target="exalted",
            status="any",
        )
    )

    assert [(job.category, job.target, job.status) for job in jobs] == [("ItemBases", "exalted", "any")]


def test_collect_market_snapshots_continues_after_category_error(monkeypatch):
    async def fake_jobs(**kwargs):
        return [
            market_snapshots.SnapshotJob(league="Fate", category="Currency", target="exalted", status="any"),
            market_snapshots.SnapshotJob(league="Fate", category="Broken", target="exalted", status="any"),
        ]

    async def fake_rates(**kwargs):
        if kwargs["category"] == "Broken":
            raise RuntimeError("boom")
        assert kwargs["force_refresh"] is True
        return {"source": "poe.ninja", "rows": [{"id": "chaos"}], "errors": []}

    monkeypatch.setattr(market_snapshots, "build_market_snapshot_jobs", fake_jobs)
    monkeypatch.setattr(market_snapshots, "get_category_rates", fake_rates)

    summary = asyncio.run(market_snapshots.collect_market_snapshots(league="Fate", pause_seconds=0))

    assert summary["jobs_total"] == 2
    assert summary["jobs_ok"] == 1
    assert summary["jobs_failed"] == 1
    assert summary["results"][0]["rows"] == 1
    assert summary["results"][1]["error"] == "boom"


def test_collect_market_snapshots_uses_base_market_collector(monkeypatch):
    async def fake_jobs(**kwargs):
        return [
            market_snapshots.SnapshotJob(league="Fate", category="Currency", target="exalted", status="any"),
            market_snapshots.SnapshotJob(league="Fate", category="ItemBases", target="exalted", status="any"),
        ]

    calls = []

    async def fake_rates(**kwargs):
        calls.append(("rates", kwargs))
        return {"source": "poe.ninja", "rows": [{"id": "chaos"}], "errors": []}

    async def fake_bases(**kwargs):
        calls.append(("bases", kwargs))
        return {"source": "trade2/search+fetch", "rows": [{"id": "base:waxed-jacket"}], "errors": []}

    monkeypatch.setattr(market_snapshots, "build_market_snapshot_jobs", fake_jobs)
    monkeypatch.setattr(market_snapshots, "get_category_rates", fake_rates)
    monkeypatch.setattr(market_snapshots, "get_item_base_market", fake_bases)

    summary = asyncio.run(market_snapshots.collect_market_snapshots(league="Fate", pause_seconds=0))

    assert summary["jobs_total"] == 2
    assert summary["jobs_ok"] == 2
    assert summary["results"][1]["category"] == "ItemBases"
    assert summary["results"][1]["rows"] == 1
    assert calls[1] == (
        "bases",
        {
            "league": "Fate",
            "target": "exalted",
            "status": "securable",
            "limit": market_snapshots.ITEM_BASE_MARKET_MAX_BASES,
            "force_refresh": True,
        },
    )
