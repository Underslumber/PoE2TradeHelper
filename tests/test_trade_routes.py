from __future__ import annotations

import asyncio

from app.web import routes


def test_category_rates_latest_marks_stored_snapshot(monkeypatch) -> None:
    def fake_read_latest_rates(**kwargs):
        return {
            "created_ts": 10.0,
            "league": kwargs["league"],
            "category": kwargs["category"],
            "target": kwargs["target"],
            "status": kwargs["status"],
            "source": "poe.ninja",
            "cached": True,
            "rows": [{"id": "chaos", "median": 2.0}],
        }

    monkeypatch.setattr(routes, "read_latest_rates", fake_read_latest_rates)

    payload = routes.api_trade_category_rates_latest(
        league="Fate",
        category="Currency",
        target="exalted",
        status="any",
    )

    assert payload["stored"] is True
    assert payload["cached"] is True
    assert payload["rows"] == [{"id": "chaos", "median": 2.0}]


def test_category_rates_latest_omits_rows_when_unchanged(monkeypatch) -> None:
    def fake_read_latest_rates(**kwargs):
        return {
            "created_ts": 10.0,
            "league": kwargs["league"],
            "category": kwargs["category"],
            "target": kwargs["target"],
            "status": kwargs["status"],
            "source": "poe.ninja",
            "cached": True,
            "rows": [{"id": "chaos", "median": 2.0}],
        }

    monkeypatch.setattr(routes, "read_latest_rates", fake_read_latest_rates)

    payload = routes.api_trade_category_rates_latest(
        league="Fate",
        category="Currency",
        target="exalted",
        status="any",
        since_ts=10.0,
    )

    assert payload["stored"] is True
    assert payload["unchanged"] is True
    assert "rows" not in payload


def test_latest_item_market_falls_back_to_item_history(monkeypatch) -> None:
    def fake_read_latest_rates(**kwargs):
        return {
            "created_ts": 10.0,
            "league": kwargs["league"],
            "category": kwargs["category"],
            "target": kwargs["target"],
            "status": kwargs["status"],
            "source": "trade2/search+fetch:overview",
            "cached": True,
            "rows": [{"id": "base:other", "low": 1.0}],
        }

    def fake_read_item_history(**kwargs):
        assert kwargs["category"] == "ItemBases"
        assert kwargs["item_id"] == "base:waxed-jacket"
        return [
            {"created_ts": 8.0, "value": 0.2, "price": 0.2, "source": "trade2/search+fetch:overview"},
            {"created_ts": 9.0, "value": 0.4, "price": 0.4, "source": "trade2/search+fetch:overview"},
        ]

    monkeypatch.setattr(routes, "read_latest_rates", fake_read_latest_rates)
    monkeypatch.setattr(routes, "read_item_history", fake_read_item_history)

    market = routes._latest_item_market("Fate", "ItemBases", "exalted", "base:waxed-jacket")

    assert market["price"] == 0.4
    assert market["created_ts"] == 9.0
    assert market["sparkline_kind"] == "price"


def test_market_diagnostics_uses_latest_snapshot_and_history(monkeypatch) -> None:
    latest = {
        "created_ts": 3700.0,
        "league": "Fate",
        "category": "Currency",
        "target": "exalted",
        "status": "any",
        "source": "poe.ninja",
        "rows": [{"id": "cheap", "median": 12.0, "change": -9, "volume": 50}],
    }

    def fake_read_latest_rates(**kwargs):
        assert kwargs["league"] == "Fate"
        return latest

    def fake_read_history(**kwargs):
        assert kwargs["limit"] == 24
        return [
            {
                "created_ts": 100.0,
                "league": "Fate",
                "category": "Currency",
                "target": "exalted",
                "status": "any",
                "rows": [{"id": "cheap", "median": 10.0, "change": -10, "volume": 50}],
            },
            latest,
        ]

    monkeypatch.setattr(routes, "read_latest_rates", fake_read_latest_rates)
    monkeypatch.setattr(routes, "read_history", fake_read_history)

    payload = routes.api_trade_market_diagnostics(
        league="Fate",
        category="Currency",
        target="exalted",
        status="any",
        expected_items=3,
        history_limit=24,
        horizon_hours=1,
    )

    assert payload["schema_version"] == "poe2-market-diagnostics/v1"
    assert payload["stored"] is True
    assert payload["health"]["priced"] == 1
    assert payload["health"]["expected"] == 3
    assert payload["backtest"]["evaluated"] == 1


