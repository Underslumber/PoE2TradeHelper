from __future__ import annotations

import os
import re
import time
from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager
from typing import Any

import httpx
from dotenv import load_dotenv

load_dotenv()


_FALSE_VALUES = {"0", "false", "no", "off"}
_PROXY_SPLIT_RE = re.compile(r"[\s,;]+")
_ROUND_ROBIN_STRATEGY = "round_robin"
_SUPPORTED_PROXY_STRATEGIES = {"failover", "sticky", _ROUND_ROBIN_STRATEGY}
_DEFAULT_FAILOVER_STATUS_CODES = "403,407,408,421,425,500,502,503,504,520-524"
_DEFAULT_FAILOVER_METHODS = "GET,HEAD,OPTIONS"
_DEFAULT_FAILOVER_BODY_MARKERS = (
    "access denied|temporarily unavailable|service unavailable|bad gateway|gateway timeout|"
    "cloudflare|captcha|checking your browser|ddos protection"
)
_active_proxy_index = 0
_round_robin_index = 0
_proxy_cooldowns: dict[str, float] = {}
_proxy_config_key: tuple[str, ...] = ()


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() not in _FALSE_VALUES


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _split_proxy_urls(value: str | None) -> list[str]:
    urls: list[str] = []
    for item in _PROXY_SPLIT_RE.split(str(value or "").strip()):
        item = item.strip()
        if item and item not in urls:
            urls.append(item)
    return urls


def _split_env_list(value: str | None) -> list[str]:
    items: list[str] = []
    for item in re.split(r"[,;|]+", str(value or "")):
        item = item.strip()
        if item:
            items.append(item)
    return items


def _parse_status_codes(value: str) -> set[int]:
    codes: set[int] = set()
    for item in _split_env_list(value):
        if "-" in item:
            start_text, end_text = item.split("-", 1)
            try:
                start = int(start_text.strip())
                end = int(end_text.strip())
            except ValueError:
                continue
            codes.update(range(min(start, end), max(start, end) + 1))
            continue
        try:
            codes.add(int(item))
        except ValueError:
            continue
    return codes


def _failover_status_codes() -> set[int]:
    return _parse_status_codes(os.environ.get("OUTBOUND_PROXY_FAILOVER_STATUS_CODES", _DEFAULT_FAILOVER_STATUS_CODES))


def _failover_body_markers() -> tuple[str, ...]:
    raw = os.environ.get("OUTBOUND_PROXY_FAILOVER_BODY_MARKERS", _DEFAULT_FAILOVER_BODY_MARKERS)
    return tuple(item.lower() for item in _split_env_list(raw))


def _failover_methods_from_env() -> set[str]:
    raw = os.environ.get("OUTBOUND_PROXY_FAILOVER_METHODS", _DEFAULT_FAILOVER_METHODS)
    return {item.upper() for item in _split_env_list(raw)}


def outbound_proxy_urls() -> list[str]:
    for name in ("POE2_PROXY_URLS", "POE2_PROXY_URL", "OUTBOUND_PROXY_URLS", "OUTBOUND_PROXY_URL"):
        urls = _split_proxy_urls(os.environ.get(name))
        if urls:
            return urls
    return []


def _proxy_strategy() -> str:
    strategy = os.environ.get("OUTBOUND_PROXY_STRATEGY", "failover").strip().lower().replace("-", "_")
    return strategy if strategy in _SUPPORTED_PROXY_STRATEGIES else "failover"


def _proxy_cooldown_seconds() -> float:
    return max(0.0, _env_float("OUTBOUND_PROXY_COOLDOWN_SECONDS", 60.0))


def _proxy_failover_attempts() -> int:
    urls = outbound_proxy_urls()
    default = max(1, len(urls))
    try:
        configured = int(os.environ.get("OUTBOUND_PROXY_FAILOVER_ATTEMPTS", default))
    except (TypeError, ValueError):
        configured = default
    return max(1, configured)


def _failover_on_response_enabled() -> bool:
    return _env_bool("OUTBOUND_PROXY_FAILOVER_ON_RESPONSE", True)


