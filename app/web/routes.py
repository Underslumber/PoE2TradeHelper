from __future__ import annotations

import asyncio
import json
import os
import uuid
from time import perf_counter
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Body, Depends, Query, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.account import (
    SESSION_DAYS,
    calculate_benchmark_adjusted_pnl,
    calculate_trade_pnl,
    hash_password,
    is_valid_email,
    new_session_token,
    new_email_verification_token,
    normalize_email,
    normalize_username,
    now_iso,
    send_verification_email,
    session_expires_iso,
    utc_now,
    verify_password,
)
from app.ai_context import load_ai_market_context
from app.codex_market_analyzer import run_codex_market_analysis
from app.currency_analyzer import load_currency_trend_context
from app.db.models import (
    AIUsageEvent,
    PinnedPosition,
    Row,
    Snapshot,
    TelegramNotificationRule,
    TradeJournalEntry,
    User,
    UserSession,
)
from app.db.session import get_session
from app.export.export_csv import export_rows_csv
from app.export.export_jsonl import export_rows_jsonl
from app.funpay_market import load_funpay_rub_context
from app.market_service import market_snapshot_service
from app.notifications import (
    normalize_event_type,
    notification_rule_payload,
    process_telegram_notifications,
    send_test_notification,
    telegram_is_configured,
)
from app.trade2 import (
    build_category_meta,
    get_category_rates,
    get_exchange_offers,
    get_seller_lot_market,
    get_seller_lots_analysis,
    get_trade_leagues,
    get_trade_static,
    read_item_history,
    read_history,
    read_latest_rates,
)
from app.version import APP_VERSION

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))
templates.env.globals["app_version"] = APP_VERSION
SESSION_COOKIE = "poe2_session"
AI_MARKET_CONTEXT_FEATURE = "market_context"
AI_MARKET_ANALYSIS_FEATURE = "market_analysis"
AI_CURRENCY_ANALYSIS_FEATURE = "currency_analysis"
AI_MARKET_ANALYSIS_JOBS: dict[str, dict] = {}
AI_CURRENCY_ANALYSIS_JOBS: dict[str, dict] = {}
AI_MARKET_ANALYSIS_MAX_JOBS = 50
PROJECT_ROOT = Path(__file__).resolve().parents[2]
# Strong references to fire-and-forget tasks so the event loop does not
# garbage-collect them mid-execution.
_BACKGROUND_TASKS: set[asyncio.Task] = set()
# Serializes the AI daily-quota check and slot reservation so concurrent
# requests cannot both pass a stale remaining-count check.
_AI_QUOTA_LOCK = asyncio.Lock()


def trade_api_error(exc: Exception) -> JSONResponse:
    return JSONResponse({"error": str(exc)}, status_code=502)


def get_db() -> Iterator[Session]:
    db = get_session()
    try:
        yield db
    finally:
        db.close()


def account_api_error(message: str, status_code: int = 400, key: str | None = None) -> JSONResponse:
    content = {"error": message}
    if key:
        content["error_key"] = key
    return JSONResponse(content, status_code=status_code)


def _text(payload: dict, key: str, default: str = "") -> str:
    value = payload.get(key, default)
    return str(value or "").strip()


def _float_value(payload: dict, key: str, default: float | None = None) -> float | None:
    value = payload.get(key, default)
    if value in (None, ""):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int_value(payload: dict, key: str, default: int | None = None) -> int | None:
    value = payload.get(key, default)
    if value in (None, ""):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _session_user(request: Request, db: Session) -> User | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    session = db.get(UserSession, token)
    if not session:
        return None
    try:
        expired = datetime_from_iso(session.expires_at) <= utc_now()
    except ValueError:
        expired = True
    if expired:
        db.delete(session)
        db.commit()
        return None
    return db.get(User, session.user_id)


def datetime_from_iso(value: str):
    from datetime import datetime

    return datetime.fromisoformat(value)


def require_user(request: Request, db: Session) -> User | JSONResponse:
    user = _session_user(request, db)
    if not user:
        return account_api_error("Требуется вход в аккаунт.", status_code=401, key="accountErrorLoginRequired")
    return user


def _user_is_admin(user: User) -> bool:
    return bool(user.is_admin)


def _user_can_use_ai(user: User) -> bool:
    return bool(user.is_admin or user.can_use_ai)


def _user_fiat_rub_enabled(user: User) -> bool:
    return bool(user.fiat_rub_enabled)


def require_admin(request: Request, db: Session) -> User | JSONResponse:
    user = require_user(request, db)
    if isinstance(user, JSONResponse):
        return user
    if not _user_is_admin(user):
        return account_api_error("Нужен доступ администратора.", status_code=403, key="accountErrorAdminRequired")
    return user


def require_ai_access(request: Request, db: Session) -> User | JSONResponse:
    user = require_user(request, db)
    if isinstance(user, JSONResponse):
        return user
    if not _user_can_use_ai(user):
        return account_api_error("Нет доступа к ИИ-функциям.", status_code=403, key="accountErrorAiAccessRequired")
    return user


def require_fiat_rub_access(request: Request, db: Session) -> User | JSONResponse:
    user = require_user(request, db)
    if isinstance(user, JSONResponse):
        return user
    if not _user_fiat_rub_enabled(user):
        return account_api_error(
            "Рублевый рыночный слой выключен в профиле.",
            status_code=403,
            key="accountErrorFiatRubDisabled",
        )
    return user


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_DAYS * 24 * 60 * 60,
        httponly=True,
        samesite="lax",
        secure=os.environ.get("APP_BASE_URL", "").lower().startswith("https"),
    )


def _verification_url(request: Request, token: str) -> str:
    base_url = os.environ.get("APP_BASE_URL") or str(request.base_url).rstrip("/")
    return f"{base_url}/auth/verify-email?token={token}"


def _create_session(db: Session, user: User) -> str:
    token = new_session_token()
    db.add(
        UserSession(
            token=token,
            user_id=user.id,
            created_at=now_iso(),
            expires_at=session_expires_iso(),
        )
    )
    db.commit()
    return token


def _user_payload(user: User | None) -> dict:
    if not user:
        return {"authenticated": False, "user": None}
    return {
        "authenticated": True,
        "user": {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "email_verified": bool(user.email_verified_at),
            "display_name": user.display_name,
            "is_admin": _user_is_admin(user),
            "can_use_ai": _user_can_use_ai(user),
            "fiat_rub_enabled": _user_fiat_rub_enabled(user),
            "account_target_currency": user.account_target_currency or "exalted",
            "created_at": user.created_at,
        },
    }


def _admin_user_payload(user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "email_verified": bool(user.email_verified_at),
        "display_name": user.display_name,
        "is_admin": _user_is_admin(user),
        "can_use_ai": bool(user.can_use_ai),
        "effective_can_use_ai": _user_can_use_ai(user),
        "fiat_rub_enabled": _user_fiat_rub_enabled(user),
        "account_target_currency": user.account_target_currency or "exalted",
        "created_at": user.created_at,
    }


def _ai_daily_limit() -> int | None:
    try:
        limit = int(os.environ.get("AI_DAILY_QUOTA", "100"))
    except ValueError:
        limit = 100
    return limit if limit > 0 else None


def _ai_quota_window_start() -> str:
    return utc_now().replace(hour=0, minute=0, second=0, microsecond=0).isoformat()


