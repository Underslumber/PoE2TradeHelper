from __future__ import annotations

import os
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.account import now_iso
from app.db.models import PinnedPosition, TelegramNotificationRule


SUPPORTED_TELEGRAM_EVENTS = {"price_above", "price_below", "change_pct", "any_update"}


def telegram_bot_token() -> str:
    return os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()


def telegram_is_configured() -> bool:
    return bool(telegram_bot_token())


def normalize_event_type(value: str) -> str:
    event_type = str(value or "").strip()
    return event_type if event_type in SUPPORTED_TELEGRAM_EVENTS else ""


def row_price(row: dict[str, Any] | None) -> float | None:
    if not row:
        return None
    value = row.get("median", row.get("best"))
    try:
        price = float(value)
    except (TypeError, ValueError):
        return None
    return price if price > 0 else None


def notification_rule_payload(rule: TelegramNotificationRule, pin: PinnedPosition | None) -> dict[str, Any]:
    return {
        "id": rule.id,
        "pin_id": rule.pin_id,
        "chat_id": rule.chat_id,
        "event_type": rule.event_type,
        "threshold_value": rule.threshold_value,
        "enabled": bool(rule.enabled),
        "last_price": rule.last_price,
        "last_triggered_at": rule.last_triggered_at,
        "created_at": rule.created_at,
        "updated_at": rule.updated_at,
        "pin": None if not pin else {
            "id": pin.id,
            "league": pin.league,
            "category": pin.category,
            "item_id": pin.item_id,
            "item_name": pin.item_name,
            "item_name_ru": pin.item_name_ru,
            "icon_url": pin.icon_url,
            "target_currency": pin.target_currency,
            "last_price": pin.last_price,
        },
    }


def should_trigger(rule: TelegramNotificationRule, current_price: float) -> tuple[bool, str]:
    previous_price = rule.last_price
    threshold = rule.threshold_value
    if previous_price is None:
        return False, "baseline"
    if rule.event_type == "any_update":
        return abs(current_price - previous_price) > 0.000001, "any_update"
    if threshold is None:
        return False, "missing_threshold"
    if rule.event_type == "price_above":
        return current_price >= threshold and previous_price < threshold, "price_above"
    if rule.event_type == "price_below":
        return current_price <= threshold and previous_price > threshold, "price_below"
    if rule.event_type == "change_pct":
        if previous_price <= 0:
            return False, "bad_previous_price"
        change_pct = abs((current_price - previous_price) / previous_price * 100)
        return change_pct >= threshold, "change_pct"
    return False, "unsupported"


def message_for_rule(
    rule: TelegramNotificationRule,
    pin: PinnedPosition,
    current_price: float,
    target: str,
    reason: str,
) -> str:
    previous = "-" if rule.last_price is None else f"{rule.last_price:g} {target}"
    threshold = "" if rule.threshold_value is None else f"\nПорог: {rule.threshold_value:g}"
    name = pin.item_name_ru or pin.item_name
    return (
        "PoE2 Trade Helper\n"
        f"{name}\n"
        f"{pin.league} / {pin.category}\n"
        f"Событие: {reason}\n"
        f"Цена: {current_price:g} {target}\n"
        f"Было: {previous}"
        f"{threshold}"
    )


async def send_telegram_message(chat_id: str, text: str) -> None:
    token = telegram_bot_token()
    if not token:
        raise RuntimeError("telegram bot token is not configured")
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": text,
                "disable_web_page_preview": True,
            },
        )
        response.raise_for_status()


async def send_test_notification(rule: TelegramNotificationRule, pin: PinnedPosition) -> None:
    target = pin.target_currency or "exalted"
    price = rule.last_price or pin.last_price or 0
    await send_telegram_message(
        rule.chat_id,
        message_for_rule(rule, pin, float(price), target, "test"),
    )


async def process_telegram_notifications(
    db: Session,
    *,
    league: str,
    category: str,
    target: str,
    rows: list[dict[str, Any]],
    source: str,
) -> dict[str, int]:
    row_map = {str(row.get("id")): row for row in rows}
    rules = db.execute(
        select(TelegramNotificationRule, PinnedPosition)
        .join(PinnedPosition, TelegramNotificationRule.pin_id == PinnedPosition.id)
        .where(
            TelegramNotificationRule.enabled == 1,
            PinnedPosition.league == league,
            PinnedPosition.category == category,
        )
    ).all()
    result = {"checked": 0, "sent": 0, "skipped": 0, "failed": 0}
    configured = telegram_is_configured()
    now = now_iso()
    for rule, pin in rules:
        # The incoming prices are denominated in `target`; comparing them against
        # a pin tracked in another currency would be meaningless, and overwriting
        # the pin's currency from an unrelated request corrupts the user's choice.
        if (pin.target_currency or "exalted") != target:
            result["skipped"] += 1
            continue
        row = row_map.get(pin.item_id)
        current_price = row_price(row)
        if current_price is None:
            result["skipped"] += 1
            continue
        result["checked"] += 1
        triggered, reason = should_trigger(rule, current_price)
        if triggered and configured:
            try:
                await send_telegram_message(
                    rule.chat_id,
                    message_for_rule(rule, pin, current_price, target, reason),
                )
                rule.last_triggered_at = now
                result["sent"] += 1
            except httpx.HTTPError:
                result["failed"] += 1
        elif triggered:
            result["skipped"] += 1
        rule.last_price = current_price
        rule.updated_at = now
        pin.last_price = current_price
        pin.last_source = source
        pin.updated_at = now
    db.commit()
    return result
