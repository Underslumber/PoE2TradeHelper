from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Optional


def extract_rows(payload: Dict[str, Any], json_path: Optional[str] = None) -> List[Dict[str, Any]]:
    if json_path and isinstance(payload.get(json_path), list):
        return payload[json_path]
    for key in ("lines", "entries", "rows", "items"):
        if isinstance(payload.get(key), list):
            return payload[key]
    return []


def build_row_id(league: str, category: str, row: Dict[str, Any]) -> str:
    raw_key = f"{league}|{category}|{row.get('id') or row.get('name') or row.get('currencyTypeName', '')}"
    return hashlib.sha1(raw_key.encode("utf-8", "ignore")).hexdigest()


def normalize_row(row: Dict[str, Any]) -> Dict[str, Any]:
    columns = {k: v for k, v in row.items() if k not in {"name", "icon"}}
    name = row.get("name") or row.get("currencyTypeName") or row.get("id") or "unknown"
    return {
        "name": name,
        "icon_url": row.get("icon"),
        "columns": columns,
        "raw": row,
    }
