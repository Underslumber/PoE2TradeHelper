from __future__ import annotations

import asyncio

import pytest

import app.trade.rate_limit as rate_limit
from app.trade.rate_limit import trade2_rate_limit_delay
from app.trade.rate_limit import trade2_rate_limited_request
from app.trade.rate_limit import Trade2RateLimitWaitError


def test_trade2_rate_limit_delay_uses_retry_after() -> None:
    assert trade2_rate_limit_delay({"Retry-After": "17"}) >= 17


def test_trade2_rate_limit_delay_accepts_fractional_and_padded_retry_after() -> None:
    assert trade2_rate_limit_delay({"Retry-After": "1.5"}) >= 1.5
    assert trade2_rate_limit_delay({"Retry-After": " 17 "}) >= 17


def test_trade2_rate_limit_delay_ignores_non_numeric_retry_after() -> None:
    assert trade2_rate_limit_delay({"Retry-After": "Wed, 21 Oct 2099 07:28:00 GMT"}) == 0.0


def test_trade2_rate_limit_delay_slows_down_when_window_is_nearly_full() -> None:
    delay = trade2_rate_limit_delay(
        {
            "X-Rate-Limit-Rules": "Ip",
            "X-Rate-Limit-Ip": "20:5:60",
            "X-Rate-Limit-Ip-State": "19:5:0",
        }
    )

    assert delay >= 5


def test_trade2_rate_limit_delay_uses_active_restriction() -> None:
    delay = trade2_rate_limit_delay(
        {
            "X-Rate-Limit-Rules": "client",
            "X-Rate-Limit-Client": "10:5:10",
            "X-Rate-Limit-Client-State": "11:5:10",
        }
    )

    assert delay >= 10


def test_trade2_rate_limited_request_fails_fast_on_long_wait(monkeypatch) -> None:
    class FakeResponse:
        headers = {"Retry-After": "30"}

    async def fake_request():
        return FakeResponse()

    async def run_check() -> None:
        rate_limit.reset_trade2_rate_limit_state()
        await trade2_rate_limited_request(fake_request)
        with pytest.raises(Trade2RateLimitWaitError, match="retry after"):
            await trade2_rate_limited_request(fake_request)

    monkeypatch.setattr(rate_limit, "MAX_RATE_LIMIT_WAIT_SECONDS", 1.0)
    try:
        asyncio.run(run_check())
    finally:
        rate_limit.reset_trade2_rate_limit_state()


def test_trade2_rate_limited_request_tracks_routes_independently(monkeypatch) -> None:
    class FakeResponse:
        headers = {"Retry-After": "30"}

    async def fake_request():
        return FakeResponse()

    async def run_check() -> None:
        rate_limit.reset_trade2_rate_limit_state()
        await trade2_rate_limited_request(fake_request, route_key="proxy-a")
        await trade2_rate_limited_request(fake_request, route_key="proxy-b")
        with pytest.raises(Trade2RateLimitWaitError, match="retry after"):
            await trade2_rate_limited_request(fake_request, route_key="proxy-a")

    monkeypatch.setattr(rate_limit, "MAX_RATE_LIMIT_WAIT_SECONDS", 1.0)
    try:
        asyncio.run(run_check())
    finally:
        rate_limit.reset_trade2_rate_limit_state()
