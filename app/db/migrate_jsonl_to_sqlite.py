import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.config import DATA_DIR
from app.db.models import CacheEntry, MarketHistory
from app.db.session import get_session
from sqlalchemy import and_, func, or_, select


MIGRATION_MARKER_KEY = "migration:trade_rate_history_jsonl:v1"
MIGRATION_MARKER_EXPIRY_TS = 4102444800.0
RAW_GRANULARITY = "raw"
HOURLY_GRANULARITY = "hourly"
DAILY_GRANULARITY = "daily"


def _json_dump(value) -> str | None:
    if value in (None, [], {}):
        return None
    return json.dumps(value, ensure_ascii=False)


def _float_or_none(value):
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _positive_float(value):
    number = _float_or_none(value)
    return number if number is not None and number > 0 else None


def _positive_int(value):
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if number > 0 else None


def _file_identity(history_path: Path) -> dict[str, str | int]:
    stat = history_path.stat()
    return {
        "path": str(history_path.resolve()),
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }


def _existing_records_for_snapshot(db, *, timestamp, league, category, target, status, source):
    rows = db.scalars(
        select(MarketHistory).where(
            MarketHistory.timestamp == float(timestamp),
            MarketHistory.league == str(league),
            MarketHistory.category == str(category),
            MarketHistory.target == str(target),
            MarketHistory.status == str(status or "any"),
            func.coalesce(MarketHistory.source, "") == str(source or ""),
            MarketHistory.granularity == RAW_GRANULARITY,
        )
    ).all()
    return {row.item_id: row for row in rows}


