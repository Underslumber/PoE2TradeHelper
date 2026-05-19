from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any

from app.config import DEFAULT_RATE_LIMIT_DELAY
from app.trade.cache import SQLiteCacheManager
from app.trade2 import get_exchange_offers_many

DEFAULT_CYCLE_FEE_PCT = 0.003
DEFAULT_CYCLE_MIN_MARGIN = 0.001
DEFAULT_CYCLE_MIN_VOLUME = 1.0
DEFAULT_CYCLE_LIMIT = 30
DEFAULT_PAIR_TIMEOUT_SECONDS = 6.0
MAX_CYCLE_STEPS = 5

ExchangeFetcher = Callable[..., Awaitable[dict[str, Any]]]


def _positive_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _clean_currency_id(value: Any) -> str:
    return str(value or "").strip().lower()


def normalize_cycle_targets(base: str, targets: list[str] | tuple[str, ...] | None) -> list[str]:
    ordered: list[str] = []
    for value in [base, *(targets or [])]:
        currency_id = _clean_currency_id(value)
        if currency_id and currency_id not in ordered:
            ordered.append(currency_id)
    return ordered


def _edge_from_row(row: dict[str, Any], have: str, want: str, fee_pct: float) -> dict[str, Any] | None:
    ratio = _positive_float(row.get("ratio"))
    if ratio is None:
        return None
    stock = _positive_float(row.get("stock"))
    have_amount = _positive_float(row.get("have_amount"))
    want_amount = _positive_float(row.get("want_amount"))
    available_to = stock or want_amount or 0.0
    available_from = available_to / ratio if available_to and ratio else have_amount or 0.0
    fee_multiplier = max(0.0, 1.0 - max(0.0, fee_pct))
    return {
        "from": have,
        "to": want,
        "rate": ratio,
        "raw_rate": ratio,
        "effective_rate": ratio * fee_multiplier,
        "fee_pct": max(0.0, fee_pct),
        "available_from": available_from,
        "available_to": available_to,
        "min_trade_from": have_amount,
        "min_trade_to": want_amount,
        "stock": stock,
        "seller": row.get("seller") or "",
        "indexed": row.get("indexed") or "",
    }


def best_exchange_edge(
    payload: dict[str, Any],
    *,
    have: str,
    want: str,
    fee_pct: float = DEFAULT_CYCLE_FEE_PCT,
    min_volume: float = DEFAULT_CYCLE_MIN_VOLUME,
) -> dict[str, Any] | None:
    candidates: list[dict[str, Any]] = []
    for row in payload.get("rows") or []:
        row_have = _clean_currency_id(row.get("have_currency"))
        row_want = _clean_currency_id(row.get("want_currency"))
        if row_have != have or row_want != want:
            continue
        edge = _edge_from_row(row, have, want, fee_pct)
        if edge:
            candidates.append(edge)
    if not candidates:
        return None

    liquid = [edge for edge in candidates if (edge.get("available_from") or 0) >= min_volume]
    selected = max(liquid or candidates, key=lambda edge: edge["effective_rate"])
    selected["offer_count"] = len(candidates)
    selected["total"] = payload.get("total") or len(candidates)
    selected["low_volume"] = (selected.get("available_from") or 0) < min_volume
    return selected


def find_currency_cycles_from_edges(
    edges: list[dict[str, Any]],
    *,
    base: str,
    max_steps: int = MAX_CYCLE_STEPS,
    min_margin: float = DEFAULT_CYCLE_MIN_MARGIN,
    limit: int = DEFAULT_CYCLE_LIMIT,
) -> list[dict[str, Any]]:
    base = _clean_currency_id(base)
    max_steps = max(2, min(MAX_CYCLE_STEPS, int(max_steps or MAX_CYCLE_STEPS)))
    min_margin = max(0.0, float(min_margin or 0.0))
    graph: dict[str, list[dict[str, Any]]] = {}
    for edge in edges:
        source = _clean_currency_id(edge.get("from"))
        target = _clean_currency_id(edge.get("to"))
        rate = _positive_float(edge.get("effective_rate"))
        if not source or not target or source == target or rate is None:
            continue
        normalized = dict(edge)
        normalized["from"] = source
        normalized["to"] = target
        normalized["effective_rate"] = rate
        graph.setdefault(source, []).append(normalized)

    for outgoing in graph.values():
        outgoing.sort(key=lambda edge: edge["effective_rate"], reverse=True)

    cycles: list[dict[str, Any]] = []
    seen_routes: set[tuple[str, ...]] = set()

    def walk(current: str, amount: float, route: list[str], steps: list[dict[str, Any]], visited: set[str]) -> None:
        if len(steps) >= max_steps:
            return
        for edge in graph.get(current, []):
            next_currency = edge["to"]
            next_amount = amount * edge["effective_rate"]
            next_steps = [*steps, edge]
            if next_currency == base:
                if len(next_steps) < 2:
                    continue
                full_route = [*route, base]
                route_key = tuple(full_route)
                if route_key in seen_routes:
                    continue
                margin = next_amount - 1.0
                if margin < min_margin:
                    continue
                seen_routes.add(route_key)
                step_count = len(next_steps)
                min_liquidity = min((float(step.get("available_from") or 0) for step in next_steps), default=0.0)
                cycles.append(
                    {
                        "route": full_route,
                        "steps": next_steps,
                        "step_count": step_count,
                        "start_amount": 1.0,
                        "finish_amount": next_amount,
                        "profit": next_amount - 1.0,
                        "margin": margin,
                        "rank_score": margin / (step_count**0.75),
                        "min_volume": min_liquidity,
                        "profitable": True,
                        "severity": "signal" if margin >= 0.02 else "weak",
                    }
                )
                continue
            if next_currency in visited:
                continue
            walk(next_currency, next_amount, [*route, next_currency], next_steps, {*visited, next_currency})

    if base:
        walk(base, 1.0, [base], [], {base})

    cycles.sort(key=lambda item: (item["rank_score"], item["margin"], -item["step_count"]), reverse=True)
    return cycles[: max(1, limit)]


