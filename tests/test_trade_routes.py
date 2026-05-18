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
