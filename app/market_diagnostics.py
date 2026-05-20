from __future__ import annotations

import math
from collections import Counter
from statistics import mean
from time import time
from typing import Any

from app.profitability import execution_quality, row_price

FRESH_SNAPSHOT_SECONDS = 20 * 60
AGING_SNAPSHOT_SECONDS = 2 * 60 * 60
DEFAULT_SIGNAL_CHANGE_PCT = 8.0
DEFAULT_SIGNAL_MIN_VOLUME = 10.0


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _positive_number(value: Any) -> float | None:
    result = _number(value)
    return result if result is not None and result > 0 else None


def _snapshot_ts(snapshot: dict[str, Any] | None) -> float | None:
    result = _positive_number((snapshot or {}).get("created_ts"))
    return result


def _snapshot_rows(snapshot: dict[str, Any] | None) -> list[dict[str, Any]]:
    rows = (snapshot or {}).get("rows") or []
    return [row for row in rows if isinstance(row, dict)]


def _snapshot_freshness(age_seconds: float | None) -> str:
    if age_seconds is None:
        return "missing"
    if age_seconds <= FRESH_SNAPSHOT_SECONDS:
        return "fresh"
    if age_seconds <= AGING_SNAPSHOT_SECONDS:
        return "aging"
    return "stale"


def build_market_health(
    snapshot: dict[str, Any] | None,
    *,
    expected_items: int = 0,
    now_ts: float | None = None,
) -> dict[str, Any]:
    created_ts = _snapshot_ts(snapshot)
    now_value = time() if now_ts is None else now_ts
    age_seconds = max(0.0, now_value - created_ts) if created_ts else None
    rows = _snapshot_rows(snapshot)
    priced_rows = [row for row in rows if row_price(row) is not None]
    expected = max(int(expected_items or 0), len(rows))
    coverage_pct = (len(priced_rows) / expected * 100) if expected else 0.0

    executions = [execution_quality(row, snapshot_ts=created_ts) for row in priced_rows]
    executable = [item for item in executions if item.get("executable")]
    risk_flags = Counter(flag for item in executions for flag in item.get("risk_flags") or [])
    freshness = _snapshot_freshness(age_seconds)
    errors = (snapshot or {}).get("errors") or []

    warnings: list[str] = []
    if freshness in {"missing", "stale"}:
        warnings.append("stale_snapshot")
    if expected and coverage_pct < 40:
        warnings.append("low_coverage")
    if errors:
        warnings.append("source_errors")
    if len(priced_rows) and len(executable) / len(priced_rows) < 0.35:
        warnings.append("many_risky_rows")

    if not priced_rows or freshness == "missing":
        data_quality = "poor"
    elif freshness == "stale" or coverage_pct < 40:
        data_quality = "partial"
    elif errors or coverage_pct < 70:
        data_quality = "partial"
    else:
        data_quality = "good"

    return {
        "created_ts": created_ts,
        "age_seconds": age_seconds,
        "freshness": freshness,
        "data_quality": data_quality,
        "source": (snapshot or {}).get("source") or "",
        "rows": len(rows),
        "priced": len(priced_rows),
        "expected": expected,
        "coverage_pct": round(coverage_pct, 2),
        "executable": len(executable),
        "risky": max(0, len(priced_rows) - len(executable)),
        "errors": len(errors),
        "risk_flags": dict(risk_flags.most_common()),
        "warnings": warnings,
    }


