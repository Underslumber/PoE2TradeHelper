from __future__ import annotations

import json
import math
import re
import asyncio
import statistics
import time
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import USER_AGENT
from app.db.models import FunpayRubOffer, FunpayRubSnapshot
from app.db.session import get_session
from app.market_snapshots import (
    DEFAULT_EARLY_DAYS,
    DEFAULT_EARLY_INTERVAL_MINUTES,
    DEFAULT_INTERVAL_MINUTES,
    market_snapshot_interval_seconds,
)

FUNPAY_POE2_CHIPS_URL = "https://funpay.com/chips/209/"
FUNPAY_CACHE_SECONDS = 15 * 60
FUNPAY_CONTEXT_SCHEMA_VERSION = "funpay-rub-market/v3"

FUNPAY_SIDE_TO_TRADE_ID = {
    "101": "alch",
    "102": "transmute",
    "103": "aug",
    "104": "regal",
    "105": "exalted",
    "106": "divine",
    "107": "chaos",
    "108": "annul",
    "109": "chance",
    "110": "vaal",
    "111": "artificers",
    "112": "gcp",
    "113": "bauble",
    "114": "whetstone",
    "115": "scrap",
    "116": "lesser-jewellers-orb",
    "117": "greater-jewellers-orb",
    "118": "perfect-jewellers-orb",
    "119": "etcher",
    "174": "fracturing-orb",
}

PRIMARY_TRADE_IDS = ("divine", "exalted", "chaos")
PRICE_RE = re.compile(r"[-+]?\d+(?:[\s\u00a0]\d{3})*(?:[.,]\d+)?|[-+]?\d+")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _text(node) -> str:
    if not node:
        return ""
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip()


def _number(value: str | None) -> float | None:
    if not value:
        return None
    match = PRICE_RE.search(value.replace("\u00a0", " "))
    if not match:
        return None
    normalized = match.group(0).replace(" ", "").replace(",", ".")
    try:
        return float(normalized)
    except ValueError:
        return None


def _int_number(value: str | None) -> int | None:
    number = _number(value)
    return int(number) if number is not None else None


def _seller_id_from_href(value: str | None) -> str:
    if not value:
        return ""
    match = re.search(r"/users/(\d+)/?", value)
    return match.group(1) if match else ""


def _offer_id_from_href(value: str | None) -> str:
    if not value:
        return ""
    parsed = urlparse(value)
    offer_id = parse_qs(parsed.query).get("id", [""])[0]
    return offer_id or value.rsplit("/", 1)[-1]


def _option_map(soup: BeautifulSoup, name: str) -> dict[str, str]:
    select_node = soup.select_one(f'select[name="{name}"]')
    if not select_node:
        return {}
    return {
        str(option.get("value") or ""): _text(option)
        for option in select_node.select("option")
        if option.get("value")
    }


def parse_funpay_chips_html(html: str, *, source_url: str = FUNPAY_POE2_CHIPS_URL) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    servers = _option_map(soup, "server")
    sides = _option_map(soup, "side")
    offers: list[dict[str, Any]] = []

    for node in soup.select("a.tc-item"):
        side_id = str(node.get("data-side") or "")
        league_id = str(node.get("data-server") or "")
        price_text = _text(node.select_one(".tc-price"))
        rub_per_unit = _number(price_text)
        if rub_per_unit is None or rub_per_unit <= 0 or "₽" not in price_text:
            continue

        offer = {
            "offer_id": _offer_id_from_href(node.get("href")),
            "offer_url": node.get("href") or "",
            "league": _text(node.select_one(".tc-server.hidden-xxs"))
            or _text(node.select_one(".tc-server-inside"))
            or servers.get(league_id, ""),
            "league_id": league_id,
            "currency_name": _text(node.select_one(".tc-side.hidden-xxs"))
            or _text(node.select_one(".tc-side-inside"))
            or sides.get(side_id, ""),
            "side_id": side_id,
            "trade_item_id": FUNPAY_SIDE_TO_TRADE_ID.get(side_id),
            "seller_id": _seller_id_from_href(node.select_one(".avatar-photo") and node.select_one(".avatar-photo").get("data-href")),
            "seller_name": _text(node.select_one(".media-user-name")),
            "seller_reviews": _int_number(_text(node.select_one(".rating-mini-count"))),
            "seller_online": bool(node.get("data-online")) or bool(node.select_one(".media-user.online")),
            "stock": _number(_text(node.select_one(".tc-amount"))),
            "rub_per_unit": rub_per_unit,
        }
        if offer["offer_id"] and offer["league"] and offer["currency_name"]:
            offers.append(offer)

    return {
        "source_url": source_url,
        "servers": servers,
        "sides": sides,
        "offers": offers,
    }


