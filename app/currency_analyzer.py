from __future__ import annotations

import math
from datetime import datetime, timezone
from statistics import mean, pstdev
from typing import Any

from app.ai_context import league_phase
from app.trade2 import get_category_rates, read_item_history, read_latest_rates

CURRENCY_CONTEXT_SCHEMA_VERSION = "poe2-currency-trend-context/v1"


def _positive_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _timestamp(value: Any) -> float | None:
    try:
        timestamp = float(value)
    except (TypeError, ValueError):
        return None
    return timestamp if timestamp > 0 else None


def _ts_to_iso(value: Any) -> str | None:
    timestamp = _timestamp(value)
    if timestamp is None:
        return None
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()


def _row_price(row: dict[str, Any] | None) -> float | None:
    if not row:
        return None
    return _positive_number(row.get("median")) or _positive_number(row.get("best"))


def _row_name(row: dict[str, Any] | None, currency_id: str) -> str:
    if not row:
        return currency_id
    return str(row.get("text_ru") or row.get("text") or row.get("name") or row.get("id") or currency_id)


def _normalize_history(series: list[dict[str, Any]], current_row: dict[str, Any] | None, current_ts: Any) -> list[dict[str, Any]]:
    points: dict[float, dict[str, Any]] = {}
    for item in series:
        timestamp = _timestamp(item.get("created_ts"))
        value = _positive_number(item.get("value"))
        if timestamp is None or value is None:
            continue
        points[timestamp] = {
            "created_ts": timestamp,
            "created_at": _ts_to_iso(timestamp),
            "value": value,
            "volume": _positive_number(item.get("volume")),
            "offers": _positive_number(item.get("offers")),
            "change": item.get("change"),
            "source": item.get("source") or "",
        }

    current_timestamp = _timestamp(current_ts)
    current_price = _row_price(current_row)
    if current_timestamp is not None and current_price is not None:
        points[current_timestamp] = {
            "created_ts": current_timestamp,
            "created_at": _ts_to_iso(current_timestamp),
            "value": current_price,
            "volume": _positive_number((current_row or {}).get("volume")),
            "offers": _positive_number((current_row or {}).get("offers")),
            "change": (current_row or {}).get("change"),
            "source": "",
        }
    return [points[key] for key in sorted(points)]


