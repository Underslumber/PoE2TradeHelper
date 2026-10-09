from __future__ import annotations

from app.market_diagnostics import backtest_signal_history, build_market_health


def test_market_health_summarizes_freshness_coverage_and_risk() -> None:
    snapshot = {
        "created_ts": 1000.0,
        "source": "poe.ninja",
        "rows": [
            {"id": "chaos", "median": 2.0, "volume": 80, "offers": 12},
            {"id": "thin", "median": 4.0, "volume": 1, "offers": 1},
            {"id": "missing", "volume": 0},
        ],
        "errors": [],
    }

    health = build_market_health(snapshot, expected_items=4, now_ts=1100.0)

    assert health["freshness"] == "fresh"
    assert health["data_quality"] == "partial"
    assert health["priced"] == 2
    assert health["expected"] == 4
    assert health["coverage_pct"] == 50.0
    assert health["executable"] == 1
    assert health["risk_flags"]["thin_listings"] == 1


def test_backtest_signal_history_scores_buy_and_sell_direction() -> None:
    history = [
        {
            "created_ts": 100.0,
            "rows": [
                {"id": "cheap", "text": "Cheap", "median": 10.0, "change": -10, "volume": 50},
                {"id": "expensive", "text": "Expensive", "median": 20.0, "change": 12, "volume": 60},
                {"id": "quiet", "text": "Quiet", "median": 5.0, "change": 2, "volume": 60},
            ],
        },
        {
            "created_ts": 3700.0,
            "rows": [
                {"id": "cheap", "median": 12.0, "volume": 50},
                {"id": "expensive", "median": 18.0, "volume": 60},
                {"id": "quiet", "median": 5.1, "volume": 60},
            ],
        },
    ]

    result = backtest_signal_history(history, horizon_hours=1)

    assert result["history_points"] == 2
    assert result["raw_candidates"] == 2
    assert result["evaluated"] == 2
    assert result["successful"] == 2
    assert result["success_rate"] == 100.0
    assert result["by_action"] == {"buy_dip": 1, "sell_momentum": 1}


def test_backtest_does_not_compare_different_sources_or_currencies() -> None:
    initial = {
        "created_ts": 100.0, "source": "poe.ninja", "target": "exalted",
        "rows": [{"id": "chaos", "median": 10, "change": -10, "volume": 50}],
    }
    other_source = {
        "created_ts": 3700.0, "source": "trade2", "target": "exalted",
        "rows": [{"id": "chaos", "median": 100}],
    }
    other_currency = {
        "created_ts": 3800.0, "source": "poe.ninja", "target": "divine",
        "rows": [{"id": "chaos", "median": 0.1}],
    }
    result = backtest_signal_history([initial, other_source, other_currency], horizon_hours=1)
    assert result["evaluated"] == 0
    assert result["pending"] == 1
    comparable = {
        "created_ts": 3900.0, "source": "poe.ninja", "target": "exalted",
        "rows": [{"id": "chaos", "median": 11}],
    }
    result = backtest_signal_history([initial, other_source, other_currency, comparable], horizon_hours=1)
    assert result["evaluated"] == 1
    assert result["samples"][0]["future_price"] == 11
