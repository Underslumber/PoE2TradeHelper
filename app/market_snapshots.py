from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

from app.config import DEFAULT_RATE_LIMIT_DELAY
from app.trade2 import POE_NINJA_CATEGORY_TYPES, get_category_rates, get_trade_static

DEFAULT_MARKET_TARGET = "exalted"
DEFAULT_MARKET_STATUS = "any"
DEFAULT_INTERVAL_MINUTES = 15.0
DEFAULT_EARLY_INTERVAL_MINUTES = 5.0
DEFAULT_EARLY_DAYS = 2.0
SKIPPED_STATIC_CATEGORIES = {"Misc"}


@dataclass(frozen=True)
class SnapshotJob:
    league: str
    category: str
    target: str = DEFAULT_MARKET_TARGET
    status: str = DEFAULT_MARKET_STATUS


def split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


def parse_league_start(value: str | None) -> float | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.now().astimezone().tzinfo)
    return parsed.timestamp()


def market_snapshot_interval_seconds(
    *,
    now_ts: float | None = None,
    league_start_ts: float | None = None,
    early_days: float = DEFAULT_EARLY_DAYS,
    early_interval_minutes: float = DEFAULT_EARLY_INTERVAL_MINUTES,
    interval_minutes: float = DEFAULT_INTERVAL_MINUTES,
) -> float:
    now = time.time() if now_ts is None else now_ts
    if league_start_ts is not None:
        early_window = max(0.0, early_days) * 24 * 60 * 60
        if 0 <= now - league_start_ts < early_window:
            return max(0.1, early_interval_minutes * 60)
    return max(0.1, interval_minutes * 60)


async def build_market_snapshot_jobs(
    *,
    league: str,
    target: str = DEFAULT_MARKET_TARGET,
    status: str = DEFAULT_MARKET_STATUS,
    categories: list[str] | None = None,
    include_unsupported: bool = True,
    currency_targets: list[str] | None = None,
) -> list[SnapshotJob]:
    static = await get_trade_static()
    if categories:
        selected_categories = [category for category in categories if static.get(category)]
    else:
        selected_categories = [
            category
            for category, entries in static.items()
            if entries and category not in SKIPPED_STATIC_CATEGORIES
        ]
    if not include_unsupported:
        selected_categories = [category for category in selected_categories if category in POE_NINJA_CATEGORY_TYPES]

    jobs: list[SnapshotJob] = []
    seen: set[tuple[str, str]] = set()
    for category in selected_categories:
        key = (category, target)
        if key in seen:
            continue
        seen.add(key)
        jobs.append(SnapshotJob(league=league, category=category, target=target, status=status))

    for extra_target in currency_targets or []:
        if not extra_target or extra_target == target:
            continue
        key = ("Currency", extra_target)
        if key in seen or "Currency" not in static:
            continue
        seen.add(key)
        jobs.append(SnapshotJob(league=league, category="Currency", target=extra_target, status=status))
    return jobs


async def collect_market_snapshots(
    *,
    league: str,
    target: str = DEFAULT_MARKET_TARGET,
    status: str = DEFAULT_MARKET_STATUS,
    categories: list[str] | None = None,
    include_unsupported: bool = True,
    currency_targets: list[str] | None = None,
    pause_seconds: float = DEFAULT_RATE_LIMIT_DELAY,
    force_refresh: bool = True,
) -> dict[str, Any]:
    jobs = await build_market_snapshot_jobs(
        league=league,
        target=target,
        status=status,
        categories=categories,
        include_unsupported=include_unsupported,
        currency_targets=currency_targets,
    )
    started_ts = time.time()
    results: list[dict[str, Any]] = []
    for index, job in enumerate(jobs):
        try:
            snapshot = await get_category_rates(
                league=job.league,
                category=job.category,
                target=job.target,
                status=job.status,
                force_refresh=force_refresh,
            )
            rows = snapshot.get("rows") or []
            results.append(
                {
                    "ok": True,
                    "category": job.category,
                    "target": job.target,
                    "status": job.status,
                    "source": snapshot.get("source") or "",
                    "rows": len(rows),
                    "errors": len(snapshot.get("errors") or []),
                }
            )
        except Exception as exc:
            results.append(
                {
                    "ok": False,
                    "category": job.category,
                    "target": job.target,
                    "status": job.status,
                    "error": str(exc),
                }
            )
        if index < len(jobs) - 1 and pause_seconds > 0:
            await asyncio.sleep(pause_seconds)

    ok_count = sum(1 for item in results if item.get("ok"))
    return {
        "created_ts": started_ts,
        "league": league,
        "target": target,
        "status": status,
        "jobs_total": len(jobs),
        "jobs_ok": ok_count,
        "jobs_failed": len(jobs) - ok_count,
        "duration_seconds": round(time.time() - started_ts, 3),
        "results": results,
    }


async def run_market_snapshot_loop(
    *,
    league: str,
    target: str = DEFAULT_MARKET_TARGET,
    status: str = DEFAULT_MARKET_STATUS,
    categories: list[str] | None = None,
    include_unsupported: bool = True,
    currency_targets: list[str] | None = None,
    interval_minutes: float = DEFAULT_INTERVAL_MINUTES,
    early_interval_minutes: float = DEFAULT_EARLY_INTERVAL_MINUTES,
    early_days: float = DEFAULT_EARLY_DAYS,
    league_start_ts: float | None = None,
    pause_seconds: float = DEFAULT_RATE_LIMIT_DELAY,
    max_cycles: int | None = None,
    on_summary: Callable[[dict[str, Any]], None] | None = None,
) -> None:
    cycles = 0
    while max_cycles is None or cycles < max_cycles:
        cycle_started = time.time()
        summary = await collect_market_snapshots(
            league=league,
            target=target,
            status=status,
            categories=categories,
            include_unsupported=include_unsupported,
            currency_targets=currency_targets,
            pause_seconds=pause_seconds,
            force_refresh=True,
        )
        cycles += 1
        if on_summary:
            on_summary(summary)
        if max_cycles is not None and cycles >= max_cycles:
            break
        interval_seconds = market_snapshot_interval_seconds(
            now_ts=time.time(),
            league_start_ts=league_start_ts,
            early_days=early_days,
            early_interval_minutes=early_interval_minutes,
            interval_minutes=interval_minutes,
        )
        await asyncio.sleep(max(0.0, interval_seconds - (time.time() - cycle_started)))
