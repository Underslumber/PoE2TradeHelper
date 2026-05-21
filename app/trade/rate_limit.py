from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any

MIN_LIMITED_REQUEST_INTERVAL_SECONDS = 0.35
RATE_LIMIT_SAFETY_SECONDS = 0.25
RATE_LIMIT_REMAINING_HEADROOM = 1

_trade2_request_lock: asyncio.Lock | None = None
_trade2_request_lock_loop: asyncio.AbstractEventLoop | None = None
_trade2_next_request_ts = 0.0


def _split_header_list(value: Any) -> list[str]:
    return [part.strip() for part in str(value or "").split(",") if part.strip()]


def _get_header(headers: Any, key: str) -> Any:
    if hasattr(headers, "get"):
        value = headers.get(key)
        if value is not None:
            return value
        lower_key = key.lower()
        for header_key, header_value in getattr(headers, "items", lambda: [])():
            if str(header_key).lower() == lower_key:
                return header_value
    return None


def _parse_rate_triplet(value: str) -> tuple[float, float, float] | None:
    parts = value.split(":")
    if len(parts) != 3:
        return None
    try:
        return float(parts[0]), float(parts[1]), float(parts[2])
    except ValueError:
        return None


def trade2_rate_limit_delay(headers: Any) -> float:
    """Return a conservative delay from Path of Exile X-Rate-Limit headers."""
    if not headers:
        return 0.0

    delays: list[float] = []
    retry_after = _get_header(headers, "Retry-After")
    if retry_after and str(retry_after).isdigit():
        delays.append(float(retry_after))

    rules = _split_header_list(_get_header(headers, "X-Rate-Limit-Rules"))
    for rule in rules:
        limits = _split_header_list(_get_header(headers, f"X-Rate-Limit-{rule}"))
        states = _split_header_list(_get_header(headers, f"X-Rate-Limit-{rule}-State"))
        for limit_text, state_text in zip(limits, states):
            limit = _parse_rate_triplet(limit_text)
            state = _parse_rate_triplet(state_text)
            if not limit or not state:
                continue
            max_hits, period_seconds, _restriction_seconds = limit
            current_hits, _state_period_seconds, active_seconds = state
            if active_seconds > 0:
                delays.append(active_seconds)
                continue
            if max_hits <= 0 or period_seconds <= 0:
                continue
            remaining = max_hits - current_hits
            if remaining <= RATE_LIMIT_REMAINING_HEADROOM:
                delays.append(period_seconds)
            else:
                delays.append(MIN_LIMITED_REQUEST_INTERVAL_SECONDS)

    delay = max(delays or [0.0])
    if delay <= 0:
        return 0.0
    return delay + RATE_LIMIT_SAFETY_SECONDS


def reset_trade2_rate_limit_state() -> None:
    global _trade2_next_request_ts
    _trade2_next_request_ts = 0.0


def _trade2_lock() -> asyncio.Lock:
    global _trade2_request_lock, _trade2_request_lock_loop
    loop = asyncio.get_running_loop()
    if _trade2_request_lock is None or _trade2_request_lock_loop is not loop:
        _trade2_request_lock = asyncio.Lock()
        _trade2_request_lock_loop = loop
    return _trade2_request_lock


async def trade2_rate_limited_request(
    request: Callable[[], Awaitable[Any]],
) -> Any:
    global _trade2_next_request_ts
    async with _trade2_lock():
        now = time.time()
        if _trade2_next_request_ts > now:
            await asyncio.sleep(_trade2_next_request_ts - now)
        response = await request()
        delay = trade2_rate_limit_delay(getattr(response, "headers", None))
        if delay > 0:
            _trade2_next_request_ts = max(_trade2_next_request_ts, time.time() + delay)
        return response
