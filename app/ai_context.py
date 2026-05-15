from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.trade2 import build_trade_advice, get_category_rates, read_latest_rates

CONTEXT_SCHEMA_VERSION = "poe2-market-ai-context/v1"


def now_iso_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def league_phase(league_day: int | None) -> str:
    if league_day is None or league_day < 0:
        return "unknown"
    if league_day <= 1:
        return "day_0_1"
    if league_day <= 7:
        return "day_2_7"
    if league_day <= 21:
        return "day_8_21"
    return "late_league"


def ts_to_iso(value: Any) -> str | None:
    try:
        timestamp = float(value)
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()


def positive_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def risk_flags_for_row(row: dict[str, Any]) -> list[str]:
    flags = []
    if positive_number(row.get("best")) is None and positive_number(row.get("median")) is None:
        flags.append("missing_price")
    volume = positive_number(row.get("volume"))
    if volume is None:
        flags.append("missing_volume")
    elif volume < 10:
        flags.append("low_volume")
    offers = positive_number(row.get("offers"))
    if offers is None:
        flags.append("missing_listing_count")
    elif offers < 3:
        flags.append("thin_listings")
    if row.get("change") is not None and volume is not None:
        try:
            if abs(float(row.get("change"))) >= 25 and volume < 10:
                flags.append("large_move_low_volume")
        except (TypeError, ValueError):
            pass
    if row.get("sparkline") and row.get("sparkline_kind") != "price":
        flags.append("sparkline_not_price")
    return flags


def market_row_payload(row: dict[str, Any], snapshot: dict[str, Any], snapshot_iso: str | None) -> dict[str, Any]:
    sparkline_is_price = row.get("sparkline_kind") == "price"
    return {
        "id": row.get("id") or "",
        "name_en": row.get("text") or row.get("name") or row.get("id") or "",
        "name_ru": row.get("text_ru") or row.get("text") or row.get("name") or row.get("id") or "",
        "category": snapshot.get("category") or "",
        "source": snapshot.get("source") or "",
        "target": snapshot.get("target") or "",
        "best": row.get("best"),
        "median": row.get("median"),
        "offers": row.get("offers"),
        "volume": row.get("volume"),
        "change_7d_percent": row.get("change"),
        "sparkline_kind": row.get("sparkline_kind") if sparkline_is_price else None,
        "sparkline": row.get("sparkline") if sparkline_is_price else [],
        "snapshot_ts": snapshot_iso,
        "listing_count": row.get("offers"),
        "risk_flags": risk_flags_for_row(row),
    }


