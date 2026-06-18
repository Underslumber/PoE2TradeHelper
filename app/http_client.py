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
_DEFAULT_PROXY_GROUP = "outbound"
_POE2_PROXY_GROUP = "poe2"
_active_proxy_index_by_group: dict[str, int] = {}
_round_robin_index_by_group: dict[str, int] = {}
_proxy_cooldowns: dict[tuple[str, str], float] = {}
_proxy_config_key_by_group: dict[str, tuple[str, ...]] = {}


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


def _normalize_proxy_group(proxy_group: str | None) -> str:
    value = str(proxy_group or _DEFAULT_PROXY_GROUP).strip().lower()
    return value or _DEFAULT_PROXY_GROUP


def outbound_proxy_urls(proxy_group: str | None = None) -> list[str]:
    group = _normalize_proxy_group(proxy_group)
    names = ("OUTBOUND_PROXY_URLS", "OUTBOUND_PROXY_URL")
    if group == _POE2_PROXY_GROUP:
        names = ("POE2_PROXY_URLS", "POE2_PROXY_URL", *names)
    for name in names:
        urls = _split_proxy_urls(os.environ.get(name))
        if urls:
            return urls
    return []


def _proxy_strategy() -> str:
    strategy = os.environ.get("OUTBOUND_PROXY_STRATEGY", "failover").strip().lower().replace("-", "_")
    return strategy if strategy in _SUPPORTED_PROXY_STRATEGIES else "failover"


def _proxy_cooldown_seconds() -> float:
    return max(0.0, _env_float("OUTBOUND_PROXY_COOLDOWN_SECONDS", 60.0))


def _proxy_failover_attempts(proxy_group: str | None = None) -> int:
    urls = outbound_proxy_urls(proxy_group)
    default = max(1, len(urls))
    try:
        configured = int(os.environ.get("OUTBOUND_PROXY_FAILOVER_ATTEMPTS", default))
    except (TypeError, ValueError):
        configured = default
    return max(1, configured)


def _failover_on_response_enabled() -> bool:
    return _env_bool("OUTBOUND_PROXY_FAILOVER_ON_RESPONSE", True)


def _reset_state_if_config_changed(urls: list[str], proxy_group: str | None = None) -> None:
    group = _normalize_proxy_group(proxy_group)
    key = tuple(urls)
    if key == _proxy_config_key_by_group.get(group):
        return
    _proxy_config_key_by_group[group] = key
    _active_proxy_index_by_group[group] = 0
    _round_robin_index_by_group[group] = 0
    for cooldown_key in [item for item in _proxy_cooldowns if item[0] == group]:
        _proxy_cooldowns.pop(cooldown_key, None)


def _forced_proxy_index(urls: list[str], proxy_group: str | None = None) -> int | None:
    group = _normalize_proxy_group(proxy_group)
    names = ("OUTBOUND_PROXY_INDEX",)
    if group == _POE2_PROXY_GROUP:
        names = ("POE2_PROXY_INDEX", *names)
    value = next((os.environ.get(name, "").strip() for name in names if os.environ.get(name, "").strip()), "")
    if not value:
        return None
    try:
        raw_index = int(value)
    except ValueError:
        return None
    index = raw_index - 1 if raw_index > 0 else 0
    return index if 0 <= index < len(urls) else None


def _available_indices(urls: list[str], now: float, proxy_group: str | None = None) -> list[int]:
    group = _normalize_proxy_group(proxy_group)
    return [index for index, url in enumerate(urls) if _proxy_cooldowns.get((group, url), 0.0) <= now]


def _select_proxy_url(proxy_group: str | None = None) -> str:
    group = _normalize_proxy_group(proxy_group)
    urls = outbound_proxy_urls(group)
    if not urls:
        return ""
    _reset_state_if_config_changed(urls, group)

    forced_index = _forced_proxy_index(urls, group)
    if forced_index is not None:
        _active_proxy_index_by_group[group] = forced_index
        return urls[forced_index]

    now = time.time()
    available = _available_indices(urls, now, group) or list(range(len(urls)))
    strategy = _proxy_strategy()
    active_index = _active_proxy_index_by_group.get(group, 0)
    if strategy == _ROUND_ROBIN_STRATEGY:
        round_robin_index = _round_robin_index_by_group.get(group, 0)
        selected = available[round_robin_index % len(available)]
        _round_robin_index_by_group[group] = round_robin_index + 1
        _active_proxy_index_by_group[group] = selected
        return urls[selected]

    if active_index in available:
        return urls[active_index]

    selected = next((index for index in available if index > active_index), available[0])
    _active_proxy_index_by_group[group] = selected
    return urls[selected]


def outbound_proxy_url(proxy_group: str | None = None) -> str:
    return _select_proxy_url(proxy_group)


def outbound_trust_env() -> bool:
    return _env_bool("OUTBOUND_TRUST_ENV", False)


def httpx_client_kwargs(*, proxy_url: str | None = None, proxy_group: str | None = None, **kwargs: Any) -> dict[str, Any]:
    options = dict(kwargs)
    proxy_url = outbound_proxy_url(proxy_group) if proxy_url is None else proxy_url
    if proxy_url and "proxy" not in options:
        options["proxy"] = proxy_url
    options.setdefault("trust_env", outbound_trust_env())
    return options


