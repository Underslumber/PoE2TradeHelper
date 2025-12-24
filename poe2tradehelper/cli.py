from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict

from .analytics import ListingAnalytics
from .client import PoE2TradeClient
from .llm import LlmInsights


def _load_query(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as fp:
        return json.load(fp)


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fetch and analyze PoE2 trade data")
    parser.add_argument("query", type=Path, help="Path to a JSON query file (search or exchange payload)")
    parser.add_argument("--league", default="standard", help="League to query")
    parser.add_argument("--limit", type=int, default=20, help="How many listings to fetch")
    parser.add_argument("--exchange", action="store_true", help="Treat query as an exchange payload")
    parser.add_argument("--llm-endpoint", type=str, help="Optional local LLM HTTP endpoint for summarization")
    parser.add_argument("--engine", default="new", help="Search engine version (default: new)")
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = create_parser()
    args = parser.parse_args(argv)

    query = _load_query(args.query)
    client = PoE2TradeClient()

    if args.exchange:
        trade = client.exchange_currency(args.league, query, limit=args.limit, engine=args.engine)
    else:
        trade = client.search_items(args.league, query, limit=args.limit, engine=args.engine)

    analytics = ListingAnalytics.from_results(trade.listings)
    summary = analytics.as_dict()

    print("Search ID:", trade.search_id)
    print("Total results:", trade.total)
    print("Fetched listings:", len(trade.listings))
    print("Price summary:", summary["price_summary"])
    print("Top currencies:", summary["top_currencies"])
    print("Top sellers:", summary["top_sellers"])

    if args.llm_endpoint:
        llm = LlmInsights(args.llm_endpoint)
        prompt = llm.build_prompt(analytics, league=args.league, query_hint=args.query.name)
        print("\nLLM prompt:\n", prompt)
        try:
            result = llm.summarize(prompt)
            print("\nLLM insight:\n", result)
        except Exception as exc:  # noqa: BLE001 - surface friendly message to CLI user
            print("Failed to call LLM:", exc)


if __name__ == "__main__":  # pragma: no cover
    main()
