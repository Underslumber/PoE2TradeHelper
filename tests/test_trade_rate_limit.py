from __future__ import annotations

from app.trade.rate_limit import trade2_rate_limit_delay


def test_trade2_rate_limit_delay_uses_retry_after() -> None:
    assert trade2_rate_limit_delay({"Retry-After": "17"}) >= 17


def test_trade2_rate_limit_delay_slows_down_when_window_is_nearly_full() -> None:
    delay = trade2_rate_limit_delay(
        {
            "X-Rate-Limit-Rules": "Ip",
            "X-Rate-Limit-Ip": "20:5:60",
            "X-Rate-Limit-Ip-State": "19:5:0",
        }
    )

    assert delay >= 5


def test_trade2_rate_limit_delay_uses_active_restriction() -> None:
    delay = trade2_rate_limit_delay(
        {
            "X-Rate-Limit-Rules": "client",
            "X-Rate-Limit-Client": "10:5:10",
            "X-Rate-Limit-Client-State": "11:5:10",
        }
    )

    assert delay >= 10
