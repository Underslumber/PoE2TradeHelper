from __future__ import annotations

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