def _ai_metered_events_today(db: Session) -> int:
    return int(
        db.scalar(
            select(func.count(AIUsageEvent.id)).where(
                AIUsageEvent.created_at >= _ai_quota_window_start(),
                AIUsageEvent.status_code != 429,
            )
        )
        or 0
    )


def _ai_quota_payload(db: Session) -> dict:
    limit = _ai_daily_limit()
    used = _ai_metered_events_today(db)
    remaining = None if limit is None else max(limit - used, 0)
    return {
        "daily_limit": limit,
        "used_today": used,
        "remaining": remaining,
        "window_start": _ai_quota_window_start(),
    }


def _record_ai_usage(
    db: Session,
    user: User,
    *,
    feature: str,
    success: bool,
    status_code: int,
    duration_ms: int | None = None,
) -> AIUsageEvent:
    event = AIUsageEvent(
        user_id=user.id,
        feature=feature,
        created_at=now_iso(),
        success=1 if success else 0,
        status_code=status_code,
        duration_ms=duration_ms,
    )
    db.add(event)
    db.commit()
    return event


def _prune_ai_market_analysis_jobs() -> None:
    if len(AI_MARKET_ANALYSIS_JOBS) <= AI_MARKET_ANALYSIS_MAX_JOBS:
        return
    ordered = sorted(
        AI_MARKET_ANALYSIS_JOBS.items(),
        key=lambda item: str(item[1].get("created_at") or ""),
    )
    for job_id, _job in ordered[: max(0, len(ordered) - AI_MARKET_ANALYSIS_MAX_JOBS)]:
        AI_MARKET_ANALYSIS_JOBS.pop(job_id, None)


def _prune_ai_currency_analysis_jobs() -> None:
    if len(AI_CURRENCY_ANALYSIS_JOBS) <= AI_MARKET_ANALYSIS_MAX_JOBS:
        return
    ordered = sorted(
        AI_CURRENCY_ANALYSIS_JOBS.items(),
        key=lambda item: str(item[1].get("created_at") or ""),
    )
    for job_id, _job in ordered[: max(0, len(ordered) - AI_MARKET_ANALYSIS_MAX_JOBS)]:
        AI_CURRENCY_ANALYSIS_JOBS.pop(job_id, None)


def _ai_market_analysis_job_payload(job: dict) -> dict:
    return {
        "job_id": job.get("job_id"),
        "status": job.get("status"),
        "created_at": job.get("created_at"),
        "started_at": job.get("started_at"),
        "finished_at": job.get("finished_at"),
        "duration_ms": job.get("duration_ms"),
        "params": job.get("params") or {},
        "context": job.get("context"),
        "assessment": job.get("assessment"),
        "analysis_path": job.get("analysis_path"),
        "error": job.get("error"),
    }


async def _run_ai_market_analysis_job(job_id: str, params: dict) -> None:
    job = AI_MARKET_ANALYSIS_JOBS.get(job_id)
    if not job:
        return
    started = perf_counter()
    job["status"] = "running"
    job["started_at"] = now_iso()
    try:
        context = await load_ai_market_context(
            league=params["league"],
            category=params["category"],
            target=params["target"],
            status=params["status"],
            league_day=params.get("league_day"),
            limit=params["limit"],
            refresh=params["refresh"],
        )
        context.setdefault("request", {})["max_candidates"] = params["max_candidates"]
        result = await asyncio.to_thread(
            run_codex_market_analysis,
            context,
            timeout_seconds=params["timeout_seconds"],
            cwd=PROJECT_ROOT,
        )
        job["status"] = "completed"
        job["assessment"] = result.get("assessment")
        job["analysis_path"] = result.get("analysis_path")
    except Exception as exc:
        job["status"] = "failed"
        job["error"] = str(exc)
    finally:
        job["finished_at"] = now_iso()
        job["duration_ms"] = int((perf_counter() - started) * 1000)


def _schedule_ai_market_analysis_job(job_id: str, params: dict) -> None:
    task = asyncio.create_task(_run_ai_market_analysis_job(job_id, params))
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)


async def _run_ai_currency_analysis_job(job_id: str, params: dict) -> None:
    job = AI_CURRENCY_ANALYSIS_JOBS.get(job_id)
    if not job:
        return
    started = perf_counter()
    job["status"] = "running"
    job["started_at"] = now_iso()
    try:
        context = await load_currency_trend_context(
            league=params["league"],
            currency_id=params["currency_id"],
            target=params["target"],
            status=params["status"],
            league_day=params.get("league_day"),
            history_limit=params["history_limit"],
            horizon_hours=params["horizon_hours"],
            forecast_points=params["forecast_points"],
            refresh=params["refresh"],
        )
        context.setdefault("request", {})["max_candidates"] = 1
        result = await asyncio.to_thread(
            run_codex_market_analysis,
            context,
            timeout_seconds=params["timeout_seconds"],
            cwd=PROJECT_ROOT,
        )
        job["status"] = "completed"
        job["context"] = context
        job["assessment"] = result.get("assessment")
        job["analysis_path"] = result.get("analysis_path")
    except Exception as exc:
        job["status"] = "failed"
        job["error"] = str(exc)
    finally:
        job["finished_at"] = now_iso()
        job["duration_ms"] = int((perf_counter() - started) * 1000)


def _schedule_ai_currency_analysis_job(job_id: str, params: dict) -> None:
    task = asyncio.create_task(_run_ai_currency_analysis_job(job_id, params))
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)


