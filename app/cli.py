from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uvicorn

from app.ai_context import load_ai_market_context
from app.collector.discover import run_discovery, save_source_map
from app.collector.sync import sync_all, sync_pair
from app.codex_market_analyzer import run_codex_market_analysis
from app.market_snapshots import collect_market_snapshots, parse_league_start, run_market_snapshot_loop, split_csv


def run_web():
    uvicorn.run("app.web.main:app", host="0.0.0.0", port=8000, reload=False)


def main():
    parser = argparse.ArgumentParser(description="poe2 ninja economy collector")
    sub = parser.add_subparsers(dest="command")

    discover_cmd = sub.add_parser("discover")
    discover_cmd.add_argument("--league", required=True)
    discover_cmd.add_argument("--category", required=True)

    sync_cmd = sub.add_parser("sync")
    sync_cmd.add_argument("--league")
    sync_cmd.add_argument("--category")
    sync_cmd.add_argument("--all", action="store_true")

    ai_context_cmd = sub.add_parser("ai-context")
    ai_context_cmd.add_argument("--league", required=True)
    ai_context_cmd.add_argument("--category", required=True)
    ai_context_cmd.add_argument("--target", default="exalted")
    ai_context_cmd.add_argument("--status", choices=("online", "any"), default="any")
    ai_context_cmd.add_argument("--league-day", type=int)
    ai_context_cmd.add_argument("--limit", type=int, default=80)
    ai_context_cmd.add_argument("--refresh", action="store_true")

    market_analyze_cmd = sub.add_parser("market-analyze")
    market_analyze_cmd.add_argument("--league", required=True)
    market_analyze_cmd.add_argument("--category", required=True)
    market_analyze_cmd.add_argument("--target", default="exalted")
    market_analyze_cmd.add_argument("--status", choices=("online", "any"), default="any")
    market_analyze_cmd.add_argument("--league-day", type=int)
    market_analyze_cmd.add_argument("--limit", type=int, default=80)
    market_analyze_cmd.add_argument("--max-candidates", type=int, default=10)
    market_analyze_cmd.add_argument("--refresh", action="store_true")
    market_analyze_cmd.add_argument("--codex-bin", default="codex")
    market_analyze_cmd.add_argument("--model")
    market_analyze_cmd.add_argument("--timeout-seconds", type=int, default=600)
    market_analyze_cmd.add_argument("--output-dir")
    market_analyze_cmd.add_argument("--no-save", action="store_true")

    market_snapshots_cmd = sub.add_parser("market-snapshots")
    market_snapshots_cmd.add_argument("--league", required=True)
    market_snapshots_cmd.add_argument("--target", default="exalted")
    market_snapshots_cmd.add_argument("--status", choices=("online", "any"), default="any")
    market_snapshots_cmd.add_argument("--categories", help="Comma-separated static category ids. Default: all stackable categories")
    market_snapshots_cmd.add_argument("--currency-targets", default="", help="Extra Currency targets, comma-separated")
    market_snapshots_cmd.add_argument("--once", action="store_true")
    market_snapshots_cmd.add_argument("--interval-minutes", type=float, default=15.0)
    market_snapshots_cmd.add_argument("--early-interval-minutes", type=float, default=5.0)
    market_snapshots_cmd.add_argument("--early-days", type=float, default=2.0)
    market_snapshots_cmd.add_argument("--league-start", help="ISO timestamp; uses early interval while inside the early window")
    market_snapshots_cmd.add_argument("--max-cycles", type=int)
    market_snapshots_cmd.add_argument("--pause-seconds", type=float, default=1.0)
    market_snapshots_cmd.add_argument("--skip-unsupported", action="store_true")

    sub.add_parser("run")
    args = parser.parse_args()

    if args.command == "discover":
        result = asyncio.run(run_discovery(args.league, args.category))
        save_source_map(result)
        print(f"Discovery complete for {args.league}/{args.category} -> {result.method}")
    elif args.command == "sync":
        if args.all:
            asyncio.run(sync_all())
        else:
            if not args.league or not args.category:
                raise SystemExit("--league and --category required unless --all")
            asyncio.run(sync_pair(args.league, args.category))
    elif args.command == "ai-context":
        payload = asyncio.run(
            load_ai_market_context(
                league=args.league,
                category=args.category,
                target=args.target,
                status=args.status,
                league_day=args.league_day,
                limit=args.limit,
                refresh=args.refresh,
            )
        )
        json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    elif args.command == "market-analyze":
        context = asyncio.run(
            load_ai_market_context(
                league=args.league,
                category=args.category,
                target=args.target,
                status=args.status,
                league_day=args.league_day,
                limit=args.limit,
                refresh=args.refresh,
            )
        )
        context.setdefault("request", {})["max_candidates"] = max(1, args.max_candidates)
        payload = run_codex_market_analysis(
            context,
            codex_bin=args.codex_bin,
            model=args.model,
            timeout_seconds=args.timeout_seconds,
            output_dir=args.output_dir,
            save=not args.no_save,
        )
        json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    elif args.command == "market-snapshots":
        categories = split_csv(args.categories)
        currency_targets = split_csv(args.currency_targets)
        if args.once:
            payload = asyncio.run(
                collect_market_snapshots(
                    league=args.league,
                    target=args.target,
                    status=args.status,
                    categories=categories or None,
                    include_unsupported=not args.skip_unsupported,
                    currency_targets=currency_targets,
                    pause_seconds=args.pause_seconds,
                    force_refresh=True,
                )
            )
            json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
            sys.stdout.write("\n")
        else:
            def print_summary(summary):
                json.dump(summary, sys.stdout, ensure_ascii=False)
                sys.stdout.write("\n")
                sys.stdout.flush()

            asyncio.run(
                run_market_snapshot_loop(
                    league=args.league,
                    target=args.target,
                    status=args.status,
                    categories=categories or None,
                    include_unsupported=not args.skip_unsupported,
                    currency_targets=currency_targets,
                    interval_minutes=args.interval_minutes,
                    early_interval_minutes=args.early_interval_minutes,
                    early_days=args.early_days,
                    league_start_ts=parse_league_start(args.league_start),
                    pause_seconds=args.pause_seconds,
                    max_cycles=args.max_cycles,
                    on_summary=print_summary,
                )
            )
    elif args.command == "run":
        run_web()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
