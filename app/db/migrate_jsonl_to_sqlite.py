import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.config import DATA_DIR
from app.db.models import MarketHistory
from app.db.session import get_session
from sqlalchemy import func, or_, select


def _json_dump(value) -> str | None:
    if value in (None, [], {}):
        return None
    return json.dumps(value, ensure_ascii=False)


def _float_or_none(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _positive_float(value):
    number = _float_or_none(value)
    return number if number is not None and number > 0 else None


def _positive_int(value):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _latest_jsonl_timestamp(history_path):
    try:
        with history_path.open("rb") as handle:
            handle.seek(0, 2)
            position = handle.tell()
            buffer = b""
            while position > 0:
                read_size = min(1024 * 1024, position)
                position -= read_size
                handle.seek(position)
                block = handle.read(read_size)
                parts = (block + buffer).split(b"\n")
                buffer = parts[0]
                for raw_line in reversed(parts[1:]):
                    if not raw_line:
                        continue
                    try:
                        snapshot = json.loads(raw_line.decode("utf-8", "ignore"))
                    except json.JSONDecodeError:
                        continue
                    return _float_or_none(snapshot.get("created_ts"))
            if buffer:
                try:
                    snapshot = json.loads(buffer.decode("utf-8", "ignore"))
                except json.JSONDecodeError:
                    return None
                return _float_or_none(snapshot.get("created_ts"))
    except OSError:
        return None
    return None


def _existing_records_for_snapshot(db, *, timestamp, league, category, target, status):
    rows = db.scalars(
        select(MarketHistory).where(
            MarketHistory.timestamp == float(timestamp),
            MarketHistory.league == str(league),
            MarketHistory.category == str(category),
            MarketHistory.target == str(target),
            MarketHistory.status == str(status or "any"),
        )
    ).all()
    return {row.item_id: row for row in rows}


def migrate_history(*, verbose: bool = True) -> None:
    history_path = DATA_DIR / "trade_rate_history.jsonl"
    if not history_path.exists():
        if verbose:
            print("No jsonl history file found.")
        return

    latest_jsonl_ts = _latest_jsonl_timestamp(history_path)

    with get_session() as db:
        max_db_ts = db.scalar(func.max(MarketHistory.timestamp))
        missing_source = (
            db.query(MarketHistory)
            .filter(or_(MarketHistory.source.is_(None), MarketHistory.source == ""))
            .first()
        )
        if latest_jsonl_ts and max_db_ts and float(max_db_ts) >= latest_jsonl_ts and missing_source is None:
            if verbose:
                print("SQLite market_history is already up to date.")
            return

        if verbose:
            print("Migrating history from JSONL to SQLite...")

        batch = []
        batch_size = 5000
        inserted = 0
        updated = 0

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

                created_at = datetime.fromtimestamp(created_ts_value, tz=timezone.utc).isoformat()
                existing = _existing_records_for_snapshot(
                    db,
                    timestamp=created_ts_value,
                    league=league,
                    category=category,
                    target=target,
                    status=status,
                )

                for row in rows:
                    item_id = row.get("id")
                    if not item_id:
                        continue

                    price = _positive_float(row.get("median") if row.get("median") is not None else row.get("best"))
                    if price is None:
                        continue

                    record = existing.get(str(item_id))
                    values = {
                        "league": league,
                        "category": category,
                        "target": target,
                        "status": status,
                        "source": source,
                        "item_id": item_id,
                        "price": price,
                        "volume": _positive_float(row.get("volume")),
                        "offers": _positive_int(row.get("offers")),
                        "change": _float_or_none(row.get("change")),
                        "sparkline_json": _json_dump(row.get("sparkline")),
                        "sparkline_kind": row.get("sparkline_kind"),
                        "max_volume_currency": row.get("max_volume_currency"),
                        "max_volume_rate": _float_or_none(row.get("max_volume_rate")),
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
                        record = MarketHistory(**values)
                        existing[str(item_id)] = record
                        batch.append(record)

                    if len(batch) >= batch_size:
                        db.add_all(batch)
                        db.commit()
                        inserted += len(batch)
                        batch.clear()

        if batch:
            db.add_all(batch)
            db.commit()
            inserted += len(batch)
        else:
            db.commit()

        if verbose:
            print(f"Migration complete. Inserted {inserted}, updated {updated} records in market_history.")


if __name__ == "__main__":
    migrate_history()