def _parse_event_datetime(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _admin_metrics_payload(db: Session) -> dict:
    users = db.scalars(select(User)).all()
    users_by_id = {user.id: user for user in users}
    now = utc_now()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    since = today - timedelta(days=6)
    events = db.scalars(
        select(AIUsageEvent)
        .where(AIUsageEvent.created_at >= since.isoformat())
        .order_by(AIUsageEvent.created_at.desc())
        .limit(500)
    ).all()
    today_events = [event for event in events if (_parse_event_datetime(event.created_at) or since) >= today]
    daily = []
    for offset in range(6, -1, -1):
        day = today - timedelta(days=offset)
        next_day = day + timedelta(days=1)
        day_events = [
            event
            for event in events
            if (parsed := _parse_event_datetime(event.created_at)) and day <= parsed < next_day
        ]
        daily.append(
            {
                "date": day.date().isoformat(),
                "requests": len(day_events),
                "failures": sum(1 for event in day_events if not event.success),
            }
        )
    top_users = []
    for user in users:
        user_events = [event for event in today_events if event.user_id == user.id]
        if user_events:
            top_users.append(
                {
                    "user_id": user.id,
                    "username": user.username,
                    "display_name": user.display_name,
                    "requests": len(user_events),
                    "failures": sum(1 for event in user_events if not event.success),
                    "last_at": max(user_events, key=lambda event: event.created_at).created_at,
                }
            )
    top_users.sort(key=lambda item: (-item["requests"], item["username"]))
    recent = []
    for event in events[:20]:
        user = users_by_id.get(event.user_id)
        recent.append(
            {
                "id": event.id,
                "created_at": event.created_at,
                "username": user.username if user else "",
                "display_name": user.display_name if user else "",
                "feature": event.feature,
                "success": bool(event.success),
                "status_code": event.status_code,
                "duration_ms": event.duration_ms,
            }
        )
    return {
        "users": {
            "total": len(users),
            "admins": sum(1 for user in users if _user_is_admin(user)),
            "ai_enabled": sum(1 for user in users if _user_can_use_ai(user)),
            "email_verified": sum(1 for user in users if user.email_verified_at),
        },
        "ai_quota": _ai_quota_payload(db),
        "ai_usage": {
            "events_today": len(today_events),
            "failures_today": sum(1 for event in today_events if not event.success),
            "total_events": int(db.scalar(select(func.count(AIUsageEvent.id))) or 0),
            "daily": daily,
            "top_users_today": top_users[:8],
            "recent": recent,
        },
    }


def _verification_payload(request: Request, user: User) -> dict:
    verification_url = _verification_url(request, user.email_verification_token or "")
    try:
        email_sent = send_verification_email(user.email or "", verification_url)
    except Exception:
        email_sent = False
    return {
        "authenticated": False,
        "verification_required": True,
        "email_sent": email_sent,
        "email": user.email,
        "dev_verification_url": None if email_sent else verification_url,
    }


def _row_price(row: dict | None) -> float | None:
    if not row:
        return None
    for key in ("median", "best"):
        try:
            value = float(row.get(key))
        except (TypeError, ValueError):
            continue
        if value > 0:
            return value
    return None


def _latest_rates_snapshot(league: str, category: str, target: str, cache: dict | None = None) -> dict | None:
    key = ("latest_rates", league, category, target)
    if cache is not None and key in cache:
        return cache[key]
    result = None
    for status in ("any", "online"):
        snapshot = read_latest_rates(league=league, category=category, target=target, status=status)
        if snapshot:
            result = snapshot
            break
    if cache is not None:
        cache[key] = result
    return result


def _latest_item_market(league: str, category: str, target: str, item_id: str, cache: dict | None = None) -> dict:
    snapshot = _latest_rates_snapshot(league, category, target, cache)
    if not snapshot:
        return {}
    row = next((item for item in snapshot.get("rows") or [] if item.get("id") == item_id), None)
    price = _row_price(row)
    if price is None:
        return {}
    return {
        "target_currency": snapshot.get("target") or target,
        "price": price,
        "source": snapshot.get("source"),
        "created_ts": snapshot.get("created_ts"),
        "change": row.get("change"),
        "sparkline": row.get("sparkline") or [],
        "sparkline_kind": row.get("sparkline_kind"),
        "volume": row.get("volume", 0),
    }


def _benchmark_price(
    league: str,
    target_currency: str | None,
    benchmark_currency: str | None,
    cache: dict | None = None,
) -> float | None:
    if not target_currency or not benchmark_currency:
        return None
    if target_currency == benchmark_currency:
        return 1.0
    snapshot = _latest_rates_snapshot(league, "Currency", target_currency, cache)
    if not snapshot:
        return None
    row = next((item for item in snapshot.get("rows") or [] if item.get("id") == benchmark_currency), None)
    return _row_price(row)


def _iso_timestamp(value: str | None) -> float | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def _benchmark_price_at(
    league: str,
    target_currency: str | None,
    benchmark_currency: str | None,
    timestamp: float | None,
    cache: dict | None = None,
) -> float | None:
    if not target_currency or not benchmark_currency or timestamp is None:
        return None
    if target_currency == benchmark_currency:
        return 1.0
    history_key = ("benchmark_history", league, target_currency)
    if cache is not None and history_key in cache:
        snapshots = cache[history_key]
    else:
        snapshots = read_history(
            limit=1000,
            league=league,
            category="Currency",
            target=target_currency,
            status="any",
        ) or read_history(
            limit=1000,
            league=league,
            category="Currency",
            target=target_currency,
            status="online",
        )
        if cache is not None:
            cache[history_key] = snapshots
    candidates = []
    for snapshot in snapshots:
        created_ts = snapshot.get("created_ts")
        if not isinstance(created_ts, (int, float)):
            continue
        row = next((item for item in snapshot.get("rows") or [] if item.get("id") == benchmark_currency), None)
        price = _row_price(row)
        if price is not None:
            candidates.append((float(created_ts), price))
    if not candidates:
        return None
    before = [item for item in candidates if item[0] <= timestamp]
    if before:
        return max(before, key=lambda item: item[0])[1]
    nearest_ts, nearest_price = min(candidates, key=lambda item: abs(item[0] - timestamp))
    return nearest_price if abs(nearest_ts - timestamp) <= 36 * 60 * 60 else None


def _prefixed(prefix: str, values: dict) -> dict:
    return {f"{prefix}_{key}": value for key, value in values.items()}


def _pin_payload(pin: PinnedPosition, cache: dict | None = None) -> dict:
    market = _latest_item_market(pin.league, pin.category, pin.target_currency, pin.item_id, cache)
    return {
        "id": pin.id,
        "league": pin.league,
        "category": pin.category,
        "item_id": pin.item_id,
        "item_name": pin.item_name,
        "item_name_ru": pin.item_name_ru,
        "icon_url": pin.icon_url,
        "target_currency": pin.target_currency,
        "last_price": pin.last_price,
        "last_source": pin.last_source,
        "market": market,
        "note": pin.note,
        "created_at": pin.created_at,
        "updated_at": pin.updated_at,
    }


def _trade_payload(trade: TradeJournalEntry, cache: dict | None = None) -> dict:
    pnl = calculate_trade_pnl(
        quantity=trade.quantity,
        entry_price=trade.entry_price,
        entry_currency=trade.entry_currency,
        exit_price=trade.exit_price,
        exit_currency=trade.exit_currency,
    )
    benchmark_currency = trade.benchmark_currency or "divine"
    market = _latest_item_market(trade.league, trade.category, trade.entry_currency, trade.item_id, cache)
    current_price = market.get("price")
    is_benchmark_item = trade.item_id == benchmark_currency
    current_benchmark_price = 1.0 if is_benchmark_item else _benchmark_price(trade.league, trade.entry_currency, benchmark_currency, cache)
    entry_benchmark_price = 1.0 if is_benchmark_item else trade.entry_benchmark_price
    if entry_benchmark_price is None:
        entry_benchmark_price = _benchmark_price_at(
            trade.league,
            trade.entry_currency,
            benchmark_currency,
            _iso_timestamp(trade.entry_at),
            cache,
        )
    exit_benchmark_price = 1.0 if is_benchmark_item and trade.exit_price is not None else trade.exit_benchmark_price
    if is_benchmark_item:
        entry_benchmark_price = 1.0
    current_pnl = calculate_trade_pnl(
        quantity=trade.quantity,
        entry_price=trade.entry_price,
        entry_currency=trade.entry_currency,
        exit_price=current_price,
        exit_currency=trade.entry_currency if current_price is not None else None,
    )
    current_real_pnl = calculate_benchmark_adjusted_pnl(
        quantity=trade.quantity,
        entry_price=trade.entry_price,
        entry_currency=trade.entry_currency,
        current_price=current_price,
        current_currency=trade.entry_currency if current_price is not None else None,
        benchmark_currency=benchmark_currency,
        entry_benchmark_price=entry_benchmark_price,
        current_benchmark_price=current_benchmark_price,
    )
    real_pnl = calculate_benchmark_adjusted_pnl(
        quantity=trade.quantity,
        entry_price=trade.entry_price,
        entry_currency=trade.entry_currency,
        current_price=trade.exit_price,
        current_currency=trade.exit_currency,
        benchmark_currency=benchmark_currency,
        entry_benchmark_price=entry_benchmark_price,
        current_benchmark_price=exit_benchmark_price,
    )
    return {
        "id": trade.id,
        "pin_id": trade.pin_id,
        "league": trade.league,
        "category": trade.category,
        "item_id": trade.item_id,
        "item_name": trade.item_name,
        "item_name_ru": trade.item_name_ru,
        "icon_url": trade.icon_url,
        "quantity": trade.quantity,
        "entry_price": trade.entry_price,
        "entry_currency": trade.entry_currency,
        "entry_at": trade.entry_at,
        "benchmark_currency": benchmark_currency,
        "entry_benchmark_price": entry_benchmark_price,
        "exit_price": trade.exit_price,
        "exit_currency": trade.exit_currency,
        "exit_at": trade.exit_at,
        "exit_benchmark_price": exit_benchmark_price,
        "status": trade.status,
        "notes": trade.notes,
        "market": market,
        "current_benchmark_price": current_benchmark_price,
        "created_at": trade.created_at,
        "updated_at": trade.updated_at,
        **pnl,
        **real_pnl,
        **_prefixed("current", current_pnl),
        **_prefixed("current", current_real_pnl),
    }


def _notification_payload(rule: TelegramNotificationRule, db: Session) -> dict:
    pin = db.get(PinnedPosition, rule.pin_id)
    return notification_rule_payload(rule, pin)


@router.get("/", response_class=HTMLResponse)
def live_home(request: Request):
    return templates.TemplateResponse(request=request, name="live.html")


@router.get("/economy", response_class=HTMLResponse)
def economy_home(request: Request, db: Session = Depends(get_db)):
    leagues = sorted({snap.league for snap in db.scalars(select(Snapshot)).all()})
    categories = sorted({snap.category for snap in db.scalars(select(Snapshot)).all()})
    latest = db.scalars(select(Snapshot).order_by(Snapshot.created_at.desc())).first()
    return templates.TemplateResponse(
        request=request,
        name="economy.html",
        context={
            "leagues": leagues,
            "categories": categories,
            "default_snapshot": latest,
        },
    )


@router.get("/api/auth/me")
def api_auth_me(request: Request, db: Session = Depends(get_db)):
    return _user_payload(_session_user(request, db))


@router.post("/api/auth/register")
def api_auth_register(
    request: Request,
    response: Response,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
):
    username = normalize_username(_text(payload, "username"))
    email = normalize_email(_text(payload, "email"))
    password = str(payload.get("password") or "")
    display_name = _text(payload, "display_name", username) or username
    if len(username) < 3:
        return account_api_error("Логин должен быть не короче 3 символов.", key="accountErrorUsernameShort")
    if not is_valid_email(email):
        return account_api_error("Укажите корректный email.", key="accountErrorEmailInvalid")
    if len(password) < 6:
        return account_api_error("Пароль должен быть не короче 6 символов.", key="accountErrorPasswordShort")
    existing = db.scalars(select(User).where(User.username == username)).first()
    if existing:
        return account_api_error("Такой логин уже зарегистрирован.", status_code=409, key="accountErrorUsernameTaken")
    existing_email = db.scalars(select(User).where(User.email == email)).first()
    if existing_email:
        return account_api_error("Такой email уже зарегистрирован.", status_code=409, key="accountErrorEmailTaken")
    is_first_user = db.scalars(select(User.id)).first() is None
    user = User(
        username=username,
        email=email,
        display_name=display_name,
        password_hash=hash_password(password),
        email_verification_token=new_email_verification_token(),
        email_verification_sent_at=now_iso(),
        is_admin=1 if is_first_user else 0,
        can_use_ai=1 if is_first_user else 0,
        created_at=now_iso(),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return _verification_payload(request, user)


@router.get("/auth/verify-email")
def auth_verify_email(
    request: Request,
    token: str = Query(..., min_length=20),
    db: Session = Depends(get_db),
):
    user = db.scalars(select(User).where(User.email_verification_token == token)).first()
    if not user:
        return RedirectResponse(url="/?view=cabinet&verify=invalid", status_code=303)
    user.email_verified_at = now_iso()
    user.email_verification_token = None
    user.email_verification_sent_at = None
    db.commit()
    db.refresh(user)
    response = RedirectResponse(url="/?view=cabinet&verified=1", status_code=303)
    _set_session_cookie(response, _create_session(db, user))
    return response


@router.post("/api/auth/resend-verification")
def api_auth_resend_verification(
    request: Request,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
):
    username_or_email = _text(payload, "username")
    password = str(payload.get("password") or "")
    normalized_email = normalize_email(username_or_email)
    normalized_username = normalize_username(username_or_email)
    user = db.scalars(
        select(User).where((User.username == normalized_username) | (User.email == normalized_email))
    ).first()
    if not user or not verify_password(password, user.password_hash):
        return account_api_error("Неверный логин или пароль.", status_code=401, key="accountErrorInvalidLogin")
    if user.email_verified_at:
        return {"verification_required": False, "email": user.email}
    user.email_verification_token = new_email_verification_token()
    user.email_verification_sent_at = now_iso()
    db.commit()
    db.refresh(user)
    return _verification_payload(request, user)


@router.post("/api/auth/login")
def api_auth_login(
    response: Response,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
):
    username = normalize_username(_text(payload, "username"))
    password = str(payload.get("password") or "")
    user = db.scalars(select(User).where(User.username == username)).first()
    if not user or not verify_password(password, user.password_hash):
        return account_api_error("Неверный логин или пароль.", status_code=401, key="accountErrorInvalidLogin")
    if user.email and not user.email_verified_at:
        return account_api_error("Подтвердите email перед входом.", status_code=403, key="accountErrorEmailNotVerified")
    token = _create_session(db, user)
    _set_session_cookie(response, token)
    return _user_payload(user)


@router.post("/api/auth/logout")
def api_auth_logout(request: Request, response: Response, db: Session = Depends(get_db)):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        session = db.get(UserSession, token)
        if session:
            db.delete(session)
            db.commit()
    response.delete_cookie(SESSION_COOKIE)
    return {"authenticated": False}


@router.get("/api/admin/users")
def api_admin_users(request: Request, db: Session = Depends(get_db)):
    admin = require_admin(request, db)
    if isinstance(admin, JSONResponse):
        return admin
    users = db.scalars(select(User).order_by(User.created_at.desc(), User.id.desc())).all()
    return {"users": [_admin_user_payload(user) for user in users]}


@router.get("/api/admin/metrics")
def api_admin_metrics(request: Request, db: Session = Depends(get_db)):
    admin = require_admin(request, db)
    if isinstance(admin, JSONResponse):
        return admin
    return _admin_metrics_payload(db)


@router.patch("/api/admin/users/{user_id}/permissions")
def api_admin_user_permissions(
    user_id: int,
    request: Request,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
):
    admin = require_admin(request, db)
    if isinstance(admin, JSONResponse):
        return admin
    user = db.get(User, user_id)
    if not user:
        return account_api_error("Пользователь не найден.", status_code=404, key="accountErrorUserNotFound")
    if "is_admin" in payload:
        next_is_admin = 1 if bool(payload.get("is_admin")) else 0
        if user.id == admin.id and not next_is_admin:
            return account_api_error(
                "Нельзя снять админский доступ с текущей учетной записи.",
                status_code=400,
                key="accountErrorAdminSelfDemote",
            )
        user.is_admin = next_is_admin
    if "can_use_ai" in payload:
        user.can_use_ai = 1 if bool(payload.get("can_use_ai")) else 0
    db.commit()
    db.refresh(user)
    return {"user": _admin_user_payload(user)}


@router.patch("/api/account/preferences")
def api_account_preferences(
    request: Request,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    if isinstance(user, JSONResponse):
        return user
    if "fiat_rub_enabled" in payload:
        user.fiat_rub_enabled = 1 if bool(payload.get("fiat_rub_enabled")) else 0
    if "account_target_currency" in payload:
        user.account_target_currency = _text(payload, "account_target_currency", "exalted") or "exalted"
    db.commit()
    db.refresh(user)
    return _user_payload(user)


@router.get("/api/account/pins")
def api_account_pins(request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    if isinstance(user, JSONResponse):
        return user
    pins = db.scalars(
        select(PinnedPosition)
        .where(PinnedPosition.user_id == user.id)
        .order_by(PinnedPosition.updated_at.desc())
    ).all()
    market_cache: dict = {}
    return {"pins": [_pin_payload(pin, market_cache) for pin in pins]}


@router.post("/api/account/pins")
def api_account_pin_save(
    request: Request,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    if isinstance(user, JSONResponse):
        return user
    league = _text(payload, "league")
    category = _text(payload, "category")
    item_id = _text(payload, "item_id")
    item_name = _text(payload, "item_name") or _text(payload, "item_name_ru") or item_id
    target_currency = _text(payload, "target_currency", "exalted") or "exalted"
    if not league or not category or not item_id:
        return account_api_error("Для закрепления нужны лига, категория и id позиции.", key="accountErrorPinPayload")
    pin = db.scalars(
        select(PinnedPosition).where(
            PinnedPosition.user_id == user.id,
            PinnedPosition.league == league,
            PinnedPosition.category == category,
            PinnedPosition.item_id == item_id,
        )
    ).first()
    now = now_iso()
    if not pin:
        pin = PinnedPosition(
            user_id=user.id,
            league=league,
            category=category,
            item_id=item_id,
            created_at=now,
            updated_at=now,
            item_name=item_name,
            target_currency=target_currency,
        )
        db.add(pin)
    pin.item_name = item_name
    pin.item_name_ru = _text(payload, "item_name_ru") or None
    pin.icon_url = _text(payload, "icon_url") or None
    pin.target_currency = target_currency
    pin.last_price = _float_value(payload, "last_price")
    pin.last_source = _text(payload, "last_source") or None
    if "note" in payload:
        pin.note = _text(payload, "note") or None
    pin.updated_at = now
    db.commit()
    db.refresh(pin)
    return {"pin": _pin_payload(pin)}


@router.delete("/api/account/pins/{pin_id}")
def api_account_pin_delete(pin_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    if isinstance(user, JSONResponse):
        return user
    pin = db.get(PinnedPosition, pin_id)
    if not pin or pin.user_id != user.id:
        return account_api_error("Закрепленная позиция не найдена.", status_code=404, key="accountErrorPinNotFound")
    db.delete(pin)
    db.commit()
    return {"deleted": True}


@router.get("/api/account/trades")
def api_account_trades(request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    if isinstance(user, JSONResponse):
        return user
    trades = db.scalars(
        select(TradeJournalEntry)
        .where(TradeJournalEntry.user_id == user.id)
        .order_by(TradeJournalEntry.updated_at.desc())
    ).all()
    market_cache: dict = {}
    return {"trades": [_trade_payload(trade, market_cache) for trade in trades]}


@router.post("/api/account/trades")
def api_account_trade_create(
    request: Request,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    if isinstance(user, JSONResponse):
        return user
    pin = None
    pin_id = payload.get("pin_id")
    if pin_id not in (None, ""):
        try:
            pin = db.get(PinnedPosition, int(pin_id))
        except (TypeError, ValueError):
            pin = None
        if not pin or pin.user_id != user.id:
            return account_api_error("Закрепленная позиция не найдена.", status_code=404, key="accountErrorPinNotFound")
    league = _text(payload, "league") or (pin.league if pin else "")
    category = _text(payload, "category") or (pin.category if pin else "")
    item_id = _text(payload, "item_id") or (pin.item_id if pin else "")
    item_name = _text(payload, "item_name") or (pin.item_name if pin else item_id)
    entry_currency = _text(payload, "entry_currency") or (pin.target_currency if pin else "")
    entry_price = _float_value(payload, "entry_price", pin.last_price if pin else None)
    quantity = _float_value(payload, "quantity", 1.0) or 1.0
    benchmark_currency = _text(payload, "benchmark_currency") or "divine"
    if not league or not category or not item_id:
        return account_api_error("Для входа в сделку нужны лига, категория и позиция.", key="accountErrorTradePayload")
    if entry_price is None or entry_price <= 0 or quantity <= 0 or not entry_currency:
        return account_api_error("Укажите положительную цену входа, количество и валюту.", key="accountErrorTradePrice")
    entry_benchmark_price = _float_value(payload, "entry_benchmark_price")
    if item_id == benchmark_currency:
        entry_benchmark_price = 1.0
    if entry_benchmark_price is None:
        entry_benchmark_price = _benchmark_price(league, entry_currency, benchmark_currency)
    now = now_iso()
    trade = TradeJournalEntry(
        user_id=user.id,
        pin_id=pin.id if pin else None,
        league=league,
        category=category,
        item_id=item_id,
        item_name=item_name,
        item_name_ru=_text(payload, "item_name_ru") or (pin.item_name_ru if pin else None),
        icon_url=_text(payload, "icon_url") or (pin.icon_url if pin else None),
        quantity=quantity,
        entry_price=entry_price,
        entry_currency=entry_currency,
        entry_at=_text(payload, "entry_at") or now,
        benchmark_currency=benchmark_currency,
        entry_benchmark_price=entry_benchmark_price,
        status="open",
        notes=_text(payload, "notes") or None,
        created_at=now,
        updated_at=now,
    )
    db.add(trade)
    db.commit()
    db.refresh(trade)
    return {"trade": _trade_payload(trade)}


@router.patch("/api/account/trades/{trade_id}")
def api_account_trade_update(
    trade_id: int,
    request: Request,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    if isinstance(user, JSONResponse):
        return user
    trade = db.get(TradeJournalEntry, trade_id)
    if not trade or trade.user_id != user.id:
        return account_api_error("Сделка не найдена.", status_code=404, key="accountErrorTradeNotFound")
    if "quantity" in payload:
        quantity = _float_value(payload, "quantity")
        if quantity is None or quantity <= 0:
            return account_api_error("Количество должно быть положительным.", key="accountErrorQuantity")
        trade.quantity = quantity
    if "entry_price" in payload:
        entry_price = _float_value(payload, "entry_price")
        if entry_price is None or entry_price <= 0:
            return account_api_error("Цена входа должна быть положительной.", key="accountErrorEntryPrice")
        trade.entry_price = entry_price
    if "entry_currency" in payload:
        trade.entry_currency = _text(payload, "entry_currency") or trade.entry_currency
    if "benchmark_currency" in payload:
        trade.benchmark_currency = _text(payload, "benchmark_currency") or trade.benchmark_currency or "divine"
    if "entry_benchmark_price" in payload:
        trade.entry_benchmark_price = 1.0 if trade.item_id == (trade.benchmark_currency or "divine") else _float_value(payload, "entry_benchmark_price")
    if "exit_price" in payload:
        exit_price = _float_value(payload, "exit_price")
        if exit_price is None or exit_price <= 0:
            return account_api_error("Цена выхода должна быть положительной.", key="accountErrorExitPrice")
        trade.exit_price = exit_price
        trade.exit_currency = _text(payload, "exit_currency") or trade.entry_currency
        trade.exit_at = _text(payload, "exit_at") or now_iso()
        trade.exit_benchmark_price = _float_value(payload, "exit_benchmark_price")
        if trade.item_id == (trade.benchmark_currency or "divine"):
            trade.exit_benchmark_price = 1.0
        if trade.exit_benchmark_price is None:
            trade.exit_benchmark_price = _benchmark_price(
                trade.league,
                trade.exit_currency,
                trade.benchmark_currency or "divine",
            )
        trade.status = "closed"
    if "notes" in payload:
        trade.notes = _text(payload, "notes") or None
    if _text(payload, "status") in {"open", "closed"}:
        trade.status = _text(payload, "status")
    trade.updated_at = now_iso()
    db.commit()
    db.refresh(trade)
    return {"trade": _trade_payload(trade)}


@router.delete("/api/account/trades/{trade_id}")
def api_account_trade_delete(trade_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    if isinstance(user, JSONResponse):
        return user
    trade = db.get(TradeJournalEntry, trade_id)
    if not trade or trade.user_id != user.id:
        return account_api_error("Сделка не найдена.", status_code=404, key="accountErrorTradeNotFound")
    db.delete(trade)
    db.commit()
    return {"deleted": True}


@router.get("/api/account/notifications")
def api_account_notifications(request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    if isinstance(user, JSONResponse):
        return user
    rules = db.scalars(
        select(TelegramNotificationRule)
        .where(TelegramNotificationRule.user_id == user.id)
        .order_by(TelegramNotificationRule.updated_at.desc())
    ).all()
    return {
        "telegram_configured": telegram_is_configured(),
        "notifications": [_notification_payload(rule, db) for rule in rules],
    }


@router.post("/api/account/notifications")
def api_account_notification_create(
    request: Request,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    if isinstance(user, JSONResponse):
        return user
    pin_id = payload.get("pin_id")
    try:
        pin = db.get(PinnedPosition, int(pin_id))
    except (TypeError, ValueError):
        pin = None
    if not pin or pin.user_id != user.id:
        return account_api_error("Закрепленная позиция не найдена.", status_code=404, key="accountErrorPinNotFound")
    event_type = normalize_event_type(_text(payload, "event_type"))
    if not event_type:
        return account_api_error("Выберите тип Telegram-уведомления.", key="accountErrorTelegramEvent")
    threshold = _float_value(payload, "threshold_value")
    if event_type != "any_update" and (threshold is None or threshold <= 0):
        return account_api_error("Укажите положительный порог уведомления.", key="accountErrorTelegramThreshold")
    chat_id = _text(payload, "chat_id")
    if not chat_id:
        return account_api_error("Укажите Telegram chat id.", key="accountErrorTelegramChat")
    now = now_iso()
    rule = TelegramNotificationRule(
        user_id=user.id,
        pin_id=pin.id,
        chat_id=chat_id,
        event_type=event_type,
        threshold_value=None if event_type == "any_update" else threshold,
        enabled=1,
        last_price=pin.last_price,
        created_at=now,
        updated_at=now,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return {"notification": _notification_payload(rule, db), "telegram_configured": telegram_is_configured()}


@router.patch("/api/account/notifications/{rule_id}")
def api_account_notification_update(
    rule_id: int,
    request: Request,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    if isinstance(user, JSONResponse):
        return user
    rule = db.get(TelegramNotificationRule, rule_id)
    if not rule or rule.user_id != user.id:
        return account_api_error("Telegram-уведомление не найдено.", status_code=404, key="accountErrorTelegramRuleNotFound")
    if "enabled" in payload:
        rule.enabled = 1 if bool(payload.get("enabled")) else 0
    if "chat_id" in payload:
        chat_id = _text(payload, "chat_id")
        if not chat_id:
            return account_api_error("Укажите Telegram chat id.", key="accountErrorTelegramChat")
        rule.chat_id = chat_id
    if "event_type" in payload:
        event_type = normalize_event_type(_text(payload, "event_type"))
        if not event_type:
            return account_api_error("Выберите тип Telegram-уведомления.", key="accountErrorTelegramEvent")
        rule.event_type = event_type
    if "threshold_value" in payload:
        threshold = _float_value(payload, "threshold_value")
        if rule.event_type != "any_update" and (threshold is None or threshold <= 0):
            return account_api_error("Укажите положительный порог уведомления.", key="accountErrorTelegramThreshold")
        rule.threshold_value = None if rule.event_type == "any_update" else threshold
    rule.updated_at = now_iso()
    db.commit()
    db.refresh(rule)
    return {"notification": _notification_payload(rule, db)}


@router.delete("/api/account/notifications/{rule_id}")
def api_account_notification_delete(rule_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    if isinstance(user, JSONResponse):
        return user
    rule = db.get(TelegramNotificationRule, rule_id)
    if not rule or rule.user_id != user.id:
        return account_api_error("Telegram-уведомление не найдено.", status_code=404, key="accountErrorTelegramRuleNotFound")
    db.delete(rule)
    db.commit()
    return {"deleted": True}


@router.post("/api/account/notifications/{rule_id}/test")
async def api_account_notification_test(rule_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    if isinstance(user, JSONResponse):
        return user
    rule = db.get(TelegramNotificationRule, rule_id)
    if not rule or rule.user_id != user.id:
        return account_api_error("Telegram-уведомление не найдено.", status_code=404, key="accountErrorTelegramRuleNotFound")
    pin = db.get(PinnedPosition, rule.pin_id)
    if not pin:
        return account_api_error("Закрепленная позиция не найдена.", status_code=404, key="accountErrorPinNotFound")
    if not telegram_is_configured():
        return account_api_error("TELEGRAM_BOT_TOKEN не настроен.", key="accountErrorTelegramNotConfigured")
    try:
        await send_test_notification(rule, pin)
    except Exception:
        return account_api_error("Не удалось отправить Telegram-сообщение.", status_code=502, key="accountErrorTelegramSend")
    return {"sent": True}


@router.get("/api/account/funpay-rub")
async def api_account_funpay_rub(
    request: Request,
    league: str = Query(...),
    target: str = Query("divine"),
    refresh: bool = Query(False),
    history_days: int = Query(7, ge=1, le=30),
    db: Session = Depends(get_db),
):
    user = require_fiat_rub_access(request, db)
    if isinstance(user, JSONResponse):
        return user
    try:
        return await load_funpay_rub_context(
            db,
            league=league,
            target_currency=target,
            refresh=refresh,
            history_days=history_days,
        )
    except Exception as exc:
        return trade_api_error(exc)


@router.get("/api/trade/leagues")
async def api_trade_leagues():
    try:
        return {"leagues": await get_trade_leagues()}
    except asyncio.TimeoutError:
        return JSONResponse(
            status_code=504,
            content={"error": "Поиск лотов занял слишком много времени. Попробуйте уменьшить число лотов или уточнить фильтр."},
        )
    except Exception as exc:
        return trade_api_error(exc)


@router.get("/api/trade/static")
async def api_trade_static():
    try:
        categories = await get_trade_static()
        return {"categories": categories, "category_meta": build_category_meta(categories)}
    except Exception as exc:
        return trade_api_error(exc)


@router.get("/api/trade/exchange")
async def api_trade_exchange(
    league: str = Query(...),
    have: str = Query(...),
    want: str = Query(...),
    status: str = Query("online", pattern="^(online|any)$"),
):
    try:
        return await get_exchange_offers(league=league, have=have, want=want, status=status)
    except Exception as exc:
        return trade_api_error(exc)


@router.get("/api/trade/category-rates")
async def api_trade_category_rates(
    league: str = Query(...),
    category: str = Query(...),
    target: str = Query("divine"),
    status: str = Query("any", pattern="^(online|any)$"),
    db: Session = Depends(get_db),
):
    try:
        data = await get_category_rates(league=league, category=category, target=target, status=status)
        if isinstance(data, dict):
            data["notifications"] = await process_telegram_notifications(
                db,
                league=league,
                category=category,
                target=data.get("target") or target,
                rows=data.get("rows") or [],
                source=data.get("source") or "",
            )
        return data
    except Exception as exc:
        return trade_api_error(exc)


@router.get("/api/trade/category-rates/latest")
def api_trade_category_rates_latest(
    league: str = Query(...),
    category: str = Query(...),
    target: str = Query("exalted"),
    status: str = Query("any", pattern="^(online|any)$"),
):
    latest = read_latest_rates(league=league, category=category, target=target, status=status)
    if not latest:
        return {"cached": False, "rows": []}
    return latest


@router.get("/api/trade/market-snapshot-service")
def api_trade_market_snapshot_service():
    return market_snapshot_service.status()


@router.get("/api/trade/seller-lots")
async def api_trade_seller_lots(
    league: str = Query(...),
    seller: str = Query(..., min_length=1),
    q: str = Query(""),
    target: str = Query("exalted"),
    status: str = Query("any", pattern="^(online|any)$"),
    limit: int = Query(10, ge=1, le=20),
    analyze: bool = Query(True),
):
    try:
        return await get_seller_lots_analysis(
            league=league,
            seller=seller,
            text=q,
            target=target,
            status=status,
            limit=limit,
            analyze=analyze,
        )
    except Exception as exc:
        return trade_api_error(exc)


@router.get("/api/trade/seller-lot-market")
async def api_trade_seller_lot_market(
    league: str = Query(...),
    seller: str = Query(..., min_length=1),
    lot_id: str = Query(..., min_length=1),
    target: str = Query("exalted"),
    status: str = Query("any", pattern="^(online|any)$"),
):
    try:
        return await get_seller_lot_market(
            league=league,
            seller=seller,
            lot_id=lot_id,
            target=target,
            status=status,
        )
    except asyncio.TimeoutError:
        return JSONResponse(
            status_code=504,
            content={"error": "Оценка лота заняла слишком много времени."},
        )
    except Exception as exc:
        return trade_api_error(exc)


@router.get("/api/trade/history")
def api_trade_history(
    limit: int = Query(30, ge=1, le=1500),
    league: str | None = Query(None),
    category: str | None = Query(None),
    target: str | None = Query(None),
    status: str | None = Query(None, pattern="^(online|any)$"),
):
    return {
        "history": read_history(
            limit=limit,
            league=league,
            category=category,
            target=target,
            status=status,
        )
    }


@router.get("/api/trade/history/item")
def api_trade_item_history(
    league: str = Query(...),
    category: str = Query(...),
    item_id: str = Query(...),
    target: str = Query("exalted"),
    status: str = Query("any", pattern="^(online|any)$"),
    metric: str = Query("price", pattern="^(price|demand|offers)$"),
    limit: int = Query(1000, ge=1, le=2000),
):
    return {
        "series": read_item_history(
            league=league,
            category=category,
            item_id=item_id,
            target=target,
            status=status,
            metric=metric,
            limit=limit,
        )
    }


@router.get("/api/trade/currency-analysis")
async def api_trade_currency_analysis(
    league: str = Query(...),
    currency_id: str = Query(...),
    target: str = Query("exalted"),
    status: str = Query("any", pattern="^(online|any)$"),
    league_day: int | None = Query(None, ge=0),
    history_limit: int = Query(1500, ge=2, le=2000),
    horizon_hours: int = Query(24, ge=1, le=168),
    forecast_points: int = Query(12, ge=2, le=48),
    refresh: bool = Query(False),
):
    try:
        return await load_currency_trend_context(
            league=league,
            currency_id=currency_id,
            target=target,
            status=status,
            league_day=league_day,
            history_limit=history_limit,
            horizon_hours=horizon_hours,
            forecast_points=forecast_points,
            refresh=refresh,
        )
    except Exception as exc:
        return trade_api_error(exc)


@router.get("/api/ai/market-context")
async def api_ai_market_context(
    request: Request,
    league: str = Query(...),
    category: str = Query(...),
    target: str = Query("exalted"),
    status: str = Query("any", pattern="^(online|any)$"),
    league_day: int | None = Query(None, ge=0),
    limit: int = Query(80, ge=1, le=250),
    refresh: bool = Query(False),
    db: Session = Depends(get_db),
):
    user = require_ai_access(request, db)
    if isinstance(user, JSONResponse):
        return user
    async with _AI_QUOTA_LOCK:
        quota = _ai_quota_payload(db)
        if quota["remaining"] == 0:
            _record_ai_usage(
                db,
                user,
                feature=AI_MARKET_CONTEXT_FEATURE,
                success=False,
                status_code=429,
                duration_ms=0,
            )
            return account_api_error("Дневная квота ИИ-функций исчерпана.", status_code=429, key="accountErrorAiQuotaExceeded")
        usage_event = _record_ai_usage(
            db,
            user,
            feature=AI_MARKET_CONTEXT_FEATURE,
            success=True,
            status_code=200,
        )
    started = perf_counter()
    try:
        data = await load_ai_market_context(
            league=league,
            category=category,
            target=target,
            status=status,
            league_day=league_day,
            limit=limit,
            refresh=refresh,
        )
        usage_event.duration_ms = int((perf_counter() - started) * 1000)
        db.commit()
        if isinstance(data, dict):
            data["ai_quota"] = _ai_quota_payload(db)
        return data
    except Exception as exc:
        usage_event.success = 0
        usage_event.status_code = 502
        usage_event.duration_ms = int((perf_counter() - started) * 1000)
        db.commit()
        return trade_api_error(exc)


@router.post("/api/ai/market-analysis")
async def api_ai_market_analysis_create(
    request: Request,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
):
    user = require_ai_access(request, db)
    if isinstance(user, JSONResponse):
        return user

    league = _text(payload, "league")
    category = _text(payload, "category")
    target = _text(payload, "target", "exalted") or "exalted"
    status = _text(payload, "status", "any") or "any"
    if status not in {"online", "any"}:
        status = "any"
    if not league or not category:
        return account_api_error("Для ИИ-анализа нужны лига и категория.", key="accountErrorAiAnalysisPayload")

    params = {
        "league": league,
        "category": category,
        "target": target,
        "status": status,
        "league_day": _int_value(payload, "league_day"),
        "limit": min(max(_int_value(payload, "limit", 80) or 80, 1), 250),
        "max_candidates": min(max(_int_value(payload, "max_candidates", 10) or 10, 1), 20),
        "refresh": bool(payload.get("refresh")),
        "timeout_seconds": min(max(_int_value(payload, "timeout_seconds", 600) or 600, 30), 1800),
    }
    async with _AI_QUOTA_LOCK:
        quota = _ai_quota_payload(db)
        if quota["remaining"] == 0:
            _record_ai_usage(
                db,
                user,
                feature=AI_MARKET_ANALYSIS_FEATURE,
                success=False,
                status_code=429,
                duration_ms=0,
            )
            return account_api_error("Дневная квота ИИ-функций исчерпана.", status_code=429, key="accountErrorAiQuotaExceeded")
        job_id = uuid.uuid4().hex
        AI_MARKET_ANALYSIS_JOBS[job_id] = {
            "job_id": job_id,
            "user_id": user.id,
            "status": "queued",
            "created_at": now_iso(),
            "params": params,
            "assessment": None,
            "analysis_path": None,
            "error": None,
        }
        _prune_ai_market_analysis_jobs()
        _record_ai_usage(
            db,
            user,
            feature=AI_MARKET_ANALYSIS_FEATURE,
            success=True,
            status_code=202,
            duration_ms=0,
        )
    _schedule_ai_market_analysis_job(job_id, params)
    return JSONResponse(
        _ai_market_analysis_job_payload(AI_MARKET_ANALYSIS_JOBS[job_id]) | {"ai_quota": _ai_quota_payload(db)},
        status_code=202,
    )


@router.get("/api/ai/market-analysis/{job_id}")
def api_ai_market_analysis_status(
    job_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    user = require_ai_access(request, db)
    if isinstance(user, JSONResponse):
        return user
    job = AI_MARKET_ANALYSIS_JOBS.get(job_id)
    if not job:
        return account_api_error("ИИ-анализ не найден.", status_code=404, key="accountErrorAiAnalysisNotFound")
    if job.get("user_id") != user.id and not _user_is_admin(user):
        return account_api_error("ИИ-анализ не найден.", status_code=404, key="accountErrorAiAnalysisNotFound")
    payload = _ai_market_analysis_job_payload(job)
    payload["ai_quota"] = _ai_quota_payload(db)
    return payload


@router.post("/api/ai/currency-analysis")
async def api_ai_currency_analysis_create(
    request: Request,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
):
    user = require_ai_access(request, db)
    if isinstance(user, JSONResponse):
        return user

    league = _text(payload, "league")
    currency_id = _text(payload, "currency_id")
    target = _text(payload, "target", "exalted") or "exalted"
    status = _text(payload, "status", "any") or "any"
    if status not in {"online", "any"}:
        status = "any"
    if not league or not currency_id:
        return account_api_error("Для ИИ-анализа валюты нужны лига и валюта.", key="accountErrorAiCurrencyPayload")

    params = {
        "league": league,
        "currency_id": currency_id,
        "target": target,
        "status": status,
        "league_day": _int_value(payload, "league_day"),
        "history_limit": min(max(_int_value(payload, "history_limit", 1500) or 1500, 2), 2000),
        "horizon_hours": min(max(_int_value(payload, "horizon_hours", 24) or 24, 1), 168),
        "forecast_points": min(max(_int_value(payload, "forecast_points", 12) or 12, 2), 48),
        "refresh": bool(payload.get("refresh")),
        "timeout_seconds": min(max(_int_value(payload, "timeout_seconds", 600) or 600, 30), 1800),
    }
    async with _AI_QUOTA_LOCK:
        quota = _ai_quota_payload(db)
        if quota["remaining"] == 0:
            _record_ai_usage(
                db,
                user,
                feature=AI_CURRENCY_ANALYSIS_FEATURE,
                success=False,
                status_code=429,
                duration_ms=0,
            )
            return account_api_error("Дневная квота ИИ-функций исчерпана.", status_code=429, key="accountErrorAiQuotaExceeded")
        job_id = uuid.uuid4().hex
        AI_CURRENCY_ANALYSIS_JOBS[job_id] = {
            "job_id": job_id,
            "user_id": user.id,
            "status": "queued",
            "created_at": now_iso(),
            "params": params,
            "context": None,
            "assessment": None,
            "analysis_path": None,
            "error": None,
        }
        _prune_ai_currency_analysis_jobs()
        _record_ai_usage(
            db,
            user,
            feature=AI_CURRENCY_ANALYSIS_FEATURE,
            success=True,
            status_code=202,
            duration_ms=0,
        )
    _schedule_ai_currency_analysis_job(job_id, params)
    return JSONResponse(
        _ai_market_analysis_job_payload(AI_CURRENCY_ANALYSIS_JOBS[job_id]) | {"ai_quota": _ai_quota_payload(db)},
        status_code=202,
    )


@router.get("/api/ai/currency-analysis/{job_id}")
def api_ai_currency_analysis_status(
    job_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    user = require_ai_access(request, db)
    if isinstance(user, JSONResponse):
        return user
    job = AI_CURRENCY_ANALYSIS_JOBS.get(job_id)
    if not job:
        return account_api_error("ИИ-анализ не найден.", status_code=404, key="accountErrorAiAnalysisNotFound")
    if job.get("user_id") != user.id and not _user_is_admin(user):
        return account_api_error("ИИ-анализ не найден.", status_code=404, key="accountErrorAiAnalysisNotFound")
    payload = _ai_market_analysis_job_payload(job)
    payload["ai_quota"] = _ai_quota_payload(db)
    return payload


@router.get("/api/rows")
def api_rows(
    league: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    snapshot_id: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    stmt = select(Row, Snapshot).join(Snapshot, Row.snapshot_id == Snapshot.id)
    if league:
        stmt = stmt.where(Snapshot.league == league)
    if category:
        stmt = stmt.where(Snapshot.category == category)
    if snapshot_id:
        stmt = stmt.where(Row.snapshot_id == snapshot_id)
    rows = db.execute(stmt).all()
    payload = []
    columns_union = set()
    for row, snap in rows:
        cols = json.loads(row.columns_json)
        columns_union.update(cols.keys())
        payload.append(
            {
                "snapshot_id": row.snapshot_id,
                "row_id": row.row_id,
                "league": snap.league,
                "category": snap.category,
                "name": row.name,
                "icon_url": row.icon_url,
                "icon_local": row.icon_local,
                "columns": cols,
            }
        )
    if q:
        payload = [p for p in payload if q.lower() in p["name"].lower()]
    return {"columns": sorted(columns_union), "rows": payload}


@router.get("/row/{snapshot_id}/{row_id}", response_class=HTMLResponse)
def row_detail(snapshot_id: str, row_id: str, request: Request, db: Session = Depends(get_db)):
    stmt = select(Row).where(Row.snapshot_id == snapshot_id, Row.row_id == row_id)
    row = db.scalars(stmt).first()
    if not row:
        return PlainTextResponse("Not found", status_code=404)
    return templates.TemplateResponse(
        request=request,
        name="row.html",
        context={
            "row": row,
            "columns": json.loads(row.columns_json),
            "raw": json.loads(row.raw_json),
        },
    )


@router.get("/export/csv")
def export_csv(
    league: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    snapshot_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    stmt = select(Row, Snapshot).join(Snapshot, Row.snapshot_id == Snapshot.id)
    if league:
        stmt = stmt.where(Snapshot.league == league)
    if category:
        stmt = stmt.where(Snapshot.category == category)
    if snapshot_id:
        stmt = stmt.where(Row.snapshot_id == snapshot_id)
    rows = db.execute(stmt).all()
    content = export_rows_csv(rows)
    return PlainTextResponse(content, media_type="text/csv")


@router.get("/export/jsonl")
def export_jsonl(
    league: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    snapshot_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    stmt = select(Row, Snapshot).join(Snapshot, Row.snapshot_id == Snapshot.id)
    if league:
        stmt = stmt.where(Snapshot.league == league)
    if category:
        stmt = stmt.where(Snapshot.category == category)
    if snapshot_id:
        stmt = stmt.where(Row.snapshot_id == snapshot_id)
    rows = db.execute(stmt).all()
    content = export_rows_jsonl(rows)
    return PlainTextResponse(content, media_type="application/jsonl")
