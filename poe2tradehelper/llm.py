from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import requests

from .analytics import ListingAnalytics


@dataclass
class LlmInsights:
    """Helper for sending analytics context to a local LLM endpoint."""

    endpoint: str

    def build_prompt(self, analytics: ListingAnalytics, *, league: str, query_hint: str | None = None) -> str:
        summary = analytics.as_dict()
        parts = [
            "You are assisting with Path of Exile 2 market analysis.",
            f"League: {league}.",
            f"Query: {query_hint or 'ad-hoc'}.",
            "Summarize the following price and listing statistics in plain language and highlight potential trends or arbitrage opportunities:",
            json.dumps(summary, ensure_ascii=False, indent=2),
        ]
        return "\n".join(parts)

    def summarize(self, prompt: str) -> str:
        response = requests.post(self.endpoint, json={"prompt": prompt}, timeout=60)
        response.raise_for_status()
        data: Any = response.json()
        if isinstance(data, dict):
            return str(data.get("response") or data.get("text") or data)
        return str(data)
