from __future__ import annotations

import statistics
from collections import Counter
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Tuple


@dataclass
class ListingAnalytics:
    """Utility helpers for summarizing trade listings."""

    listings: List[Dict[str, Any]]

    def prices(self) -> List[float]:
        values: List[float] = []
        for listing in self.listings:
            price = listing.get("listing", {}).get("price", {})
            amount = price.get("amount")
            if isinstance(amount, (int, float)):
                values.append(float(amount))
        return values

    def currencies(self) -> Counter:
        counter: Counter = Counter()
        for listing in self.listings:
            price = listing.get("listing", {}).get("price", {})
            currency = price.get("currency")
            if currency:
                counter[currency] += 1
        return counter

    def sellers(self) -> Counter:
        counter: Counter = Counter()
        for listing in self.listings:
            account = listing.get("listing", {}).get("account", {})
            name = account.get("lastCharacterName") or account.get("name")
            if name:
                counter[name] += 1
        return counter

    def price_summary(self) -> Dict[str, float]:
        values = self.prices()
        if not values:
            return {"count": 0, "average": 0.0, "median": 0.0, "min": 0.0, "max": 0.0}

        return {
            "count": len(values),
            "average": round(statistics.mean(values), 4),
            "median": round(statistics.median(values), 4),
            "min": round(min(values), 4),
            "max": round(max(values), 4),
        }

    def top_currencies(self, n: int = 5) -> List[Tuple[str, int]]:
        return self.currencies().most_common(n)

    def top_sellers(self, n: int = 5) -> List[Tuple[str, int]]:
        return self.sellers().most_common(n)

    def item_buckets(self, field: str) -> Counter:
        counter: Counter = Counter()
        for listing in self.listings:
            item = listing.get("item", {})
            value = item
            for part in field.split("."):
                value = value.get(part, {}) if isinstance(value, dict) else None
            if value and not isinstance(value, dict):
                counter[str(value)] += 1
        return counter

    def as_dict(self) -> Dict[str, Any]:
        return {
            "price_summary": self.price_summary(),
            "top_currencies": self.top_currencies(),
            "top_sellers": self.top_sellers(),
        }

    @classmethod
    def from_results(cls, results: Iterable[Dict[str, Any]]) -> "ListingAnalytics":
        return cls(listings=list(results))
