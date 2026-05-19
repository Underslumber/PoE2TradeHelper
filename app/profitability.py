from __future__ import annotations

import math
import time
from typing import Any


LOW_VOLUME = 10.0
MEDIUM_VOLUME = 50.0
MIN_OFFERS = 3
WIDE_SPREAD = 0.18
STALE_SNAPSHOT_SECONDS = 60 * 60


def number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result > 0 else None


def _finite_number(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _bounded_ratio(value: float, full_score_at: float) -> float:
    if full_score_at <= 0:
        return 0.0
    return max(0.0, min(1.0, value / full_score_at)) * 100


def _bounded_log_score(value: float, full_score_at: float) -> float:
    if value <= 0 or full_score_at <= 0:
        return 0.0
    return max(0.0, min(1.0, math.log1p(value) / math.log1p(full_score_at))) * 100


def row_price(row: dict[str, Any] | None) -> float | None:
    if not row:
        return None
    return number(row.get("median")) or number(row.get("best"))


def row_spread(row: dict[str, Any] | None) -> float | None:
    if not row:
        return None
    best = number(row.get("best"))
    median = number(row.get("median"))
    if not best or not median:
        return None
    base = max(best, median)
    return abs(median - best) / base if base else None


def row_risk_flags(row: dict[str, Any] | None, *, snapshot_ts: float | None = None, now_ts: float | None = None) -> list[str]:
    flags: list[str] = []
    if not row or row_price(row) is None:
        flags.append("missing_price")
        return flags

    volume = number(row.get("volume"))
    if volume is None:
        flags.append("missing_volume")
    elif volume < LOW_VOLUME:
        flags.append("low_volume")

    offers = number(row.get("offers"))
    if offers is None and volume is None:
        flags.append("missing_listing_count")
    elif offers is not None and offers < MIN_OFFERS and (volume or 0) < LOW_VOLUME:
        flags.append("thin_listings")

    spread = row_spread(row)
    if spread is not None and spread >= WIDE_SPREAD:
        flags.append("wide_spread")

    try:
        change = abs(float(row.get("change")))
    except (TypeError, ValueError):
        change = None
    if change is not None and change >= 25 and (volume or 0) < LOW_VOLUME:
        flags.append("large_move_low_volume")
    if change is not None and change >= 40 and offers is not None and offers < MIN_OFFERS:
        flags.append("price_fixing_risk")

    if row.get("sparkline") and row.get("sparkline_kind") != "price":
        flags.append("sparkline_not_price")

    if snapshot_ts:
        now = time.time() if now_ts is None else now_ts
        if now - float(snapshot_ts) > STALE_SNAPSHOT_SECONDS:
            flags.append("stale_snapshot")
    return flags


def execution_quality(row: dict[str, Any] | None, *, snapshot_ts: float | None = None) -> dict[str, Any]:
    flags = row_risk_flags(row, snapshot_ts=snapshot_ts)
    blockers = {"missing_price", "missing_volume", "thin_listings", "price_fixing_risk", "stale_snapshot"}
    warnings = {"low_volume", "wide_spread", "large_move_low_volume", "sparkline_not_price"}
    volume = number((row or {}).get("volume")) or 0
    offers = number((row or {}).get("offers")) or 0
    score = 100
    score -= 24 * len([flag for flag in flags if flag in blockers])
    score -= 10 * len([flag for flag in flags if flag in warnings])
    if volume >= MEDIUM_VOLUME:
        score += 10
    if offers >= 8:
        score += 8
    score = max(0, min(100, score))
    if score >= 75:
        quality = "good"
    elif score >= 45:
        quality = "partial"
    else:
        quality = "poor"
    return {
        "quality": quality,
        "score": score,
        "risk_flags": flags,
        "volume": volume,
        "offers": offers,
        "spread": row_spread(row),
        "executable": quality != "poor" and "price_fixing_risk" not in flags,
    }


def combined_execution_quality(*rows: dict[str, Any] | None, snapshot_ts: float | None = None) -> dict[str, Any]:
    qualities = [execution_quality(row, snapshot_ts=snapshot_ts) for row in rows if row]
    if not qualities:
        return execution_quality(None, snapshot_ts=snapshot_ts)
    score = min(item["score"] for item in qualities)
    flags = sorted({flag for item in qualities for flag in item["risk_flags"]})
    if score >= 75:
        quality = "good"
    elif score >= 45:
        quality = "partial"
    else:
        quality = "poor"
    return {
        "quality": quality,
        "score": score,
        "risk_flags": flags,
        "volume": min(item["volume"] for item in qualities),
        "offers": min(item["offers"] for item in qualities),
        "spread": max((item["spread"] or 0) for item in qualities),
        "executable": all(item["executable"] for item in qualities),
    }


def executable_severity(base_severity: str, execution: dict[str, Any]) -> str:
    if not execution.get("executable"):
        return "watch"
    if base_severity == "signal" and execution.get("quality") == "partial":
        return "weak"
    return base_severity


def opportunity_rank_score(item: dict[str, Any]) -> float:
    profit = max(0.0, _finite_number(item.get("profit")))
    margin = max(0.0, _finite_number(item.get("margin")))
    try:
        path_steps = max(1, int(item.get("path_steps") or 1))
    except (TypeError, ValueError):
        path_steps = 1

    execution = item.get("execution") if isinstance(item.get("execution"), dict) else {}
    execution_score = max(0.0, min(100.0, _finite_number(execution.get("score"), 50.0)))
    volume = max(_finite_number(item.get("min_volume")), _finite_number(execution.get("volume")))
    risk_flags = list(item.get("risk_flags") or execution.get("risk_flags") or [])

    margin_score = _bounded_ratio(margin, 0.25)
    profit_score = _bounded_log_score(profit, 100.0)
    liquidity_score = _bounded_log_score(volume, 100.0)
    efficiency_score = _bounded_ratio(margin / path_steps, 0.10)
    risk_penalty = min(30.0, len(risk_flags) * 6.0)
    if not execution.get("executable", True):
        risk_penalty += 25.0
    if item.get("low_volume"):
        risk_penalty += 10.0
    if profit <= 0:
        risk_penalty += 50.0

    score = (
        margin_score * 0.32
        + profit_score * 0.18
        + liquidity_score * 0.22
        + execution_score * 0.22
        + efficiency_score * 0.06
        - risk_penalty
    )
    return round(max(0.0, score), 4)


def opportunity_sort_key(item: dict[str, Any]) -> tuple[float, float, float, float, int]:
    execution = item.get("execution") if isinstance(item.get("execution"), dict) else {}
    volume = max(_finite_number(item.get("min_volume")), _finite_number(execution.get("volume")))
    try:
        path_steps = max(1, int(item.get("path_steps") or 1))
    except (TypeError, ValueError):
        path_steps = 1
    return (
        -opportunity_rank_score(item),
        -max(0.0, _finite_number(item.get("margin"))),
        -max(0.0, _finite_number(item.get("profit"))),
        -volume,
        path_steps,
    )


def rank_opportunities(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ranked = [dict(item, rank_score=opportunity_rank_score(item)) for item in items]
    return sorted(ranked, key=opportunity_sort_key)


def enrich_trade_advice(
    advice: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    *,
    snapshot_ts: float | None = None,
) -> list[dict[str, Any]]:
    by_id = {row.get("id"): row for row in rows}
    enriched: list[dict[str, Any]] = []
    for item in advice:
        if item.get("kind") == "emotion_path":
            source_row = by_id.get(item.get("source"))
            result_row = by_id.get(item.get("result"))
            execution = combined_execution_quality(source_row, result_row, snapshot_ts=snapshot_ts)
            updated = dict(item)
            updated["execution"] = execution
            updated["severity"] = executable_severity(str(item.get("severity") or "watch"), execution)
            updated["executable"] = bool(execution.get("executable"))
            updated["risk_flags"] = execution.get("risk_flags") or []
            enriched.append(updated)
        else:
            enriched.append(item)
    return enriched


def build_profitability_snapshot(snapshot: dict[str, Any], *, top: int = 12) -> dict[str, Any]:
    rows = list(snapshot.get("rows") or [])
    target = snapshot.get("target") or ""
    created_ts = snapshot.get("created_ts")
    candidates = []
    for row in rows:
        price = row_price(row)
        if price is None:
            continue
        execution = execution_quality(row, snapshot_ts=created_ts)
        candidates.append(
            {
                "id": row.get("id"),
                "name": row.get("text") or row.get("name") or row.get("id"),
                "name_ru": row.get("text_ru") or row.get("text") or row.get("id"),
                "target": target,
                "price": price,
                "change": row.get("change"),
                "volume": execution["volume"],
                "offers": execution["offers"],
                "spread": execution["spread"],
                "execution": execution,
            }
        )
    executable = [item for item in candidates if item["execution"]["executable"]]
    risky = [item for item in candidates if not item["execution"]["executable"]]
    executable.sort(key=lambda item: (item["execution"]["score"], item["volume"]), reverse=True)
    risky.sort(key=lambda item: (len(item["execution"]["risk_flags"]), -item["execution"]["score"]), reverse=True)
    return {
        "schema_version": "poe2-profitability/v1",
        "league": snapshot.get("league"),
        "category": snapshot.get("category"),
        "target": target,
        "created_ts": created_ts,
        "summary": {
            "rows": len(rows),
            "priced": len(candidates),
            "executable": len(executable),
            "risky": len(risky),
        },
        "executable_candidates": executable[:top],
        "risky_candidates": risky[:top],
        "notes": [
            "Execution quality is a conservative filter over asking-price snapshots.",
            "Volume is an activity proxy, not confirmed completed trades.",
        ],
    }
