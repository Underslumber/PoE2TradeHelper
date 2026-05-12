from __future__ import annotations

import csv
import io
import json
from typing import Iterable

from app.db.models import Row, Snapshot


def export_rows_csv(rows: Iterable[tuple[Row, Snapshot]]) -> str:
    buffer = io.StringIO()
    fieldnames = [
        "snapshot_id",
        "league",
        "category",
        "row_id",
        "name",
        "icon_url",
    ]
    seen_keys = set()
    normalized = []
    for row, snap in rows:
        cols = json.loads(row.columns_json)
        seen_keys.update(cols.keys())
        base = {
            "snapshot_id": row.snapshot_id,
            "league": snap.league,
            "category": snap.category,
            "row_id": row.row_id,
            "name": row.name,
            "icon_url": row.icon_url,
        }
        base.update({k: cols.get(k) for k in seen_keys})
        normalized.append(base)
    writer = csv.DictWriter(buffer, fieldnames=fieldnames + sorted(seen_keys))
    writer.writeheader()
    for row in normalized:
        writer.writerow(row)
    return buffer.getvalue()
