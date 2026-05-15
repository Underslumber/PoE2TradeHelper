import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import desc, select
from sqlalchemy.exc import SQLAlchemyError

from app.config import DATA_DIR
from app.db.models import MarketHistory
from app.db.session import get_session

DEFAULT_HISTORY_PATH = DATA_DIR / "trade_rate_history.jsonl"


def _json_dump(value: Any) -> str | None:
    if value in (None, [], {}):
        return None
    return json.dumps(value, ensure_ascii=False)


def _json_load(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def _positive_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _positive_int(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _history_row_price(row: dict[str, Any] | None) -> float | None:
    if not row:
        return None
    for key in ("median", "best"):
        value = _positive_float(row.get(key))
        if value is not None:
            return value
    return None


def _history_row_metric(row: dict[str, Any] | None, metric: str) -> float | None:
    if metric in {"demand", "volume"}:
        return _positive_float((row or {}).get("volume"))
    if metric == "offers":
        return _positive_float((row or {}).get("offers"))
    return _history_row_price(row)


def _iter_jsonl_lines_reverse(path: Path, block_size: int = 1024 * 1024) -> Iterable[str]:
    with path.open("rb") as handle:
        handle.seek(0, 2)
        position = handle.tell()
        buffer = b""
        while position > 0:
            read_size = min(block_size, position)
            position -= read_size
            handle.seek(position)
            block = handle.read(read_size)
            parts = (block + buffer).split(b"\n")
            buffer = parts[0]
            for line in reversed(parts[1:]):
                if line:
                    yield line.decode("utf-8", "ignore")
        if buffer:
            yield buffer.decode("utf-8", "ignore")


def _read_jsonl_history(
    *,
    history_path: Path,
    limit: int,
    league: str | None = None,
    category: str | None = None,
    target: str | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    if not history_path.exists():
        return []
    history: list[dict[str, Any]] = []
    for line in _iter_jsonl_lines_reverse(history_path):
        try:
            snapshot = json.loads(line)
        except json.JSONDecodeError:
            continue
        if league and snapshot.get("league") != league:
            continue
        if category and snapshot.get("category") != category:
            continue
        if target and snapshot.get("target") != target:
            continue
        if status and snapshot.get("status") != status:
            continue
        history.append(snapshot)
        if len(history) >= limit:
            break
    return history


def _snapshot_from_group(records: list[MarketHistory]) -> dict[str, Any]:
    first = records[0]
    rows = []
    for record in records:
        rows.append(
            {
                "id": record.item_id,
                "median": record.price,
                "best": record.price,
                "volume": record.volume or 0,
                "offers": record.offers or 0,
                "change": record.change,
                "sparkline": _json_load(record.sparkline_json, []),
                "sparkline_kind": record.sparkline_kind,
                "max_volume_currency": record.max_volume_currency,
                "max_volume_rate": record.max_volume_rate,
            }
        )
    return {
        "created_ts": first.timestamp,
        "league": first.league,
        "category": first.category,
        "target": first.target,
        "status": first.status or "any",
        "source": first.source or "",
        "query_ids": _json_load(first.query_ids_json, []),
        "errors": _json_load(first.errors_json, []),
        "rows": rows,
    }


def _read_sqlite_history(
    *,
    limit: int,
    league: str | None = None,
    category: str | None = None,
    target: str | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    try:
        with get_session() as db:
            timestamp_stmt = select(MarketHistory.timestamp).distinct()
            if league:
                timestamp_stmt = timestamp_stmt.where(MarketHistory.league == league)
            if category:
                timestamp_stmt = timestamp_stmt.where(MarketHistory.category == category)
            if target:
                timestamp_stmt = timestamp_stmt.where(MarketHistory.target == target)
            if status:
                timestamp_stmt = timestamp_stmt.where(MarketHistory.status == status)
            timestamp_stmt = timestamp_stmt.order_by(desc(MarketHistory.timestamp)).limit(max(1, limit))
            timestamps = db.scalars(timestamp_stmt).all()
            if not timestamps:
                return []

            records_stmt = select(MarketHistory).where(MarketHistory.timestamp.in_(timestamps))
            if league:
                records_stmt = records_stmt.where(MarketHistory.league == league)
            if category:
                records_stmt = records_stmt.where(MarketHistory.category == category)
            if target:
                records_stmt = records_stmt.where(MarketHistory.target == target)
            if status:
                records_stmt = records_stmt.where(MarketHistory.status == status)
            records_stmt = records_stmt.order_by(desc(MarketHistory.timestamp), MarketHistory.id.asc())
            records = db.scalars(records_stmt).all()
    except SQLAlchemyError:
        return []

    grouped: dict[float, list[MarketHistory]] = {}
    ordered_timestamps: list[float] = []
    for record in records:
        timestamp = float(record.timestamp)
        if timestamp not in grouped:
            grouped[timestamp] = []
            ordered_timestamps.append(timestamp)
        grouped[timestamp].append(record)
    return [_snapshot_from_group(grouped[timestamp]) for timestamp in ordered_timestamps[:limit]]


def _write_jsonl(snapshot: Dict[str, Any], history_path: Path) -> None:
    history_path.parent.mkdir(parents=True, exist_ok=True)
    with history_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(snapshot, ensure_ascii=False) + "\n")


def _write_sqlite(snapshot: Dict[str, Any]) -> None:
    league = snapshot.get("league")
    category = snapshot.get("category")
    target = snapshot.get("target")
    created_ts = snapshot.get("created_ts")
    rows = snapshot.get("rows") or []
    if not (league and category and target and created_ts):
        return

    created_at = datetime.fromtimestamp(float(created_ts), tz=timezone.utc).isoformat()
    status = snapshot.get("status") or "any"
    source = snapshot.get("source") or ""
    query_ids_json = _json_dump(snapshot.get("query_ids"))
    errors_json = _json_dump(snapshot.get("errors"))
    records = []
    for row in rows:
        item_id = row.get("id")
        price = _history_row_price(row)
        if not item_id or price is None:
            continue
        records.append(
            MarketHistory(
                league=league,
                category=category,
                target=target,
                status=status,
                source=source,
                item_id=item_id,
                price=price,
                volume=_positive_float(row.get("volume")),
                offers=_positive_int(row.get("offers")),
                change=_positive_float(row.get("change")),
                sparkline_json=_json_dump(row.get("sparkline")),
                sparkline_kind=row.get("sparkline_kind"),
                max_volume_currency=row.get("max_volume_currency"),
                max_volume_rate=_positive_float(row.get("max_volume_rate")),
                query_ids_json=query_ids_json,
                errors_json=errors_json,
                timestamp=float(created_ts),
                created_at=created_at,
            )
        )
    if not records:
        return
    with get_session() as db:
        db.add_all(records)
        db.commit()


def log_market_history(
    snapshot: Dict[str, Any],
    history_path: Path | None = DEFAULT_HISTORY_PATH,
    *,
    write_jsonl: bool = False,
    write_sqlite: bool = True,
) -> None:
    wrote_sqlite = False
    if write_sqlite:
        try:
            _write_sqlite(snapshot)
            wrote_sqlite = True
        except SQLAlchemyError:
            wrote_sqlite = False
    if (write_jsonl or not wrote_sqlite) and history_path is not None:
        _write_jsonl(snapshot, history_path)


def read_market_history(
    limit: int = 30,
    league: Optional[str] = None,
    category: Optional[str] = None,
    target: Optional[str] = None,
    status: Optional[str] = None,
    history_path: Path | None = DEFAULT_HISTORY_PATH,
    prefer_sqlite: bool = True,
) -> List[Dict[str, Any]]:
    if history_path is not None and history_path != DEFAULT_HISTORY_PATH and history_path.exists():
        return _read_jsonl_history(
            history_path=history_path,
            limit=limit,
            league=league,
            category=category,
            target=target,
            status=status,
        )
    if prefer_sqlite:
        history = _read_sqlite_history(limit=limit, league=league, category=category, target=target, status=status)
        if history:
            return history
    if history_path is not None and history_path.exists():
        return _read_jsonl_history(
            history_path=history_path,
            limit=limit,
            league=league,
            category=category,
            target=target,
            status=status,
        )
    return _read_sqlite_history(limit=limit, league=league, category=category, target=target, status=status)


def read_latest_rates(
    league: str,
    category: str,
    target: str = "exalted",
    status: str = "any",
    history_path: Path | None = DEFAULT_HISTORY_PATH,
) -> Optional[Dict[str, Any]]:
    snapshots = read_market_history(
        limit=1,
        league=league,
        category=category,
        target=target,
        status=status,
        history_path=history_path,
    )
    if not snapshots:
        return None
    snapshot = dict(snapshots[0])
    snapshot["cached"] = True
    return snapshot


def read_item_history(
    league: str,
    category: str,
    target: str,
    status: str,
    item_id: str,
    metric: str = "price",
    limit: int = 1500,
    history_path: Path | None = DEFAULT_HISTORY_PATH,
) -> List[Dict[str, Any]]:
    snapshots = read_market_history(
        limit=limit,
        league=league,
        category=category,
        target=target,
        status=status,
        history_path=history_path,
    )
    series: list[dict[str, Any]] = []
    seen: set[float] = set()
    for snapshot in sorted(snapshots, key=lambda item: float(item.get("created_ts") or 0)):
        try:
            created_ts = float(snapshot.get("created_ts"))
        except (TypeError, ValueError):
            continue
        if created_ts <= 0 or created_ts in seen:
            continue
        row = next((item for item in snapshot.get("rows") or [] if item.get("id") == item_id), None)
        value = _history_row_metric(row, metric)
        if value is None:
            continue
        seen.add(created_ts)
        series.append(
            {
                "created_ts": created_ts,
                "value": value,
                "price": _history_row_price(row),
                "volume": (row or {}).get("volume", 0),
                "offers": (row or {}).get("offers", 0),
                "change": (row or {}).get("change"),
                "source": snapshot.get("source") or "",
            }
        )
    return series
