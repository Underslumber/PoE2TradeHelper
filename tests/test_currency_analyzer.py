import asyncio
import math
import time

from app import currency_analyzer
from app.currency_analyzer import build_currency_trend_context


def test_currency_trend_context_builds_forecast_from_history():
    snapshot = {
        "created_ts": 1760007200,
        "league": "Fate",
        "category": "Currency",
        "target": "exalted",
        "status": "any",
        "source": "poe.ninja",
        "rows": [
            {
                "id": "divine",
                "text_ru": "Божественная сфера",
                "median": 60,
                "volume": 120,
                "offers": 40,
                "change": 12,
            }
        ],
    }
    history = [
        {"created_ts": 1760000000, "value": 50, "volume": 100, "offers": 30},
        {"created_ts": 1760003600, "value": 55, "volume": 110, "offers": 35},
    ]

    payload = build_currency_trend_context(
        snapshot,
        history,
        league="Fate",
        currency_id="divine",
        target="exalted",
        league_day=2,
        horizon_hours=6,
        forecast_points=3,
    )

    assert payload["schema_version"] == "poe2-currency-trend-context/v1"
    assert payload["league"]["phase"] == "day_2_7"
    assert payload["currency"]["name_ru"] == "Божественная сфера"
    assert payload["currency"]["latest_price"] == 60
    assert payload["trend"]["direction"] == "strengthening"
    assert payload["trend"]["history_points"] == 3
    assert len(payload["forecast"]["points"]) == 3
    assert payload["forecast"]["expected_change_pct"] > 0
    assert payload["forecast"]["method"] == "weighted_24h_72h_7d_log_trend"
    assert set(payload["trend"]["change_pct"]) == {"1h", "6h", "24h", "72h", "7d"}


def test_currency_trend_context_marks_short_history_as_poor():
    payload = build_currency_trend_context(
        {"rows": []},
        [],
        league="Fate",
        currency_id="missing",
        target="exalted",
    )

    assert payload["currency"]["latest_price"] is None
    assert payload["trend"]["data_quality"] == "poor"
    assert payload["forecast"]["points"] == []
    assert "short_history" in payload["trend"]["risk_flags"]


def test_currency_forecast_dampens_daily_and_weekly_downtrend():
    base_ts = 1760000000
    history = [
        {"created_ts": base_ts + 0 * 3600, "value": 220},
        {"created_ts": base_ts + 24 * 3600, "value": 210},
        {"created_ts": base_ts + 48 * 3600, "value": 205},
        {"created_ts": base_ts + 96 * 3600, "value": 195},
        {"created_ts": base_ts + 144 * 3600, "value": 185},
        {"created_ts": base_ts + 167 * 3600, "value": 178},
    ]
    snapshot = {
        "created_ts": base_ts + 168 * 3600,
        "league": "Fate",
        "target": "exalted",
        "status": "any",
        "rows": [{"id": "divine", "median": 176, "volume": 80, "offers": 20}],
    }

    payload = build_currency_trend_context(
        snapshot,
        history,
        league="Fate",
        currency_id="divine",
        target="exalted",
        horizon_hours=72,
        forecast_points=12,
    )

    assert payload["trend"]["change_pct"]["24h"] < 0
    assert payload["trend"]["change_pct"]["7d"] < 0
    assert payload["forecast"]["expected_change_pct"] <= 0


def test_currency_trend_preserves_measured_zero_for_seven_day_change():
    base_ts = 1_760_000_000
    history = [
        {"created_ts": base_ts + day * 86400, "value": 100}
        for day in range(8)
    ]
    snapshot = {
        "created_ts": base_ts + 8 * 86400,
        "source": "poe.ninja",
        "rows": [{"id": "divine", "median": 100, "change": 25, "volume": 100, "offers": 10}],
    }

    payload = build_currency_trend_context(
        snapshot,
        history,
        league="Fate",
        currency_id="divine",
        target="exalted",
    )

    assert payload["trend"]["change_pct"]["7d"] == 0


def test_currency_trend_uses_one_source_when_history_has_same_timestamp_rows():
    base_ts = 1_760_000_000
    history = [
        {"created_ts": base_ts, "value": 100, "source": "poe.ninja"},
        {"created_ts": base_ts + 3600, "value": 100, "source": "poe.ninja"},
        {"created_ts": base_ts + 3600, "value": 200, "source": "trade2/search+fetch"},
    ]
    snapshot = {
        "created_ts": base_ts + 7200,
        "source": "poe.ninja",
        "rows": [{"id": "divine", "median": 100, "volume": 100, "offers": 10}],
    }

    payload = build_currency_trend_context(
        snapshot,
        history,
        league="Fate",
        currency_id="divine",
        target="exalted",
    )

    assert payload["trend"]["history_points"] == 3
    assert payload["trend"]["change_pct"]["1h"] == 0


def test_currency_trend_ignores_nonfinite_prices_and_timestamps():
    payload = build_currency_trend_context(
        {"created_ts": math.inf, "rows": [{"id": "divine", "median": math.inf}]},
        [{"created_ts": math.inf, "value": 100}, {"created_ts": 1_760_000_000, "value": math.nan}],
        league="Fate",
        currency_id="divine",
        target="exalted",
    )

    assert payload["currency"]["latest_price"] is None
    assert payload["trend"]["history_points"] == 0
    assert payload["forecast"]["points"] == []


def test_currency_analysis_database_reads_do_not_block_event_loop(monkeypatch):
    def slow_snapshot(**_kwargs):
        time.sleep(0.25)
        return {"created_ts": 1_760_000_000, "rows": []}

    def slow_history(**_kwargs):
        time.sleep(0.25)
        return []

    monkeypatch.setattr(currency_analyzer, "read_latest_rates", slow_snapshot)
    monkeypatch.setattr(currency_analyzer, "read_item_history", slow_history)

    async def run_check():
        analysis = asyncio.create_task(
            currency_analyzer.load_currency_trend_context(
                league="Fate",
                currency_id="divine",
                target="exalted",
            )
        )
        started = time.monotonic()
        await asyncio.sleep(0.02)
        heartbeat_elapsed = time.monotonic() - started
        result = await analysis
        return heartbeat_elapsed, result

    heartbeat_elapsed, payload = asyncio.run(run_check())

    assert heartbeat_elapsed < 0.15
    assert payload["currency"]["latest_price"] is None
