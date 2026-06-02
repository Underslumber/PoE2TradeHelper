import asyncio

import httpx
import pytest

import app.http_client as http_client
from app.http_client import (
    httpx_client_kwargs,
    mark_outbound_proxy_failed,
    outbound_httpx_client,
    outbound_proxy_status,
    outbound_proxy_url,
    outbound_proxy_urls,
    playwright_proxy_options,
)


@pytest.fixture(autouse=True)
def clear_proxy_env(monkeypatch):
    for name in (
        "OUTBOUND_PROXY_URL",
        "OUTBOUND_PROXY_URLS",
        "POE2_PROXY_URL",
        "POE2_PROXY_URLS",
        "OUTBOUND_PROXY_STRATEGY",
        "OUTBOUND_PROXY_INDEX",
        "POE2_PROXY_INDEX",
        "OUTBOUND_PROXY_COOLDOWN_SECONDS",
        "OUTBOUND_PROXY_FAILOVER_ATTEMPTS",
        "OUTBOUND_PROXY_FAILOVER_BODY_MARKERS",
        "OUTBOUND_PROXY_FAILOVER_METHODS",
        "OUTBOUND_PROXY_FAILOVER_ON_RESPONSE",
        "OUTBOUND_PROXY_FAILOVER_STATUS_CODES",
        "OUTBOUND_TRUST_ENV",
    ):
        monkeypatch.delenv(name, raising=False)


def test_httpx_client_kwargs_uses_project_proxy(monkeypatch):
    monkeypatch.setenv("OUTBOUND_PROXY_URL", "http://127.0.0.1:7890")

    kwargs = httpx_client_kwargs(timeout=30)

    assert kwargs["proxy"] == "http://127.0.0.1:7890"
    assert kwargs["trust_env"] is False


def test_httpx_client_kwargs_can_trust_system_proxy_env(monkeypatch):
    monkeypatch.setenv("OUTBOUND_TRUST_ENV", "true")

    kwargs = httpx_client_kwargs(timeout=30)

    assert "proxy" not in kwargs
    assert kwargs["trust_env"] is True


def test_poe2_proxy_is_scoped_to_poe2_group(monkeypatch):
    monkeypatch.setenv("OUTBOUND_PROXY_URL", "http://127.0.0.1:7890")
    monkeypatch.setenv("POE2_PROXY_URL", "socks5://127.0.0.1:1080")

    assert outbound_proxy_url() == "http://127.0.0.1:7890"
    assert outbound_proxy_url(proxy_group="poe2") == "socks5://127.0.0.1:1080"
    assert playwright_proxy_options() == {"server": "http://127.0.0.1:7890"}
    assert playwright_proxy_options(proxy_group="poe2") == {"server": "socks5://127.0.0.1:1080"}


def test_httpx_client_kwargs_can_ignore_system_proxy_env(monkeypatch):
    monkeypatch.setenv("OUTBOUND_TRUST_ENV", "false")

    kwargs = httpx_client_kwargs(headers={"User-Agent": "test"})

    assert "proxy" not in kwargs
    assert kwargs["trust_env"] is False
    assert kwargs["headers"] == {"User-Agent": "test"}


def test_outbound_proxy_urls_support_failover_list(monkeypatch):
    monkeypatch.setenv("OUTBOUND_PROXY_URLS", "http://127.0.0.1:7891; socks5://127.0.0.1:1081")

    assert outbound_proxy_urls() == ["http://127.0.0.1:7891", "socks5://127.0.0.1:1081"]
    assert outbound_proxy_url() == "http://127.0.0.1:7891"

    mark_outbound_proxy_failed("http://127.0.0.1:7891")

    status = outbound_proxy_status()
    assert outbound_proxy_url() == "socks5://127.0.0.1:1081"
    assert status["active_index"] == 1
    assert status["urls"][0]["cooldown_seconds"] > 0


def test_outbound_proxy_round_robin_strategy(monkeypatch):
    monkeypatch.setenv("OUTBOUND_PROXY_URLS", "http://127.0.0.1:7892, http://127.0.0.1:7893")
    monkeypatch.setenv("OUTBOUND_PROXY_STRATEGY", "round_robin")

    assert outbound_proxy_url() == "http://127.0.0.1:7892"
    assert outbound_proxy_url() == "http://127.0.0.1:7893"


