from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, select

from app.db.models import MarketHistory
from app.db.session import get_session


RAW_GRANULARITY = "raw"
HOURLY_GRANULARITY = "hourly"
DAILY_GRANULARITY = "daily"


@dataclass(frozen=True)
class CompactionPolicy:
    raw_days: int = 7
    hourly_days: int = 30


def _json_or_none(value: Any) -> str | None:
    if value in (None, [], {}):
        return None
    return json.dumps(value, ensure_ascii=False)


def _bucket(timestamp: float, granularity: str) -> float:
    seconds = 3600 if granularity == HOURLY_GRANULARITY else 86400
    return float(int(timestamp // seconds) * seconds)


def _sample_weight(record: MarketHistory) -> int:
    try:
        samples = int(record.samples or 1)
    except (TypeError, ValueError):
        samples = 1
    return max(1, samples)


def _weighted_average(records: list[MarketHistory], field: str) -> float | None:
    total = 0.0
    weight_total = 0
    for record in records:
        value = getattr(record, field, None)
        if value is None:
            continue
        weight = _sample_weight(record)
        total += float(value) * weight
        weight_total += weight
    return total / weight_total if weight_total else None


def _weighted_int(records: list[MarketHistory], field: str) -> int | None:
    value = _weighted_average(records, field)
    return round(value) if value is not None else None


def _aggregate(records: list[MarketHistory], granularity: str) -> MarketHistory:
    first = records[0]
    records = sorted(records, key=lambda item: item.timestamp)
    latest = records[-1]
    timestamp = _bucket(float(latest.timestamp), granularity)
    price = _weighted_average(records, "price")
    volume = _weighted_average(records, "volume")
    offers = _weighted_average(records, "offers")
    raw_count = _weighted_int(records, "raw_count")
    clean_count = _weighted_int(records, "clean_count")
    stale_count = _weighted_int(records, "stale_count")
    recent_listing_count = _weighted_int(records, "recent_listing_count")
    return MarketHistory(
        league=first.league,
        category=first.category,
        target=first.target,
        status=first.status or "any",
        source=latest.source,
        item_id=first.item_id,
        price=price if price is not None else latest.price,
        volume=volume,
        offers=round(offers) if offers is not None else None,
        raw_count=raw_count,
        clean_count=clean_count,
        stale_count=stale_count,
        recent_listing_count=recent_listing_count,
        high_demand=latest.high_demand,
        weak_activity=latest.weak_activity,
        change=latest.change,
        sparkline_json=latest.sparkline_json,
        sparkline_kind=latest.sparkline_kind,
        max_volume_currency=latest.max_volume_currency,
        max_volume_rate=latest.max_volume_rate,
        query_ids_json=latest.query_ids_json,
        errors_json=latest.errors_json,
        timestamp=timestamp,
        created_at=datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat(),
        granularity=granularity,
        samples=sum(_sample_weight(record) for record in records),
    )


def _group_records(records: list[MarketHistory], granularity: str) -> dict[tuple[Any, ...], list[MarketHistory]]:
    groups: dict[tuple[Any, ...], list[MarketHistory]] = defaultdict(list)
    for record in records:
        key = (
            record.league,
            record.category,
            record.target,
            record.status or "any",
            record.item_id,
            _bucket(float(record.timestamp), granularity),
        )
        groups[key].append(record)
    return groups


def _merge_existing_aggregates(db: Any, groups: dict[tuple[Any, ...], list[MarketHistory]], granularity: str) -> None:
    bucket_timestamps = sorted({key[-1] for key in groups})
    if not bucket_timestamps:
        return
    existing = db.scalars(
        select(MarketHistory)
        .where(MarketHistory.granularity == granularity)
        .where(MarketHistory.timestamp.in_(bucket_timestamps))
    ).all()
    for record in existing:
        key = (
            record.league,
            record.category,
            record.target,
            record.status or "any",
            record.item_id,
            _bucket(float(record.timestamp), granularity),
        )
        if key in groups:
            groups[key].append(record)


def compact_market_history(policy: CompactionPolicy | None = None, *, now_ts: float | None = None) -> dict[str, Any]:
    policy = policy or CompactionPolicy()
    now = now_ts if now_ts is not None else datetime.now(timezone.utc).timestamp()
    raw_cutoff = now - policy.raw_days * 86400
    hourly_cutoff = now - policy.hourly_days * 86400
    with get_session() as db:
        old_raw = db.scalars(
            select(MarketHistory)
            .where(MarketHistory.timestamp < raw_cutoff)
            .where((MarketHistory.granularity == RAW_GRANULARITY) | (MarketHistory.granularity.is_(None)))
        ).all()
        old_hourly = db.scalars(
            select(MarketHistory)
            .where(MarketHistory.timestamp < hourly_cutoff)
            .where(MarketHistory.granularity == HOURLY_GRANULARITY)
        ).all()

        hourly_groups = _group_records([record for record in old_raw if record.timestamp >= hourly_cutoff], HOURLY_GRANULARITY)
        daily_groups = _group_records([*old_hourly, *[record for record in old_raw if record.timestamp < hourly_cutoff]], DAILY_GRANULARITY)
        _merge_existing_aggregates(db, hourly_groups, HOURLY_GRANULARITY)
        _merge_existing_aggregates(db, daily_groups, DAILY_GRANULARITY)

        hourly_records = [_aggregate(records, HOURLY_GRANULARITY) for records in hourly_groups.values()]
        daily_records = [_aggregate(records, DAILY_GRANULARITY) for records in daily_groups.values()]

        affected = hourly_records + daily_records
        for record in affected:
            db.execute(
                delete(MarketHistory)
                .where(MarketHistory.league == record.league)
                .where(MarketHistory.category == record.category)
                .where(MarketHistory.target == record.target)
                .where(MarketHistory.status == record.status)
                .where(MarketHistory.item_id == record.item_id)
                .where(MarketHistory.timestamp == record.timestamp)
                .where(MarketHistory.granularity == record.granularity)
            )
        if affected:
            db.add_all(affected)

        raw_delete = db.execute(
            delete(MarketHistory)
            .where(MarketHistory.timestamp < raw_cutoff)
            .where((MarketHistory.granularity == RAW_GRANULARITY) | (MarketHistory.granularity.is_(None)))
        ).rowcount or 0
        hourly_delete = db.execute(
            delete(MarketHistory)
            .where(MarketHistory.timestamp < hourly_cutoff)
            .where(MarketHistory.granularity == HOURLY_GRANULARITY)
        ).rowcount or 0
        db.commit()
    return {
        "raw_cutoff_ts": raw_cutoff,
        "hourly_cutoff_ts": hourly_cutoff,
        "hourly_written": len(hourly_records),
        "daily_written": len(daily_records),
        "raw_deleted": raw_delete,
        "hourly_deleted": hourly_delete,
    }