async def fetch_funpay_chips_html(url: str = FUNPAY_POE2_CHIPS_URL) -> str:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "ru,en;q=0.8",
    }
    async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=30) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.text


def _snapshot_summary(parsed: dict[str, Any]) -> dict[str, Any]:
    offers = parsed.get("offers") or []
    return {
        "servers": parsed.get("servers") or {},
        "sides": parsed.get("sides") or {},
        "offer_count": len(offers),
        "mapped_offer_count": sum(1 for offer in offers if offer.get("trade_item_id")),
    }


def save_funpay_rub_snapshot(db: Session, parsed: dict[str, Any], *, created_ts: float | None = None) -> FunpayRubSnapshot:
    created_ts = time.time() if created_ts is None else created_ts
    offers = parsed.get("offers") or []
    summary = _snapshot_summary(parsed)
    snapshot = FunpayRubSnapshot(
        id=f"funpay-rub-{int(created_ts * 1000)}",
        created_at=datetime.fromtimestamp(created_ts, tz=timezone.utc).isoformat(),
        created_ts=created_ts,
        source_url=parsed.get("source_url") or FUNPAY_POE2_CHIPS_URL,
        offer_count=len(offers),
        mapped_offer_count=summary["mapped_offer_count"],
        raw_json=json.dumps(summary, ensure_ascii=False, separators=(",", ":")),
    )
    db.add(snapshot)
    for offer in offers:
        db.add(
            FunpayRubOffer(
                snapshot_id=snapshot.id,
                offer_id=str(offer["offer_id"]),
                league=str(offer["league"]),
                league_id=str(offer.get("league_id") or ""),
                currency_name=str(offer["currency_name"]),
                side_id=str(offer["side_id"]),
                trade_item_id=offer.get("trade_item_id"),
                seller_id=str(offer.get("seller_id") or ""),
                seller_name=str(offer.get("seller_name") or ""),
                seller_reviews=offer.get("seller_reviews"),
                seller_online=1 if offer.get("seller_online") else 0,
                stock=offer.get("stock"),
                rub_per_unit=float(offer["rub_per_unit"]),
                raw_json=json.dumps(offer, ensure_ascii=False, separators=(",", ":")),
            )
        )
    db.commit()
    db.refresh(snapshot)
    return snapshot


async def collect_funpay_rub_snapshot(db: Session) -> FunpayRubSnapshot:
    html = await fetch_funpay_chips_html()
    parsed = parse_funpay_chips_html(html)
    return save_funpay_rub_snapshot(db, parsed)