def test_should_failover_response_ignores_minimal_fake_response():
    class MinimalResponse:
        pass

    assert http_client.should_failover_response(MinimalResponse()) == (False, "")


def test_outbound_httpx_client_marks_failed_proxy(monkeypatch):
    calls = []

    class FailingAsyncClient:
        def __init__(self, **kwargs):
            calls.append(kwargs)

        async def __aenter__(self):
            raise httpx.ConnectError("proxy down")

        async def __aexit__(self, exc_type, exc, tb):
            return None

    async def use_client():
        async with outbound_httpx_client(timeout=30):
            return None

    monkeypatch.setenv("OUTBOUND_PROXY_URLS", "http://127.0.0.1:7894, http://127.0.0.1:7895")
    monkeypatch.setattr(http_client.httpx, "AsyncClient", FailingAsyncClient)

    with pytest.raises(httpx.TransportError):
        asyncio.run(use_client())

    assert calls[0]["proxy"] == "http://127.0.0.1:7894"
    assert outbound_proxy_url() == "http://127.0.0.1:7895"


def test_outbound_httpx_client_retries_request_on_next_proxy(monkeypatch):
    calls = []

    class FlakyAsyncClient:
        def __init__(self, **kwargs):
            self.proxy = kwargs.get("proxy")
            calls.append(("init", self.proxy))

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            calls.append(("close", self.proxy))
            return None

        async def get(self, url, **kwargs):
            calls.append(("get", self.proxy, url))
            if self.proxy == "http://127.0.0.1:7896":
                raise httpx.ConnectError("first proxy is down")
            return httpx.Response(200)

    async def use_client():
        async with outbound_httpx_client(timeout=30) as client:
            return await client.get("https://example.test/data")

    monkeypatch.setenv("OUTBOUND_PROXY_URLS", "http://127.0.0.1:7896, http://127.0.0.1:7897")
    monkeypatch.setattr(http_client.httpx, "AsyncClient", FlakyAsyncClient)

    response = asyncio.run(use_client())

    assert response.status_code == 200
    assert ("get", "http://127.0.0.1:7896", "https://example.test/data") in calls
    assert ("get", "http://127.0.0.1:7897", "https://example.test/data") in calls
    assert outbound_proxy_url() == "http://127.0.0.1:7897"


def test_outbound_httpx_client_retries_unavailable_response_on_next_proxy(monkeypatch):
    calls = []

    class UnavailableAsyncClient:
        def __init__(self, **kwargs):
            self.proxy = kwargs.get("proxy")

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, url, **kwargs):
            calls.append(("get", self.proxy, url))
            if self.proxy == "http://127.0.0.1:7898":
                return httpx.Response(503, text="Service unavailable", headers={"Content-Type": "text/plain"})
            return httpx.Response(200, json={"ok": True})

    async def use_client():
        async with outbound_httpx_client(timeout=30) as client:
            return await client.get("https://example.test/data")

    monkeypatch.setenv("OUTBOUND_PROXY_URLS", "http://127.0.0.1:7898, http://127.0.0.1:7899")
    monkeypatch.setattr(http_client.httpx, "AsyncClient", UnavailableAsyncClient)

    response = asyncio.run(use_client())

    assert response.status_code == 200
    assert ("get", "http://127.0.0.1:7898", "https://example.test/data") in calls
    assert ("get", "http://127.0.0.1:7899", "https://example.test/data") in calls
    assert outbound_proxy_url() == "http://127.0.0.1:7899"


def test_outbound_httpx_client_does_not_failover_on_rate_limit_by_default(monkeypatch):
    calls = []

    class RateLimitAsyncClient:
        def __init__(self, **kwargs):
            self.proxy = kwargs.get("proxy")

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, url, **kwargs):
            calls.append(("get", self.proxy, url))
            return httpx.Response(429, headers={"Retry-After": "10"})

    async def use_client():
        async with outbound_httpx_client(timeout=30) as client:
            return await client.get("https://example.test/data")

    monkeypatch.setenv("OUTBOUND_PROXY_URLS", "http://127.0.0.1:7900, http://127.0.0.1:7901")
    monkeypatch.setattr(http_client.httpx, "AsyncClient", RateLimitAsyncClient)

    response = asyncio.run(use_client())

    assert response.status_code == 429
    assert calls == [("get", "http://127.0.0.1:7900", "https://example.test/data")]
    assert outbound_proxy_url() == "http://127.0.0.1:7900"


