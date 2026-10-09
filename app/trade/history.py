import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import desc, func, select
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
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def _finite_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _positive_int(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if number > 0 else None


def _nonnegative_int(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if number >= 0 else None


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
        volume = _finite_float(record.volume)
        offers = _nonnegative_int(record.offers)
        rows.append(
            {
                "id": record.item_id,
                "min_ilvl": record.min_ilvl,
                "median": _positive_float(record.price),
                "best": _positive_float(record.price),
                "volume": volume if volume is not None else 0,
                "offers": offers if offers is not None else 0,
                "raw_count": _nonnegative_int(record.raw_count),
                "clean_count": _nonnegative_int(record.clean_count),
                "stale_count": _nonnegative_int(record.stale_count),
                "recent_listing_count": _nonnegative_int(record.recent_listing_count),
                "high_demand": bool(record.high_demand) if record.high_demand is not None else False,
                "weak_activity": bool(record.weak_activity) if record.weak_activity is not None else False,
                "change": _finite_float(record.change),
                "sparkline": _json_load(record.sparkline_json, []),
                "sparkline_kind": record.sparkline_kind,
                "max_volume_currency": record.max_volume_currency,
                "max_volume_rate": _positive_float(record.max_volume_rate),
            }
        )
    return {
        "created_ts": first.timestamp,
        "league": first.league,
        "category": first.category,
        "target": first.target,
        "status": first.status or "any",
        "source": first.source or "",
        "granularity": first.granularity or "raw",
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

    grouped: dict[tuple[Any, ...], list[MarketHistory]] = {}
    ordered_keys: list[tuple[Any, ...]] = []
    for record in records:
        timestamp = float(record.timestamp)
        key = (
            timestamp,
            record.league,
            record.category,
            record.target,
            record.status or "any",
            record.source or "",
            record.granularity or "raw",
        )
        if key not in grouped:
            grouped[key] = []
            ordered_keys.append(key)
        grouped[key].append(record)
    if limit <= 0:
        return []
    return [_snapshot_from_group(grouped[key]) for key in ordered_keys]


def _read_sqlite_item_snapshots(
    *,
    limit: int,
    league: str,
    category: str,
    target: str,
    status: str,
    item_id: str,
) -> tuple[bool, list[dict[str, Any]]]:
    """Сначала выбирает окно меток категории, затем читает строки нужного предмета."""
    try:
        with get_session() as db:
            filters = (
                MarketHistory.league == league,
                MarketHistory.category == category,
                MarketHistory.target == target,
                MarketHistory.status == status,
            )
            timestamp_stmt = (
                select(MarketHistory.timestamp)
                .where(*filters)
                .distinct()
                .order_by(desc(MarketHistory.timestamp))
                .limit(max(1, limit))
            )
            timestamps = db.scalars(timestamp_stmt).all()
            if not timestamps:
                return False, []
            if limit <= 0:
                return True, []

            # Прежняя функция брала метаданные снимка из строки с наименьшим id
            # для каждой метки времени, даже если снимки имели одинаковую метку.
            representatives = (
                select(func.min(MarketHistory.id).label("id"))
                .where(*filters, MarketHistory.timestamp.in_(timestamps))
                .group_by(
                    MarketHistory.timestamp,
                    func.coalesce(MarketHistory.source, ""),
                    func.coalesce(MarketHistory.granularity, "raw"),
                )
                .subquery()
            )
            representative_stmt = (
                select(MarketHistory)
                .join(representatives, MarketHistory.id == representatives.c.id)
                .order_by(MarketHistory.timestamp.desc(), MarketHistory.id.asc())
            )
            representative_rows = db.scalars(representative_stmt).all()

            item_stmt = (
                select(MarketHistory)
                .where(*filters, MarketHistory.timestamp.in_(timestamps), MarketHistory.item_id == item_id)
                .order_by(MarketHistory.timestamp.desc(), MarketHistory.id.asc())
            )
            item_rows = db.scalars(item_stmt).all()
    except SQLAlchemyError:
        return False, []

    metadata = {
        (float(record.timestamp), record.source or "", record.granularity or "raw"): record
        for record in representative_rows
    }
    grouped: dict[tuple[float, str, str], list[MarketHistory]] = {}
    for record in item_rows:
        key = (float(record.timestamp), record.source or "", record.granularity or "raw")
        grouped.setdefault(key, []).append(record)

    snapshots: list[dict[str, Any]] = []
    for timestamp in sorted(timestamps, reverse=True):
        timestamp = float(timestamp)
        keys = sorted(key for key in grouped if key[0] == timestamp)
        for key in keys:
            snapshot = _snapshot_from_group(grouped[key])
            representative = metadata.get(key)
            if representative is not None:
                snapshot["source"] = representative.source or ""
            snapshots.append(snapshot)
    return True, snapshots


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

    timestamp = _finite_float(created_ts)
    if timestamp is None:
        return
    try:
        created_at = datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()
    except (OverflowError, OSError, ValueError):
        return
    status = snapshot.get("status") or "any"
    source = snapshot.get("source") or ""
    query_ids_json = _json_dump(snapshot.get("query_ids"))
    errors_json = _json_dump(snapshot.get("errors"))
    records = []
    seen_item_ids: set[str] = set()
    for row in rows:
        item_id = row.get("id")
        price = _history_row_price(row)
        if not item_id or price is None or item_id in seen_item_ids:
            continue
        seen_item_ids.add(item_id)
        records.append(
            MarketHistory(
                league=league,
                category=category,
                target=target,
                status=status,
                source=source,
                item_id=item_id,
                min_ilvl=_positive_int(row.get("min_ilvl")),
                price=price,
                volume=_positive_float(row.get("volume")),
                offers=_positive_int(row.get("offers")),
                raw_count=_nonnegative_int(row.get("raw_count")),
                clean_count=_nonnegative_int(row.get("clean_count")),
                stale_count=_nonnegative_int(row.get("stale_count")),
                recent_listing_count=_nonnegative_int(row.get("recent_listing_count")),
                high_demand=1 if row.get("high_demand") else 0,
                weak_activity=1 if row.get("weak_activity") else 0,
                change=_finite_float(row.get("change")),
                sparkline_json=_json_dump(row.get("sparkline")),
                sparkline_kind=row.get("sparkline_kind"),
                max_volume_currency=row.get("max_volume_currency"),
                max_volume_rate=_positive_float(row.get("max_volume_rate")),
                query_ids_json=query_ids_json,
                errors_json=errors_json,
                timestamp=timestamp,
                created_at=created_at,
                granularity="raw",
                samples=1,
            )
        )
    if not records:
        return
    with get_session() as db:
        if db.get_bind().dialect.name == "sqlite":
            db.connection().exec_driver_sql("BEGIN IMMEDIATE")
        existing_ids = set(
            db.scalars(
                select(MarketHistory.item_id)
                .where(MarketHistory.league == league)
                .where(MarketHistory.category == category)
                .where(MarketHistory.target == target)
                .where(MarketHistory.status == status)
                .where(func.coalesce(MarketHistory.source, "") == source)
                .where(MarketHistory.timestamp == timestamp)
                .where(MarketHistory.granularity == "raw")
                .where(MarketHistory.item_id.in_([record.item_id for record in records]))
            ).all()
        )
        new_records = [record for record in records if record.item_id not in existing_ids]
        if not new_records:
            db.rollback()
            return
        db.add_all(new_records)
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
    snapshots = None
    if history_path == DEFAULT_HISTORY_PATH or history_path is None or not history_path.exists():
        category_found, item_snapshots = _read_sqlite_item_snapshots(
            limit=limit,
            league=league,
            category=category,
            target=target,
            status=status,
            item_id=item_id,
        )
        if category_found:
            snapshots = item_snapshots
    if snapshots is None:
        snapshots = read_market_history(
            limit=limit,
            league=league,
            category=category,
            target=target,
            status=status,
            history_path=history_path,
        )
    series: list[dict[str, Any]] = []
    seen: set[tuple[float, str, str]] = set()
    for snapshot in sorted(snapshots, key=lambda item: float(item.get("created_ts") or 0)):
        try:
            created_ts = float(snapshot.get("created_ts"))
        except (TypeError, ValueError):
            continue
        identity = (created_ts, snapshot.get("source") or "", snapshot.get("granularity") or "raw")
        if created_ts <= 0 or identity in seen:
            continue
        row = next((item for item in snapshot.get("rows") or [] if item.get("id") == item_id), None)
        value = _history_row_metric(row, metric)
        if value is None:
            continue
        seen.add(identity)
        series.append(
            {
                "created_ts": created_ts,
                "value": value,
                "price": _history_row_price(row),
                "volume": (row or {}).get("volume", 0),
                "offers": (row or {}).get("offers", 0),
                "raw_count": (row or {}).get("raw_count"),
                "clean_count": (row or {}).get("clean_count"),
                "stale_count": (row or {}).get("stale_count"),
                "recent_listing_count": (row or {}).get("recent_listing_count"),
                "high_demand": (row or {}).get("high_demand"),
                "recent_high_demand": (row or {}).get("recent_high_demand"),
                "recent_high_demand_count": (row or {}).get("recent_high_demand_count"),
                "recent_high_demand_age_seconds": (row or {}).get("recent_high_demand_age_seconds"),
                "weak_activity": (row or {}).get("weak_activity"),
                "change": (row or {}).get("change"),
                "source": snapshot.get("source") or "",
                "granularity": snapshot.get("granularity") or "raw",
            }
        )
    return series