def category_summary(snapshot: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    priced = [row for row in rows if positive_number(row.get("best")) or positive_number(row.get("median"))]
    high_liquidity = [row for row in rows if (positive_number(row.get("volume")) or 0) >= 50]
    medium_liquidity = [row for row in rows if 10 <= (positive_number(row.get("volume")) or 0) < 50]
    low_liquidity = [row for row in rows if 0 < (positive_number(row.get("volume")) or 0) < 10]
    strong_movers = []
    for row in rows:
        try:
            if abs(float(row.get("change"))) >= 25:
                strong_movers.append(row)
        except (TypeError, ValueError):
            continue
    top_volume = sorted(rows, key=lambda item: positive_number(item.get("volume")) or 0, reverse=True)[:5]
    return {
        "category": snapshot.get("category") or "",
        "source": snapshot.get("source") or "",
        "target": snapshot.get("target") or "",
        "rows_count": len(rows),
        "priced_count": len(priced),
        "high_liquidity_count": len(high_liquidity),
        "medium_liquidity_count": len(medium_liquidity),
        "low_liquidity_count": len(low_liquidity),
        "strong_movers_count": len(strong_movers),
        "top_volume_items": [
            {
                "id": row.get("id") or "",
                "name_ru": row.get("text_ru") or row.get("text") or row.get("id") or "",
                "volume": row.get("volume") or 0,
            }
            for row in top_volume
        ],
        "notes": [],
    }


def chain_opportunity_payload(advice: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": advice.get("kind") or "trade_advice",
        "source_id": advice.get("source"),
        "source_name_ru": advice.get("source_name_ru"),
        "result_id": advice.get("result"),
        "result_name_ru": advice.get("result_name_ru"),
        "input_count": advice.get("input_count"),
        "path_steps": advice.get("path_steps"),
        "target": snapshot.get("target") or "",
        "source_value": advice.get("source_value"),
        "result_value": advice.get("result_value"),
        "craft_cost": advice.get("craft_cost"),
        "profit": advice.get("profit"),
        "margin": advice.get("margin"),
        "source_volume": advice.get("source_volume"),
        "result_volume": advice.get("result_volume"),
        "min_volume": advice.get("min_volume"),
        "risk": "medium" if advice.get("low_volume") else "low",
        "source": snapshot.get("source") or "",
        "snapshot_ts": ts_to_iso(snapshot.get("created_ts")),
    }


def build_ai_market_context(
    snapshot: dict[str, Any] | None,
    *,
    league: str,
    category: str,
    target: str = "exalted",
    status: str = "any",
    league_day: int | None = None,
    limit: int = 80,
) -> dict[str, Any]:
    snapshot = snapshot or {
        "league": league,
        "category": category,
        "target": target,
        "status": status,
        "rows": [],
        "source": "",
        "errors": [],
    }
    rows = list(snapshot.get("rows") or [])[:limit]
    snapshot_iso = ts_to_iso(snapshot.get("created_ts"))
    advice = snapshot.get("advice")
    if advice is None:
        advice = build_trade_advice(category, rows, target)
    return {
        "schema_version": CONTEXT_SCHEMA_VERSION,
        "generated_at": now_iso_utc(),
        "league": {
            "id": snapshot.get("league") or league,
            "day": league_day,
            "phase": league_phase(league_day),
            "status": "fresh_economy" if league_day is not None and league_day <= 21 else "unknown",
            "notes": [],
        },
        "sources": {
            "trade2": {
                "enabled": True,
                "checked_at": snapshot_iso,
                "notes": "Public trade2 listings/exchange are asking prices, not guaranteed executed trades.",
            },
            "poe_ninja": {
                "enabled": True,
                "checked_at": snapshot_iso,
                "notes": "PoE2 Currency Exchange overview for supported stackable categories.",
            },
        },
        "benchmarks": {
            "target_currency": snapshot.get("target") or target,
            "available": ["chaos", "exalted", "divine"],
            "basket": {
                "enabled": False,
                "notes": "Composite benchmark is not implemented yet.",
            },
        },
        "market_rows": [market_row_payload(row, snapshot, snapshot_iso) for row in rows],
        "category_summaries": [category_summary(snapshot, rows)] if rows else [],
        "chain_opportunities": [
            chain_opportunity_payload(item, snapshot)
            for item in advice[:limit]
            if item.get("kind") == "emotion_path"
        ],
        "seller_lot_checks": [],
        "external_context": {
            "patch_notes": [],
            "hotfixes": [],
            "popular_builds": [],
            "streamer_mentions": [],
            "news": [],
            "known_risks": [],
        },
        "request": {
            "task": "find_watchlist_and_trade_candidates",
            "risk_profile": "conservative",
            "max_candidates": 10,
            "language": "ru",
        },
        "snapshot_meta": {
            "status": snapshot.get("status") or status,
            "cached": bool(snapshot.get("cached")),
            "source": snapshot.get("source") or "",
            "errors": snapshot.get("errors") or [],
        },
    }


async def load_ai_market_context(
    *,
    league: str,
    category: str,
    target: str = "exalted",
    status: str = "any",
    league_day: int | None = None,
    limit: int = 80,
    refresh: bool = False,
) -> dict[str, Any]:
    snapshot = None
    if refresh:
        snapshot = await get_category_rates(
            league=league,
            category=category,
            target=target,
            status=status,
            force_refresh=True,
        )
    else:
        snapshot = read_latest_rates(league=league, category=category, target=target, status=status)
    return build_ai_market_context(
        snapshot,
        league=league,
        category=category,
        target=target,
        status=status,
        league_day=league_day,
        limit=limit,
    )
