from app.db.models import TelegramNotificationRule
from app.notifications import normalize_event_type, row_price, should_trigger


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