def _sorted_history(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    snapshots = [snapshot for snapshot in history if _snapshot_ts(snapshot)]
    return sorted(snapshots, key=lambda item: float(item.get("created_ts") or 0))


def _rows_by_id(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(row.get("id")): row for row in _snapshot_rows(snapshot) if row.get("id")}


def _future_snapshot(history: list[dict[str, Any]], index: int, horizon_seconds: float) -> dict[str, Any] | None:
    current_ts = float(history[index].get("created_ts") or 0)
    target_ts = current_ts + horizon_seconds
    for candidate in history[index + 1 :]:
        if float(candidate.get("created_ts") or 0) >= target_ts:
            return candidate
    return None


def _signal_candidates(
    snapshot: dict[str, Any],
    *,
    min_change_pct: float,
    min_volume: float,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for row in _snapshot_rows(snapshot):
        price = row_price(row)
        change = _number(row.get("change"))
        volume = _number(row.get("volume")) or 0.0
        item_id = row.get("id")
        if not item_id or price is None or change is None:
            continue
        if volume < min_volume or abs(change) < min_change_pct:
            continue
        action = "buy_dip" if change < 0 else "sell_momentum"
        candidates.append(
            {
                "item_id": str(item_id),
                "item_name": row.get("text") or row.get("name") or row.get("id"),
                "action": action,
                "price": price,
                "change_pct": change,
                "volume": volume,
            }
        )
    return candidates


def backtest_signal_history(
    history: list[dict[str, Any]],
    *,
    horizon_hours: float = 24.0,
    min_change_pct: float = DEFAULT_SIGNAL_CHANGE_PCT,
    min_volume: float = DEFAULT_SIGNAL_MIN_VOLUME,
    sample_limit: int = 8,
) -> dict[str, Any]:
    snapshots = _sorted_history(history)
    horizon_seconds = max(1.0, horizon_hours) * 3600
    evaluated: list[dict[str, Any]] = []
    pending = 0
    raw_candidates = 0

    for index, snapshot in enumerate(snapshots):
        future = _future_snapshot(snapshots, index, horizon_seconds)
        candidates = _signal_candidates(snapshot, min_change_pct=min_change_pct, min_volume=min_volume)
        raw_candidates += len(candidates)
        if not future:
            pending += len(candidates)
            continue
        future_rows = _rows_by_id(future)
        for candidate in candidates:
            future_price = row_price(future_rows.get(candidate["item_id"]))
            if future_price is None:
                continue
            current_price = candidate["price"]
            future_return_pct = ((future_price - current_price) / current_price) * 100
            outcome_pct = future_return_pct if candidate["action"] == "buy_dip" else -future_return_pct
            evaluated.append(
                {
                    **candidate,
                    "snapshot_ts": snapshot.get("created_ts"),
                    "future_ts": future.get("created_ts"),
                    "future_price": future_price,
                    "future_return_pct": round(future_return_pct, 2),
                    "outcome_pct": round(outcome_pct, 2),
                    "success": outcome_pct > 0,
                }
            )

    action_counts = Counter(item["action"] for item in evaluated)
    successes = [item for item in evaluated if item["success"]]
    return {
        "horizon_hours": horizon_hours,
        "history_points": len(snapshots),
        "raw_candidates": raw_candidates,
        "evaluated": len(evaluated),
        "successful": len(successes),
        "failed": max(0, len(evaluated) - len(successes)),
        "pending": pending,
        "success_rate": round(len(successes) / len(evaluated) * 100, 2) if evaluated else None,
        "average_outcome_pct": round(mean(item["outcome_pct"] for item in evaluated), 2) if evaluated else None,
        "by_action": dict(action_counts),
        "samples": sorted(evaluated, key=lambda item: abs(item["outcome_pct"]), reverse=True)[:sample_limit],
    }


def build_market_diagnostics(
    snapshot: dict[str, Any] | None,
    history: list[dict[str, Any]],
    *,
    expected_items: int = 0,
    horizon_hours: float = 24.0,
    now_ts: float | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": "poe2-market-diagnostics/v1",
        "stored": bool(snapshot),
        "league": (snapshot or {}).get("league"),
        "category": (snapshot or {}).get("category"),
        "target": (snapshot or {}).get("target"),
        "status": (snapshot or {}).get("status"),
        "health": build_market_health(snapshot, expected_items=expected_items, now_ts=now_ts),
        "backtest": backtest_signal_history(history, horizon_hours=horizon_hours),
    }
