from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

from app.config import (
    MARKET_SNAPSHOT_CATEGORIES,
    MARKET_SNAPSHOT_CURRENCY_TARGETS,
    MARKET_SNAPSHOT_EARLY_DAYS,
    MARKET_SNAPSHOT_EARLY_INTERVAL_MINUTES,
    MARKET_SNAPSHOT_ENABLED,
    MARKET_SNAPSHOT_INCLUDE_UNSUPPORTED,
    MARKET_SNAPSHOT_INTERVAL_MINUTES,
    MARKET_SNAPSHOT_LEAGUE,
    MARKET_SNAPSHOT_LEAGUE_CHECK_MINUTES,
    MARKET_SNAPSHOT_LEAGUE_START,
    MARKET_SNAPSHOT_PAUSE_SECONDS,
    MARKET_SNAPSHOT_STATUS,
    MARKET_SNAPSHOT_TARGET,
)
from app.market_snapshots import (
    collect_market_snapshots,
    market_snapshot_interval_seconds,
    parse_league_start,
    split_csv,
)
from app.trade2 import get_trade_leagues

KNOWN_LEAGUE_STARTS = {
    "runes of aldur": "2026-05-29T19:00:00+00:00",
}
LEAGUE_EXCLUDE_TOKENS = (
    "standard",
    "hardcore",
    "solo self-found",
    "ssf",
    "private",
)


@dataclass
class MarketSnapshotServiceSettings:
    enabled: bool = MARKET_SNAPSHOT_ENABLED
    preferred_league: str = MARKET_SNAPSHOT_LEAGUE
    target: str = MARKET_SNAPSHOT_TARGET
    status: str = MARKET_SNAPSHOT_STATUS
    categories: list[str] = field(default_factory=lambda: split_csv(MARKET_SNAPSHOT_CATEGORIES))
    currency_targets: list[str] = field(default_factory=lambda: split_csv(MARKET_SNAPSHOT_CURRENCY_TARGETS))
    include_unsupported: bool = MARKET_SNAPSHOT_INCLUDE_UNSUPPORTED
    interval_minutes: float = MARKET_SNAPSHOT_INTERVAL_MINUTES
    early_interval_minutes: float = MARKET_SNAPSHOT_EARLY_INTERVAL_MINUTES
    early_days: float = MARKET_SNAPSHOT_EARLY_DAYS
    league_start_ts: float | None = field(default_factory=lambda: parse_league_start(MARKET_SNAPSHOT_LEAGUE_START))
    league_check_minutes: float = MARKET_SNAPSHOT_LEAGUE_CHECK_MINUTES
    pause_seconds: float = MARKET_SNAPSHOT_PAUSE_SECONDS


def _league_name(league: dict[str, Any]) -> str:
    return str(league.get("text") or league.get("id") or "")


def _is_poe2_league(league: dict[str, Any]) -> bool:
    realm = str(league.get("realm") or "poe2").lower()
    return realm == "poe2" and bool(league.get("id"))


def _is_trade_challenge_league(league: dict[str, Any]) -> bool:
    if not _is_poe2_league(league):
        return False
    name = _league_name(league).lower()
    return not any(token in name for token in LEAGUE_EXCLUDE_TOKENS)


def select_market_league(leagues: list[dict[str, Any]], preferred_league: str = "") -> dict[str, Any] | None:
    if preferred_league:
        preferred_lower = preferred_league.lower()
        for league in leagues:
            if str(league.get("id") or "").lower() == preferred_lower or _league_name(league).lower() == preferred_lower:
                return league
    for league in leagues:
        if _is_trade_challenge_league(league):
            return league
    for league in leagues:
        if _is_poe2_league(league):
            return league
    return None


def known_league_start_ts(league_id: str | None, league_text: str | None) -> float | None:
    name = f"{league_id or ''} {league_text or ''}".lower()
    for token, start in KNOWN_LEAGUE_STARTS.items():
        if token in name:
            return parse_league_start(start)
    return None


