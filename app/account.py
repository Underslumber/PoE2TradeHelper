from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import smtplib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage


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
    amount = (exit_price - entry_price) * quantity
    percent = ((exit_price - entry_price) / entry_price * 100) if entry_price else None
    return {
        "pnl_available": True,
        "pnl_amount": amount,
        "pnl_percent": percent,
        "pnl_currency": exit_currency,
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
