from __future__ import annotations

import asyncio
import hashlib
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from playwright.async_api import async_playwright

from app.config import BASE_URL, RAW_DIR, SOURCE_MAP_PATH, USER_AGENT


class DiscoveryResult:
    def __init__(self, league: str, category: str, source_url: str, method: str, endpoint: Optional[dict], artifacts: List[dict]):
        self.league = league
        self.category = category
        self.source_url = source_url
        self.method = method
        self.endpoint = endpoint
        self.artifacts = artifacts


def _sha1_bytes(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def _candidate_json(obj: Any) -> Tuple[int, Optional[str]]:
    if isinstance(obj, list) and obj:
        return 5, None
    if not isinstance(obj, dict):
        return 0, None
    for key in ("lines", "entries", "rows", "items"):
        if isinstance(obj.get(key), list) and obj[key]:
            return 10 + min(len(obj[key]), 200), key
    return 0, None


def _score_json(obj: Any) -> Tuple[int, Optional[str]]:
    base_score, key = _candidate_json(obj)
    if base_score == 0:
        return 0, None
    sample = obj
    if key and isinstance(obj.get(key), list):
        sample = obj[key][0] if obj[key] else {}
    if isinstance(sample, dict):
        for field in ("name", "icon", "currencyTypeName", "chaosValue", "value", "change", "low", "high"):
            if field in sample:
                base_score += 5
    return base_score, key


async def run_discovery(league: str, category: str) -> DiscoveryResult:
    ts = int(time.time())
    raw_base = RAW_DIR / "xhr" / str(ts)
    raw_base.mkdir(parents=True, exist_ok=True)
    artifacts: List[dict] = []
    page_url = f"{BASE_URL}/poe2/economy/{league}/{category}"

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(user_agent=USER_AGENT)
        main_json: Optional[Any] = None
        endpoint_meta: Optional[dict] = None
        best_score = 0

        page_html: Optional[str] = None

        async def handle_response(response):
            nonlocal main_json, endpoint_meta
            try:
                if response.request.resource_type not in {"fetch", "xhr"}:
                    return
                content_type = response.headers.get("content-type", "")
                body = await response.body()
                status = response.status
                url = response.url
                sha = _sha1_bytes(body)
                meta = {
                    "url": url,
                    "status": status,
                    "content_type": content_type,
                    "path": str(raw_base / f"{sha}.json"),
                }
                parsed: Optional[Any] = None
                if content_type.startswith("application/json") or body[:1] in {b"{", b"["}:
                    try:
                        parsed = json.loads(body.decode("utf-8", "ignore"))
                    except json.JSONDecodeError:
                        parsed = None
                if parsed is not None:
                    Path(meta["path"]).write_text(json.dumps(parsed, ensure_ascii=False), encoding="utf-8")
                    score, key = _score_json(parsed)
                    if score > best_score:
                        best_score = score
                        main_json = parsed
                        endpoint_meta = {
                            "url": url,
                            "json_path": key,
                            "method": "xhr",
                        }
                artifacts.append(meta)
            except Exception:
                return

        page.on("response", handle_response)
        await page.goto(page_url, wait_until="networkidle")
        page_html = await page.content()
        await browser.close()

    if main_json is None:
        html_path = RAW_DIR / "html" / f"{ts}.html"
        html_path.parent.mkdir(parents=True, exist_ok=True)
        html_path.write_text(page_html or "", encoding="utf-8")
        dom_path = RAW_DIR / "dom" / f"{ts}.json"
        dom_path.parent.mkdir(parents=True, exist_ok=True)
        dom_snapshot = {"html_path": str(html_path)}
        artifacts.append({"kind": "html", "path": str(html_path)})
        artifacts.append({"kind": "dom", "path": str(dom_path)})
        dom_path.write_text(json.dumps(dom_snapshot), encoding="utf-8")
        return DiscoveryResult(league, category, page_url, "playwright-dom", None, artifacts)

    return DiscoveryResult(league, category, page_url, "xhr", endpoint_meta, artifacts)


def save_source_map(result: DiscoveryResult) -> None:
    SOURCE_MAP_PATH.parent.mkdir(parents=True, exist_ok=True)
    existing: Dict[str, Any] = {}
    if SOURCE_MAP_PATH.exists():
        existing = json.loads(SOURCE_MAP_PATH.read_text(encoding="utf-8"))
    existing.setdefault(result.league, {})[result.category] = {
        "source_url": result.source_url,
        "method": result.method,
        "endpoint": result.endpoint,
    }
    SOURCE_MAP_PATH.write_text(json.dumps(existing, indent=2), encoding="utf-8")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Discover poe.ninja endpoints for a league/category")
    parser.add_argument("--league", required=True)
    parser.add_argument("--category", required=True)
    args = parser.parse_args()
    result = asyncio.run(run_discovery(args.league, args.category))
    save_source_map(result)
    print(f"Discovery finished for {args.league}/{args.category}: method={result.method}")


if __name__ == "__main__":
    main()
