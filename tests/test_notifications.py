import asyncio

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.account import now_iso
from app.db.models import Base, PinnedPosition, TelegramNotificationRule, User
from app.notifications import (
    normalize_event_type,
    process_telegram_notifications,
    row_price,
    should_trigger,
)


def test_notification_event_validation():
    assert normalize_event_type("price_above") == "price_above"
    assert normalize_event_type("bad") == ""


def test_row_price_prefers_median_and_skips_bad_values():
    assert row_price({"median": 12, "best": 10}) == 12
    assert row_price({"best": "3.5"}) == 3.5
    assert row_price({"median": None}) is None


def test_price_above_triggers_on_threshold_crossing():
    rule = TelegramNotificationRule(event_type="price_above", threshold_value=10, last_price=9)

    triggered, reason = should_trigger(rule, 10.5)

    assert triggered is True
    assert reason == "price_above"


def test_change_pct_triggers_from_previous_snapshot():
    rule = TelegramNotificationRule(event_type="change_pct", threshold_value=10, last_price=100)

    triggered, reason = should_trigger(rule, 111)

    assert triggered is True
    assert reason == "change_pct"


def test_first_notification_check_only_sets_baseline():
    rule = TelegramNotificationRule(event_type="any_update", last_price=None)

    triggered, reason = should_trigger(rule, 5)

    assert triggered is False
    assert reason == "baseline"


def _memory_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)()


def _add_pin_with_rule(db, *, user_id, item_id, target_currency):
    now = now_iso()
    pin = PinnedPosition(
        user_id=user_id,
        league="Standard",
        category="Currency",
        item_id=item_id,
        item_name=item_id.title(),
        target_currency=target_currency,
        created_at=now,
        updated_at=now,
    )
    db.add(pin)
    db.flush()
    rule = TelegramNotificationRule(
        user_id=user_id,
        pin_id=pin.id,
        chat_id="123",
        event_type="any_update",
        enabled=1,
        created_at=now,
        updated_at=now,
    )
    db.add(rule)
    db.commit()
    return pin


def test_notifications_skip_rules_with_mismatched_currency_and_keep_pin_currency():
    db = _memory_session()
    now = now_iso()
    db.add(User(id=1, username="t", email="t@e.local", display_name="T", password_hash="x", created_at=now))
    db.commit()
    divine_pin = _add_pin_with_rule(db, user_id=1, item_id="divine", target_currency="divine")
    exalted_pin = _add_pin_with_rule(db, user_id=1, item_id="exalted", target_currency="exalted")

    result = asyncio.run(
        process_telegram_notifications(
            db,
            league="Standard",
            category="Currency",
            target="divine",
            rows=[{"id": "divine", "median": 42.0}],
            source="trade2",
        )
    )

    db.refresh(divine_pin)
    db.refresh(exalted_pin)
    # The pin tracked in another currency must not be re-priced or have its currency overwritten.
    assert exalted_pin.target_currency == "exalted"
    assert exalted_pin.last_price is None
    # The matching pin is updated, still in its own currency.
    assert divine_pin.target_currency == "divine"
    assert divine_pin.last_price == 42.0
    assert result["checked"] == 1
