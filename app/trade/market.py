import asyncio
import time
from typing import Any, Dict, List, Optional, Tuple

from app.config import DEFAULT_RATE_LIMIT_DELAY
from app.trade.api_client import PoeTradeClient
from app.trade.cache import SQLiteCacheManager
from app.trade.history import log_market_history
from app.trade.logic import (
    POE_NINJA_CATEGORY_TYPES,
    build_trade_advice,
    chunked,
    clean_trade_text,
    normalize_exchange_result,
    normalize_poe_ninja_overview,
    normalize_static_entries,
)
from app.trade.math_utils import rate_stats

RATE_CACHE_TTL = 300

async def get_trade_static() -> Dict[str, List[Dict[str, Optional[str]]]]:
    response, ru_response = await PoeTradeClient.get_trade_static()
    return normalize_static_entries(response, ru_response)


async def get_category_rates(
    league: str,
    category: str,
    target: str = "divine",
    status: str = "any",
    force_refresh: bool = False,
) -> Dict[str, Any]:
    cache_key = SQLiteCacheManager.get_dict_key("rate", league, category, target, status)
    if not force_refresh:
        cached = SQLiteCacheManager.get(cache_key)
        if cached:
            cached["cached"] = True
            return cached

    categories = await get_trade_static()
    entries = categories.get(category, [])
    query_ids = []
    errors = []
    source = "trade2"

    poe_ninja_rates = None
    try:
        category_type = POE_NINJA_CATEGORY_TYPES.get(category)
        if category_type:
            poe_ninja_payload = await PoeTradeClient.get_poe_ninja_rates(league, category_type)
            if poe_ninja_payload:
                normalized = normalize_poe_ninja_overview(poe_ninja_payload, target)
                if normalized.get("target_supported"):
                    poe_ninja_rates = normalized
    except Exception as exc:
        errors.append({"source": "poe.ninja", "error": str(exc)})

    if poe_ninja_rates:
        source = "poe.ninja"
        rate_by_id = {row["id"]: row for row in poe_ninja_rates.get("rows", []) if row.get("id")}
    else:
        ids = [entry["id"] for entry in entries if entry.get("id") and entry.get("id") != target]
        all_rows: List[Dict[str, Any]] = []
        for chunk in chunked(ids, 5):
            try:
                payload = await PoeTradeClient.post_exchange(league, chunk, [target], status=status)
                query_ids.append(payload.get("id"))
                all_rows.extend(normalize_exchange_result(payload, limit=250).get("rows", []))
            except Exception as exc:
                errors.append({"items": chunk, "error": str(exc)})
            await asyncio.sleep(DEFAULT_RATE_LIMIT_DELAY)
        rate_by_id = {entry["id"]: rate_stats(all_rows, str(entry["id"])) for entry in entries}

    rows = []
    for entry in entries:
        item_id = str(entry["id"])
        stats = rate_by_id.get(item_id, {})
        rows.append(
            {
                "id": item_id,
                "text": str(entry["text"]),
                "text_ru": str(entry.get("text_ru") or entry["text"]),
                "image": entry.get("image"),
                "best": stats.get("best"),
                "median": stats.get("median"),
                "offers": stats.get("offers", 0),
                "volume": stats.get("volume", 0),
                "change": stats.get("change"),
                "sparkline": stats.get("sparkline", []),
                "sparkline_kind": stats.get("sparkline_kind"),
                "max_volume_currency": stats.get("max_volume_currency"),
                "max_volume_rate": stats.get("max_volume_rate"),
            }
        )

    created_ts = time.time()
    snapshot = {
        "created_ts": created_ts,
        "league": league,
        "category": category,
        "target": target,
        "status": status,
        "query_ids": [q for q in query_ids if q],
        "source": source,
        "rows": rows,
        "errors": errors,
    }

    result = {
        "created_ts": created_ts,
        "league": league,
        "category": category,
        "target": target,
        "status": status,
        "rows": rows,
        "advice": build_trade_advice(category, rows, target),
        "errors": errors,
        "source": source,
        "cached": False,
    }

    log_market_history(snapshot)
    SQLiteCacheManager.set(cache_key, result, RATE_CACHE_TTL)
    return result

def static_entry_lookup(
    categories: Dict[str, List[Dict[str, Optional[str]]]],
) -> Dict[str, Tuple[str, Dict[str, Optional[str]]]]:
    lookup: Dict[str, Tuple[str, Dict[str, Optional[str]]]] = {}
    for category, entries in categories.items():
        if category not in POE_NINJA_CATEGORY_TYPES:
            continue
        for entry in entries:
            for value in (entry.get("id"), entry.get("text"), entry.get("text_ru")):
                key = clean_trade_text(value).lower()
                key = " ".join(key.replace("-", " ").replace("_", " ").split())
                if key:
                    lookup[key] = (category, entry)
    return lookup