def test_outbound_httpx_client_can_failover_on_route_rate_limit(monkeypatch):
    calls = []

    class RateLimitThenOkAsyncClient:
        def __init__(self, **kwargs):
            self.proxy = kwargs.get("proxy")

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, url, **kwargs):
            calls.append(("get", self.proxy, url))
            if self.proxy == "http://127.0.0.1:7908":
                return httpx.Response(429, headers={"Retry-After": "30"})
            return httpx.Response(200, json={"ok": True})

    async def use_client():
        async with outbound_httpx_client(timeout=30, failover_on_rate_limit=True) as client:
            return await client.get("https://example.test/data")

    monkeypatch.setenv("OUTBOUND_PROXY_URLS", "http://127.0.0.1:7908, http://127.0.0.1:7909")
    monkeypatch.setattr(http_client.httpx, "AsyncClient", RateLimitThenOkAsyncClient)

    response = asyncio.run(use_client())
    status = outbound_proxy_status()

    assert response.status_code == 200
    assert calls == [
        ("get", "http://127.0.0.1:7908", "https://example.test/data"),
        ("get", "http://127.0.0.1:7909", "https://example.test/data"),
    ]
    assert outbound_proxy_url() == "http://127.0.0.1:7909"
    assert status["urls"][0]["cooldown_seconds"] > 0


def test_outbound_httpx_client_retries_body_marker_response_on_next_proxy(monkeypatch):
    calls = []

    class MarkerAsyncClient:
        def __init__(self, **kwargs):
            self.proxy = kwargs.get("proxy")

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, url, **kwargs):
            calls.append(("get", self.proxy, url))
            if self.proxy == "http://127.0.0.1:7902":
                return httpx.Response(200, text="<html>Cloudflare captcha</html>", headers={"Content-Type": "text/html"})
            return httpx.Response(200, json={"ok": True})

    async def use_client():
        async with outbound_httpx_client(timeout=30) as client:
            return await client.get("https://example.test/data")

    monkeypatch.setenv("OUTBOUND_PROXY_URLS", "http://127.0.0.1:7902, http://127.0.0.1:7903")
    monkeypatch.setattr(http_client.httpx, "AsyncClient", MarkerAsyncClient)

    response = asyncio.run(use_client())

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert ("get", "http://127.0.0.1:7902", "https://example.test/data") in calls
    assert ("get", "http://127.0.0.1:7903", "https://example.test/data") in calls


def test_outbound_httpx_client_only_retries_post_when_allowed(monkeypatch):
    calls = []

    class PostAsyncClient:
        def __init__(self, **kwargs):
            self.proxy = kwargs.get("proxy")

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, **kwargs):
            calls.append(("post", self.proxy, url))
            if self.proxy in {"http://127.0.0.1:7904", "http://127.0.0.1:7906"}:
                return httpx.Response(503, text="Service unavailable", headers={"Content-Type": "text/plain"})
            return httpx.Response(200, json={"ok": True})

    async def use_client(**kwargs):
        async with outbound_httpx_client(timeout=30, **kwargs) as client:
            return await client.post("https://example.test/search", json={})

    monkeypatch.setenv("OUTBOUND_PROXY_URLS", "http://127.0.0.1:7904, http://127.0.0.1:7905")
    monkeypatch.setattr(http_client.httpx, "AsyncClient", PostAsyncClient)

    response = asyncio.run(use_client())

    assert response.status_code == 503
    assert calls == [("post", "http://127.0.0.1:7904", "https://example.test/search")]

    calls.clear()
    monkeypatch.setenv("OUTBOUND_PROXY_URLS", "http://127.0.0.1:7906, http://127.0.0.1:7907")

    response = asyncio.run(use_client(failover_response_methods=("GET", "POST")))

    assert response.status_code == 200
    assert calls == [
        ("post", "http://127.0.0.1:7906", "https://example.test/search"),
        ("post", "http://127.0.0.1:7907", "https://example.test/search"),
    ]
