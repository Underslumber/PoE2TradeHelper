from __future__ import annotations

import argparse
import asyncio
import uvicorn

from app.collector.discover import run_discovery, save_source_map
from app.collector.sync import sync_all, sync_pair


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
    elif args.command == "run":
        run_web()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
