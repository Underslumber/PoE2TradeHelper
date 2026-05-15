import asyncio
import logging
import time
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import httpx
from tenacity import (
    AsyncRetrying,
    RetryCallState,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.config import USER_AGENT, BASE_URL

TRADE2_BASE = "https://www.pathofexile.com/api/trade2"
TRADE2_RU_BASE = "https://ru.pathofexile.com/api/trade2"
POE_SITE_BASE = "https://www.pathofexile.com"

logger = logging.getLogger(__name__)
TRADE_STATIC_CACHE_TTL = 3600
_trade_static_cache: tuple[float, tuple[Dict[str, Any], Dict[str, Any]]] | None = None
_trade_static_lock = asyncio.Lock()


def _headers(extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if extra:
        headers.update(extra)
    return headers


def get_retry_after(retry_state: RetryCallState) -> float:
    """Extract Retry-After header if exception is HTTPStatusError 429"""
    if retry_state.outcome and retry_state.outcome.failed:
        exc = retry_state.outcome.exception()
        if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 429:
            retry_after = exc.response.headers.get("Retry-After")
            if retry_after and retry_after.isdigit():
                return float(retry_after)
    return 0.0


class RateLimitWait(wait_exponential):
    """Custom wait strategy that respects Retry-After header"""
    def __call__(self, retry_state: RetryCallState) -> float:
        retry_after = get_retry_after(retry_state)
        if retry_after > 0:
            logger.warning(f"Rate limited. Waiting for {retry_after} seconds.")
            return retry_after
        return super().__call__(retry_state)


def _make_retry() -> AsyncRetrying:
    return AsyncRetrying(
        stop=stop_after_attempt(4),
        wait=RateLimitWait(multiplier=1.5, min=2, max=15),
        retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.RequestError)),
        reraise=True,
    )


class PoeTradeClient:
    """Client for Path of Exile 2 Trade API"""

    @staticmethod
    async def get_trade_leagues() -> List[Dict[str, str]]:
        async for attempt in _make_retry():
            with attempt:
                async with httpx.AsyncClient(headers=_headers(), timeout=30) as client:
                    response = await client.get(f"{TRADE2_BASE}/data/leagues")
                    response.raise_for_status()

                    leagues = response.json().get("result", [])
                    return [
                        {
                            "id": league.get("id", ""),
                            "text": league.get("text") or league.get("id", ""),
                            "realm": league.get("realm", "poe2"),
                        }
                        for league in leagues
                        if league.get("realm") == "poe2" and league.get("id")
                    ]

    @staticmethod
    async def get_trade_static() -> tuple[Dict[str, Any], Dict[str, Any]]:
        global _trade_static_cache
        now = time.time()
        if _trade_static_cache and now - _trade_static_cache[0] < TRADE_STATIC_CACHE_TTL:
            return _trade_static_cache[1]

        async with _trade_static_lock:
            now = time.time()
            if _trade_static_cache and now - _trade_static_cache[0] < TRADE_STATIC_CACHE_TTL:
                return _trade_static_cache[1]
            async for attempt in _make_retry():
                with attempt:
                    async with httpx.AsyncClient(headers=_headers(), timeout=30) as client:
                        response, ru_response = await asyncio.gather(
                            client.get(f"{TRADE2_BASE}/data/static"),
                            client.get(f"{TRADE2_RU_BASE}/data/static"),
                        )
                        response.raise_for_status()
                        ru_response.raise_for_status()
                        payloads = (response.json(), ru_response.json())
                        _trade_static_cache = (time.time(), payloads)
                        return payloads
        raise RuntimeError("trade static data fetch did not return a response")

    @staticmethod
    async def post_exchange(
        league: str,
        have: List[str],
        want: List[str],
        status: str = "online",
    ) -> Dict[str, Any]:
        body = {
            "exchange": {
                "status": {"option": status},
                "have": have,
                "want": want,
            }
        }
        async for attempt in _make_retry():
            with attempt:
                async with httpx.AsyncClient(headers=_headers({"Content-Type": "application/json"}), timeout=30) as client:
                    response = await client.post(f"{TRADE2_BASE}/exchange/poe2/{quote(league, safe='')}", json=body)
                    response.raise_for_status()
                    return response.json()

    @staticmethod
    async def post_search(
        league: str,
        query: Dict[str, Any],
        sort: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        body = {"query": query, "sort": sort or {"price": "asc"}}
        async for attempt in _make_retry():
            with attempt:
                async with httpx.AsyncClient(headers=_headers({"Content-Type": "application/json"}), timeout=30) as client:
                    response = await client.post(f"{TRADE2_RU_BASE}/search/poe2/{quote(league, safe='')}", json=body)
                    response.raise_for_status()
                    return response.json()

    @staticmethod
    async def fetch_trade_items(ids: List[str], query_id: str, limit: int = 60, delay_between_chunks: float = 1.0) -> List[Dict[str, Any]]:
        selected_ids = [item_id for item_id in ids[:limit] if item_id]
        if not selected_ids:
            return []

        results: List[Dict[str, Any]] = []
        chunks = [selected_ids[i : i + 10] for i in range(0, len(selected_ids), 10)]

        async with httpx.AsyncClient(headers=_headers(), timeout=30) as client:
            for index, chunk_ids in enumerate(chunks):
                chunk_str = ",".join(chunk_ids)

                async for attempt in _make_retry():
                    with attempt:
                        response = await client.get(f"{TRADE2_RU_BASE}/fetch/{chunk_str}", params={"query": query_id})
                        response.raise_for_status()
                        results.extend(response.json().get("result") or [])

                if index < len(chunks) - 1:
                    await asyncio.sleep(delay_between_chunks)

        return results

    @staticmethod
    async def get_poe_ninja_rates(league: str, category_type: str) -> Optional[Dict[str, Any]]:
        async for attempt in _make_retry():
            with attempt:
                async with httpx.AsyncClient(headers=_headers(), timeout=30) as client:
                    response = await client.get(
                        f"{BASE_URL}/poe2/api/economy/exchange/current/overview",
                        params={"league": league, "type": category_type},
                    )
                    response.raise_for_status()
                    return response.json()