def _reset_state_if_config_changed(urls: list[str]) -> None:
    global _active_proxy_index, _round_robin_index, _proxy_config_key
    key = tuple(urls)
    if key == _proxy_config_key:
        return
    _proxy_config_key = key
    _active_proxy_index = 0
    _round_robin_index = 0
    _proxy_cooldowns.clear()


def _forced_proxy_index(urls: list[str]) -> int | None:
    value = (os.environ.get("POE2_PROXY_INDEX") or os.environ.get("OUTBOUND_PROXY_INDEX") or "").strip()
    if not value:
        return None
    try:
        raw_index = int(value)
    except ValueError:
        return None
    index = raw_index - 1 if raw_index > 0 else 0
    return index if 0 <= index < len(urls) else None


def _available_indices(urls: list[str], now: float) -> list[int]:
    return [index for index, url in enumerate(urls) if _proxy_cooldowns.get(url, 0.0) <= now]


def _select_proxy_url() -> str:
    global _active_proxy_index, _round_robin_index
    urls = outbound_proxy_urls()
    if not urls:
        return ""
    _reset_state_if_config_changed(urls)

    forced_index = _forced_proxy_index(urls)
    if forced_index is not None:
        _active_proxy_index = forced_index
        return urls[forced_index]

    now = time.time()
    available = _available_indices(urls, now) or list(range(len(urls)))
    strategy = _proxy_strategy()
    if strategy == _ROUND_ROBIN_STRATEGY:
        selected = available[_round_robin_index % len(available)]
        _round_robin_index += 1
        _active_proxy_index = selected
        return urls[selected]

    if _active_proxy_index in available:
        return urls[_active_proxy_index]

    selected = next((index for index in available if index > _active_proxy_index), available[0])
    _active_proxy_index = selected
    return urls[selected]


def outbound_proxy_url() -> str:
    return _select_proxy_url()


def outbound_trust_env() -> bool:
    return _env_bool("OUTBOUND_TRUST_ENV", True)


def httpx_client_kwargs(*, proxy_url: str | None = None, **kwargs: Any) -> dict[str, Any]:
    options = dict(kwargs)
    proxy_url = outbound_proxy_url() if proxy_url is None else proxy_url
    if proxy_url and "proxy" not in options:
        options["proxy"] = proxy_url
    options.setdefault("trust_env", outbound_trust_env())
    return options


def mark_outbound_proxy_failed(proxy_url: str, *, now: float | None = None) -> None:
    global _active_proxy_index
    if not proxy_url:
        return
    urls = outbound_proxy_urls()
    _reset_state_if_config_changed(urls)
    if proxy_url not in urls:
        return
    current = time.time() if now is None else now
    cooldown_until = current + _proxy_cooldown_seconds()
    _proxy_cooldowns[proxy_url] = cooldown_until
    if urls[_active_proxy_index % len(urls)] == proxy_url:
        available = _available_indices(urls, current)
        if available:
            _active_proxy_index = next((index for index in available if index > _active_proxy_index), available[0])


def mark_outbound_proxy_success(proxy_url: str) -> None:
    if proxy_url:
        _proxy_cooldowns.pop(proxy_url, None)


def outbound_proxy_status() -> dict[str, Any]:
    urls = outbound_proxy_urls()
    _reset_state_if_config_changed(urls)
    now = time.time()
    return {
        "strategy": _proxy_strategy(),
        "failover_attempts": _proxy_failover_attempts(),
        "failover_on_response": _failover_on_response_enabled(),
        "active_index": _active_proxy_index if urls else None,
        "urls": [
            {
                "index": index,
                "url": url,
                "active": index == _active_proxy_index,
                "cooldown_seconds": max(0.0, round(_proxy_cooldowns.get(url, 0.0) - now, 3)),
            }
            for index, url in enumerate(urls)
        ],
        "trust_env": outbound_trust_env(),
    }


