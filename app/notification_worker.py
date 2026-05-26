from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy import select

from app.db.models import PinnedPosition, TelegramNotificationRule
from app.db.session import get_session
from app.notifications import process_telegram_notifications
from app.trade2 import read_latest_rates


async def process_due_telegram_notifications(*, league: str | None = None) -> dict[str, Any]:
    with get_session() as db:
        stmt = (
            select(TelegramNotificationRule, PinnedPosition)
            .join(PinnedPosition, TelegramNotificationRule.pin_id == PinnedPosition.id)
            .where(TelegramNotificationRule.enabled == 1)
        )
        if league:
            stmt = stmt.where(PinnedPosition.league == league)
        rows = db.execute(stmt).all()
        groups: dict[tuple[str, str, str], int] = defaultdict(int)
        for _rule, pin in rows:
            groups[(pin.league, pin.category, pin.target_currency or "exalted")] += 1

        summary = {
            "groups": len(groups),
            "rules": len(rows),
            "checked": 0,
            "sent": 0,
            "skipped": 0,
            "failed": 0,
            "missing_snapshots": 0,
        }
        for group_league, category, target in groups:
            statuses = ("securable", "any", "online") if category == "ItemBases" else ("any", "online")
            snapshot = None
            for status in statuses:
                snapshot = read_latest_rates(group_league, category, target=target, status=status)
                if snapshot:
                    break
            if not snapshot:
                summary["missing_snapshots"] += 1
                continue
            result = await process_telegram_notifications(
                db,
                league=group_league,
                category=category,
                target=target,
                rows=snapshot.get("rows") or [],
                source=snapshot.get("source") or "",
            )
            for key in ("checked", "sent", "skipped", "failed"):
                summary[key] += int(result.get(key) or 0)
        return summary
