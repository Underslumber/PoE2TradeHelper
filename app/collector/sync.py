from __future__ import annotations

import asyncio
import hashlib
import json
import time
from typing import Dict, List

import httpx
from sqlalchemy.orm import Session

from app.collector.discover import run_discovery, save_source_map
from app.collector.dom_extract import extract_dom_rows
from app.collector.fetch import fetch_all
from app.collector.icons import fetch_icon
from app.collector.parse import build_row_id, extract_rows, normalize_row
from app.config import BASE_URL, INDEX_MAP_PATH, RAW_DIR, SOURCE_MAP_PATH, USER_AGENT
from app.db.models import Artifact, Row, Snapshot
from app.db.session import get_session


async def _fetch_index_map() -> Dict[str, List[str]]:
    if INDEX_MAP_PATH.exists():
        return json.loads(INDEX_MAP_PATH.read_text(encoding="utf-8"))
    async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}, timeout=30) as client:
        resp = await client.get(f"{BASE_URL}/poe2/economy")
        resp.raise_for_status()
        html = resp.text
    leagues: Dict[str, List[str]] = {}
    for token in html.split("/poe2/economy/"):
        if "/" not in token:
            continue
        parts = token.split('"')[0].split('/')
        if len(parts) >= 2:
            league, category = parts[0], parts[1]
            leagues.setdefault(league, [])
            if category not in leagues[league]:
                leagues[league].append(category)
    INDEX_MAP_PATH.write_text(json.dumps(leagues, indent=2), encoding="utf-8")
    return leagues


def _load_source_map() -> Dict[str, Dict[str, dict]]:
    if SOURCE_MAP_PATH.exists():
        return json.loads(SOURCE_MAP_PATH.read_text(encoding="utf-8"))
    return {}


async def ensure_source(league: str, category: str) -> dict:
    source_map = _load_source_map()
    league_map = source_map.get(league, {})
    if category in league_map:
        return league_map[category]
    result = await run_discovery(league, category)
    save_source_map(result)
    return _load_source_map()[league][category]


def _store_snapshot(session: Session, snapshot_id: str, league: str, category: str, source_url: str, method: str):
    snapshot = Snapshot(
        id=snapshot_id,
        created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        league=league,
        category=category,
        source_url=source_url,
        method=method,
    )
    session.merge(snapshot)


def _store_rows(session: Session, snapshot_id: str, league: str, category: str, rows: List[dict], icon_map: Dict[str, str]):
    for row in rows:
        row_id = build_row_id(league, category, row)
        normalized = normalize_row(row)
        icon_url = normalized["icon_url"]
        icon_local = icon_map.get(icon_url) if icon_url else None
        session.merge(
            Row(
                snapshot_id=snapshot_id,
                row_id=row_id,
                name=normalized["name"],
                icon_url=icon_url,
                icon_local=icon_local,
                columns_json=json.dumps(normalized["columns"], ensure_ascii=False),
                raw_json=json.dumps(normalized["raw"], ensure_ascii=False),
            )
        )


def _store_artifact(session: Session, snapshot_id: str, kind: str, url: str | None, path: str):
    session.merge(Artifact(snapshot_id=snapshot_id, kind=kind, url=url, path=path))


async def sync_pair(league: str, category: str) -> None:
    source = await ensure_source(league, category)
    snapshot_id = str(int(time.time()))
    raw_dir = RAW_DIR / "xhr" / snapshot_id
    raw_dir.mkdir(parents=True, exist_ok=True)
    session = get_session()
    try:
        if source.get("method") == "xhr" and source.get("endpoint"):
            endpoint = source["endpoint"]["url"]
            json_path = source["endpoint"].get("json_path")
            params = None
            results = await fetch_all([(endpoint, params)])
            for res in results:
                if "data" in res:
                    raw = json.dumps(res["data"], ensure_ascii=False)
                    sha = hashlib.sha1(raw.encode("utf-8", "ignore")).hexdigest()
                    raw_path = raw_dir / f"{sha}.json"
                    raw_path.write_text(raw, encoding="utf-8")
                    _store_snapshot(session, snapshot_id, league, category, endpoint, "xhr")
                    _store_artifact(session, snapshot_id, "xhr", res["url"], str(raw_path))
                    rows = extract_rows(res["data"], json_path=json_path)
                    icon_map = await _download_icons(rows)
                    _store_rows(session, snapshot_id, league, category, rows, icon_map)
        else:
            rows = await extract_dom_rows(league, category)
            dom_raw = json.dumps(rows, ensure_ascii=False)
            sha = hashlib.sha1(dom_raw.encode("utf-8", "ignore")).hexdigest()
            dom_path = RAW_DIR / "dom" / f"{sha}.json"
            dom_path.write_text(dom_raw, encoding="utf-8")
            _store_snapshot(session, snapshot_id, league, category, source.get("source_url", ""), "playwright-dom")
            _store_artifact(session, snapshot_id, "dom", source.get("source_url"), str(dom_path))
            icon_map = await _download_icons(rows)
            _store_rows(session, snapshot_id, league, category, rows, icon_map)
        session.commit()
    finally:
        session.close()


async def _download_icons(rows: List[dict]) -> Dict[str, str]:
    icons = {row.get("icon") for row in rows if row.get("icon")}
    icon_map: Dict[str, str] = {}
    if not icons:
        return icon_map

    sem = asyncio.Semaphore(3)

    async def _fetch(url: str):
        async with sem:
            path = await fetch_icon(url)
            if path:
                icon_map[url] = path.name

    await asyncio.gather(*(_fetch(url) for url in icons))
    return icon_map


async def sync_all():
    leagues = await _fetch_index_map()
    tasks = []
    for league, categories in leagues.items():
        for category in categories:
            tasks.append(sync_pair(league, category))
    for task in tasks:
        await task


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Sync poe.ninja economy data")
    parser.add_argument("--league", help="League to sync")
    parser.add_argument("--category", help="Category to sync")
    parser.add_argument("--all", action="store_true", help="Sync all league/category pairs")
    args = parser.parse_args()

    if args.all:
        asyncio.run(sync_all())
    else:
        if not args.league or not args.category:
            raise SystemExit("--league and --category are required unless --all is set")
        asyncio.run(sync_pair(args.league, args.category))


if __name__ == "__main__":
    main()
