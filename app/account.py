from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import smtplib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from typing import Any


PASSWORD_ITERATIONS = 260_000
SESSION_DAYS = 30
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def now_iso() -> str:
    return utc_now().isoformat()


def session_expires_iso() -> str:
    return (utc_now() + timedelta(days=SESSION_DAYS)).isoformat()


def normalize_username(value: str) -> str:
    return " ".join(str(value or "").strip().lower().split())


def normalize_email(value: str) -> str:
    return str(value or "").strip().lower()


def is_valid_email(value: str) -> bool:
    return bool(EMAIL_RE.match(normalize_email(value)))


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("ascii"),
        PASSWORD_ITERATIONS,
    ).hex()
    return f"pbkdf2_sha256${PASSWORD_ITERATIONS}${salt}${digest}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, iterations_text, salt, expected = stored_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("ascii"),
            int(iterations_text),
        ).hex()
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest, expected)


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def new_email_verification_token() -> str:
    return secrets.token_urlsafe(40)


def smtp_is_configured() -> bool:
    return bool(os.environ.get("SMTP_HOST") and os.environ.get("SMTP_FROM"))


def send_verification_email(to_email: str, verification_url: str) -> bool:
    if not smtp_is_configured():
        return False
    message = EmailMessage()
    message["Subject"] = "PoE2 Trade Helper email confirmation"
    message["From"] = os.environ["SMTP_FROM"]
    message["To"] = to_email
    message.set_content(
        "Confirm your PoE2 Trade Helper account by opening this link:\n\n"
        f"{verification_url}\n\n"
        "If you did not create this account, ignore this message.\n"
    )
    host = os.environ["SMTP_HOST"]
    port = int(os.environ.get("SMTP_PORT", "587"))
    username = os.environ.get("SMTP_USERNAME")
    password = os.environ.get("SMTP_PASSWORD")
    use_tls = os.environ.get("SMTP_TLS", "true").lower() not in {"0", "false", "no"}
    with smtplib.SMTP(host, port, timeout=15) as smtp:
        if use_tls:
            smtp.starttls()
        if username and password:
            smtp.login(username, password)
        smtp.send_message(message)
    return True


def calculate_trade_pnl(
    *,
    quantity: float | None,
    entry_price: float | None,
    entry_currency: str | None,
    exit_price: float | None,
    exit_currency: str | None,
    fee_amount: float | None = None,
    fee_currency: str | None = None,
) -> dict:
    if (
        quantity is None
        or entry_price is None
        or exit_price is None
        or not entry_currency
        or not exit_currency
        or entry_currency != exit_currency
    ):
        return {
            "pnl_available": False,
            "pnl_amount": None,
            "pnl_percent": None,
            "pnl_currency": exit_currency or entry_currency,
        }
    gross_amount = (exit_price - entry_price) * quantity
    fee = fee_amount if fee_currency == exit_currency and fee_amount is not None else 0
    amount = gross_amount - fee
    percent = ((exit_price - entry_price) / entry_price * 100) if entry_price else None
    net_percent = (amount / (entry_price * quantity) * 100) if entry_price and quantity else percent
    return {
        "pnl_available": True,
        "pnl_amount": amount,
        "pnl_percent": net_percent,
        "pnl_currency": exit_currency,
        "gross_pnl_amount": gross_amount,
        "fee_applied": fee,
    }


def calculate_benchmark_adjusted_pnl(
    *,
    quantity: float | None,
    entry_price: float | None,
    entry_currency: str | None,
    current_price: float | None,
    current_currency: str | None,
    benchmark_currency: str | None,
    entry_benchmark_price: float | None,
    current_benchmark_price: float | None,
) -> dict:
    if (
        quantity is None
        or entry_price is None
        or current_price is None
        or not entry_currency
        or not current_currency
        or entry_currency != current_currency
        or not benchmark_currency
        or entry_benchmark_price is None
        or current_benchmark_price is None
        or entry_price <= 0
        or entry_benchmark_price <= 0
        or current_benchmark_price <= 0
    ):
        return {
            "real_pnl_available": False,
            "real_pnl_amount": None,
            "real_pnl_percent": None,
            "real_pnl_currency": entry_currency or current_currency,
            "benchmark_currency": benchmark_currency,
            "benchmark_change_percent": None,
        }
    nominal_ratio = current_price / entry_price
    benchmark_ratio = current_benchmark_price / entry_benchmark_price
    real_percent = (nominal_ratio / benchmark_ratio - 1) * 100
    entry_total = entry_price * quantity
    current_total = current_price * quantity
    real_current_total = current_total / benchmark_ratio
    return {
        "real_pnl_available": True,
        "real_pnl_amount": real_current_total - entry_total,
        "real_pnl_percent": real_percent,
        "real_pnl_currency": entry_currency,
        "benchmark_currency": benchmark_currency,
        "benchmark_change_percent": (benchmark_ratio - 1) * 100,
    }