async def fetch_currency_cycle_edges(
    *,
    league: str,
    targets: list[str],
    status: str = "online",
    fee_pct: float = DEFAULT_CYCLE_FEE_PCT,
    min_volume: float = DEFAULT_CYCLE_MIN_VOLUME,
    pair_timeout_seconds: float = DEFAULT_PAIR_TIMEOUT_SECONDS,
    fetcher: ExchangeFetcher = get_exchange_offers_many,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    edges: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    pair_count = 0
    for have in targets:
        wants = [want for want in targets if want != have]
        pair_count += len(wants)
        if not wants:
            continue
        try:
            payload = await asyncio.wait_for(
                fetcher(league=league, have=have, want=wants, status=status),
                timeout=max(1.0, pair_timeout_seconds),
            )
            for want in wants:
                edge = best_exchange_edge(payload, have=have, want=want, fee_pct=fee_pct, min_volume=min_volume)
                if edge:
                    edges.append(edge)
        except TimeoutError:
            for want in wants:
                errors.append({"have": have, "want": want, "error": "exchange pair timeout"})
        except Exception as exc:  # pragma: no cover - defensive around live API failures
            for want in wants:
                errors.append({"have": have, "want": want, "error": str(exc)})
        if DEFAULT_RATE_LIMIT_DELAY > 0:
            await asyncio.sleep(DEFAULT_RATE_LIMIT_DELAY)
    return edges, errors, pair_count


async def load_currency_cycles(
    *,
    league: str,
    base: str = "exalted",
    targets: list[str] | None = None,
    status: str = "online",
    max_steps: int = MAX_CYCLE_STEPS,
    min_margin: float = DEFAULT_CYCLE_MIN_MARGIN,
    fee_pct: float = DEFAULT_CYCLE_FEE_PCT,
    min_volume: float = DEFAULT_CYCLE_MIN_VOLUME,
    limit: int = DEFAULT_CYCLE_LIMIT,
    pair_timeout_seconds: float = DEFAULT_PAIR_TIMEOUT_SECONDS,
    fetcher: ExchangeFetcher = get_exchange_offers_many,
    use_cache: bool = True,
) -> dict[str, Any]:
    normalized_targets = normalize_cycle_targets(base, targets)
    max_steps = max(2, min(MAX_CYCLE_STEPS, int(max_steps or MAX_CYCLE_STEPS)))
    min_margin = max(0.0, float(min_margin or 0.0))
    fee_pct = max(0.0, float(fee_pct or 0.0))
    min_volume = max(0.0, float(min_volume or 0.0))
    limit = max(1, int(limit or DEFAULT_CYCLE_LIMIT))
    cache_key = SQLiteCacheManager.get_dict_key(
        "currency-cycles",
        league,
        base,
        ",".join(normalized_targets),
        status,
        max_steps,
        min_margin,
        fee_pct,
        min_volume,
        limit,
    )
    if use_cache:
        cached = SQLiteCacheManager.get(cache_key)
        if cached:
            cached["cached"] = True
            return cached

    started_ts = time.time()
    edges, errors, pair_count = await fetch_currency_cycle_edges(
        league=league,
        targets=normalized_targets,
        status=status,
        fee_pct=fee_pct,
        min_volume=min_volume,
        pair_timeout_seconds=pair_timeout_seconds,
        fetcher=fetcher,
    )
    cycles = find_currency_cycles_from_edges(
        edges,
        base=base,
        max_steps=max_steps,
        min_margin=min_margin,
        limit=limit,
    )
    payload = {
        "schema_version": "poe2-currency-cycles/v1",
        "created_ts": started_ts,
        "league": league,
        "base": _clean_currency_id(base),
        "targets": normalized_targets,
        "status": status,
        "max_steps": max_steps,
        "min_margin": min_margin,
        "fee_pct": fee_pct,
        "min_volume": min_volume,
        "pair_count": pair_count,
        "edge_count": len(edges),
        "cycles": cycles,
        "errors": errors,
        "source": "trade2/exchange",
        "cached": False,
    }
    if use_cache and len(errors) < pair_count:
        SQLiteCacheManager.set(cache_key, payload, 120)
    return payload
