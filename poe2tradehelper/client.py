from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

import requests


DEFAULT_USER_AGENT = "poe2-trade-helper/0.1"


@dataclass
class TradeResult:
    """Container for a trade search response and fetched listings."""

    search_id: str
    result_ids: List[str]
    total: int
    listings: List[Dict[str, Any]]


class PoE2TradeClient:
    """Thin wrapper around the official Path of Exile trade endpoints.

    The API surface closely follows the public trade API that backs the
    official trade site. It works for both regular searches (items) and
    exchange queries (currency). For convenience, the client can also fetch
    listing details for the first ``limit`` results from a search, enabling
    quick analytics without extra calls.
    """

    def __init__(
        self,
        base_url: str = "https://www.pathofexile.com/api/trade",
        session: Optional[requests.Session] = None,
        request_delay: float = 1.0,
        user_agent: str = DEFAULT_USER_AGENT,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.session = session or requests.Session()
        self.request_delay = request_delay
        self.user_agent = user_agent

    def _post(self, path: str, json: Dict[str, Any]) -> Dict[str, Any]:
        response = self.session.post(
            f"{self.base_url}/{path.lstrip('/')}",
            json=json,
            headers={"User-Agent": self.user_agent},
            timeout=30,
        )
        response.raise_for_status()
        return response.json()

    def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        response = self.session.get(
            f"{self.base_url}/{path.lstrip('/')}",
            params=params,
            headers={"User-Agent": self.user_agent},
            timeout=30,
        )
        response.raise_for_status()
        return response.json()

    def search_items(
        self,
        league: str,
        query: Dict[str, Any],
        *,
        limit: int = 20,
        engine: str = "new",
    ) -> TradeResult:
        """Perform an item search and fetch the first ``limit`` listings."""

        payload = {"query": query, "engine": engine}
        search = self._post(f"search/{league}", payload)
        return self._fetch_listing_details(search, limit)

    def exchange_currency(
        self,
        league: str,
        query: Dict[str, Any],
        *,
        limit: int = 20,
        engine: str = "new",
    ) -> TradeResult:
        """Perform a currency exchange query and fetch the first ``limit`` listings."""

        payload = {"query": query, "engine": engine}
        search = self._post(f"exchange/{league}", payload)
        return self._fetch_listing_details(search, limit)

    def fetch_raw_search(
        self,
        league: str,
        query: Dict[str, Any],
        *,
        engine: str = "new",
    ) -> Dict[str, Any]:
        """Return the raw search response without fetching listing details."""

        payload = {"query": query, "engine": engine}
        return self._post(f"search/{league}", payload)

    def fetch_raw_exchange(
        self,
        league: str,
        query: Dict[str, Any],
        *,
        engine: str = "new",
    ) -> Dict[str, Any]:
        """Return the raw exchange response without fetching listing details."""

        payload = {"query": query, "engine": engine}
        return self._post(f"exchange/{league}", payload)

    def fetch_listing_details(
        self,
        search_id: str,
        result_ids: Iterable[str],
        *,
        limit: int = 20,
        exchange: bool = False,
    ) -> List[Dict[str, Any]]:
        """Fetch listing details by IDs from a previous search/exchange."""

        ids = ",".join(list(result_ids)[:limit])
        params = {"query": search_id}
        if exchange:
            params["exchange"] = "1"
        details = self._get(f"fetch/{ids}", params=params)
        return details.get("result", [])

    def _fetch_listing_details(self, search: Dict[str, Any], limit: int) -> TradeResult:
        search_id = search.get("id", "")
        result_ids: List[str] = search.get("result", [])
        total = int(search.get("total", len(result_ids)))

        if not search_id or not result_ids:
            return TradeResult(search_id=search_id, result_ids=result_ids, total=total, listings=[])

        time.sleep(max(0.0, self.request_delay))
        listings = self.fetch_listing_details(
            search_id,
            result_ids,
            limit=limit,
            exchange="exchange" in search.get("query", {}),
        )
        return TradeResult(search_id=search_id, result_ids=result_ids, total=total, listings=listings)