def _add_currency_amount(bucket: dict[str, float], currency: str | None, amount: Any) -> None:
    try:
        value = float(amount)
    except (TypeError, ValueError):
        return
    if not currency or value == 0:
        return
    bucket[currency] = bucket.get(currency, 0.0) + value


def _strategy_report(tag: str) -> dict[str, Any]:
    return {
        "strategy_tag": tag,
        "total": 0,
        "open": 0,
        "closed": 0,
        "wins": 0,
        "losses": 0,
        "break_even": 0,
        "fees_by_currency": {},
        "nominal_by_currency": {},
        "real_by_currency": {},
        "entry_reasons": 0,
        "exit_reasons": 0,
    }


def build_trade_report(trades: list[dict[str, Any]]) -> dict[str, Any]:
    report: dict[str, Any] = {
        "schema_version": "poe2-trade-report/v1",
        "total": len(trades),
        "open": 0,
        "closed": 0,
        "wins": 0,
        "losses": 0,
        "break_even": 0,
        "fees_by_currency": {},
        "nominal_closed_by_currency": {},
        "real_closed_by_currency": {},
        "open_current_by_currency": {},
        "open_real_current_by_currency": {},
        "entry_reasons": 0,
        "exit_reasons": 0,
        "by_strategy": [],
    }
    by_strategy: dict[str, dict[str, Any]] = {}

    for trade in trades:
        status = str(trade.get("status") or "open")
        strategy = str(trade.get("strategy_tag") or "Без стратегии")
        strategy_item = by_strategy.setdefault(strategy, _strategy_report(strategy))
        strategy_item["total"] += 1

        if trade.get("entry_reason"):
            report["entry_reasons"] += 1
            strategy_item["entry_reasons"] += 1
        if trade.get("exit_reason"):
            report["exit_reasons"] += 1
            strategy_item["exit_reasons"] += 1
        _add_currency_amount(report["fees_by_currency"], trade.get("fee_currency"), trade.get("fee_applied"))
        _add_currency_amount(strategy_item["fees_by_currency"], trade.get("fee_currency"), trade.get("fee_applied"))

        if status == "closed":
            report["closed"] += 1
            strategy_item["closed"] += 1
            if trade.get("pnl_available"):
                amount = float(trade.get("pnl_amount") or 0)
                _add_currency_amount(report["nominal_closed_by_currency"], trade.get("pnl_currency"), amount)
                _add_currency_amount(strategy_item["nominal_by_currency"], trade.get("pnl_currency"), amount)
                if amount > 0:
                    report["wins"] += 1
                    strategy_item["wins"] += 1
                elif amount < 0:
                    report["losses"] += 1
                    strategy_item["losses"] += 1
                else:
                    report["break_even"] += 1
                    strategy_item["break_even"] += 1
            if trade.get("real_pnl_available"):
                _add_currency_amount(
                    report["real_closed_by_currency"],
                    trade.get("real_pnl_currency"),
                    trade.get("real_pnl_amount"),
                )
                _add_currency_amount(
                    strategy_item["real_by_currency"],
                    trade.get("real_pnl_currency"),
                    trade.get("real_pnl_amount"),
                )
        else:
            report["open"] += 1
            strategy_item["open"] += 1
            if trade.get("current_pnl_available"):
                _add_currency_amount(
                    report["open_current_by_currency"],
                    trade.get("current_pnl_currency"),
                    trade.get("current_pnl_amount"),
                )
            if trade.get("current_real_pnl_available"):
                _add_currency_amount(
                    report["open_real_current_by_currency"],
                    trade.get("current_real_pnl_currency"),
                    trade.get("current_real_pnl_amount"),
                )

    for item in by_strategy.values():
        item["win_rate"] = (item["wins"] / item["closed"] * 100) if item["closed"] else None
    report["win_rate"] = (report["wins"] / report["closed"] * 100) if report["closed"] else None
    report["by_strategy"] = sorted(
        by_strategy.values(),
        key=lambda item: (item["closed"], item["total"], item["strategy_tag"]),
        reverse=True,
    )
    return report
