from __future__ import annotations

import asyncio

import pytest

import app.trade.rate_limit as rate_limit
from app.trade.rate_limit import trade2_rate_limit_delay
from app.trade.rate_limit import trade2_rate_limited_request
from app.trade.rate_limit import Trade2RateLimitWaitError


def test_trade2_rate_limit_delay_uses_retry_after() -> None:
    assert trade2_rate_limit_delay({"Retry-After": "17"}) >= 17


@pytest.mark.parametrize("value", [" 2.5 ", "2.5", "3"])
def test_retry_after_accepts_positive_finite_seconds(value):
    assert trade2_rate_limit_delay({"Retry-After": value}) >= float(value)


@pytest.mark.parametrize("value", [None, "nan", "inf", "-1", "invalid", "0"])
def test_retry_after_rejects_invalid_seconds(value):
    assert trade2_rate_limit_delay({"Retry-After": value}) == 0


def test_cooldown_sleep_does_not_block_ready_route_and_rechecks_limit(monkeypatch):
    clock = [0.0]
    calls = []
    sleeps = []

    class Response:
        headers = {}

    async def scenario():
        sleeping = asyncio.Event()
        release = asyncio.Event()

        async def sleep(seconds):
            sleeps.append(seconds)
            if len(sleeps) == 1:
                sleeping.set()
                await release.wait()
            clock[0] += seconds

        async def request(name):
            calls.append(name)
            return Response()

        monkeypatch.setattr(rate_limit.asyncio, "sleep", sleep)
        rate_limit._trade2_next_request_ts_by_route["a"] = 2.0
        delayed = asyncio.create_task(trade2_rate_limited_request(lambda: request("a"), route_key="a"))
        try:
            await asyncio.wait_for(sleeping.wait(), 2)
            await asyncio.wait_for(trade2_rate_limited_request(lambda: request("b"), route_key="b"), 2)
            assert calls == ["b"]
            # Ограничение продлилось во время ожидания: его нельзя пропустить.
            rate_limit._trade2_next_request_ts_by_route["a"] = 4.0
            release.set()
            await asyncio.wait_for(delayed, 2)
            assert calls == ["b", "a"]
            assert sleeps == [2.0, 2.0]
        finally:
            release.set()
            if not delayed.done():
                delayed.cancel()
            await asyncio.gather(delayed, return_exceptions=True)

    monkeypatch.setattr(rate_limit.time, "time", lambda: clock[0])
    rate_limit.reset_trade2_rate_limit_state()
    try:
        asyncio.run(scenario())
    finally:
        rate_limit.reset_trade2_rate_limit_state()


def test_http_requests_remain_serialized_across_routes():
    class Response:
        headers = {}

    async def scenario():
        started = asyncio.Event()
        release = asyncio.Event()
        queued = asyncio.Event()
        calls = []

        async def first():
            calls.append("a")
            started.set()
            await release.wait()
            return Response()

        async def second_request():
            calls.append("b")
            return Response()

        async def second():
            queued.set()
            return await trade2_rate_limited_request(second_request, route_key="b")

        a = asyncio.create_task(trade2_rate_limited_request(first, route_key="a"))
        b = None
        try:
            await asyncio.wait_for(started.wait(), 2)
            b = asyncio.create_task(second())
            await asyncio.wait_for(queued.wait(), 2)
            assert calls == ["a"]
            release.set()
            await asyncio.wait_for(asyncio.gather(a, b), 2)
            assert calls == ["a", "b"]
        finally:
            release.set()
            for task in (a, b):
                if task and not task.done():
                    task.cancel()
            await asyncio.gather(*(task for task in (a, b) if task), return_exceptions=True)

    rate_limit.reset_trade2_rate_limit_state()
    try:
        asyncio.run(scenario())
    finally:
        rate_limit.reset_trade2_rate_limit_state()


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
