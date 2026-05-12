from __future__ import annotations

import asyncio
import random
from typing import Any, Dict, List, Tuple

import httpx

from app.config import DEFAULT_RATE_LIMIT_DELAY, MAX_CONCURRENCY, USER_AGENT


async def fetch_json(
    client: httpx.AsyncClient,
    url: str,
    params: Dict[str, Any] | None = None,
    attempts: int = 5,
) -> Dict[str, Any]:
    delay = DEFAULT_RATE_LIMIT_DELAY
    for attempt in range(1, attempts + 1):
        resp = await client.get(url, params=params)
        if resp.status_code in {429, 500, 502, 503, 504}:
            retry_after = resp.headers.get("Retry-After")
            if retry_after and retry_after.isdigit():
                wait = int(retry_after)
            else:
                wait = delay + random.uniform(0, 0.5)
            if attempt == attempts:
                resp.raise_for_status()
            await asyncio.sleep(wait)
            delay *= 2
            continue
        resp.raise_for_status()
        return resp.json()
    raise RuntimeError("Unreachable retry loop")


async def fetch_all(endpoints: List[Tuple[str, Dict[str, Any] | None]]):
    sem = asyncio.Semaphore(MAX_CONCURRENCY)
    results: List[Dict[str, Any]] = []

    async def _fetch(pair: Tuple[str, Dict[str, Any] | None]):
        url, params = pair
        async with sem:
            try:
                async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}, timeout=30) as client:
                    data = await fetch_json(client, url, params=params)
                results.append({"url": url, "data": data})
            except Exception as exc:
                results.append({"url": url, "error": str(exc)})

    await asyncio.gather(*(_fetch(ep) for ep in endpoints))
    return results