def _hourly_series(series: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[int, dict[str, Any]] = {}
    for point in series:
        timestamp = _timestamp(point.get("created_ts"))
        value = _positive_number(point.get("value"))
        if timestamp is None or value is None:
            continue
        hour_ts = int(timestamp // 3600) * 3600
        previous = buckets.get(hour_ts)
        if not previous or timestamp >= previous["created_ts"]:
            item = dict(point)
            item["created_ts"] = timestamp
            buckets[hour_ts] = item
    return [buckets[key] for key in sorted(buckets)]


def _window_change(series: list[dict[str, Any]], hours: float) -> float | None:
    if len(series) < 2:
        return None
    latest = series[-1]
    latest_ts = _timestamp(latest.get("created_ts"))
    latest_value = _positive_number(latest.get("value"))
    if latest_ts is None or latest_value is None:
        return None
    first_ts = _timestamp(series[0].get("created_ts"))
    if first_ts is None or latest_ts - first_ts < hours * 3600 * 0.8:
        return None
    cutoff = latest_ts - hours * 3600
    candidates = [point for point in series if (_timestamp(point.get("created_ts")) or 0) <= cutoff]
    if not candidates:
        return None
    base = candidates[-1]
    base_value = _positive_number(base.get("value"))
    if base_value is None:
        return None
    return ((latest_value - base_value) / base_value) * 100


def _log_returns(series: list[dict[str, Any]]) -> list[float]:
    returns = []
    for left, right in zip(series, series[1:]):
        left_value = _positive_number(left.get("value"))
        right_value = _positive_number(right.get("value"))
        if left_value is None or right_value is None:
            continue
        returns.append(math.log(right_value / left_value))
    return returns


def _safe_log_slope_from_change(change_pct: float | None, hours: float) -> float | None:
    if change_pct is None or hours <= 0:
        return None
    factor = 1 + change_pct / 100
    if factor <= 0:
        return None
    return math.log(factor) / hours


def _volatility_label(log_returns: list[float]) -> str:
    if len(log_returns) < 3:
        return "unknown"
    volatility = pstdev(log_returns) * 100
    if volatility >= 8:
        return "high"
    if volatility >= 3:
        return "medium"
    return "low"


def _data_quality(series: list[dict[str, Any]], span_hours: float) -> str:
    if len(series) >= 24 and span_hours >= 48:
        return "good"
    if len(series) >= 8 and span_hours >= 12:
        return "partial"
    return "poor"


def _trend_direction(change_24h: float | None, slope_pct_hour: float | None) -> str:
    signal = change_24h if change_24h is not None else slope_pct_hour
    if signal is None:
        return "unknown"
    if signal >= 3:
        return "strengthening"
    if signal <= -3:
        return "weakening"
    return "sideways"


def _recent_linear_log_slope(series: list[dict[str, Any]], window_hours: float = 72) -> float | None:
    if len(series) < 2:
        return None
    latest_ts = _timestamp(series[-1].get("created_ts"))
    if latest_ts is None:
        return None
    window_start = latest_ts - window_hours * 3600
    window = [point for point in series if (_timestamp(point.get("created_ts")) or 0) >= window_start]
    if len(window) < 2:
        window = series[-min(len(series), 40) :]

    first_ts = _timestamp(window[0].get("created_ts"))
    if first_ts is None:
        return None
    xs = []
    ys = []
    for point in window:
        timestamp = _timestamp(point.get("created_ts"))
        value = _positive_number(point.get("value"))
        if timestamp is None or value is None:
            continue
        xs.append((timestamp - first_ts) / 3600)
        ys.append(math.log(value))
    if len(xs) < 2:
        return None
    x_avg = mean(xs)
    y_avg = mean(ys)
    denominator = sum((x - x_avg) ** 2 for x in xs)
    if denominator <= 0:
        return None
    return sum((x - x_avg) * (y - y_avg) for x, y in zip(xs, ys)) / denominator


def _forecast_weights(horizon_hours: int) -> dict[str, float]:
    if horizon_hours <= 24:
        return {"recent": 0.2, "24h": 0.45, "72h": 0.25, "7d": 0.1}
    if horizon_hours <= 72:
        return {"recent": 0.15, "24h": 0.25, "72h": 0.35, "7d": 0.25}
    return {"recent": 0.15, "24h": 0.15, "72h": 0.25, "7d": 0.45}


def _blend_forecast_slope(
    series: list[dict[str, Any]],
    changes: dict[str, float | None],
    *,
    horizon_hours: int,
    returns: list[float],
) -> tuple[float | None, dict[str, Any]]:
    candidates = {
        "recent": _recent_linear_log_slope(series, 72),
        "24h": _safe_log_slope_from_change(changes.get("24h"), 24),
        "72h": _safe_log_slope_from_change(changes.get("72h"), 72),
        "7d": _safe_log_slope_from_change(changes.get("7d"), 24 * 7),
    }
    weights = _forecast_weights(horizon_hours)
    weighted = [
        (slope, weights[key])
        for key, slope in candidates.items()
        if slope is not None and weights.get(key, 0) > 0
    ]
    if not weighted:
        return None, {"inputs": candidates, "weights": weights, "dampening": "no_data"}

    slope = sum(value * weight for value, weight in weighted) / sum(weight for _value, weight in weighted)
    dampening: list[str] = []
    change_24h = changes.get("24h")
    change_72h = changes.get("72h")
    change_7d = changes.get("7d")
    change_6h = changes.get("6h")

    if change_24h is not None and change_7d is not None and change_24h * change_7d < 0:
        slope *= 0.55
        dampening.append("24h_7d_disagree")
    if change_72h is not None and change_7d is not None and change_72h * change_7d < 0:
        slope *= 0.7
        dampening.append("72h_7d_disagree")
    if change_24h is not None and change_7d is not None and change_24h <= -2 and change_7d <= -2 and slope > 0:
        if change_6h is not None and change_6h >= 3:
            slope *= 0.25
            dampening.append("countertrend_bounce")
        else:
            slope = min(0, slope)
            dampening.append("daily_weekly_downtrend")
    if change_24h is not None and change_7d is not None and change_24h >= 2 and change_7d >= 2 and slope < 0:
        if change_6h is not None and change_6h <= -3:
            slope *= 0.25
            dampening.append("countertrend_pullback")
        else:
            slope = max(0, slope)
            dampening.append("daily_weekly_uptrend")
    if len(returns) >= 3 and pstdev(returns) * 100 >= 3:
        slope *= 0.75
        dampening.append("volatility")

    slope = max(min(slope, 0.035), -0.035)
    return slope, {"inputs": candidates, "weights": weights, "dampening": dampening}


def _forecast_series(
    series: list[dict[str, Any]],
    *,
    changes: dict[str, float | None],
    horizon_hours: int,
    forecast_points: int,
    returns: list[float],
) -> tuple[list[dict[str, Any]], float | None, dict[str, Any]]:
    if len(series) < 2:
        return [], None, {"dampening": "short_history"}
    latest = series[-1]
    latest_ts = _timestamp(latest.get("created_ts"))
    latest_value = _positive_number(latest.get("value"))
    if latest_ts is None or latest_value is None:
        return [], None, {"dampening": "missing_latest_price"}

    slope, diagnostics = _blend_forecast_slope(series, changes, horizon_hours=horizon_hours, returns=returns)
    if slope is None:
        return [], None, diagnostics
    step = max(1, horizon_hours / max(1, forecast_points))
    points = []
    for index in range(1, max(1, forecast_points) + 1):
        delta_hours = step * index
        value = latest_value * math.exp(slope * delta_hours)
        timestamp = latest_ts + delta_hours * 3600
        points.append(
            {
                "created_ts": timestamp,
                "created_at": _ts_to_iso(timestamp),
                "value": round(value, 6),
            }
        )
    return points, (math.exp(slope) - 1) * 100, diagnostics


def build_currency_trend_context(
    snapshot: dict[str, Any] | None,
    history: list[dict[str, Any]],
    *,
    league: str,
    currency_id: str,
    target: str = "exalted",
    status: str = "any",
    league_day: int | None = None,
    horizon_hours: int = 24,
    forecast_points: int = 12,
) -> dict[str, Any]:
    snapshot = snapshot or {}
    rows = list(snapshot.get("rows") or [])
    current_row = next((row for row in rows if row.get("id") == currency_id), None)
    normalized_history = _hourly_series(_normalize_history(history, current_row, snapshot.get("created_ts")))
    latest = normalized_history[-1] if normalized_history else None
    earliest = normalized_history[0] if normalized_history else None
    span_hours = 0.0
    if latest and earliest:
        span_hours = max(0.0, ((latest.get("created_ts") or 0) - (earliest.get("created_ts") or 0)) / 3600)

    latest_value = _positive_number((latest or {}).get("value"))
    returns = _log_returns(normalized_history)
    changes = {
        "1h": _window_change(normalized_history, 1),
        "6h": _window_change(normalized_history, 6),
        "24h": _window_change(normalized_history, 24),
        "72h": _window_change(normalized_history, 72),
        "7d": _window_change(normalized_history, 24 * 7) or _number((current_row or {}).get("change")),
    }
    forecast, slope_pct_hour, forecast_diagnostics = _forecast_series(
        normalized_history,
        changes=changes,
        horizon_hours=max(1, horizon_hours),
        forecast_points=max(1, forecast_points),
        returns=returns,
    )
    forecast_last = _positive_number((forecast[-1] if forecast else {}).get("value"))
    forecast_change = None
    if latest_value is not None and forecast_last is not None:
        forecast_change = ((forecast_last - latest_value) / latest_value) * 100

    data_quality = _data_quality(normalized_history, span_hours)
    trend = _trend_direction(changes["24h"], slope_pct_hour)
    risk_flags = []
    if data_quality == "poor":
        risk_flags.append("short_history")
    if _volatility_label(returns) == "high":
        risk_flags.append("high_volatility")
    if _positive_number((current_row or {}).get("volume")) is None:
        risk_flags.append("missing_volume")
    elif (_positive_number((current_row or {}).get("volume")) or 0) < 10:
        risk_flags.append("low_volume")
    if _positive_number((current_row or {}).get("offers")) is None:
        risk_flags.append("missing_listing_count")
    elif (_positive_number((current_row or {}).get("offers")) or 0) < 3:
        risk_flags.append("thin_listings")

    return {
        "schema_version": CURRENCY_CONTEXT_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "league": {
            "id": snapshot.get("league") or league,
            "day": league_day,
            "phase": league_phase(league_day),
        },
        "currency": {
            "id": currency_id,
            "name_ru": _row_name(current_row, currency_id),
            "target": snapshot.get("target") or target,
            "status": snapshot.get("status") or status,
            "source": snapshot.get("source") or "",
            "latest_price": latest_value,
            "latest_ts": _ts_to_iso((latest or {}).get("created_ts")),
            "volume": _positive_number((current_row or {}).get("volume")),
            "offers": _positive_number((current_row or {}).get("offers")),
            "change_7d_percent": (current_row or {}).get("change"),
        },
        "trend": {
            "direction": trend,
            "slope_pct_per_hour": slope_pct_hour,
            "change_pct": changes,
            "volatility": _volatility_label(returns),
            "data_quality": data_quality,
            "history_points": len(normalized_history),
            "history_span_hours": span_hours,
            "risk_flags": risk_flags,
        },
        "price_history": normalized_history,
        "forecast": {
            "method": "weighted_24h_72h_7d_log_trend",
            "horizon_hours": max(1, horizon_hours),
            "points": forecast,
            "expected_change_pct": forecast_change,
            "confidence": "low" if data_quality == "poor" or not forecast or forecast_diagnostics.get("dampening") else "medium",
            "diagnostics": forecast_diagnostics,
            "notes": [
                "Forecast blends recent linear trend with 24h, 72h, and 7d changes from saved asking-price snapshots.",
                "Countertrend moves are dampened when daily and weekly windows disagree.",
                "Volume is a demand/activity proxy, not exact completed trade count.",
            ],
        },
        "request": {
            "task": "interpret_currency_trend_and_forecast",
            "risk_profile": "conservative",
            "language": "ru",
            "max_candidates": 1,
        },
        "external_context": {
            "patch_notes": [],
            "hotfixes": [],
            "popular_builds": [],
            "news": [],
            "known_risks": [],
        },
        "snapshot_meta": {
            "cached": bool(snapshot.get("cached")),
            "errors": snapshot.get("errors") or [],
        },
    }


async def load_currency_trend_context(
    *,
    league: str,
    currency_id: str,
    target: str = "exalted",
    status: str = "any",
    league_day: int | None = None,
    history_limit: int = 1500,
    horizon_hours: int = 24,
    forecast_points: int = 12,
    refresh: bool = False,
) -> dict[str, Any]:
    snapshot = None
    if refresh:
        snapshot = await get_category_rates(
            league=league,
            category="Currency",
            target=target,
            status=status,
            force_refresh=True,
        )
    else:
        snapshot = read_latest_rates(league=league, category="Currency", target=target, status=status)
    history = read_item_history(
        league=league,
        category="Currency",
        target=target,
        status=status,
        item_id=currency_id,
        metric="price",
        limit=history_limit,
    )
    return build_currency_trend_context(
        snapshot,
        history,
        league=league,
        currency_id=currency_id,
        target=target,
        status=status,
        league_day=league_day,
        horizon_hours=horizon_hours,
        forecast_points=forecast_points,
    )
