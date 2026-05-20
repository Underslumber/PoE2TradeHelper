from app.account import (
    build_trade_report,
    calculate_benchmark_adjusted_pnl,
    calculate_trade_pnl,
    hash_password,
    is_valid_email,
    normalize_email,
    normalize_username,
    verify_password,
)


def test_password_hash_verification():
    stored = hash_password("secret-pass")

    assert stored != "secret-pass"
    assert verify_password("secret-pass", stored) is True
    assert verify_password("wrong-pass", stored) is False


def test_normalize_username_is_case_insensitive_and_trimmed():
    assert normalize_username("  Hatzy Trader  ") == "hatzy trader"


def test_email_normalization_and_validation():
    assert normalize_email(" Trader@Example.COM ") == "trader@example.com"
    assert is_valid_email("trader@example.com") is True
    assert is_valid_email("not-an-email") is False


def test_calculate_trade_pnl_for_same_currency():
    pnl = calculate_trade_pnl(
        quantity=2,
        entry_price=10,
        entry_currency="exalted",
        exit_price=13,
        exit_currency="exalted",
    )

    assert pnl["pnl_available"] is True
    assert pnl["pnl_amount"] == 6
    assert pnl["pnl_percent"] == 30
    assert pnl["pnl_currency"] == "exalted"


def test_calculate_trade_pnl_skips_mixed_currency():
    pnl = calculate_trade_pnl(
        quantity=1,
        entry_price=10,
        entry_currency="exalted",
        exit_price=1,
        exit_currency="divine",
    )

    assert pnl["pnl_available"] is False
    assert pnl["pnl_amount"] is None
    assert pnl["pnl_currency"] == "divine"


def test_calculate_benchmark_adjusted_pnl_deflates_currency_gain():
    pnl = calculate_benchmark_adjusted_pnl(
        quantity=1,
        entry_price=100,
        entry_currency="exalted",
        current_price=150,
        current_currency="exalted",
        benchmark_currency="divine",
        entry_benchmark_price=100,
        current_benchmark_price=200,
    )

    assert pnl["real_pnl_available"] is True
    assert pnl["real_pnl_amount"] == -25
    assert pnl["real_pnl_percent"] == -25
    assert pnl["benchmark_change_percent"] == 100


def test_calculate_benchmark_adjusted_pnl_requires_benchmark_snapshot():
    pnl = calculate_benchmark_adjusted_pnl(
        quantity=1,
        entry_price=100,
        entry_currency="exalted",
        current_price=150,
        current_currency="exalted",
        benchmark_currency="divine",
        entry_benchmark_price=None,
        current_benchmark_price=200,
    )

    assert pnl["real_pnl_available"] is False
    assert pnl["real_pnl_amount"] is None


def test_build_trade_report_groups_by_currency_and_strategy():
    report = build_trade_report(
        [
            {
                "status": "closed",
                "strategy_tag": "flip",
                "pnl_available": True,
                "pnl_amount": 20,
                "pnl_currency": "exalted",
                "real_pnl_available": True,
                "real_pnl_amount": 5,
                "real_pnl_currency": "exalted",
                "fee_applied": 1,
                "fee_currency": "exalted",
                "entry_reason": "cheap",
                "exit_reason": "target",
            },
            {
                "status": "closed",
                "strategy_tag": "flip",
                "pnl_available": True,
                "pnl_amount": -3,
                "pnl_currency": "divine",
                "real_pnl_available": False,
                "fee_applied": 0.1,
                "fee_currency": "divine",
            },
            {
                "status": "open",
                "strategy_tag": "hold",
                "current_pnl_available": True,
                "current_pnl_amount": 4,
                "current_pnl_currency": "exalted",
            },
        ]
    )

    assert report["closed"] == 2
    assert report["open"] == 1
    assert report["wins"] == 1
    assert report["losses"] == 1
    assert report["nominal_closed_by_currency"] == {"exalted": 20.0, "divine": -3.0}
    assert report["real_closed_by_currency"] == {"exalted": 5.0}
    assert report["fees_by_currency"] == {"exalted": 1.0, "divine": 0.1}
    assert report["open_current_by_currency"] == {"exalted": 4.0}
    assert report["by_strategy"][0]["strategy_tag"] == "flip"
    assert report["by_strategy"][0]["win_rate"] == 50