async def collect_funpay_rub_market_snapshot(
    *,
    league: str,
    target_currency: str = "divine",
    history_days: int = 7,
) -> dict[str, Any]:
    started_ts = time.time()
    with get_session() as db:
        snapshot = await collect_funpay_rub_snapshot(db)
        context = build_funpay_rub_context(
            db,
            snapshot,
            league=league,
            target_currency=target_currency,
            cached=False,
            history_days=history_days,
        )
    focus = context.get("focus") or {}
    return {
        "ok": True,
        "created_ts": started_ts,
        "league": league,
        "target_currency": target_currency,
        "source": context.get("source"),
        "source_url": context.get("source_url"),
        "snapshot": context.get("snapshot"),
        "focus": {
            "market_price": focus.get("market_price"),
            "best": focus.get("best"),
            "low_market_offers": focus.get("low_market_offers"),
            "low_market_stock": focus.get("low_market_stock"),
            "ignored_high_offers": focus.get("ignored_high_offers"),
            "offers": focus.get("offers"),
            "seller_count": focus.get("seller_count"),
            "online_sellers": focus.get("online_sellers"),
            "change_24h_pct": focus.get("change_24h_pct"),
        }
        if focus
        else None,
        "duration_seconds": round(time.time() - started_ts, 3),
    }


async def run_funpay_rub_snapshot_loop(
    *,
    league: str,
    target_currency: str = "divine",
    interval_minutes: float = DEFAULT_INTERVAL_MINUTES,
    early_interval_minutes: float = DEFAULT_EARLY_INTERVAL_MINUTES,
    early_days: float = DEFAULT_EARLY_DAYS,
    league_start_ts: float | None = None,
    max_cycles: int | None = None,
    on_summary: Callable[[dict[str, Any]], None] | None = None,
) -> None:
    cycles = 0
    while max_cycles is None or cycles < max_cycles:
        cycle_started = time.time()
        try:
            summary = await collect_funpay_rub_market_snapshot(
                league=league,
                target_currency=target_currency,
            )
        except Exception as exc:
            summary = {
                "ok": False,
                "created_ts": cycle_started,
                "league": league,
                "target_currency": target_currency,
                "error": str(exc),
            }
        cycles += 1
        if on_summary:
            on_summary(summary)
        if max_cycles is not None and cycles >= max_cycles:
            break
        interval_seconds = market_snapshot_interval_seconds(
            now_ts=time.time(),
            league_start_ts=league_start_ts,
            early_days=early_days,
            early_interval_minutes=early_interval_minutes,
            interval_minutes=interval_minutes,
        )
        await asyncio.sleep(max(0.0, interval_seconds - (time.time() - cycle_started)))


def latest_funpay_rub_snapshot(db: Session) -> FunpayRubSnapshot | None:
    return db.scalars(select(FunpayRubSnapshot).order_by(FunpayRubSnapshot.created_ts.desc())).first()


async def ensure_funpay_rub_snapshot(
    db: Session,
    *,
    refresh: bool = False,
    max_age_seconds: int = FUNPAY_CACHE_SECONDS,
) -> tuple[FunpayRubSnapshot | None, bool]:
    latest = latest_funpay_rub_snapshot(db)
    if not refresh and latest and time.time() - float(latest.created_ts or 0) <= max_age_seconds:
        return latest, True
    snapshot = await collect_funpay_rub_snapshot(db)
    return snapshot, False