class MarketSnapshotService:
    def __init__(self, settings: MarketSnapshotServiceSettings | None = None):
        self.settings = settings or MarketSnapshotServiceSettings()
        self._task: asyncio.Task | None = None
        self._stop_event: asyncio.Event | None = None
        self._league_switched_starts: dict[str, float] = {}
        self.current_league: str = ""
        self.current_league_text: str = ""
        self.known_leagues: list[str] = []
        self.last_league_check_ts: float | None = None
        self.last_collection_ts: float | None = None
        self.next_collection_ts: float | None = None
        self.last_summary: dict[str, Any] | None = None
        self.last_error: str = ""
        self.running = False

    async def start(self) -> None:
        if not self.settings.enabled or self._task:
            return
        self._stop_event = asyncio.Event()
        self._task = asyncio.create_task(self._run(), name="market-snapshot-service")

    async def stop(self) -> None:
        if not self._task:
            return
        if self._stop_event:
            self._stop_event.set()
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None
        self.running = False

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.settings.enabled,
            "running": self.running,
            "league": self.current_league,
            "league_text": self.current_league_text,
            "known_leagues": self.known_leagues,
            "target": self.settings.target,
            "status": self.settings.status,
            "categories": self.settings.categories,
            "currency_targets": self.settings.currency_targets,
            "last_league_check_ts": self.last_league_check_ts,
            "last_collection_ts": self.last_collection_ts,
            "next_collection_ts": self.next_collection_ts,
            "last_summary": self.last_summary,
            "last_error": self.last_error,
        }

    async def _run(self) -> None:
        self.running = True
        try:
            while not self._stopped:
                await self._refresh_league()
                if not self.current_league:
                    await self._sleep_or_stop(60)
                    continue

                cycle_started = time.time()
                try:
                    summary = await collect_market_snapshots(
                        league=self.current_league,
                        target=self.settings.target,
                        status=self.settings.status,
                        categories=self.settings.categories or None,
                        include_unsupported=self.settings.include_unsupported,
                        currency_targets=self.settings.currency_targets,
                        pause_seconds=self.settings.pause_seconds,
                        force_refresh=True,
                    )
                    self.last_summary = summary
                    self.last_collection_ts = cycle_started
                    self.last_error = ""
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    self.last_error = str(exc)

                interval_seconds = market_snapshot_interval_seconds(
                    now_ts=time.time(),
                    league_start_ts=self._active_league_start_ts(),
                    early_days=self.settings.early_days,
                    early_interval_minutes=self.settings.early_interval_minutes,
                    interval_minutes=self.settings.interval_minutes,
                )
                self.next_collection_ts = cycle_started + interval_seconds
                await self._sleep_between_cycles(self.next_collection_ts)
        finally:
            self.running = False

    @property
    def _stopped(self) -> bool:
        return bool(self._stop_event and self._stop_event.is_set())

    async def _sleep_or_stop(self, seconds: float) -> None:
        if not self._stop_event:
            await asyncio.sleep(seconds)
            return
        try:
            await asyncio.wait_for(self._stop_event.wait(), timeout=max(0.0, seconds))
        except asyncio.TimeoutError:
            return

    async def _sleep_between_cycles(self, deadline_ts: float) -> None:
        while not self._stopped:
            remaining = deadline_ts - time.time()
            if remaining <= 0:
                return
            check_seconds = max(60.0, self.settings.league_check_minutes * 60)
            if self._league_check_due():
                old_league = self.current_league
                await self._refresh_league()
                if self.current_league and self.current_league != old_league:
                    return
            await self._sleep_or_stop(min(remaining, check_seconds))

    def _league_check_due(self) -> bool:
        if self.last_league_check_ts is None:
            return True
        return time.time() - self.last_league_check_ts >= max(60.0, self.settings.league_check_minutes * 60)

    async def _refresh_league(self) -> None:
        if not self._league_check_due():
            return
        try:
            leagues = await get_trade_leagues()
        except Exception as exc:
            self.last_error = str(exc)
            self.last_league_check_ts = time.time()
            return
        self.last_league_check_ts = time.time()
        self.known_leagues = [_league_name(league) for league in leagues if _is_poe2_league(league)]
        selected = select_market_league(leagues, self.settings.preferred_league)
        if not selected:
            return
        selected_id = str(selected.get("id") or "")
        selected_text = _league_name(selected)
        if selected_id != self.current_league:
            if self.current_league and selected_id not in self._league_switched_starts:
                self._league_switched_starts[selected_id] = time.time()
            self.current_league = selected_id
            self.current_league_text = selected_text

    def _active_league_start_ts(self) -> float | None:
        if self.settings.league_start_ts is not None:
            return self.settings.league_start_ts
        known = known_league_start_ts(self.current_league, self.current_league_text)
        if known is not None:
            return known
        return self._league_switched_starts.get(self.current_league)


market_snapshot_service = MarketSnapshotService()