def _response_body_matches_failover_marker(response: httpx.Response) -> bool:
    markers = _failover_body_markers()
    if not markers:
        return False
    headers = getattr(response, "headers", {}) or {}
    content_type = headers.get("content-type", "").lower() if hasattr(headers, "get") else ""
    if not any(kind in content_type for kind in ("text/", "html", "json", "xml")):
        return False
    try:
        text = getattr(response, "text")[:8192].lower()
    except (AttributeError, TypeError, UnicodeDecodeError):
        return False
    return any(marker in text for marker in markers)


def should_failover_response(response: httpx.Response) -> tuple[bool, str]:
    if not _failover_on_response_enabled():
        return False, ""
    status_code = getattr(response, "status_code", None)
    if status_code in _failover_status_codes():
        return True, f"status:{status_code}"
    if _response_body_matches_failover_marker(response):
        return True, "body-marker"
    return False, ""


class OutboundHttpxClient:
    def __init__(
        self,
        *,
        failover_response_methods: Iterable[str] | None = None,
        failover_on_response: bool | None = None,
        **kwargs: Any,
    ):
        self._kwargs = dict(kwargs)
        self._client: httpx.AsyncClient | None = None
        self._proxy_url = ""
        self._failover_response_methods = (
            {item.upper() for item in failover_response_methods}
            if failover_response_methods is not None
            else _failover_methods_from_env()
        )
        self._failover_on_response = _failover_on_response_enabled() if failover_on_response is None else failover_on_response

    async def __aenter__(self) -> "OutboundHttpxClient":
        await self._open_client()
        return self

    async def __aexit__(self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: Any) -> None:
        await self.aclose()

    async def _open_client(self) -> None:
        self._proxy_url = outbound_proxy_url()
        self._client = httpx.AsyncClient(**httpx_client_kwargs(proxy_url=self._proxy_url, **self._kwargs))
        try:
            await self._client.__aenter__()
        except httpx.TransportError:
            mark_outbound_proxy_failed(self._proxy_url)
            self._client = None
            raise

    async def _close_client(self) -> None:
        if not self._client:
            return
        client = self._client
        self._client = None
        await client.__aexit__(None, None, None)

    async def aclose(self) -> None:
        await self._close_client()

    async def _switch_after_failure(self, failed_proxy_url: str) -> bool:
        await self._close_client()
        await self._open_client()
        return bool(self._proxy_url and self._proxy_url != failed_proxy_url)

    def _response_failover_allowed(self, method_name: str, args: tuple[Any, ...]) -> bool:
        if not self._failover_on_response:
            return False
        method = str(args[0]).upper() if method_name == "request" and args else method_name.upper()
        return method in self._failover_response_methods

    async def _send(self, method_name: str, *args: Any, **kwargs: Any) -> httpx.Response:
        attempts = _proxy_failover_attempts()
        for attempt in range(1, attempts + 1):
            if not self._client:
                await self._open_client()
            try:
                response = await getattr(self._client, method_name)(*args, **kwargs)
                should_switch, _reason = should_failover_response(response)
                if should_switch and self._response_failover_allowed(method_name, args):
                    failed_proxy_url = self._proxy_url
                    mark_outbound_proxy_failed(failed_proxy_url)
                    if attempt < attempts and await self._switch_after_failure(failed_proxy_url):
                        continue
                else:
                    mark_outbound_proxy_success(self._proxy_url)
                return response
            except httpx.TransportError:
                failed_proxy_url = self._proxy_url
                mark_outbound_proxy_failed(failed_proxy_url)
                if attempt >= attempts or not await self._switch_after_failure(failed_proxy_url):
                    raise
        raise RuntimeError("outbound proxy failover exhausted")

    async def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        return await self._send("request", method, url, **kwargs)

    async def get(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self._send("get", url, **kwargs)

    async def post(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self._send("post", url, **kwargs)

    def __getattr__(self, name: str) -> Any:
        if not self._client:
            raise AttributeError(name)
        return getattr(self._client, name)


@asynccontextmanager
async def outbound_httpx_client(**kwargs: Any) -> AsyncIterator[OutboundHttpxClient]:
    async with OutboundHttpxClient(**kwargs) as client:
        yield client


def playwright_proxy_options() -> dict[str, str] | None:
    proxy_url = outbound_proxy_url()
    if not proxy_url:
        return None
    return {"server": proxy_url}