def _percent_change(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None or previous <= 0:
        return None
    return ((current - previous) / previous) * 100


def _quantile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    index = min(len(values) - 1, max(0, int(round((len(values) - 1) * q))))
    return values[index]


def _offer_price_stock(offer: FunpayRubOffer) -> tuple[float, float] | None:
    price = float(offer.rub_per_unit or 0)
    if price <= 0:
        return None
    stock = float(offer.stock or 0)
    return price, max(0.0, stock)


def _weighted_price(records: list[tuple[FunpayRubOffer, float, float]]) -> float | None:
    weighted = [(price, stock) for _, price, stock in records if stock > 0]
    if weighted:
        total_stock = sum(stock for _, stock in weighted)
        if total_stock > 0:
            return sum(price * stock for price, stock in weighted) / total_stock
    prices = [price for _, price, _ in records]
    return statistics.median(prices) if prices else None


def _low_market_records(offers: list[FunpayRubOffer]) -> tuple[list[tuple[FunpayRubOffer, float, float]], float | None]:
    records: list[tuple[FunpayRubOffer, float, float]] = []
    for offer in offers:
        price_stock = _offer_price_stock(offer)
        if not price_stock:
            continue
        price, stock = price_stock
        records.append((offer, price, stock))
    records.sort(key=lambda item: item[1])
    if not records:
        return [], None

    prices = [price for _, price, _ in records]
    best = prices[0]
    p10 = _quantile(prices, 0.1) or best
    p25 = _quantile(prices, 0.25) or p10
    ceiling = max(best * 1.4, p10 * 1.75, p25)
    selected = [item for item in records if item[1] <= ceiling]

    minimum = min(len(records), 3)
    if len(selected) < minimum:
        selected = records[:minimum]
        ceiling = selected[-1][1]
    return selected, ceiling


def aggregate_funpay_offers(offers: list[FunpayRubOffer]) -> dict[str, Any]:
    prices = sorted(float(offer.rub_per_unit) for offer in offers if offer.rub_per_unit and offer.rub_per_unit > 0)
    stocks = [float(offer.stock) for offer in offers if offer.stock is not None and offer.stock > 0]
    sellers = {offer.seller_name or offer.seller_id or offer.offer_id for offer in offers}
    online_sellers = {offer.seller_name or offer.seller_id or offer.offer_id for offer in offers if offer.seller_online}
    if not prices:
        return {}
    trimmed = prices
    if len(prices) >= 8:
        trim = max(1, int(len(prices) * 0.1))
        trimmed = prices[trim:-trim] or prices
    low_records, low_ceiling = _low_market_records(offers)
    low_stocks = [stock for _, _, stock in low_records if stock > 0]
    low_sellers = {offer.seller_name or offer.seller_id or offer.offer_id for offer, _, _ in low_records}
    low_price = _weighted_price(low_records)
    ignored_high = max(0, len(prices) - len(low_records))
    ignored_high_stock = sum(stocks) - sum(low_stocks) if stocks else None
    return {
        "best": prices[0],
        "p10": _quantile(prices, 0.1),
        "median": statistics.median(prices),
        "trimmed_median": statistics.median(trimmed),
        "market_price": low_price,
        "price_basis": "low_market_weighted",
        "low_market_ceiling": low_ceiling,
        "low_market_offers": len(low_records),
        "low_market_sellers": len(low_sellers),
        "low_market_stock": sum(low_stocks) if low_stocks else None,
        "ignored_high_offers": ignored_high,
        "ignored_high_stock": ignored_high_stock,
        "offers": len(offers),
        "seller_count": len(sellers),
        "online_sellers": len(online_sellers),
        "listed_stock": sum(stocks) if stocks else None,
    }


def _offers_for_snapshot(db: Session, snapshot_id: str, *, league: str | None = None) -> list[FunpayRubOffer]:
    stmt = select(FunpayRubOffer).where(FunpayRubOffer.snapshot_id == snapshot_id)
    if league:
        stmt = stmt.where(FunpayRubOffer.league == league)
    return list(db.scalars(stmt).all())


def _history_points(
    db: Session,
    *,
    league: str,
    trade_item_id: str,
    since_ts: float,
    limit: int = 500,
) -> list[dict[str, Any]]:
    stmt = (
        select(FunpayRubSnapshot, FunpayRubOffer)
        .join(FunpayRubOffer, FunpayRubOffer.snapshot_id == FunpayRubSnapshot.id)
        .where(
            FunpayRubSnapshot.created_ts >= since_ts,
            FunpayRubOffer.league == league,
            FunpayRubOffer.trade_item_id == trade_item_id,
        )
        .order_by(FunpayRubSnapshot.created_ts.asc())
    )
    grouped: dict[str, dict[str, Any]] = {}
    for snapshot, offer in db.execute(stmt).all():
        item = grouped.setdefault(
            snapshot.id,
            {
                "snapshot": snapshot,
                "offers": [],
            },
        )
        item["offers"].append(offer)

    points = []
    for item in grouped.values():
        stats = aggregate_funpay_offers(item["offers"])
        if not stats:
            continue
        points.append(
            {
                "snapshot_id": item["snapshot"].id,
                "created_ts": item["snapshot"].created_ts,
                "created_at": item["snapshot"].created_at,
                "market_price": stats["market_price"],
                "median": stats["median"],
                "trimmed_median": stats["trimmed_median"],
                "best": stats["best"],
                "offers": stats["offers"],
                "low_market_offers": stats["low_market_offers"],
                "low_market_stock": stats["low_market_stock"],
                "ignored_high_offers": stats["ignored_high_offers"],
                "seller_count": stats["seller_count"],
                "online_sellers": stats["online_sellers"],
                "listed_stock": stats["listed_stock"],
            }
        )
    return points[-limit:]


def _point_before(points: list[dict[str, Any]], current_ts: float, hours: float) -> dict[str, Any] | None:
    cutoff = current_ts - hours * 3600
    candidates = [point for point in points if float(point.get("created_ts") or 0) <= cutoff]
    return candidates[-1] if candidates else None


def _row_changes(row: dict[str, Any], history: list[dict[str, Any]]) -> dict[str, Any]:
    current_ts = float(row.get("created_ts") or 0)
    previous = history[-2] if len(history) >= 2 else None
    previous_24h = _point_before(history, current_ts, 24)
    previous_7d = _point_before(history, current_ts, 24 * 7)
    current_price = row.get("market_price") or row.get("trimmed_median") or row.get("median")
    return {
        "change_last_pct": _percent_change(
            current_price,
            (previous.get("market_price") or previous.get("trimmed_median") or previous.get("median")) if previous else None,
        ),
        "change_24h_pct": _percent_change(
            current_price,
            (previous_24h.get("market_price") or previous_24h.get("trimmed_median") or previous_24h.get("median"))
            if previous_24h
            else None,
        ),
        "change_7d_pct": _percent_change(
            current_price,
            (previous_7d.get("market_price") or previous_7d.get("trimmed_median") or previous_7d.get("median"))
            if previous_7d
            else None,
        ),
        "listed_stock_delta_last": (
            row.get("listed_stock") - previous.get("listed_stock")
            if previous and row.get("listed_stock") is not None and previous.get("listed_stock") is not None
            else None
        ),
        "offers_delta_last": (
            row.get("offers") - previous.get("offers")
            if previous and row.get("offers") is not None and previous.get("offers") is not None
            else None
        ),
    }


def _hourly_history(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[int, dict[str, Any]] = {}
    for point in points:
        created_ts = float(point.get("created_ts") or 0)
        if created_ts <= 0:
            continue
        hour_ts = int(created_ts // 3600 * 3600)
        current = buckets.get(hour_ts)
        if not current or created_ts >= float(current.get("created_ts") or 0):
            buckets[hour_ts] = {
                **point,
                "hour_ts": hour_ts,
                "hour_at": datetime.fromtimestamp(hour_ts, tz=timezone.utc).isoformat(),
            }
    return [buckets[key] for key in sorted(buckets)]


def _rub_point_price(point: dict[str, Any]) -> float | None:
    value = point.get("market_price") or point.get("trimmed_median") or point.get("median") or point.get("best")
    try:
        price = float(value)
    except (TypeError, ValueError):
        return None
    return price if price > 0 else None


def _local_dt_from_ts(ts: float) -> datetime:
    return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone()


def _average(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _calendar_day_score(items: list[dict[str, Any]]) -> dict[str, Any] | None:
    prices = [float(item["price"]) for item in items if item.get("price") is not None]
    if not prices:
        return None
    sample = items[0]
    return {
        "weekday": sample["weekday"],
        "avg_price": _average(prices),
        "min_price": min(prices),
        "max_price": max(prices),
        "points": len(prices),
    }


def _merge_hour_intervals(hours: set[int]) -> list[tuple[int, int]]:
    if not hours:
        return []
    sorted_hours = sorted(hours)
    intervals: list[tuple[int, int]] = []
    start = previous = sorted_hours[0]
    for hour in sorted_hours[1:]:
        if hour == previous + 1:
            previous = hour
            continue
        intervals.append((start, previous + 1))
        start = previous = hour
    intervals.append((start, previous + 1))
    return intervals


def _hour_intervals(items: list[dict[str, Any]], *, prefer: str) -> list[dict[str, Any]]:
    buckets: dict[int, list[float]] = {}
    for item in items:
        buckets.setdefault(int(item["hour"]), []).append(float(item["price"]))
    if not buckets:
        return []
    scores = [
        {
            "hour": hour,
            "avg_price": _average(prices),
            "points": len(prices),
        }
        for hour, prices in buckets.items()
    ]
    reverse = prefer == "high"
    scores.sort(key=lambda item: item["avg_price"] or 0, reverse=reverse)
    min_hours = 2 if len(scores) >= 2 else 1
    take = min(6, max(min_hours, math.ceil(len(scores) * 0.25)))
    selected = {int(item["hour"]) for item in scores[:take]}
    intervals = []
    for start_hour, end_hour in _merge_hour_intervals(selected):
        interval_items = [item for item in items if start_hour <= int(item["hour"]) < end_hour]
        prices = [float(item["price"]) for item in interval_items]
        intervals.append(
            {
                "start_hour": start_hour,
                "end_hour": end_hour,
                "avg_price": _average(prices),
                "points": len(prices),
            }
        )
    intervals.sort(key=lambda item: item["avg_price"] or 0, reverse=reverse)
    return intervals[:2]


def _calendar_recommendation(
    items: list[dict[str, Any]],
    *,
    prefer: str,
) -> dict[str, Any] | None:
    day_buckets: dict[int, list[dict[str, Any]]] = {}
    for item in items:
        day_buckets.setdefault(int(item["weekday"]), []).append(item)
    day_scores = [score for score in (_calendar_day_score(values) for values in day_buckets.values()) if score]
    if not day_scores:
        return None
    reverse = prefer == "high"
    day_scores.sort(key=lambda item: item["avg_price"] or 0, reverse=reverse)
    selected_day = day_scores[0]
    day_items = day_buckets.get(int(selected_day["weekday"]), [])
    hour_source = "weekday"
    if len({item["hour"] for item in day_items}) < 2:
        day_items = items
        hour_source = "all_days"
    return {
        **selected_day,
        "hour_intervals": _hour_intervals(day_items, prefer=prefer),
        "hour_source": hour_source,
    }


def build_funpay_calendar_recommendations(hourly_history: list[dict[str, Any]]) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for point in hourly_history:
        created_ts = float(point.get("hour_ts") or point.get("created_ts") or 0)
        price = _rub_point_price(point)
        if created_ts <= 0 or price is None:
            continue
        local_dt = _local_dt_from_ts(created_ts)
        items.append(
            {
                "created_ts": created_ts,
                "date": local_dt.date().isoformat(),
                "weekday": local_dt.weekday(),
                "hour": local_dt.hour,
                "price": price,
            }
        )
    sample_days = len({item["date"] for item in items})
    weekday_count = len({item["weekday"] for item in items})
    if len(items) < 24 or weekday_count < 3:
        confidence = "insufficient"
    elif len(items) < 72 or weekday_count < 7:
        confidence = "partial"
    else:
        confidence = "ok"
    return {
        "timezone": _local_dt_from_ts(time.time()).tzname(),
        "sample_hours": len(items),
        "sample_days": sample_days,
        "weekday_count": weekday_count,
        "confidence": confidence,
        "buy": _calendar_recommendation(items, prefer="low"),
        "sell": _calendar_recommendation(items, prefer="high"),
    }


def _group_latest_rows(
    db: Session,
    snapshot: FunpayRubSnapshot,
    *,
    league: str | None = None,
) -> dict[str, list[FunpayRubOffer]]:
    grouped: dict[str, list[FunpayRubOffer]] = {}
    for offer in _offers_for_snapshot(db, snapshot.id, league=league):
        key = offer.trade_item_id or f"funpay-side-{offer.side_id}"
        grouped.setdefault(key, []).append(offer)
    return grouped


def build_funpay_rub_context(
    db: Session,
    snapshot: FunpayRubSnapshot,
    *,
    league: str,
    target_currency: str = "divine",
    cached: bool = False,
    history_days: int = 7,
) -> dict[str, Any]:
    grouped = _group_latest_rows(db, snapshot, league=league)
    since_ts = float(snapshot.created_ts or time.time()) - max(1, history_days) * 86400
    rows = []
    focus_history: list[dict[str, Any]] = []
    focus_hourly_history: list[dict[str, Any]] = []

    for trade_item_id, offers in grouped.items():
        stats = aggregate_funpay_offers(offers)
        if not stats:
            continue
        sample = offers[0]
        history = _history_points(
            db,
            league=league,
            trade_item_id=trade_item_id,
            since_ts=since_ts,
        )
        row = {
            "trade_item_id": sample.trade_item_id,
            "side_id": sample.side_id,
            "currency_name": sample.currency_name,
            "league": sample.league,
            "created_ts": snapshot.created_ts,
            "created_at": snapshot.created_at,
            **stats,
        }
        row.update(_row_changes(row, history))
        rows.append(row)
        if trade_item_id == target_currency:
            focus_history = history
            focus_hourly_history = _hourly_history(history)

    rows.sort(
        key=lambda item: (
            PRIMARY_TRADE_IDS.index(item["trade_item_id"])
            if item.get("trade_item_id") in PRIMARY_TRADE_IDS
            else len(PRIMARY_TRADE_IDS),
            item.get("currency_name") or "",
        )
    )
    by_id = {row.get("trade_item_id"): row for row in rows if row.get("trade_item_id")}
    return {
        "schema_version": FUNPAY_CONTEXT_SCHEMA_VERSION,
        "source": "funpay-public-html",
        "source_url": snapshot.source_url,
        "cached": cached,
        "league": league,
        "target_currency": target_currency,
        "snapshot": {
            "id": snapshot.id,
            "created_at": snapshot.created_at,
            "created_ts": snapshot.created_ts,
            "offer_count": snapshot.offer_count,
            "mapped_offer_count": snapshot.mapped_offer_count,
        },
        "rows": rows,
        "by_currency": by_id,
        "focus": by_id.get(target_currency),
        "focus_history": focus_history,
        "focus_hourly_history": focus_hourly_history,
        "calendar_recommendations": build_funpay_calendar_recommendations(focus_hourly_history),
        "flow_note": "stock_and_offer_deltas_are_listing_proxies_not_confirmed_sales",
    }


async def load_funpay_rub_context(
    db: Session,
    *,
    league: str,
    target_currency: str = "divine",
    refresh: bool = False,
    history_days: int = 7,
) -> dict[str, Any]:
    snapshot, cached = await ensure_funpay_rub_snapshot(db, refresh=refresh)
    if not snapshot:
        return {
            "schema_version": FUNPAY_CONTEXT_SCHEMA_VERSION,
            "source": "funpay-public-html",
            "source_url": FUNPAY_POE2_CHIPS_URL,
            "cached": False,
            "league": league,
            "target_currency": target_currency,
            "snapshot": None,
            "rows": [],
            "by_currency": {},
            "focus": None,
            "focus_history": [],
            "focus_hourly_history": [],
            "calendar_recommendations": build_funpay_calendar_recommendations([]),
            "flow_note": "stock_and_offer_deltas_are_listing_proxies_not_confirmed_sales",
        }
    return build_funpay_rub_context(
        db,
        snapshot,
        league=league,
        target_currency=target_currency,
        cached=cached,
        history_days=history_days,
    )
