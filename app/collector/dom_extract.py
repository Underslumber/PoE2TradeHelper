from __future__ import annotations

import time
from typing import Any, Dict, List

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

from app.config import BASE_URL, RAW_DIR, USER_AGENT


def _rows_from_dom(html: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    rows: List[Dict[str, Any]] = []
    if not table:
        return rows
    headers = [th.get_text(strip=True) for th in table.find_all("th")]
    for tr in table.find_all("tr"):
        cells = [td.get_text(strip=True) for td in tr.find_all("td")]
        if not cells:
            continue
        row = {"name": cells[0], "columns": {}}
        for idx, cell in enumerate(cells[1:], start=1):
            key = headers[idx] if idx < len(headers) else f"col_{idx}"
            row["columns"][key] = cell
        rows.append(row)
    return rows


async def extract_dom_rows(league: str, category: str) -> List[Dict[str, Any]]:
    ts = int(time.time())
    target = RAW_DIR / "html" / f"{ts}.html"
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(user_agent=USER_AGENT)
        await page.goto(f"{BASE_URL}/poe2/economy/{league}/{category}", wait_until="networkidle")
        content = await page.content()
        await browser.close()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return _rows_from_dom(content)