def test_trade_static_uses_bootstrap_fallback_without_error_field(monkeypatch) -> None:
    async def fake_get_trade_static():
        raise RuntimeError("trade2 unavailable")

    monkeypatch.setattr(routes, "get_trade_static", fake_get_trade_static)

    payload = asyncio.run(routes.api_trade_static())

    assert payload["fallback"] is True
    assert "error" not in payload
    assert payload["categories"]["Currency"]
    assert payload["category_meta"][0]["id"] == "Currency"


def test_trade_leagues_uses_bootstrap_fallback_without_error_field(monkeypatch) -> None:
    async def fake_get_trade_leagues():
        raise RuntimeError("trade2 unavailable")

    monkeypatch.setattr(routes, "get_trade_leagues", fake_get_trade_leagues)

    payload = asyncio.run(routes.api_trade_leagues())

    assert payload["fallback"] is True
    assert "error" not in payload
    assert payload["leagues"][0]["id"] == "Fate of the Vaal"


def test_item_base_market_refresh_starts_background_job(monkeypatch) -> None:
    calls = {"start": 0, "get": 0}

    async def noop_job():
        return {}

    def fake_start(**kwargs):
        calls["start"] += 1
        assert kwargs["q"] == "Амулет с янтарём"
        assert kwargs["status"] == "securable"
        assert kwargs["min_ilvl"] is None
        assert kwargs["sample_limit"] == 100
        return {"status": "queued"}, noop_job()

    async def fake_get(**kwargs):
        calls["get"] += 1
        assert kwargs["force_refresh"] is False
        assert kwargs["status"] == "securable"
        assert kwargs["min_ilvl"] == 82
        assert kwargs["sample_limit"] == 100
        assert kwargs["price_trigger"] == "below"
        assert kwargs["price_value"] == 10
        assert kwargs["price_currency"] == "exalted"
        assert kwargs["hide_weak_activity"] is True
        return {"rows": [], "refresh_job": {"status": "queued"}}

    monkeypatch.setattr(routes, "start_item_base_market_refresh_job", fake_start)
    monkeypatch.setattr(routes, "get_item_base_market", fake_get)

    payload = asyncio.run(
        routes.api_trade_item_base_market(
            league="PoE2 - Test",
            target="exalted",
            status="securable",
            q="Амулет с янтарём",
            limit=40,
            min_ilvl=82,
            price_trigger="below",
            price_value=10,
            price_currency="exalted",
            hide_weak_activity=True,
            sample_limit=100,
            refresh=True,
        )
    )

    assert calls == {"start": 1, "get": 1}
    assert payload["refresh_job"]["status"] == "queued"


def test_item_base_market_blank_refresh_starts_background_scan(monkeypatch) -> None:
    calls = {"start": 0, "get": 0}

    async def noop_job():
        return {}

    def fake_start(**kwargs):
        calls["start"] += 1
        assert kwargs["q"] == ""
        assert kwargs["status"] == "securable"
        assert kwargs["min_ilvl"] is None
        assert kwargs["sample_limit"] == 100
        return {"status": "queued"}, noop_job()

    async def fake_get(**kwargs):
        calls["get"] += 1
        assert kwargs["force_refresh"] is False
        assert kwargs["q"] == ""
        assert kwargs["min_ilvl"] == 82
        assert kwargs["price_trigger"] == ""
        assert kwargs["price_value"] is None
        assert kwargs["price_currency"] == ""
        return {"rows": [], "refresh_job": {"status": "queued"}}

    monkeypatch.setattr(routes, "start_item_base_market_refresh_job", fake_start)
    monkeypatch.setattr(routes, "get_item_base_market", fake_get)

    payload = asyncio.run(
        routes.api_trade_item_base_market(
            league="PoE2 - Test",
            target="exalted",
            status="securable",
            q="",
            limit=40,
            min_ilvl=82,
            price_trigger="",
            price_value=None,
            price_currency="",
            sample_limit=100,
            refresh=True,
        )
    )

    assert calls == {"start": 1, "get": 1}
    assert payload["refresh_job"]["status"] == "queued"