def mark_outbound_proxy_failed(
    proxy_url: str,
    *,
    now: float | None = None,
    proxy_group: str | None = None,
    cooldown_seconds: float | None = None,
) -> None:
    if not proxy_url:
        return
    group = _normalize_proxy_group(proxy_group)
    urls = outbound_proxy_urls(group)
    _reset_state_if_config_changed(urls, group)
    if proxy_url not in urls:
        return
    current = time.time() if now is None else now
    cooldown_until = current + (cooldown_seconds if cooldown_seconds is not None else _proxy_cooldown_seconds())
    _proxy_cooldowns[(group, proxy_url)] = cooldown_until
    active_index = _active_proxy_index_by_group.get(group, 0)
    if urls[active_index % len(urls)] == proxy_url:
        available = _available_indices(urls, current, group)
        if available:
            _active_proxy_index_by_group[group] = next((index for index in available if index > active_index), available[0])


def mark_outbound_proxy_success(proxy_url: str, *, proxy_group: str | None = None) -> None:
    if proxy_url:
        _proxy_cooldowns.pop((_normalize_proxy_group(proxy_group), proxy_url), None)


def outbound_proxy_status(proxy_group: str | None = None) -> dict[str, Any]:
    group = _normalize_proxy_group(proxy_group)
    urls = outbound_proxy_urls(group)
    _reset_state_if_config_changed(urls, group)
    now = time.time()
    active_index = _active_proxy_index_by_group.get(group, 0) if urls else None
    return {
        "proxy_group": group,
        "strategy": _proxy_strategy(),
        "failover_attempts": _proxy_failover_attempts(group),
        "failover_on_response": _failover_on_response_enabled(),
        "active_index": active_index,
        "urls": [
            {
                "index": index,
                "url": url,
                "active": index == active_index,
                "cooldown_seconds": max(0.0, round(_proxy_cooldowns.get((group, url), 0.0) - now, 3)),
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


def _retry_after_seconds(response: httpx.Response) -> float | None:
    try:
        retry_after = response.headers.get("Retry-After")
    except AttributeError:
        return None
    try:
        seconds = float(retry_after)
    except (TypeError, ValueError):
        return None
    return seconds if seconds > 0 else None


class OutboundHttpxClient:
    def __init__(
        self,
        *,
        proxy_group: str | None = None,
        failover_response_methods: Iterable[str] | None = None,
        failover_on_response: bool | None = None,
        failover_on_rate_limit: bool = False,
        **kwargs: Any,
    ):
        self._kwargs = dict(kwargs)
        self._client: httpx.AsyncClient | None = None
        self._proxy_url = ""
        self._proxy_group = _normalize_proxy_group(proxy_group)
        self._failover_on_rate_limit = failover_on_rate_limit
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
        self._proxy_url = outbound_proxy_url(self._proxy_group)
        self._client = httpx.AsyncClient(**httpx_client_kwargs(proxy_url=self._proxy_url, proxy_group=self._proxy_group, **self._kwargs))
        try:
            await self._client.__aenter__()
        except httpx.TransportError:
            mark_outbound_proxy_failed(self._proxy_url, proxy_group=self._proxy_group)
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

    @property
    def proxy_url(self) -> str:
        return self._proxy_url

    def _response_failover_allowed(self, method_name: str, args: tuple[Any, ...]) -> bool:
        if not self._failover_on_response:
            return False
        method = str(args[0]).upper() if method_name == "request" and args else method_name.upper()
        return method in self._failover_response_methods

    async def _send(self, method_name: str, *args: Any, **kwargs: Any) -> httpx.Response:
        attempts = _proxy_failover_attempts(self._proxy_group)
        for attempt in range(1, attempts + 1):
            if not self._client:
                await self._open_client()
            try:
                response = await getattr(self._client, method_name)(*args, **kwargs)
                should_switch, _reason = should_failover_response(response)
                retry_after = _retry_after_seconds(response)
                if self._failover_on_rate_limit and retry_after and self._response_failover_allowed(method_name, args):
                    failed_proxy_url = self._proxy_url
                    mark_outbound_proxy_failed(
                        failed_proxy_url,
                        proxy_group=self._proxy_group,
                        cooldown_seconds=max(retry_after, _proxy_cooldown_seconds()),
                    )
                    if attempt < attempts and await self._switch_after_failure(failed_proxy_url):
                        continue
                    # Не удалось переключиться (последняя попытка или нет свободного прокси):
                    # возвращаем ответ, сохраняя выставленный rate-limit cooldown, и не помечаем прокси успешным.
                    return response
                if should_switch and self._response_failover_allowed(method_name, args):
                    failed_proxy_url = self._proxy_url
                    mark_outbound_proxy_failed(failed_proxy_url, proxy_group=self._proxy_group)
                    if attempt < attempts and await self._switch_after_failure(failed_proxy_url):
                        continue
                else:
                    mark_outbound_proxy_success(self._proxy_url, proxy_group=self._proxy_group)
                return response
            except httpx.TransportError:
                failed_proxy_url = self._proxy_url
                mark_outbound_proxy_failed(failed_proxy_url, proxy_group=self._proxy_group)
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


def playwright_proxy_options(proxy_group: str | None = None) -> dict[str, str] | None:
    proxy_url = outbound_proxy_url(proxy_group)
    if not proxy_url:
        return None
    return {"server": proxy_url}
