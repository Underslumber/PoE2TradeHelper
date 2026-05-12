from __future__ import annotations

import json
from typing import Iterable

from app.db.models import Row, Snapshot


def export_rows_jsonl(rows: Iterable[tuple[Row, Snapshot]]) -> str:
    lines = []
    for row, snap in rows:
        obj = {
            "snapshot_id": row.snapshot_id,
            "league": snap.league,
            "category": snap.category,
            "row_id": row.row_id,
            "name": row.name,
            "icon_url": row.icon_url,
            "columns": json.loads(row.columns_json),
            "raw": json.loads(row.raw_json),
        }
        lines.append(json.dumps(obj, ensure_ascii=False))
    return "\n".join(lines)
