from __future__ import annotations

import math

import pytest

from app.benchmark import (
    DEFAULT_BASKET_ID,
    basket_price_from_snapshot,
    benchmark_price_at,
)


def test_partial_basket_keeps_coverage_diagnostics_without_a_numeric_value():
    result = basket_price_from_snapshot(
        {"rows": [{"id": "divine", "median": 10}]},
        "exalted",
        DEFAULT_BASKET_ID,
    )

    assert result["value"] is None
    assert result["coverage"] == 0.8
    assert result["missing"] == ["chaos"]
    assert [component["id"] for component in result["components"]] == ["exalted", "divine"]


def test_nonfinite_component_makes_basket_incomplete():
    result = basket_price_from_snapshot(
        {
            "rows": [
                {"id": "divine", "median": math.inf},
                {"id": "chaos", "median": 0.1},
            ]
        },
        "exalted",
        DEFAULT_BASKET_ID,
    )

    assert result["value"] is None
    assert result["coverage"] == 0.65
    assert result["missing"] == ["divine"]


def test_historical_basket_benchmark_never_uses_future_or_stale_samples():
    base_ts = 1_760_000_000
    full = {
        "created_ts": base_ts - 3600,
        "rows": [{"id": "divine", "median": 100}, {"id": "chaos", "median": 1}],
    }
    cache_key = ("basket_benchmark_history", "Fate", "exalted", DEFAULT_BASKET_ID)

    assert benchmark_price_at("Fate", "exalted", DEFAULT_BASKET_ID, base_ts, {cache_key: [full]}) == pytest.approx(35.65)
    assert benchmark_price_at(
        "Fate",
        "exalted",
        DEFAULT_BASKET_ID,
        base_ts,
        {cache_key: [{**full, "created_ts": base_ts + 3600}]},
    ) is None
    assert benchmark_price_at(
        "Fate",
        "exalted",
        DEFAULT_BASKET_ID,
        base_ts,
        {cache_key: [{**full, "created_ts": base_ts - 37 * 3600}]},
    ) is None


def test_historical_basket_benchmark_ignores_partial_snapshots():
    base_ts = 1_760_000_000
    cache_key = ("basket_benchmark_history", "Fate", "exalted", DEFAULT_BASKET_ID)
    partial = {"created_ts": base_ts - 60, "rows": [{"id": "divine", "median": 10}]}

    assert benchmark_price_at("Fate", "exalted", DEFAULT_BASKET_ID, base_ts, {cache_key: [partial]}) is None


def test_historical_basket_benchmark_uses_bucket_end_for_hourly_and_daily_data():
    cache_key = ("basket_benchmark_history", "Fate", "exalted", DEFAULT_BASKET_ID)
    rows = [{"id": "divine", "median": 100}, {"id": "chaos", "median": 1}]
    hourly = {"created_ts": 3600, "granularity": "hourly", "rows": rows}
    daily = {"created_ts": 86400, "granularity": "daily", "rows": rows}

    assert benchmark_price_at("Fate", "exalted", DEFAULT_BASKET_ID, 4000, {cache_key: [hourly]}) is None
    assert benchmark_price_at("Fate", "exalted", DEFAULT_BASKET_ID, 7200, {cache_key: [hourly]}) == pytest.approx(35.65)
    assert benchmark_price_at("Fate", "exalted", DEFAULT_BASKET_ID, 90000, {cache_key: [daily]}) is None
    assert benchmark_price_at("Fate", "exalted", DEFAULT_BASKET_ID, 172800, {cache_key: [daily]}) == pytest.approx(35.65)
