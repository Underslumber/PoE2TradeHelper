from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Dict, Optional

import httpx

from app.config import ICONS_DIR, USER_AGENT

_icon_cache: Dict[str, Path] = {}


def _extension_from_headers(content_type: str, url: str) -> str:
    if "png" in content_type:
        return "png"
    if "jpeg" in content_type or "jpg" in content_type:
        return "jpg"
    if "webp" in content_type:
        return "webp"
    if "." in url.rsplit("/", 1)[-1]:
        return url.rsplit(".", 1)[-1].split("?")[0]
    return "png"


async def fetch_icon(icon_url: str) -> Optional[Path]:
    if icon_url in _icon_cache:
        return _icon_cache[icon_url]
    ICONS_DIR.mkdir(parents=True, exist_ok=True)
    sha = hashlib.sha1(icon_url.encode("utf-8", "ignore")).hexdigest()
    try:
        async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}, timeout=30) as client:
            resp = await client.get(icon_url)
            resp.raise_for_status()
            ext = _extension_from_headers(resp.headers.get("content-type", ""), icon_url)
            target = ICONS_DIR / f"{sha}.{ext}"
            target.write_bytes(resp.content)
            _icon_cache[icon_url] = target
            return target
    except Exception:
        return None


def placeholder_svg() -> str:
    return (
        "<svg xmlns='http://www.w3.org/2000/svg' width='32' height='32' viewBox='0 0 32 32' fill='none'>"
        "<rect width='32' height='32' rx='4' fill='#1f1f1f' stroke='#3a3a3a'/>"
        "<text x='16' y='19' text-anchor='middle' fill='#888' font-size='10' font-family='sans-serif'>N/A</text>"
        "</svg>"
    )