def _compacted_item_ids(db, *, timestamp, league, category, target, status, source, item_ids):
    if not item_ids:
        return set()
    timestamp = float(timestamp)
    hourly_bucket = float(int(timestamp // 3600) * 3600)
    daily_bucket = float(int(timestamp // 86400) * 86400)
    return {
        record.item_id
        for record in db.scalars(
            select(MarketHistory)
            .where(MarketHistory.league == str(league))
            .where(MarketHistory.category == str(category))
            .where(MarketHistory.target == str(target))
            .where(MarketHistory.status == str(status or "any"))
            .where(func.coalesce(MarketHistory.source, "") == str(source or ""))
            .where(MarketHistory.item_id.in_(item_ids))
            .where(
                or_(
                    and_(
                        MarketHistory.granularity == HOURLY_GRANULARITY,
                        MarketHistory.timestamp == hourly_bucket,
                    ),
                    and_(
                        MarketHistory.granularity == DAILY_GRANULARITY,
                        MarketHistory.timestamp == daily_bucket,
                    ),
                )
            )
        ).all()
    }


def _completed_marker(db) -> CacheEntry | None:
    return db.get(CacheEntry, MIGRATION_MARKER_KEY)


def _begin_import_write_transaction(db) -> None:
    if db.get_bind().dialect.name == "sqlite":
        db.connection().exec_driver_sql("BEGIN IMMEDIATE")


def _store_completed_marker(db, identity, *, ambiguous_compacted_rows: int) -> None:
    marker = _completed_marker(db)
    payload = {**identity, "ambiguous_compacted_rows": ambiguous_compacted_rows}
    values = json.dumps(payload, sort_keys=True)
    if marker is None:
        marker = CacheEntry(
            key=MIGRATION_MARKER_KEY,
            data_json=values,
            created_ts=datetime.now(timezone.utc).timestamp(),
            expires_ts=MIGRATION_MARKER_EXPIRY_TS,
        )
        db.add(marker)
    else:
        marker.data_json = values
        marker.created_ts = datetime.now(timezone.utc).timestamp()
        marker.expires_ts = MIGRATION_MARKER_EXPIRY_TS


def migrate_history(*, verbose: bool = True) -> None:
    history_path = DATA_DIR / "trade_rate_history.jsonl"
    if not history_path.exists():
        if verbose:
            print("No jsonl history file found.")
        return

    try:
        identity_before = _file_identity(history_path)
    except OSError:
        if verbose:
            print("Не удалось прочитать метаданные файла истории; импорт пропущен.")
        return

    with get_session() as db:
        _begin_import_write_transaction(db)
        marker = _completed_marker(db)
        if marker is not None:
            try:
                marker_data = json.loads(marker.data_json)
            except (TypeError, json.JSONDecodeError):
                marker_data = None
            if isinstance(marker_data, dict) and all(
                marker_data.get(key) == value for key, value in identity_before.items()
            ):
                if verbose:
                    print("Файл истории уже импортирован; его размер и время изменения совпадают.")
                return

        if verbose:
            print("Migrating history from JSONL to SQLite...")

        batch = []
        batch_size = 5000
        inserted = 0
        updated = 0
        ambiguous_compacted_rows = 0
        pending_by_key = {}

        with history_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    snapshot = json.loads(line)
                except json.JSONDecodeError:
                    continue

                league = snapshot.get("league")
                category = snapshot.get("category")
                target = snapshot.get("target")
                status = snapshot.get("status") or "any"
                source = snapshot.get("source") or "trade2"
                created_ts = snapshot.get("created_ts")
                rows = snapshot.get("rows", [])

                if not (league and category and target and created_ts):
                    continue

                created_ts_value = _float_or_none(created_ts)
                if created_ts_value is None:
                    continue

                try:
                    created_at = datetime.fromtimestamp(created_ts_value, tz=timezone.utc).isoformat()
                except (OverflowError, OSError, ValueError):
                    continue
                existing = _existing_records_for_snapshot(
                    db,
                    timestamp=created_ts_value,
                    league=league,
                    category=category,
                    target=target,
                    status=status,
                    source=source,
                )
                item_ids = {str(row.get("id")) for row in rows if row.get("id")}
                ambiguous = _compacted_item_ids(
                    db,
                    timestamp=created_ts_value,
                    league=league,
                    category=category,
                    target=target,
                    status=status,
                    source=source,
                    item_ids=item_ids,
                )

                for row in rows:
                    item_id = row.get("id")
                    if not item_id:
                        continue

                    price = _positive_float(row.get("median") if row.get("median") is not None else row.get("best"))
                    if price is None:
                        continue

                    item_id = str(item_id)
                    if item_id in ambiguous:
                        ambiguous_compacted_rows += 1
                        continue
                    observation_key = (
                        str(league),
                        str(category),
                        str(target),
                        str(status or "any"),
                        str(source or ""),
                        created_ts_value,
                        item_id,
                        RAW_GRANULARITY,
                    )
                    record = pending_by_key.get(observation_key) or existing.get(item_id)
                    values = {
                        "league": league,
                        "category": category,
                        "target": target,
                        "status": status,
                        "source": source,
                        "item_id": item_id,
                        "min_ilvl": _positive_int(row.get("min_ilvl")),
                        "price": price,
                        "volume": _positive_float(row.get("volume")),
                        "offers": _positive_int(row.get("offers")),
                        "change": _float_or_none(row.get("change")),
                        "sparkline_json": _json_dump(row.get("sparkline")),
                        "sparkline_kind": row.get("sparkline_kind"),
                        "max_volume_currency": row.get("max_volume_currency"),
                        "max_volume_rate": _positive_float(row.get("max_volume_rate")),
                        "query_ids_json": _json_dump(snapshot.get("query_ids")),
                        "errors_json": _json_dump(snapshot.get("errors")),
                        "timestamp": created_ts_value,
                        "created_at": created_at,
                    }

                    if record:
                        for name, value in values.items():
                            setattr(record, name, value)
                        updated += 1
                    else:
                        record = MarketHistory(**values, granularity=RAW_GRANULARITY, samples=1)
                        existing[item_id] = record
                        pending_by_key[observation_key] = record
                        batch.append(record)

                    if len(batch) >= batch_size:
                        db.add_all(batch)
                        db.commit()
                        inserted += len(batch)
                        batch.clear()
                        pending_by_key.clear()
                        _begin_import_write_transaction(db)

        if batch:
            db.add_all(batch)
            db.commit()
            inserted += len(batch)
        else:
            db.commit()
        _begin_import_write_transaction(db)

        try:
            identity_after = _file_identity(history_path)
        except OSError:
            identity_after = None
        if identity_after == identity_before:
            _store_completed_marker(db, identity_before, ambiguous_compacted_rows=ambiguous_compacted_rows)
            db.commit()
        elif verbose:
            print("Файл истории изменился во время импорта; отметка завершения не сохранена.")

        if verbose:
            print(
                f"Импорт истории завершён. Добавлено {inserted}, обновлено {updated}, "
                f"пропущено неоднозначных compacted строк {ambiguous_compacted_rows}."
            )


if __name__ == "__main__":
    migrate_history()
