from __future__ import annotations

from app.trade.cache import SQLiteCacheManager
from app.trade.history import (
    log_market_history,
    read_item_history as _read_history_item,
    read_latest_rates as _read_history_latest_rates,
    read_market_history,
)

import asyncio
import json
import re
import statistics
import time
from typing import Any
from urllib.parse import quote

import httpx

from app.config import BASE_URL, DATA_DIR, DEFAULT_RATE_LIMIT_DELAY, USER_AGENT
from app.item_parser import parse_item_text
from app.profitability import enrich_trade_advice, execution_quality, rank_opportunities
from app.recipes import analyze_recipes, filter_dominated_emotion_paths

TRADE2_BASE = "https://www.pathofexile.com/api/trade2"
TRADE2_RU_BASE = "https://ru.pathofexile.com/api/trade2"
POE_SITE_BASE = "https://www.pathofexile.com"
HISTORY_PATH = DATA_DIR / "trade_rate_history.jsonl"
TRADE_STATIC_CACHE_TTL = 3600
TRADE_STATIC_CACHE: dict[str, Any] = {"created_ts": 0.0, "data": None}
TRADE_STATIC_LOCK = asyncio.Lock()
SELLER_LOTS_CACHE_TTL = 900
SELLER_LOTS_FETCH_LIMIT = 200
SELLER_MARKET_CACHE_TTL = 600
SELLER_MARKET_FETCH_LIMIT = 60
SELLER_MARKET_MIN_COMPARABLES = 3
SELLER_MARKET_MAX_STAT_FILTERS = 12
SELLER_MARKET_PROFILE_MAX_STATS = 24
SELLER_SNAPSHOT_TIMEOUT = 30
SELLER_CURRENCY_RATES_TIMEOUT = 20
SELLER_MARKET_PER_LOT_TIMEOUT = 20
SELLER_ANALYSIS_BUDGET = 70
TRADE2_MAX_RETRY_AFTER_WAIT_SECONDS = 8
SELLER_LOTS_CACHE: dict[tuple[str, str, str], dict[str, Any]] = {}
SELLER_MARKET_CACHE: dict[tuple[Any, ...], dict[str, Any]] = {}
INSTANT_BUYOUT_PRICE_TYPES = {"~price", "~b/o"}
ITEM_BASES_CACHE_TTL = 3600
ITEM_BASE_MARKET_CATEGORY = "ItemBases"
ITEM_BASE_MARKET_CACHE_TTL = 900
ITEM_BASE_MARKET_FETCH_LIMIT = 40
ITEM_BASE_MARKET_OVERVIEW_FETCH_LIMIT = 80
ITEM_BASE_MARKET_MAX_BASES = 80
ITEM_BASES_CACHE: dict[str, Any] = {"created_ts": 0.0, "data": None, "errors": []}
ITEM_BASES_LOCK = asyncio.Lock()
ITEM_BASE_MARKET_CACHE: dict[tuple[Any, ...], dict[str, Any]] = {}

ITEM_BASE_FALLBACKS = [
    {"type": "Waxed Jacket", "type_ru": "Вощеная куртка", "category": "body-armour", "category_ru": "Нательная броня", "icon_key": "armour"},
    {"type": "Silk Robe", "type_ru": "Шелковая роба", "category": "body-armour", "category_ru": "Нательная броня", "icon_key": "robe"},
    {"type": "Votive Raiment", "type_ru": "Обетное одеяние", "category": "body-armour", "category_ru": "Нательная броня", "icon_key": "robe"},
    {"type": "Feathered Tiara", "type_ru": "Перьевая тиара", "category": "helmet", "category_ru": "Шлемы", "icon_key": "helmet"},
    {"type": "Hooded Mask", "type_ru": "Маска с капюшоном", "category": "helmet", "category_ru": "Шлемы", "icon_key": "helmet"},
    {"type": "Wrapped Sandals", "type_ru": "Обмотанные сандалии", "category": "boots", "category_ru": "Обувь", "icon_key": "boots"},
    {"type": "Rawhide Boots", "type_ru": "Сыромятные сапоги", "category": "boots", "category_ru": "Обувь", "icon_key": "boots"},
    {"type": "Gold Ring", "type_ru": "Золотое кольцо", "category": "ring", "category_ru": "Кольца", "icon_key": "ring"},
    {"type": "Sapphire Ring", "type_ru": "Сапфировое кольцо", "category": "ring", "category_ru": "Кольца", "icon_key": "ring"},
    {"type": "Ruby Ring", "type_ru": "Рубиновое кольцо", "category": "ring", "category_ru": "Кольца", "icon_key": "ring"},
    {"type": "Emerald Ring", "type_ru": "Изумрудное кольцо", "category": "ring", "category_ru": "Кольца", "icon_key": "ring"},
    {"type": "Gold Amulet", "type_ru": "Золотой амулет", "category": "amulet", "category_ru": "Амулеты", "icon_key": "amulet"},
    {"type": "Heavy Belt", "type_ru": "Тяжелый пояс", "category": "belt", "category_ru": "Пояса", "icon_key": "belt"},
    {"type": "Wide Belt", "type_ru": "Широкий пояс", "category": "belt", "category_ru": "Пояса", "icon_key": "belt"},
    {"type": "Quarterstaff", "type_ru": "Боевой посох", "category": "weapon", "category_ru": "Оружие", "icon_key": "staff"},
    {"type": "Volant Quarterstaff", "type_ru": "Летучий боевой посох", "category": "weapon", "category_ru": "Оружие", "icon_key": "staff"},
    {"type": "Sceptre", "type_ru": "Скипетр", "category": "weapon", "category_ru": "Оружие", "icon_key": "sceptre"},
    {"type": "Wand", "type_ru": "Жезл", "category": "weapon", "category_ru": "Оружие", "icon_key": "wand"},
    {"type": "Shortbow", "type_ru": "Короткий лук", "category": "weapon", "category_ru": "Оружие", "icon_key": "bow"},
    {"type": "Crossbow", "type_ru": "Арбалет", "category": "weapon", "category_ru": "Оружие", "icon_key": "crossbow"},
    {"type": "Focus", "type_ru": "Фокус", "category": "focus", "category_ru": "Фокусы", "icon_key": "focus"},
    {"type": "Buckler", "type_ru": "Баклер", "category": "shield", "category_ru": "Щиты", "icon_key": "shield"},
]

ITEM_BASE_RU = {str(item["type"]): str(item["type_ru"]) for item in ITEM_BASE_FALLBACKS}
ITEM_BASE_CATEGORY_RU = {
    "armour": "Броня",
    "body-armour": "Нательная броня",
    "body armour": "Нательная броня",
    "helmet": "Шлемы",
    "helmets": "Шлемы",
    "boots": "Обувь",
    "gloves": "Перчатки",
    "ring": "Кольца",
    "rings": "Кольца",
    "amulet": "Амулеты",
    "amulets": "Амулеты",
    "belt": "Пояса",
    "belts": "Пояса",
    "weapon": "Оружие",
    "weapons": "Оружие",
    "focus": "Фокусы",
    "focuses": "Фокусы",
    "shield": "Щиты",
    "shields": "Щиты",
    "fallback": "Резервный каталог",
}
ITEM_BASE_ICON_STYLES = {
    "armour": ("#60a5fa", "ARM"),
    "robe": ("#a78bfa", "ROB"),
    "helmet": ("#f59e0b", "HLM"),
    "boots": ("#22c55e", "BOT"),
    "ring": ("#facc15", "RNG"),
    "amulet": ("#fb7185", "AMU"),
    "belt": ("#c084fc", "BLT"),
    "staff": ("#38bdf8", "STF"),
    "sceptre": ("#f97316", "SCP"),
    "wand": ("#818cf8", "WND"),
    "bow": ("#34d399", "BOW"),
    "crossbow": ("#2dd4bf", "XBW"),
    "focus": ("#e879f9", "FOC"),
    "shield": ("#93c5fd", "SHD"),
    "base": ("#94a3b8", "BAS"),
}

COMPARABLE_STAT_TYPES = ("explicit", "fractured", "implicit", "rune", "desecrated")
IMPORTANT_STAT_RE = re.compile(
    r"spirit|дух|life|здоров|resistance|сопротив|speed|скорост|skill|умени|damage|урон|"
    r"attribute|атрибут|strength|dexterity|intelligence|сил|ловк|инт|energy shield|энергет|"
    r"evasion|уклон|armour|брон",
    re.IGNORECASE,
)

POE_NINJA_CATEGORY_TYPES = {
    "Currency": "Currency",
    "Fragments": "Fragments",
    "Abyss": "Abyss",
    "UncutGems": "UncutGems",
    "LineageSupportGems": "LineageSupportGems",
    "Essences": "Essences",
    "Ultimatum": "SoulCores",
    "Idol": "Idols",
    "Runes": "Runes",
    "Ritual": "Ritual",
    "Expedition": "Expedition",
    "Delirium": "Delirium",
    "Breach": "Breach",
}


def _retry_after_wait(response: httpx.Response, context: str, fallback: int = 4) -> int:
    retry_after = response.headers.get("Retry-After")
    wait = int(retry_after) if retry_after and retry_after.isdigit() else fallback
    if wait > TRADE2_MAX_RETRY_AFTER_WAIT_SECONDS:
        suffix = f"; retry after {retry_after}s" if retry_after else ""
        raise RuntimeError(f"{context} rate limited{suffix}")
    return wait


CATEGORY_RU = {
    "Currency": "Валюта",
    "Incursion": "Ваал / Инкурсия",
    "Delirium": "Жидкие эмоции",
    "Breach": "Разлом / Катализаторы",
    "Ritual": "Ритуал / Омены",
    "Expedition": "Экспедиция",
    "Fragments": "Проходки и фрагменты",
    "Abyss": "Бездны",
    "Essences": "Эссенции",
    "Runes": "Руны",
    "Ultimatum": "Ультиматум / ядра душ",
    "Idol": "Идолы",
    "UncutGems": "Неограненные камни",
    "LineageSupportGems": "Родословные камни поддержки",
    "Waystones": "Камни пути",
}

ITEM_RU = {
    "Chaos Orb": "Сфера хаоса",
    "Exalted Orb": "Сфера возвышения",
    "Divine Orb": "Божественная сфера",
    "Mirror of Kalandra": "Зеркало Каландры",
    "Orb of Annulment": "Сфера отмены",
    "Perfect Exalted Orb": "Идеальная сфера возвышения",
    "Greater Exalted Orb": "Великая сфера возвышения",
    "Perfect Chaos Orb": "Идеальная сфера хаоса",
    "Greater Chaos Orb": "Великая сфера хаоса",
    "Diluted Liquid Ire": "Разбавленный жидкий гнев",
    "Diluted Liquid Guilt": "Разбавленная жидкая вина",
    "Diluted Liquid Greed": "Разбавленная жидкая жадность",
    "Liquid Paranoia": "Жидкая паранойя",
    "Liquid Envy": "Жидкая зависть",
    "Liquid Disgust": "Жидкое отвращение",
    "Liquid Despair": "Жидкое отчаяние",
    "Concentrated Liquid Fear": "Концентрированный жидкий страх",
    "Concentrated Liquid Suffering": "Концентрированное жидкое страдание",
    "Concentrated Liquid Isolation": "Концентрированное жидкое одиночество",
    "Simulacrum Splinter": "Осколок Симулякра",
    "Simulacrum": "Симулякр",
    "Kulemak's Invitation": "Приглашение Кулемака",
}

EMOTION_CHAIN = [
    "diluted-liquid-ire",
    "diluted-liquid-guilt",
    "diluted-liquid-greed",
    "liquid-paranoia",
    "liquid-envy",
    "liquid-disgust",
    "liquid-despair",
    "concentrated-liquid-fear",
    "concentrated-liquid-suffering",
    "concentrated-liquid-isolation",
]

LOW_VOLUME_THRESHOLD = 10.0
SIGNAL_MARGIN_THRESHOLD = 0.08
WEAK_MARGIN_THRESHOLD = 0.02


def _headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if extra:
        headers.update(extra)
    return headers


def _image_url(path: str | None) -> str | None:
    if not path:
        return None
    if path.startswith("http://") or path.startswith("https://"):
        return path
    return f"{POE_SITE_BASE}{path}"


def _localized_entry_texts(payload: dict[str, Any] | None) -> dict[str, dict[str, str]]:
    localized: dict[str, dict[str, str]] = {}
    if not payload:
        return localized
    for category in payload.get("result", []):
        category_id = category.get("id")
        if not category_id:
            continue
        localized[category_id] = {
            entry.get("id"): entry.get("text")
            for entry in category.get("entries", [])
            if entry.get("id") and entry.get("id") != "sep" and entry.get("text")
        }
    return localized


def normalize_static_entries(
    payload: dict[str, Any],
    localized_payload: dict[str, Any] | None = None,
) -> dict[str, list[dict[str, str | None]]]:
    localized = _localized_entry_texts(localized_payload)
    categories: dict[str, list[dict[str, str | None]]] = {}
    for category in payload.get("result", []):
        category_id = category.get("id")
        if not category_id:
            continue
        entries = []
        for entry in category.get("entries", []):
            entry_id = entry.get("id")
            text = entry.get("text")
            if not entry_id or entry_id == "sep" or not text:
                continue
            entries.append(
                {
                    "id": entry_id,
                    "text": text,
                    "text_ru": localized.get(category_id, {}).get(entry_id) or ITEM_RU.get(text, text),
                    "image": _image_url(entry.get("image")),
                }
            )
        categories[category_id] = entries
    return categories


def normalize_exchange_result(payload: dict[str, Any], limit: int = 50) -> dict[str, Any]:
    rows = []
    for entry in list((payload.get("result") or {}).values())[:limit]:
        listing = entry.get("listing") or {}
        account = listing.get("account") or {}
        for offer in listing.get("offers") or []:
            exchange = offer.get("exchange") or {}
            item = offer.get("item") or {}
            have_amount = exchange.get("amount")
            want_amount = item.get("amount")
            ratio = None
            try:
                if have_amount and want_amount:
                    ratio = float(want_amount) / float(have_amount)
            except (TypeError, ValueError, ZeroDivisionError):
                ratio = None
            rows.append(
                {
                    "seller": account.get("name") or "",
                    "online": bool(account.get("online")),
                    "indexed": listing.get("indexed") or "",
                    "have_currency": exchange.get("currency") or "",
                    "have_amount": have_amount,
                    "want_currency": item.get("currency") or "",
                    "want_amount": want_amount,
                    "stock": item.get("stock"),
                    "ratio": ratio,
                }
            )
    return {
        "query_id": payload.get("id"),
        "total": payload.get("total") or len(rows),
        "rows": rows,
    }


async def get_trade_leagues() -> list[dict[str, str]]:
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(headers=_headers(), timeout=30) as client:
                response = await client.get(f"{TRADE2_BASE}/data/leagues")
                if response.status_code == 429 and attempt < 2:
                    wait = _retry_after_wait(response, "trade2 leagues", fallback=2 * (attempt + 1))
                    await asyncio.sleep(wait)
                    continue
                response.raise_for_status()
            leagues = response.json().get("result", [])
            return [
                {
                    "id": league.get("id", ""),
                    "text": league.get("text") or league.get("id", ""),
                    "realm": league.get("realm", "poe2"),
                }
                for league in leagues
                if league.get("realm") == "poe2" and league.get("id")
            ]
        except (httpx.HTTPStatusError, httpx.RequestError) as exc:
            last_exc = exc
            if attempt < 2:
                await asyncio.sleep(2 * (attempt + 1))
    raise last_exc if last_exc else RuntimeError("trade leagues fetch failed")


async def get_trade_static() -> dict[str, list[dict[str, str | None]]]:
    cached = TRADE_STATIC_CACHE.get("data")
    if cached and time.time() - float(TRADE_STATIC_CACHE.get("created_ts") or 0) < TRADE_STATIC_CACHE_TTL:
        return cached

    async with TRADE_STATIC_LOCK:
        cached = TRADE_STATIC_CACHE.get("data")
        if cached and time.time() - float(TRADE_STATIC_CACHE.get("created_ts") or 0) < TRADE_STATIC_CACHE_TTL:
            return cached
        async with httpx.AsyncClient(headers=_headers(), timeout=30) as client:
            response, ru_response = await asyncio.gather(
                client.get(f"{TRADE2_BASE}/data/static"),
                client.get(f"{TRADE2_RU_BASE}/data/static"),
            )
            response.raise_for_status()
            ru_response.raise_for_status()
        data = normalize_static_entries(response.json(), ru_response.json())
        TRADE_STATIC_CACHE["created_ts"] = time.time()
        TRADE_STATIC_CACHE["data"] = data
        return data


async def _post_exchange(
    league: str,
    have: list[str],
    want: list[str],
    status: str = "online",
) -> dict[str, Any]:
    body = {
        "exchange": {
            "status": {"option": status},
            "have": have,
            "want": want,
        }
    }
    async with httpx.AsyncClient(headers=_headers({"Content-Type": "application/json"}), timeout=30) as client:
        response = await client.post(f"{TRADE2_BASE}/exchange/poe2/{quote(league, safe='')}", json=body)
        if response.status_code == 429:
            wait = _retry_after_wait(response, "trade2 exchange")
            await asyncio.sleep(wait)
            response = await client.post(f"{TRADE2_BASE}/exchange/poe2/{quote(league, safe='')}", json=body)
        response.raise_for_status()
    return response.json()


async def get_category_rates(
    league: str,
    category: str,
    target: str = "divine",
    status: str = "any",
    force_refresh: bool = False,
) -> dict[str, Any]:
    cache_key = SQLiteCacheManager.get_dict_key("rate", league, category, target, status)
    if not force_refresh:
        cached = SQLiteCacheManager.get(cache_key)
        if cached:
            cached["cached"] = True
            for row in cached.get("rows") or []:
                if "execution" not in row:
                    row["execution"] = execution_quality(row, snapshot_ts=cached.get("created_ts"))
            if "advice" not in cached:
                cached["advice"] = build_trade_advice(category, cached.get("rows") or [], target, snapshot_ts=cached.get("created_ts"))
            if "recipes" not in cached:
                cached["recipes"] = analyze_recipes(category, cached.get("rows") or [], target, snapshot_ts=cached.get("created_ts"))
            return cached

    categories = await get_trade_static()
    entries = categories.get(category, [])
    query_ids = []
    errors = []
    source = "trade2"

    poe_ninja_rates = None
    try:
        poe_ninja_rates = await _get_poe_ninja_rates(league, category, target)
    except Exception as exc:
        errors.append({"source": "poe.ninja", "error": str(exc)})

    if poe_ninja_rates:
        source = "poe.ninja"
        rate_by_id = {row["id"]: row for row in poe_ninja_rates.get("rows", []) if row.get("id")}
    else:
        ids = [entry["id"] for entry in entries if entry.get("id") and entry.get("id") != target]
        all_rows: list[dict[str, Any]] = []
        for chunk in _chunked(ids, 5):
            try:
                payload = await _post_exchange(league, chunk, [target], status=status)
                query_ids.append(payload.get("id"))
                all_rows.extend(normalize_exchange_result(payload, limit=250).get("rows", []))
            except Exception as exc:
                errors.append({"items": chunk, "error": str(exc)})
            await asyncio.sleep(DEFAULT_RATE_LIMIT_DELAY)
        rate_by_id = {entry["id"]: _rate_stats(all_rows, entry["id"]) for entry in entries}

    created_ts = time.time()
    rows = []
    for entry in entries:
        item_id = entry["id"]
        stats = rate_by_id.get(item_id, {})
        row = (
            {
                "id": item_id,
                "text": entry["text"],
                "text_ru": entry.get("text_ru") or entry["text"],
                "image": entry.get("image"),
                "best": stats.get("best"),
                "median": stats.get("median"),
                "offers": stats.get("offers", 0),
                "volume": stats.get("volume", 0),
                "change": stats.get("change"),
                "sparkline": stats.get("sparkline", []),
                "sparkline_kind": stats.get("sparkline_kind"),
                "max_volume_currency": stats.get("max_volume_currency"),
                "max_volume_rate": stats.get("max_volume_rate"),
            }
        )
        row["execution"] = execution_quality(row, snapshot_ts=created_ts)
        rows.append(row)

    snapshot = {
        "created_ts": created_ts,
        "league": league,
        "category": category,
        "target": target,
        "status": status,
        "query_ids": [query_id for query_id in query_ids if query_id],
        "source": source,
        "rows": rows,
        "errors": errors,
    }
    result = {
        "created_ts": snapshot["created_ts"],
        "league": league,
        "category": category,
        "target": target,
        "status": status,
        "rows": rows,
        "advice": build_trade_advice(category, rows, target, snapshot_ts=snapshot["created_ts"]),
        "recipes": analyze_recipes(category, rows, target, snapshot_ts=snapshot["created_ts"]),
        "errors": errors,
        "source": source,
        "cached": False,
    }
    log_market_history(snapshot, history_path=HISTORY_PATH)
    SQLiteCacheManager.set(cache_key, result, 300)
    return result


async def get_exchange_offers(
    league: str,
    have: str,
    want: str,
    status: str = "online",
) -> dict[str, Any]:
    return normalize_exchange_result(await _post_exchange(league, [have], [want], status=status))


async def get_exchange_offers_many(
    league: str,
    have: str,
    want: list[str],
    status: str = "online",
) -> dict[str, Any]:
    wants = [item for item in want if item and item != have]
    if not wants:
        return {"query_id": None, "total": 0, "rows": []}
    return normalize_exchange_result(await _post_exchange(league, [have], wants, status=status), limit=250)


async def _post_search(
    league: str,
    query: dict[str, Any],
    sort: dict[str, str] | None = None,
) -> dict[str, Any]:
    body = {"query": query, "sort": sort or {"price": "asc"}}
    async with httpx.AsyncClient(headers=_headers({"Content-Type": "application/json"}), timeout=30) as client:
        response = await client.post(f"{TRADE2_RU_BASE}/search/poe2/{quote(league, safe='')}", json=body)
        if response.status_code == 429:
            wait = _retry_after_wait(response, "trade2 search")
            await asyncio.sleep(wait)
            response = await client.post(f"{TRADE2_RU_BASE}/search/poe2/{quote(league, safe='')}", json=body)
        response.raise_for_status()
    return response.json()


async def _fetch_trade_items(ids: list[str], query_id: str, limit: int = 60) -> list[dict[str, Any]]:
    selected_ids = [item_id for item_id in ids[:limit] if item_id]
    if not selected_ids:
        return []
    results: list[dict[str, Any]] = []
    async with httpx.AsyncClient(headers=_headers(), timeout=30) as client:
        chunks = _chunked(selected_ids, 10)
        for index, chunk_ids in enumerate(chunks):
            chunk = ",".join(chunk_ids)
            response = await client.get(f"{TRADE2_RU_BASE}/fetch/{chunk}", params={"query": query_id})
            if response.status_code == 429:
                wait = _retry_after_wait(response, "trade2 fetch")
                await asyncio.sleep(wait)
                response = await client.get(f"{TRADE2_RU_BASE}/fetch/{chunk}", params={"query": query_id})
            response.raise_for_status()
            results.extend(response.json().get("result") or [])
            if index < len(chunks) - 1:
                await asyncio.sleep(DEFAULT_RATE_LIMIT_DELAY)
    return results


def _priced_trade_filters(extra: dict[str, Any] | None = None) -> dict[str, Any]:
    filters = {
        "trade_filters": {
            "filters": {
                "sale_type": {"option": "priced"},
            }
        }
    }
    if extra:
        filters["trade_filters"]["filters"].update(extra)
    return filters


def _base_market_item_id(value: str) -> str:
    text = _clean_trade_text(value).lower()
    text = re.sub(r"[^0-9a-zа-яё]+", "-", text, flags=re.IGNORECASE)
    text = text.strip("-")
    return f"base:{text or 'unknown'}"


def _item_base_icon_key(category_id: str = "", label: str = "", base_type: str = "") -> str:
    value = f"{category_id} {label} {base_type}".lower()
    if "ring" in value or "кольц" in value:
        return "ring"
    if "amulet" in value or "амулет" in value:
        return "amulet"
    if "belt" in value or "пояс" in value:
        return "belt"
    if "boot" in value or "sandals" in value or "сапог" in value or "сандал" in value:
        return "boots"
    if "helmet" in value or "tiara" in value or "mask" in value or "шлем" in value or "тиар" in value or "маск" in value:
        return "helmet"
    if "robe" in value or "raiment" in value or "одея" in value or "роб" in value:
        return "robe"
    if "armour" in value or "body" in value or "jacket" in value or "брон" in value or "куртк" in value:
        return "armour"
    if "crossbow" in value or "арбалет" in value:
        return "crossbow"
    if "shortbow" in value or "bow" in value or "лук" in value:
        return "bow"
    if "quarterstaff" in value or "staff" in value or "посох" in value:
        return "staff"
    if "sceptre" in value or "скипетр" in value:
        return "sceptre"
    if "wand" in value or "жезл" in value:
        return "wand"
    if "focus" in value or "фокус" in value:
        return "focus"
    if "shield" in value or "buckler" in value or "щит" in value or "баклер" in value:
        return "shield"
    return "base"


def _item_base_icon_data_url(icon_key: str) -> str:
    color, label = ITEM_BASE_ICON_STYLES.get(icon_key, ITEM_BASE_ICON_STYLES["base"])
    svg = (
        "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'>"
        "<rect width='64' height='64' rx='10' fill='#0b1720'/>"
        f"<circle cx='32' cy='26' r='18' fill='{color}' fill-opacity='.22' stroke='{color}' stroke-width='3'/>"
        f"<text x='32' y='48' text-anchor='middle' font-family='Arial,sans-serif' font-size='13' font-weight='700' fill='{color}'>{label}</text>"
        "</svg>"
    )
    return f"data:image/svg+xml;utf8,{quote(svg, safe='')}"


def _item_base_category_ru(category_id: str, label: str) -> str:
    key_values = [category_id.lower(), label.lower()]
    for key in key_values:
        if key in ITEM_BASE_CATEGORY_RU:
            return ITEM_BASE_CATEGORY_RU[key]
    return ITEM_BASE_CATEGORY_RU.get(_item_base_icon_key(category_id, label), label or "Основы")


def _item_base_fallback_catalog() -> list[dict[str, Any]]:
    bases = []
    for item in ITEM_BASE_FALLBACKS:
        icon_key = str(item.get("icon_key") or "base")
        base_type = str(item["type"])
        bases.append(
            {
                "id": _base_market_item_id(base_type),
                "type": base_type,
                "type_ru": str(item.get("type_ru") or ITEM_BASE_RU.get(base_type) or base_type),
                "query_type": base_type,
                "category": str(item.get("category") or "fallback"),
                "category_label": "Fallback",
                "category_label_ru": str(item.get("category_ru") or "Резервный каталог"),
                "icon_key": icon_key,
                "image": _item_base_icon_data_url(icon_key),
            }
        )
    return bases


def _entry_text(entry: dict[str, Any]) -> str:
    return str(entry.get("text") or entry.get("name") or entry.get("type") or "").strip()


def _entry_query_text(entry: dict[str, Any]) -> str:
    return str(entry.get("type") or entry.get("text") or entry.get("name") or "").strip()


def _skip_item_base_category(category_id: str, label: str) -> bool:
    value = f"{category_id} {label}".lower()
    return bool(
        re.search(
            r"currency|fragment|gem|flask|map|waystone|tablet|rune|soul|"
            r"essence|omen|delirium|breach|expedition|ritual|ultimatum|"
            r"sanctum|relic|card|hideout|microtransaction",
            value,
        )
    )


def normalize_item_base_catalog(
    payload: dict[str, Any] | None,
    localized_payload: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    if not payload:
        return []
    localized_categories = {
        category.get("id"): category
        for category in (localized_payload or {}).get("result", [])
        if category.get("id")
    }
    bases: list[dict[str, Any]] = []
    seen: set[str] = set()
    for category in payload.get("result", []):
        category_id = str(category.get("id") or "").strip()
        category_label = str(category.get("label") or category.get("text") or category_id).strip()
        if not category_id or _skip_item_base_category(category_id, category_label):
            continue
        entries = category.get("entries") or []
        localized_entries = (localized_categories.get(category_id) or {}).get("entries") or []
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                continue
            text = _entry_text(entry)
            query_type = _entry_query_text(entry) or text
            if not text or not query_type:
                continue
            localized_entry = localized_entries[index] if index < len(localized_entries) and isinstance(localized_entries[index], dict) else {}
            text_ru = _entry_text(localized_entry) or ITEM_BASE_RU.get(text) or text
            query_type_ru = _entry_query_text(localized_entry) or ITEM_BASE_RU.get(query_type) or text_ru
            key = _lookup_text_key(query_type)
            if not key or key in seen:
                continue
            seen.add(key)
            icon_key = _item_base_icon_key(category_id, category_label, query_type)
            image = _image_url(entry.get("image") or entry.get("icon") or localized_entry.get("image") or localized_entry.get("icon"))
            bases.append(
                {
                    "id": _base_market_item_id(query_type),
                    "type": text,
                    "type_ru": text_ru,
                    "query_type": query_type_ru or query_type,
                    "category": category_id,
                    "category_label": category_label,
                    "category_label_ru": str((localized_categories.get(category_id) or {}).get("label") or _item_base_category_ru(category_id, category_label)),
                    "icon_key": icon_key,
                    "image": image or _item_base_icon_data_url(icon_key),
                }
            )
    bases.sort(key=lambda item: (_lookup_text_key(item.get("category_label")), _lookup_text_key(item.get("type"))))
    return bases


async def _fetch_item_base_catalog_payload(locale: str = "en") -> dict[str, Any]:
    base_url = TRADE2_RU_BASE if locale == "ru" else TRADE2_BASE
    async with httpx.AsyncClient(headers=_headers(), timeout=30) as client:
        response = await client.get(f"{base_url}/data/items")
        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After")
            suffix = f"; retry after {retry_after}s" if retry_after else ""
            raise RuntimeError(f"trade2 item catalog rate limited{suffix}")
        response.raise_for_status()
    return response.json()


async def get_item_base_catalog(q: str = "", limit: int = 500) -> dict[str, Any]:
    q = q.strip()
    limit = max(1, min(limit, 1000))
    cached = ITEM_BASES_CACHE.get("data")
    if cached and time.time() - float(ITEM_BASES_CACHE.get("created_ts") or 0) < ITEM_BASES_CACHE_TTL:
        bases = list(cached)
        errors = list(ITEM_BASES_CACHE.get("errors") or [])
    else:
        async with ITEM_BASES_LOCK:
            cached = ITEM_BASES_CACHE.get("data")
            if cached and time.time() - float(ITEM_BASES_CACHE.get("created_ts") or 0) < ITEM_BASES_CACHE_TTL:
                bases = list(cached)
                errors = list(ITEM_BASES_CACHE.get("errors") or [])
            else:
                errors = []
                en_payload = None
                ru_payload = None
                for locale in ("en", "ru"):
                    try:
                        payload = await _fetch_item_base_catalog_payload(locale)
                        if locale == "en":
                            en_payload = payload
                        else:
                            ru_payload = payload
                    except Exception as exc:
                        errors.append({"source": f"trade2/data/items:{locale}", "error": str(exc)})
                bases = normalize_item_base_catalog(en_payload, ru_payload)
                source = "trade2/data/items"
                if not bases:
                    bases = _item_base_fallback_catalog()
                    source = "fallback"
                ITEM_BASES_CACHE["created_ts"] = time.time()
                ITEM_BASES_CACHE["data"] = bases
                ITEM_BASES_CACHE["errors"] = errors
                ITEM_BASES_CACHE["source"] = source
    filtered = _filter_item_bases(bases, q)
    return {
        "schema_version": "poe2-item-base-catalog/v1",
        "source": ITEM_BASES_CACHE.get("source") or "trade2/data/items",
        "total": len(bases),
        "matched_total": len(filtered),
        "bases": filtered[:limit],
        "errors": errors,
    }


def _filter_item_bases(bases: list[dict[str, Any]], q: str) -> list[dict[str, Any]]:
    q = q.strip().lower()
    if not q:
        return list(bases)
    return [
        base
        for base in bases
        if q in " ".join(
            str(base.get(key) or "")
            for key in ("type", "type_ru", "query_type", "category", "category_label", "category_label_ru")
        ).lower()
    ]


def _item_base_market_query(base_type: str, status: str, min_ilvl: int | None = None) -> dict[str, Any]:
    type_filters: dict[str, Any] = {"rarity": {"option": "normal"}}
    if min_ilvl is not None and min_ilvl > 0:
        type_filters["ilvl"] = {"min": min_ilvl}
    filters = _priced_trade_filters()
    filters["type_filters"] = {"filters": type_filters}
    return {
        "status": {"option": status},
        "type": base_type,
        "stats": [{"type": "and", "filters": []}],
        "filters": filters,
    }


def _item_base_market_overview_query(status: str, min_ilvl: int | None = None) -> dict[str, Any]:
    type_filters: dict[str, Any] = {"rarity": {"option": "normal"}}
    if min_ilvl is not None and min_ilvl > 0:
        type_filters["ilvl"] = {"min": min_ilvl}
    filters = _priced_trade_filters()
    filters["type_filters"] = {"filters": type_filters}
    return {
        "status": {"option": status},
        "stats": [{"type": "and", "filters": []}],
        "filters": filters,
    }


def _is_clean_item_base_lot(lot: dict[str, Any]) -> bool:
    if _rarity_option(lot.get("rarity")) != "normal":
        return False
    if lot.get("corrupted"):
        return False
    if lot.get("explicit_mods") or lot.get("rune_mods") or lot.get("desecrated_mods"):
        return False
    for mod in lot.get("stat_mods") or []:
        if mod.get("type") in {"explicit", "fractured", "rune", "desecrated", "enchant"}:
            return False
    return True


def _base_market_stats(lots: list[dict[str, Any]], raw_count: int) -> dict[str, Any]:
    raw_values = sorted(lot["price_target"] for lot in lots if isinstance(lot.get("price_target"), float))
    values, outliers = _trim_price_outliers(raw_values)
    if not values:
        return {
            "count": 0,
            "raw_count": raw_count,
            "clean_count": len(lots),
            "outliers": outliers,
            "low": None,
            "best": None,
            "median": None,
            "market_median": None,
            "avg": None,
            "p25": None,
            "p75": None,
            "max": None,
            "offers": len(lots),
            "volume": len(lots),
            "confidence": "insufficient",
        }
    return {
        "count": len(values),
        "raw_count": raw_count,
        "clean_count": len(lots),
        "outliers": outliers,
        "low": values[0],
        "best": values[0],
        "median": values[0],
        "market_median": statistics.median(values),
        "avg": statistics.mean(values),
        "p25": _percentile(values, 0.25),
        "p75": _percentile(values, 0.75),
        "max": values[-1],
        "offers": len(lots),
        "volume": len(lots),
        "confidence": "medium" if len(values) >= 8 else "low" if len(values) >= 3 else "insufficient",
    }


def _base_market_sample_lots(clean_lots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": lot.get("id"),
            "seller": lot.get("seller"),
            "stash": lot.get("stash"),
            "indexed": lot.get("indexed"),
            "item_level": lot.get("item_level"),
            "price_amount": lot.get("price_amount"),
            "price_currency": lot.get("price_currency"),
            "price_target": lot.get("price_target"),
        }
        for lot in clean_lots[:6]
    ]


def _base_market_row_from_base(base: dict[str, Any], min_ilvl: int | None = None) -> dict[str, Any]:
    query_type = str(base.get("query_type") or base.get("type") or base.get("type_ru") or "").strip()
    return {
        "id": base.get("id") or _base_market_item_id(query_type),
        "text": base.get("type") or query_type,
        "text_ru": base.get("type_ru") or ITEM_BASE_RU.get(str(base.get("type") or "")) or query_type,
        "query_type": query_type,
        "category": base.get("category") or "",
        "category_label": base.get("category_label") or "",
        "category_label_ru": base.get("category_label_ru") or _item_base_category_ru(str(base.get("category") or ""), str(base.get("category_label") or "")),
        "icon_key": base.get("icon_key") or _item_base_icon_key(str(base.get("category") or ""), str(base.get("category_label") or ""), query_type),
        "image": base.get("image") or "",
        "basis": "normal-rarity clean base without explicit/rune/desecrated affixes",
        "basis_ru": "обычная чистая основа без явных, рунных и оскверненных свойств",
        "min_ilvl": min_ilvl,
    }


def _base_market_row_keys(row: dict[str, Any]) -> set[str]:
    return {
        key
        for key in (
            _lookup_text_key(row.get("text")),
            _lookup_text_key(row.get("text_ru")),
            _lookup_text_key(row.get("query_type")),
        )
        if key
    }


async def _fetch_item_base_market_overview(
    league: str,
    target: str,
    status: str,
    rates: dict[str, float],
    min_ilvl: int | None = None,
) -> dict[str, Any]:
    market_search = await _post_search(league, _item_base_market_overview_query(status, min_ilvl=min_ilvl))
    market_items = await _fetch_trade_items(
        market_search.get("result") or [],
        market_search.get("id") or "",
        limit=ITEM_BASE_MARKET_OVERVIEW_FETCH_LIMIT,
    )
    lots = [_normalize_item_listing(item) for item in market_items]
    grouped_raw: dict[str, list[dict[str, Any]]] = {}
    grouped_clean: dict[str, list[dict[str, Any]]] = {}
    group_names: dict[str, str] = {}
    group_icons: dict[str, str] = {}
    for lot in lots:
        if not lot:
            continue
        base_name = _clean_trade_text(lot.get("base_type") or lot.get("type_line") or lot.get("display_name"))
        key = _lookup_text_key(base_name)
        if not key:
            continue
        grouped_raw.setdefault(key, []).append(lot)
        group_names.setdefault(key, base_name)
        if lot.get("icon"):
            group_icons.setdefault(key, lot["icon"])
        if _is_clean_item_base_lot(lot):
            priced_lot = _apply_target_price(lot, rates, target)
            if isinstance(priced_lot.get("price_target"), float):
                grouped_clean.setdefault(key, []).append(priced_lot)

    rows_by_key = {}
    for key, clean_lots in grouped_clean.items():
        base_name = group_names.get(key) or key
        icon_key = _item_base_icon_key(base_type=base_name)
        row = {
            "id": _base_market_item_id(base_name),
            "text": base_name,
            "text_ru": ITEM_BASE_RU.get(base_name) or base_name,
            "query_type": base_name,
            "category": "market-overview",
            "category_label": "Market overview",
            "category_label_ru": "С рынка",
            "icon_key": icon_key,
            "image": group_icons.get(key) or _item_base_icon_data_url(icon_key),
            "basis": "normal-rarity clean base without explicit/rune/desecrated affixes",
            "basis_ru": "обычная чистая основа без явных, рунных и оскверненных свойств",
            "min_ilvl": min_ilvl,
            **_base_market_stats(clean_lots, raw_count=len(grouped_raw.get(key) or [])),
            "query_id": market_search.get("id"),
            "total": market_search.get("total") or len(lots),
            "sample_lots": _base_market_sample_lots(clean_lots),
        }
        rows_by_key[key] = row
    return {
        "query_id": market_search.get("id"),
        "total": market_search.get("total") or len(lots),
        "rows_by_key": rows_by_key,
    }


async def _fetch_item_base_market_row(
    league: str,
    base: dict[str, Any],
    target: str,
    status: str,
    rates: dict[str, float],
    min_ilvl: int | None = None,
) -> dict[str, Any]:
    row = _base_market_row_from_base(base, min_ilvl=min_ilvl)
    query_type = str(row.get("query_type") or "").strip()
    if not query_type:
        return {**row, **_base_market_stats([], 0), "sample_lots": [], "error": "base type is empty"}
    try:
        market_search = await _post_search(
            league,
            _item_base_market_query(query_type, status, min_ilvl=min_ilvl),
        )
        market_items = await _fetch_trade_items(
            market_search.get("result") or [],
            market_search.get("id") or "",
            limit=ITEM_BASE_MARKET_FETCH_LIMIT,
        )
    except Exception as exc:
        return {**row, **_base_market_stats([], 0), "sample_lots": [], "error": str(exc)}

    lots = [_normalize_item_listing(item) for item in market_items]
    clean_lots = [
        _apply_target_price(lot, rates, target)
        for lot in lots
        if lot and _is_clean_item_base_lot(lot)
    ]
    clean_lots = [lot for lot in clean_lots if isinstance(lot.get("price_target"), float)]
    stats = _base_market_stats(clean_lots, raw_count=len(lots))
    return {
        **row,
        **stats,
        "query_id": market_search.get("id"),
        "total": market_search.get("total") or len(lots),
        "sample_lots": _base_market_sample_lots(clean_lots),
    }


async def get_item_base_market(
    league: str,
    target: str = "exalted",
    status: str = "any",
    q: str = "",
    limit: int = 40,
    min_ilvl: int | None = None,
    force_refresh: bool = False,
) -> dict[str, Any]:
    q = q.strip()
    limit = max(1, min(limit, ITEM_BASE_MARKET_MAX_BASES))
    min_ilvl = min_ilvl if isinstance(min_ilvl, int) and min_ilvl > 0 else None
    cache_key = (league, target, status, q.lower(), limit, min_ilvl)
    canonical_cache_key = (league, target, status, "", ITEM_BASE_MARKET_MAX_BASES, min_ilvl)
    default_cache_key = (league, target, status, "", ITEM_BASE_MARKET_MAX_BASES, None)
    if not force_refresh:
        cached = ITEM_BASE_MARKET_CACHE.get(cache_key)
        if not cached and cache_key != canonical_cache_key:
            cached = ITEM_BASE_MARKET_CACHE.get(canonical_cache_key)
        if not cached and min_ilvl is not None:
            cached = ITEM_BASE_MARKET_CACHE.get(default_cache_key)
        if cached and time.time() - cached["created_ts"] < ITEM_BASE_MARKET_CACHE_TTL:
            payload = _cache_copy(cached["data"])
            rows = _filter_item_base_market_rows(payload.get("rows") or [], q)
            if min_ilvl is not None:
                rows = [row for row in rows if not row.get("min_ilvl") or int(row.get("min_ilvl") or 0) >= min_ilvl]
            payload["rows"] = rows[:limit]
            payload["matched_total"] = len(rows)
            payload["cached"] = True
            return payload
        latest = read_latest_rates(league=league, category=ITEM_BASE_MARKET_CATEGORY, target=target, status=status)
        if latest:
            rows = _filter_item_base_market_rows(latest.get("rows") or [], q)
            if min_ilvl is not None:
                rows = [row for row in rows if not row.get("min_ilvl") or int(row.get("min_ilvl") or 0) >= min_ilvl]
            rows = sorted(rows, key=lambda row: _to_float(row.get("low")) or _to_float(row.get("best")) or 0, reverse=True)
            return {
                **latest,
                "schema_version": "poe2-item-base-market/v1",
                "category": ITEM_BASE_MARKET_CATEGORY,
                "rows": rows[:limit],
                "matched_total": len(rows),
                "catalog_total": len(rows),
                "basis": "stored clean normal bases, price chart uses low market",
                "cached": True,
                "stored": True,
            }
        return {
            "schema_version": "poe2-item-base-market/v1",
            "created_ts": None,
            "league": league,
            "category": ITEM_BASE_MARKET_CATEGORY,
            "target": target,
            "status": status,
            "rows": [],
            "matched_total": 0,
            "catalog_total": 0,
            "priced_total": 0,
            "basis": "stored clean normal bases, price chart uses low market",
            "source": "stored",
            "errors": [],
            "cached": False,
            "stored": False,
        }

    catalog = await get_item_base_catalog(q="", limit=ITEM_BASE_MARKET_MAX_BASES)
    bases = catalog.get("bases") or []
    selected_bases = bases[:ITEM_BASE_MARKET_MAX_BASES]
    catalog_errors = list(catalog.get("errors") or [])
    try:
        currency_rates = await asyncio.wait_for(
            get_category_rates(league=league, category="Currency", target=target, status="any"),
            timeout=SELLER_CURRENCY_RATES_TIMEOUT,
        )
        rates = _currency_rates_by_id(currency_rates, target)
    except Exception:
        rates = {target: 1.0}

    errors = catalog_errors
    overview_rows: dict[str, dict[str, Any]] = {}
    overview_query_id = None
    try:
        overview = await _fetch_item_base_market_overview(league, target, status, rates, min_ilvl=min_ilvl)
        overview_rows = dict(overview.get("rows_by_key") or {})
        overview_query_id = overview.get("query_id")
    except Exception as exc:
        errors.append({"source": "trade2/search", "error": str(exc)})

    rows: list[dict[str, Any]] = []
    consumed_overview_keys: set[str] = set()
    overview_error = next((item.get("error") for item in errors if item.get("source") == "trade2/search"), None)
    for base in selected_bases:
        row = _base_market_row_from_base(base, min_ilvl=min_ilvl)
        overview_row = next((overview_rows[key] for key in _base_market_row_keys(row) if key in overview_rows), None)
        if overview_row:
            consumed_overview_keys.update(_base_market_row_keys(overview_row))
            row = {
                **row,
                **{key: value for key, value in overview_row.items() if value not in (None, "", [])},
                "id": row.get("id") or overview_row.get("id"),
                "text": row.get("text") or overview_row.get("text"),
                "text_ru": row.get("text_ru") or overview_row.get("text_ru"),
                "category": row.get("category") or overview_row.get("category"),
                "category_label": row.get("category_label") or overview_row.get("category_label"),
                "category_label_ru": row.get("category_label_ru") or overview_row.get("category_label_ru"),
                "icon_key": row.get("icon_key") or overview_row.get("icon_key"),
                "image": overview_row.get("image") or row.get("image"),
            }
        else:
            row = {**row, **_base_market_stats([], 0), "sample_lots": []}
            if overview_error:
                row["error"] = overview_error
        rows.append(row)

    for key, overview_row in overview_rows.items():
        if key in consumed_overview_keys:
            continue
        rows.append(overview_row)

    priced_rows = [row for row in rows if _to_float(row.get("low")) is not None or _to_float(row.get("best")) is not None]
    unpriced_rows = [row for row in rows if row not in priced_rows]
    priced_rows.sort(key=lambda row: _to_float(row.get("low")) or _to_float(row.get("best")) or 0, reverse=True)
    unpriced_rows.sort(key=lambda row: _lookup_text_key(row.get("text_ru") or row.get("text")))
    rows = priced_rows + unpriced_rows
    created_ts = time.time()
    snapshot_rows = priced_rows
    snapshot = {
        "created_ts": created_ts,
        "league": league,
        "category": ITEM_BASE_MARKET_CATEGORY,
        "target": target,
        "status": status,
        "source": "trade2/search+fetch:overview",
        "query_ids": [item for item in [overview_query_id] if item],
        "errors": errors,
        "rows": snapshot_rows,
    }
    if snapshot_rows:
        log_market_history(snapshot, history_path=HISTORY_PATH)
    full_result = {
        "schema_version": "poe2-item-base-market/v1",
        "created_ts": created_ts,
        "league": league,
        "category": ITEM_BASE_MARKET_CATEGORY,
        "target": target,
        "status": status,
        "rows": rows,
        "matched_total": len(rows),
        "catalog_total": catalog.get("total") or len(rows),
        "priced_total": len(snapshot_rows),
        "basis": "normal rarity, clean item bases without explicit/rune/desecrated affixes; chart stores low market",
        "source": "trade2/search+fetch:overview",
        "catalog_source": catalog.get("source"),
        "errors": errors,
        "cached": False,
    }
    cache_created_ts = time.time()
    ITEM_BASE_MARKET_CACHE[canonical_cache_key] = {"created_ts": cache_created_ts, "data": full_result}
    filtered_rows = _filter_item_base_market_rows(rows, q)
    matched_total = len(filtered_rows)
    result = {
        **full_result,
        "rows": filtered_rows[:limit],
        "matched_total": matched_total,
    }
    ITEM_BASE_MARKET_CACHE[cache_key] = {"created_ts": cache_created_ts, "data": result}
    return _cache_copy(result)


def _filter_item_base_market_rows(rows: list[dict[str, Any]], q: str) -> list[dict[str, Any]]:
    q = q.strip().lower()
    if not q:
        return list(rows)
    return [
        row
        for row in rows
        if q in " ".join(
            str(row.get(key) or "")
            for key in ("text", "text_ru", "query_type", "category", "category_label", "category_label_ru")
        ).lower()
    ]


def _seller_lots_query(seller: str, text: str, status: str, text_field: str = "type") -> dict[str, Any]:
    query: dict[str, Any] = {
        "status": {"option": status},
        "stats": [{"type": "and", "filters": []}],
        "filters": _priced_trade_filters({"account": {"input": seller}}),
    }
    if text:
        if text_field not in {"type", "term"}:
            raise ValueError("text_field must be 'type' or 'term'")
        query[text_field] = text
    return query


def _rarity_option(rarity: str | None) -> str | None:
    if not rarity:
        return None
    value = rarity.lower()
    return value if value in {"normal", "magic", "rare", "unique"} else None


def _stat_filter(
    stat_id: str,
    weight: float | None = None,
    value_range: dict[str, float | None] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"id": stat_id, "disabled": False}
    value: dict[str, Any] = {}
    if weight is not None:
        value["weight"] = weight
    if value_range:
        if value_range.get("min") is not None:
            value["min"] = value_range["min"]
        if value_range.get("max") is not None:
            value["max"] = value_range["max"]
    if value:
        payload["value"] = value
    return payload


def _stat_mod_priority(mod: dict[str, Any]) -> int:
    kind = mod.get("type") or ""
    text = _clean_trade_text(mod.get("text") or mod.get("name") or "")
    score = {
        "pseudo": 95,
        "explicit": 70,
        "fractured": 75,
        "implicit": 45,
        "rune": 40,
        "desecrated": 40,
    }.get(kind, 20)
    if IMPORTANT_STAT_RE.search(text):
        score += 30
    tier = str(mod.get("tier") or "")
    tier_match = re.search(r"(\d+)", tier)
    if tier_match:
        tier_num = int(tier_match.group(1))
        if tier_num <= 2:
            score += 15
        elif tier_num >= 7:
            score -= 10
    return score


def _normalize_profile_stat_ids(values: Any) -> tuple[str, ...]:
    if values in (None, ""):
        return ()
    if isinstance(values, str):
        raw_values = re.split(r"[\s,]+", values)
    elif isinstance(values, (list, tuple, set)):
        raw_values = []
        for value in values:
            raw_values.extend(re.split(r"[\s,]+", str(value or "")))
    else:
        raw_values = [str(values)]

    result: list[str] = []
    seen: set[str] = set()
    for value in raw_values:
        stat_id = str(value or "").strip()
        if not stat_id or stat_id in seen or len(stat_id) > 140:
            continue
        if not re.match(r"^[A-Za-z0-9_.:-]+$", stat_id):
            continue
        seen.add(stat_id)
        result.append(stat_id)
        if len(result) >= SELLER_MARKET_PROFILE_MAX_STATS:
            break
    return tuple(result)


def _normalize_stat_value_ranges(values: Any) -> dict[str, dict[str, float | None]]:
    if values in (None, ""):
        return {}
    if isinstance(values, str):
        try:
            values = json.loads(values)
        except json.JSONDecodeError:
            return {}
    if not isinstance(values, dict):
        return {}

    result: dict[str, dict[str, float | None]] = {}
    for raw_stat_id, raw_range in values.items():
        stat_ids = _normalize_profile_stat_ids([raw_stat_id])
        if not stat_ids or not isinstance(raw_range, dict):
            continue
        min_value = _to_float(raw_range.get("min"))
        max_value = _to_float(raw_range.get("max"))
        if min_value is None and max_value is None:
            continue
        if min_value is not None and max_value is not None and min_value > max_value:
            min_value, max_value = max_value, min_value
        result[stat_ids[0]] = {"min": min_value, "max": max_value}
    return result


def _manual_stat_profile(
    preferred_stat_ids: Any = None,
    ignored_stat_ids: Any = None,
    base_mode: Any = None,
    tier_stat_ids: Any = None,
    stat_value_ranges: Any = None,
    base_only: Any = None,
) -> dict[str, Any]:
    tier_stats = _normalize_profile_stat_ids(tier_stat_ids)
    ranges = _normalize_stat_value_ranges(stat_value_ranges)
    preferred = _normalize_profile_stat_ids(preferred_stat_ids)
    preferred_set = set(preferred)
    for stat_id in [*tier_stats, *ranges.keys()]:
        if stat_id not in preferred_set:
            preferred_set.add(stat_id)
            preferred = (*preferred, stat_id)
    ignored = tuple(
        stat_id
        for stat_id in _normalize_profile_stat_ids(ignored_stat_ids)
        if stat_id not in preferred_set
    )
    normalized_base_mode = str(base_mode or "default").strip().lower()
    if normalized_base_mode not in {"default", "required", "ignored"}:
        normalized_base_mode = "default"
    normalized_base_only = str(base_only or "").strip().lower() in {"1", "true", "yes", "on"}
    return {
        "preferred_stat_ids": preferred,
        "ignored_stat_ids": ignored,
        "base_mode": normalized_base_mode,
        "tier_stat_ids": tier_stats,
        "stat_value_ranges": ranges,
        "base_only": normalized_base_only,
    }


def _profile_has_rules(profile: dict[str, Any] | None) -> bool:
    if not profile:
        return False
    return bool(
        profile.get("preferred_stat_ids")
        or profile.get("ignored_stat_ids")
        or profile.get("base_mode") in {"required", "ignored"}
        or profile.get("tier_stat_ids")
        or profile.get("stat_value_ranges")
        or profile.get("base_only")
    )


def _profile_requires_base(profile: dict[str, Any] | None) -> bool:
    if (profile or {}).get("base_only"):
        return True
    return (profile or {}).get("base_mode") != "ignored"


def _item_stat_mods(item: dict[str, Any]) -> list[dict[str, Any]]:
    extended = item.get("extended") or {}
    extended_mods = extended.get("mods") or {}
    extended_hashes = extended.get("hashes") or {}
    lines_by_kind = {
        "implicit": item.get("implicitMods") or [],
        "explicit": item.get("explicitMods") or [],
        "rune": item.get("runeMods") or [],
        "desecrated": item.get("desecratedMods") or [],
    }

    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for kind, raw_mods in extended_mods.items():
        if not isinstance(raw_mods, list):
            continue
        visible_lines = lines_by_kind.get(kind) or []
        for index, raw_mod in enumerate(raw_mods):
            if not isinstance(raw_mod, dict):
                continue
            line = visible_lines[index] if index < len(visible_lines) else ""
            for magnitude in raw_mod.get("magnitudes") or []:
                stat_id = magnitude.get("hash") if isinstance(magnitude, dict) else None
                if not stat_id or (kind, stat_id) in seen:
                    continue
                seen.add((kind, stat_id))
                result.append(
                    {
                        "id": stat_id,
                        "type": kind,
                        "text": line,
                        "name": raw_mod.get("name") or "",
                        "tier": raw_mod.get("tier"),
                        "level": raw_mod.get("level"),
                        "min": _to_float(magnitude.get("min")),
                        "max": _to_float(magnitude.get("max")),
                    }
                )

    for kind, hash_entries in extended_hashes.items():
        if not isinstance(hash_entries, list):
            continue
        for entry in hash_entries:
            stat_id = entry[0] if isinstance(entry, list) and entry else None
            if not stat_id or (kind, stat_id) in seen:
                continue
            seen.add((kind, stat_id))
            result.append(
                {
                    "id": stat_id,
                    "type": kind,
                    "text": "",
                    "name": "",
                    "tier": None,
                    "level": None,
                }
            )
    return result


def _lot_key_stat_mods(
    lot: dict[str, Any],
    max_count: int = SELLER_MARKET_MAX_STAT_FILTERS,
    profile: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    seen: set[str] = set()
    candidates: list[dict[str, Any]] = []
    if (profile or {}).get("base_only"):
        return []
    preferred = set((profile or {}).get("preferred_stat_ids") or ())
    ignored = set((profile or {}).get("ignored_stat_ids") or ())
    for mod in lot.get("stat_mods") or []:
        stat_id = mod.get("id")
        kind = mod.get("type")
        if not stat_id or stat_id in seen or kind not in COMPARABLE_STAT_TYPES:
            continue
        if preferred and stat_id not in preferred:
            continue
        if not preferred and stat_id in ignored:
            continue
        seen.add(stat_id)
        candidates.append(mod)

    if preferred:
        preferred_order = {stat_id: index for index, stat_id in enumerate((profile or {}).get("preferred_stat_ids") or ())}
        candidates.sort(key=lambda mod: (preferred_order.get(mod.get("id"), 10_000), -_stat_mod_priority(mod)))
    else:
        candidates.sort(key=_stat_mod_priority, reverse=True)
    return candidates[:max_count]


def _similar_lot_stat_group(
    lot: dict[str, Any],
    looseness: int,
    profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    mods = _lot_key_stat_mods(lot, profile=profile)
    if not mods:
        return {"type": "and", "filters": []}

    ranges = (profile or {}).get("stat_value_ranges") or {}
    filters = [_stat_filter(mod["id"], value_range=ranges.get(mod["id"])) for mod in mods]
    if looseness == 0 or len(filters) == 1:
        return {"type": "and", "filters": filters}
    if looseness == 1:
        return {"type": "count", "value": {"min": max(1, len(filters) - 1)}, "filters": filters}

    return {"type": "count", "value": {"min": max(1, min(2, len(filters)))}, "filters": filters}


def _similar_lots_query(
    lot: dict[str, Any],
    status: str,
    looseness: int = 0,
    profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    type_filters: dict[str, Any] = {}
    rarity = _rarity_option(lot.get("rarity"))
    if rarity and looseness < 2:
        type_filters["rarity"] = {"option": rarity}

    item_level = lot.get("item_level")
    if rarity not in {"unique"} and isinstance(item_level, int) and item_level > 0:
        tolerance = 5 if looseness == 0 else 10 if looseness == 1 else 15
        type_filters["ilvl"] = {"min": max(1, item_level - tolerance), "max": item_level + tolerance}

    filters = _priced_trade_filters()
    if type_filters:
        filters["type_filters"] = {"filters": type_filters}

    query: dict[str, Any] = {
        "status": {"option": status},
        "stats": [_similar_lot_stat_group(lot, looseness, profile)],
        "filters": filters,
    }
    if rarity == "unique" and lot.get("name"):
        query["term"] = lot["name"]
    elif _profile_requires_base(profile):
        query["type"] = lot.get("base_type") or lot.get("type_line") or lot.get("display_name")
    return query


def _to_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _to_int(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _item_display_name(item: dict[str, Any]) -> str:
    name = (item.get("name") or "").strip()
    type_line = (item.get("typeLine") or "").strip()
    if name and type_line:
        return f"{name} {type_line}"
    return name or type_line or item.get("baseType") or "-"


def _listing_text_blob(lot: dict[str, Any]) -> str:
    return " ".join(
        str(part)
        for part in [
            lot.get("display_name"),
            lot.get("name"),
            lot.get("type_line"),
            lot.get("base_type"),
            lot.get("rarity"),
            " ".join(lot.get("explicit_mods") or []),
        ]
        if part
    ).lower()


def _clean_trade_text(value: Any) -> str:
    text = str(value or "")
    return re.sub(r"\[[^\]|]*\|([^\]]+)\]", r"\1", text).strip()


def _normalize_affix_text(value: Any) -> str:
    text = _clean_trade_text(value).lower()
    text = re.sub(r"[+-]?\d+(?:[.,]\d+)?", "#", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" .;:,")


def _lot_affix_keys(
    lot: dict[str, Any],
    profile: dict[str, Any] | None = None,
) -> tuple[str, ...]:
    if (profile or {}).get("base_only"):
        return ()
    preferred = set((profile or {}).get("preferred_stat_ids") or ())
    ignored = set((profile or {}).get("ignored_stat_ids") or ())
    stat_ids = {
        f"stat:{mod.get('id')}"
        for mod in lot.get("stat_mods") or []
        if mod.get("id") and mod.get("type") in COMPARABLE_STAT_TYPES
        and (not preferred or mod.get("id") in preferred)
        and (preferred or mod.get("id") not in ignored)
    }
    if stat_ids:
        return tuple(sorted(stat_ids))
    if _profile_has_rules(profile):
        return ()
    return _lot_text_affix_keys(lot)


def _lot_text_affix_keys(lot: dict[str, Any]) -> tuple[str, ...]:
    keys = {
        key
        for mod in (lot.get("explicit_mods") or [])
        for key in [_normalize_affix_text(mod)]
        if key
    }
    return tuple(sorted(keys))


def _lot_base_key(lot: dict[str, Any]) -> str:
    return _clean_trade_text(lot.get("base_type") or lot.get("type_line") or lot.get("display_name")).lower()


def _item_level_matches(source: Any, candidate: Any, tolerance: int) -> bool:
    if not isinstance(source, int) or source <= 0:
        return True
    if not isinstance(candidate, int) or candidate <= 0:
        return True
    return abs(source - candidate) <= tolerance


def _official_stat_ids_from_keys(keys: set[str]) -> set[str]:
    return {key[5:] for key in keys if key.startswith("stat:")}


def _similarity_threshold(looseness: int, profile: dict[str, Any] | None = None) -> float:
    if (profile or {}).get("base_only"):
        return 45.0
    if looseness == 0:
        return 70.0
    if looseness == 1:
        return 55.0
    return 40.0


def _lot_similarity_details(
    target: dict[str, Any],
    candidate: dict[str, Any],
    looseness: int,
    profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    target_affixes = set(_lot_affix_keys(target, profile))
    target_official = _official_stat_ids_from_keys(target_affixes)
    candidate_affixes = set(_lot_affix_keys(candidate, profile) if target_official else _lot_text_affix_keys(candidate))
    candidate_official = _official_stat_ids_from_keys(candidate_affixes)
    matched_stat_ids = sorted(target_official & candidate_official)
    matched_affixes = sorted(target_affixes & candidate_affixes)
    target_base = _lot_base_key(target)
    candidate_base = _lot_base_key(candidate)
    base_required = _profile_requires_base(profile)
    base_match = bool(target_base and candidate_base and target_base == candidate_base)
    target_level = target.get("item_level")
    candidate_level = candidate.get("item_level")
    level_tolerance = 5 if looseness == 0 else 10 if looseness == 1 else 15
    level_match = _item_level_matches(target_level, candidate_level, level_tolerance)

    score = 0.0
    if base_required and base_match:
        score += 45.0 if (profile or {}).get("base_only") else 25.0
    elif not base_required:
        score += 10.0
    if _rarity_option(target.get("rarity")) and _rarity_option(target.get("rarity")) == _rarity_option(candidate.get("rarity")):
        score += 15.0
    if level_match:
        score += 15.0
    if target_official:
        official_ratio = len(matched_stat_ids) / len(target_official)
        score += 45.0 * official_ratio
        if len(target_official) >= 2 and len(matched_stat_ids) >= 2:
            score += 10.0
        preferred = set((profile or {}).get("preferred_stat_ids") or ())
        if preferred and preferred <= candidate_official:
            score += 10.0
    elif target_affixes:
        score += 35.0 * (len(matched_affixes) / len(target_affixes))

    return {
        "score": round(min(100.0, score), 2),
        "base_match": base_match,
        "level_match": level_match,
        "level_tolerance": level_tolerance,
        "matched_affixes": matched_affixes,
        "matched_stat_ids": matched_stat_ids,
        "missing_stat_ids": sorted(target_official - candidate_official),
        "official_stat_overlap": len(matched_stat_ids),
        "official_stat_total": len(target_official),
    }


def _comparable_lot_profile(
    lot: dict[str, Any],
    looseness: int,
    profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    affixes = _lot_affix_keys(lot, profile)
    if (profile or {}).get("base_only"):
        mode = "base-only"
        required_affixes = 0
        level_tolerance = 5 if looseness == 0 else 10 if looseness == 1 else 15
    elif looseness == 0:
        mode = "type-level-stat-ids"
        required_affixes = len(affixes)
        level_tolerance = 5
    elif looseness == 1:
        mode = "type-level-stat-ids-minus-one"
        required_affixes = max(0, len(affixes) - 1)
        level_tolerance = 10
    else:
        mode = "type-level-loose-stats"
        required_affixes = max(0, min(len(affixes), 2))
        level_tolerance = 15
    key_stats = _lot_key_stat_mods(lot, profile=profile)
    result = {
        "mode": mode,
        "base_mode": (profile or {}).get("base_mode") or "default",
        "base_type": lot.get("base_type") or lot.get("type_line") or lot.get("display_name"),
        "rarity": lot.get("rarity") or "",
        "item_level": lot.get("item_level"),
        "level_tolerance": level_tolerance,
        "affixes": list(affixes),
        "required_affixes": required_affixes,
        "stat_ids": [mod["id"] for mod in key_stats],
        "official_stat_count": len([mod for mod in key_stats if mod.get("id")]),
        "similarity_threshold": _similarity_threshold(looseness, profile),
    }
    if _profile_has_rules(profile):
        result["manual_profile"] = True
        result["preferred_stat_ids"] = list((profile or {}).get("preferred_stat_ids") or ())
        result["ignored_stat_ids"] = list((profile or {}).get("ignored_stat_ids") or ())
        result["tier_stat_ids"] = list((profile or {}).get("tier_stat_ids") or ())
        result["stat_value_ranges"] = dict((profile or {}).get("stat_value_ranges") or {})
        result["base_only"] = bool((profile or {}).get("base_only"))
    return result


def _stat_mod_by_id(lot: dict[str, Any], stat_id: str) -> dict[str, Any] | None:
    return next((mod for mod in lot.get("stat_mods") or [] if mod.get("id") == stat_id), None)


def _stat_mod_value(mod: dict[str, Any] | None) -> float | None:
    if not mod:
        return None
    max_value = _to_float(mod.get("max"))
    min_value = _to_float(mod.get("min"))
    return max_value if max_value is not None else min_value


def _stat_value_in_range(mod: dict[str, Any] | None, value_range: dict[str, float | None]) -> bool:
    value = _stat_mod_value(mod)
    if value is None:
        return False
    min_value = value_range.get("min")
    max_value = value_range.get("max")
    if min_value is not None and value < min_value:
        return False
    if max_value is not None and value > max_value:
        return False
    return True


def _stat_same_tier(target_mod: dict[str, Any] | None, candidate_mod: dict[str, Any] | None) -> bool:
    if not target_mod:
        return True
    target_tier = str(target_mod.get("tier") or "").strip().lower()
    target_level = _to_int(target_mod.get("level"))
    if not target_tier and target_level is None:
        return True
    if not candidate_mod:
        return False
    candidate_tier = str(candidate_mod.get("tier") or "").strip().lower()
    candidate_level = _to_int(candidate_mod.get("level"))
    if target_tier:
        return bool(candidate_tier) and candidate_tier == target_tier
    return candidate_level is not None and candidate_level == target_level


def _lot_matches_profile_constraints(
    target: dict[str, Any],
    candidate: dict[str, Any],
    profile: dict[str, Any] | None,
) -> bool:
    if not profile:
        return True
    for stat_id in profile.get("tier_stat_ids") or ():
        if not _stat_same_tier(_stat_mod_by_id(target, stat_id), _stat_mod_by_id(candidate, stat_id)):
            return False
    for stat_id, value_range in (profile.get("stat_value_ranges") or {}).items():
        if not _stat_value_in_range(_stat_mod_by_id(candidate, stat_id), value_range):
            return False
    return True


def _filter_comparable_lots(
    target: dict[str, Any],
    lots: list[dict[str, Any]],
    looseness: int,
    profile: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    target_rarity = _rarity_option(target.get("rarity"))
    target_base = _lot_base_key(target)
    target_name = _clean_trade_text(target.get("name")).lower()
    target_affixes = set(_lot_affix_keys(target, profile))
    target_uses_stat_ids = any(key.startswith("stat:") for key in target_affixes)
    comparison_profile = _comparable_lot_profile(target, looseness, profile)
    required_affixes = comparison_profile["required_affixes"]
    comparable: list[dict[str, Any]] = []

    for lot in lots:
        candidate_rarity = _rarity_option(lot.get("rarity"))
        if target_rarity and candidate_rarity != target_rarity:
            continue
        if target_rarity == "unique":
            candidate_name = _clean_trade_text(lot.get("name")).lower()
            if target_name and candidate_name != target_name:
                continue
        elif _profile_requires_base(profile) and target_base and _lot_base_key(lot) != target_base:
            continue
        if not _item_level_matches(target.get("item_level"), lot.get("item_level"), comparison_profile["level_tolerance"]):
            continue
        if required_affixes:
            candidate_affixes = set(_lot_affix_keys(lot, profile) if target_uses_stat_ids else _lot_text_affix_keys(lot))
            overlap = len(target_affixes & candidate_affixes)
            if overlap < required_affixes:
                continue
        if not _lot_matches_profile_constraints(target, lot, profile):
            continue
        similarity = _lot_similarity_details(target, lot, looseness, profile)
        if similarity["score"] < comparison_profile["similarity_threshold"]:
            continue
        comparable.append({**lot, "similarity": similarity})
    return comparable


def _parsed_item_lot(parsed: dict[str, Any]) -> dict[str, Any]:
    type_line = parsed.get("type_line") or parsed.get("display_name") or parsed.get("name") or ""
    return {
        "id": "pasted-item",
        "seller": "",
        "online": False,
        "indexed": "",
        "stash": "",
        "price_amount": None,
        "price_currency": "",
        "stack_size": 1,
        "display_name": parsed.get("display_name") or type_line,
        "name": parsed.get("name") or "",
        "type_line": type_line,
        "base_type": type_line,
        "rarity": parsed.get("rarity") or "",
        "item_level": parsed.get("item_level"),
        "identified": None,
        "corrupted": False,
        "icon": "",
        "implicit_mods": [],
        "explicit_mods": parsed.get("mods") or [],
        "rune_mods": [],
        "desecrated_mods": [],
        "stat_mods": [],
    }


def _normalize_item_listing(entry: dict[str, Any]) -> dict[str, Any] | None:
    listing = entry.get("listing") or {}
    item = entry.get("item") or {}
    price = listing.get("price") or {}
    stash = listing.get("stash") or {}
    price_type = price.get("type") or ""
    if price_type and price_type not in INSTANT_BUYOUT_PRICE_TYPES:
        return None
    amount = _to_float(price.get("amount"))
    currency = price.get("currency")
    if not stash or amount is None or not currency:
        return None
    account = listing.get("account") or {}
    return {
        "id": entry.get("id") or item.get("id") or "",
        "seller": account.get("name") or "",
        "online": bool(account.get("online")),
        "indexed": listing.get("indexed") or "",
        "stash": stash.get("name") or "",
        "stash_x": stash.get("x"),
        "stash_y": stash.get("y"),
        "price_amount": amount,
        "price_currency": currency,
        "price_type": price_type,
        "stack_size": _to_int(item.get("stackSize")) or 1,
        "display_name": _item_display_name(item),
        "name": item.get("name") or "",
        "type_line": item.get("typeLine") or "",
        "base_type": item.get("baseType") or item.get("typeLine") or "",
        "rarity": item.get("rarity") or "",
        "item_level": item.get("ilvl"),
        "identified": item.get("identified"),
        "corrupted": bool(item.get("corrupted")),
        "icon": item.get("icon") or "",
        "note": item.get("note") or "",
        "implicit_mods": item.get("implicitMods") or [],
        "explicit_mods": item.get("explicitMods") or [],
        "rune_mods": item.get("runeMods") or [],
        "desecrated_mods": item.get("desecratedMods") or [],
        "stat_mods": _item_stat_mods(item),
    }


def _currency_rates_by_id(currency_rates: dict[str, Any], target: str) -> dict[str, float]:
    rates = {target: 1.0}
    for row in currency_rates.get("rows") or []:
        value = _to_float(row.get("median") if row.get("median") is not None else row.get("best"))
        if row.get("id") and value:
            rates[row["id"]] = value
    return rates


def _apply_target_price(lot: dict[str, Any], rates: dict[str, float], target: str) -> dict[str, Any]:
    currency = lot.get("price_currency")
    amount = _to_float(lot.get("price_amount"))
    factor = rates.get(currency)
    lot["target"] = target
    lot["price_target"] = amount * factor if amount and factor else None
    stack_size = _to_int(lot.get("stack_size")) or 1
    lot["price_unit_target"] = lot["price_target"] / stack_size if lot.get("price_target") and stack_size > 1 else lot.get("price_target")
    return lot


def _percentile(sorted_values: list[float], position: float) -> float | None:
    if not sorted_values:
        return None
    index = min(len(sorted_values) - 1, max(0, round((len(sorted_values) - 1) * position)))
    return sorted_values[index]


def _trim_price_outliers(values: list[float]) -> tuple[list[float], int]:
    if len(values) < 5:
        return values, 0
    q1 = _percentile(values, 0.25)
    q3 = _percentile(values, 0.75)
    if q1 is None or q3 is None:
        return values, 0
    iqr = q3 - q1
    if iqr <= 0:
        return values, 0
    low = q1 - 1.5 * iqr
    high = q3 + 1.5 * iqr
    trimmed = [value for value in values if low <= value <= high]
    return trimmed or values, len(values) - len(trimmed)


def _market_confidence(
    count: int,
    comparison: dict[str, Any] | None = None,
    stats: dict[str, Any] | None = None,
) -> str:
    mode = (comparison or {}).get("mode") or ""
    official_stat_count = int((comparison or {}).get("official_stat_count") or 0)
    avg_similarity = _to_float((stats or {}).get("avg_similarity")) or 0
    if mode == "base-only":
        if count >= 12:
            return "medium"
        if count >= SELLER_MARKET_MIN_COMPARABLES:
            return "low"
        return "insufficient"
    if count >= 8 and mode == "type-level-stat-ids" and official_stat_count >= 2 and avg_similarity >= 75:
        return "high"
    if count >= 5 and mode in {"type-level-stat-ids", "type-level-stat-ids-minus-one"} and avg_similarity >= 60:
        return "medium"
    if count >= SELLER_MARKET_MIN_COMPARABLES:
        return "low"
    return "insufficient"


def _lookup_text_key(value: Any) -> str:
    text = _clean_trade_text(value).lower()
    text = re.sub(r"[-_]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _static_entry_lookup(
    categories: dict[str, list[dict[str, str | None]]],
) -> dict[str, tuple[str, dict[str, str | None]]]:
    lookup: dict[str, tuple[str, dict[str, str | None]]] = {}
    for category, entries in categories.items():
        if category not in POE_NINJA_CATEGORY_TYPES:
            continue
        for entry in entries:
            for value in (entry.get("id"), entry.get("text"), entry.get("text_ru")):
                key = _lookup_text_key(value)
                if key:
                    lookup[key] = (category, entry)
    return lookup


def _lot_static_match(
    lot: dict[str, Any],
    lookup: dict[str, tuple[str, dict[str, str | None]]],
) -> tuple[str, dict[str, str | None]] | None:
    for value in (lot.get("base_type"), lot.get("type_line"), lot.get("display_name"), lot.get("name")):
        key = _lookup_text_key(value)
        if key and key in lookup:
            return lookup[key]
    return None


async def _stackable_market_payload(
    league: str,
    lot: dict[str, Any],
    target: str,
    status: str,
    static_lookup: dict[str, tuple[str, dict[str, str | None]]],
    category_rate_cache: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    match = _lot_static_match(lot, static_lookup)
    if not match:
        return None
    category, entry = match
    if category not in category_rate_cache:
        category_rate_cache[category] = await get_category_rates(
            league=league,
            category=category,
            target=target,
            status=status,
        )
    category_rates = category_rate_cache[category]
    row = next((item for item in category_rates.get("rows") or [] if item.get("id") == entry.get("id")), None)
    if not row:
        return None
    value = _to_float(row.get("median") if row.get("median") is not None else row.get("best"))
    if value is None:
        return None
    volume = _to_float(row.get("volume")) or 0.0
    stats = {
        "count": 0,
        "raw_count": 0,
        "outliers": 0,
        "current": value,
        "min": value,
        "median": value,
        "p25": value,
        "p75": value,
        "volume": volume,
        "change": row.get("change"),
        "confidence": "medium" if volume >= LOW_VOLUME_THRESHOLD else "low",
        "source": "poe.ninja",
        "category": category,
        "item_id": entry.get("id"),
        "unit_priced": True,
    }
    return {
        "query_id": None,
        "total": 0,
        "candidate_count": 0,
        "filtered_count": 0,
        "lots": [],
        "stats": stats,
        "looseness": 0,
        "comparison": {"mode": "poe-ninja-aggregate", "category": category, "item_id": entry.get("id")},
        "cached": bool(category_rates.get("cached")),
    }


def _empty_market_payload(
    lot: dict[str, Any],
    error: str | None = None,
    looseness: int = 2,
) -> dict[str, Any]:
    stats: dict[str, Any] = {
        "count": 0,
        "raw_count": 0,
        "outliers": 0,
        "current": None,
        "min": None,
        "median": None,
        "p25": None,
        "p75": None,
        "confidence": "insufficient",
    }
    if error:
        stats["error"] = error
    return {
        "query_id": None,
        "total": 0,
        "candidate_count": 0,
        "filtered_count": 0,
        "lots": [],
        "stats": stats,
        "looseness": looseness,
        "comparison": _comparable_lot_profile(lot, looseness),
        "cached": False,
    }


def _market_price_stats(lots: list[dict[str, Any]], seller: str) -> dict[str, Any]:
    seller_key = seller.lower()
    priced_lots = [
        lot
        for lot in lots
        if isinstance(lot.get("price_target"), float) and lot.get("seller", "").lower() != seller_key
    ]
    raw_values = sorted(lot["price_target"] for lot in priced_lots)
    similarity_scores = [
        similarity["score"]
        for lot in priced_lots
        for similarity in [lot.get("similarity")]
        if isinstance(similarity, dict) and isinstance(similarity.get("score"), (int, float))
    ]
    values, outliers = _trim_price_outliers(raw_values)
    if not values:
        return {
            "count": 0,
            "raw_count": len(raw_values),
            "outliers": outliers,
            "current": None,
            "min": None,
            "median": None,
            "p25": None,
            "p75": None,
            "avg_similarity": None,
            "min_similarity": None,
        }
    median = statistics.median(values)
    return {
        "count": len(values),
        "raw_count": len(raw_values),
        "outliers": outliers,
        "current": median,
        "min": values[0],
        "median": median,
        "p25": _percentile(values, 0.25),
        "p75": _percentile(values, 0.75),
        "avg_similarity": statistics.mean(similarity_scores) if similarity_scores else None,
        "min_similarity": min(similarity_scores) if similarity_scores else None,
    }


def _seller_base_summaries(lots: list[dict[str, Any]], target: str, top: int = 12) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, int | None], dict[str, Any]] = {}
    for lot in lots:
        base = _clean_trade_text(lot.get("base_type") or lot.get("type_line") or lot.get("display_name"))
        price = lot.get("price_target")
        if not base or not isinstance(price, float):
            continue
        key = (base.lower(), _rarity_option(lot.get("rarity")) or "", lot.get("item_level") if isinstance(lot.get("item_level"), int) else None)
        group = groups.setdefault(
            key,
            {
                "base_type": base,
                "rarity": lot.get("rarity") or "",
                "item_level": lot.get("item_level"),
                "target": target,
                "count": 0,
                "prices": [],
                "sample_lots": [],
            },
        )
        group["count"] += 1
        group["prices"].append(price)
        if len(group["sample_lots"]) < 3:
            group["sample_lots"].append(
                {
                    "id": lot.get("id"),
                    "display_name": lot.get("display_name"),
                    "price_target": price,
                    "price_amount": lot.get("price_amount"),
                    "price_currency": lot.get("price_currency"),
                    "stash": lot.get("stash"),
                }
            )

    summaries: list[dict[str, Any]] = []
    for group in groups.values():
        values = sorted(group.pop("prices"))
        median = statistics.median(values)
        summaries.append(
            {
                **group,
                "avg": statistics.mean(values),
                "median": median,
                "min": values[0],
                "max": values[-1],
            }
        )
    summaries.sort(key=lambda item: (item["median"], item["avg"], item["max"], item["count"]), reverse=True)
    return summaries[:top]


def _verdict_for_lot(lot: dict[str, Any], market: dict[str, Any]) -> dict[str, Any]:
    seller_price = lot.get("price_unit_target") if market.get("unit_priced") else lot.get("price_target")
    current = market.get("current")
    count = market.get("count") or 0
    aggregate_source = market.get("source") == "poe.ninja"
    if not isinstance(seller_price, float) or not isinstance(current, float) or (count < 3 and not aggregate_source):
        return {"kind": "unknown", "delta_pct": None}
    delta_pct = ((seller_price - current) / current) * 100 if current else None
    if delta_pct is not None and delta_pct <= -15:
        kind = "cheap"
    elif delta_pct is not None and delta_pct >= 15:
        kind = "expensive"
    else:
        kind = "fair"
    return {"kind": kind, "delta_pct": delta_pct}


def _cache_copy(data: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(data, ensure_ascii=False))


def _seller_cache_key(league: str, seller: str, status: str) -> tuple[str, str, str]:
    return (league, seller.strip().lower(), status)


async def _get_seller_lots_snapshot(league: str, seller: str, status: str) -> dict[str, Any]:
    cache_key = _seller_cache_key(league, seller, status)
    cached = SELLER_LOTS_CACHE.get(cache_key)
    if cached and time.time() - cached["created_ts"] < SELLER_LOTS_CACHE_TTL:
        snapshot = _cache_copy(cached["data"])
        snapshot["cached"] = True
        return snapshot

    seller_search = await _post_search(league, _seller_lots_query(seller, "", status))
    seller_items = await _fetch_trade_items(
        seller_search.get("result") or [],
        seller_search.get("id") or "",
        limit=SELLER_LOTS_FETCH_LIMIT,
    )
    lots = [_normalize_item_listing(item) for item in seller_items]
    lots = [lot for lot in lots if lot]
    snapshot = {
        "created_ts": time.time(),
        "league": league,
        "seller": seller,
        "status": status,
        "query_id": seller_search.get("id"),
        "total": seller_search.get("total") or len(lots),
        "fetched_total": len(lots),
        "lots": lots,
        "cached": False,
    }
    SELLER_LOTS_CACHE[cache_key] = {"created_ts": time.time(), "data": snapshot}
    return _cache_copy(snapshot)


async def _fetch_similar_market(
    league: str,
    lot: dict[str, Any],
    seller: str,
    target: str,
    status: str,
    rates: dict[str, float],
    profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    rarity = _rarity_option(lot.get("rarity"))
    looseness_steps = [0] if rarity == "unique" else [0, 1, 2]
    last_payload: dict[str, Any] = {}
    for looseness in looseness_steps:
        comparison = _comparable_lot_profile(lot, looseness, profile)
        try:
            market_search = await _post_search(league, _similar_lots_query(lot, status, looseness=looseness, profile=profile))
        except httpx.HTTPStatusError as exc:
            last_payload = _empty_market_payload(lot, f"search failed: {exc.response.status_code}", looseness)
            await asyncio.sleep(DEFAULT_RATE_LIMIT_DELAY)
            continue
        except (httpx.TimeoutException, asyncio.TimeoutError):
            last_payload = _empty_market_payload(lot, "market search timeout", looseness)
            await asyncio.sleep(DEFAULT_RATE_LIMIT_DELAY)
            continue
        market_items = await _fetch_trade_items(
            market_search.get("result") or [],
            market_search.get("id") or "",
            limit=SELLER_MARKET_FETCH_LIMIT,
        )
        market_lots = [_normalize_item_listing(item) for item in market_items]
        market_lots = [_apply_target_price(item, rates, target) for item in market_lots if item]
        comparable_lots = _filter_comparable_lots(lot, market_lots, looseness, profile)
        stats = _market_price_stats(comparable_lots, seller)
        stats["confidence"] = _market_confidence(stats.get("count", 0), comparison, stats)
        last_payload = {
            "query_id": market_search.get("id"),
            "total": market_search.get("total") or len(market_lots),
            "candidate_count": len(market_lots),
            "filtered_count": len(comparable_lots),
            "lots": comparable_lots,
            "stats": stats,
            "looseness": looseness,
            "comparison": comparison,
        }
        if stats.get("count", 0) >= SELLER_MARKET_MIN_COMPARABLES:
            return last_payload
        await asyncio.sleep(DEFAULT_RATE_LIMIT_DELAY)
    return last_payload or _empty_market_payload(lot)


async def _get_cached_similar_market(
    league: str,
    lot: dict[str, Any],
    seller: str,
    target: str,
    status: str,
    rates: dict[str, float],
    profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    profile = profile or _manual_stat_profile()
    market_key = (
        league,
        status,
        target,
        seller.strip().lower(),
        lot.get("name") if lot.get("rarity") == "Unique" else "",
        lot.get("base_type"),
        lot.get("rarity"),
        lot.get("item_level") // 5 if isinstance(lot.get("item_level"), int) else None,
        _lot_affix_keys(lot, profile),
        profile.get("preferred_stat_ids") or (),
        profile.get("ignored_stat_ids") or (),
        profile.get("base_mode") or "default",
        bool(profile.get("base_only")),
        profile.get("tier_stat_ids") or (),
        tuple(
            (stat_id, value_range.get("min"), value_range.get("max"))
            for stat_id, value_range in sorted((profile.get("stat_value_ranges") or {}).items())
        ),
    )
    cached = SELLER_MARKET_CACHE.get(market_key)
    if cached and time.time() - cached["created_ts"] < SELLER_MARKET_CACHE_TTL:
        payload = _cache_copy(cached["data"])
        payload["cached"] = True
        return payload
    payload = await _fetch_similar_market(league, lot, seller, target, status, rates, profile)
    payload["cached"] = False
    SELLER_MARKET_CACHE[market_key] = {"created_ts": time.time(), "data": payload}
    return _cache_copy(payload)


async def get_seller_lots_analysis(
    league: str,
    seller: str,
    text: str = "",
    target: str = "exalted",
    status: str = "any",
    limit: int = 10,
    analyze: bool = True,
    preferred_stat_ids: Any = None,
    ignored_stat_ids: Any = None,
    base_mode: Any = None,
    tier_stat_ids: Any = None,
    stat_value_ranges: Any = None,
    base_only: Any = None,
) -> dict[str, Any]:
    seller = seller.strip()
    text = text.strip()
    limit = max(1, min(limit, SELLER_LOTS_FETCH_LIMIT))
    if not seller:
        raise ValueError("seller is required")
    profile = _manual_stat_profile(preferred_stat_ids, ignored_stat_ids, base_mode, tier_stat_ids, stat_value_ranges, base_only)

    started = time.monotonic()
    seller_snapshot = await asyncio.wait_for(
        _get_seller_lots_snapshot(league, seller, status),
        timeout=SELLER_SNAPSHOT_TIMEOUT,
    )
    all_lots = list(seller_snapshot.get("lots") or [])

    try:
        currency_rates = await asyncio.wait_for(
            get_category_rates(league=league, category="Currency", target=target, status="any"),
            timeout=SELLER_CURRENCY_RATES_TIMEOUT,
        )
        rates = _currency_rates_by_id(currency_rates, target)
    except (asyncio.TimeoutError, httpx.HTTPError):
        currency_rates = {"rows": [], "cached": False}
        rates = {target: 1.0}
    try:
        static_lookup = _static_entry_lookup(await asyncio.wait_for(get_trade_static(), timeout=SELLER_CURRENCY_RATES_TIMEOUT))
    except (asyncio.TimeoutError, httpx.HTTPError):
        static_lookup = {}
    category_rate_cache: dict[str, dict[str, Any]] = {"Currency": currency_rates}
    for lot in all_lots:
        _apply_target_price(lot, rates, target)

    filtered_lots = all_lots
    if text:
        lowered = text.lower()
        filtered_lots = [lot for lot in all_lots if lowered in _listing_text_blob(lot)]
    matched_total = len(filtered_lots)
    base_summary = _seller_base_summaries(filtered_lots, target)
    lots = filtered_lots[:limit]

    analysis_timed_out = False
    if analyze:
        for lot in lots:
            if time.monotonic() - started >= SELLER_ANALYSIS_BUDGET:
                analysis_timed_out = True
                market = _empty_market_payload(lot, "analysis budget exceeded")
            else:
                remaining = max(1.0, SELLER_ANALYSIS_BUDGET - (time.monotonic() - started))
                timeout = min(SELLER_MARKET_PER_LOT_TIMEOUT, remaining)
                try:
                    market = await asyncio.wait_for(
                        _stackable_market_payload(league, lot, target, status, static_lookup, category_rate_cache),
                        timeout=min(SELLER_CURRENCY_RATES_TIMEOUT, timeout),
                    )
                    if market is None:
                        market = await asyncio.wait_for(
                            _get_cached_similar_market(league, lot, seller, target, status, rates, profile),
                            timeout=timeout,
                        )
                except (asyncio.TimeoutError, httpx.TimeoutException):
                    analysis_timed_out = True
                    market = _empty_market_payload(lot, "market analysis timeout")
                except Exception as exc:
                    market = _empty_market_payload(lot, str(exc))
            lot["market"] = {
                "query_id": market.get("query_id"),
                "total": market.get("total"),
                "candidate_count": market.get("candidate_count"),
                "filtered_count": market.get("filtered_count"),
                "cached": market.get("cached", False),
                "comparison": market.get("comparison"),
                **market.get("stats", {}),
            }
            lot["verdict"] = _verdict_for_lot(lot, lot["market"])
    else:
        for lot in lots:
            market = _empty_market_payload(lot)
            lot["market"] = {"pending": True, **market.get("stats", {}), "comparison": market.get("comparison")}
            lot["verdict"] = {"kind": "unknown", "delta_pct": None}

    return {
        "league": league,
        "seller": seller,
        "query": text,
        "target": target,
        "status": status,
        "query_id": seller_snapshot.get("query_id"),
        "total": seller_snapshot.get("total") or len(lots),
        "matched_total": matched_total,
        "fetched_total": seller_snapshot.get("fetched_total") or len(lots),
        "cached": seller_snapshot.get("cached", False),
        "created_ts": seller_snapshot.get("created_ts"),
        "analysis_timed_out": analysis_timed_out,
        "analysis_pending": not analyze,
        "elapsed_seconds": round(time.monotonic() - started, 2),
        "lots": lots,
        "base_summary": base_summary,
        "source": "trade2/search+fetch",
        "search_mode": "cache-filter" if text else "account-cache",
        "basis": "instant buyout stash listings only",
    }


async def get_seller_lot_market(
    league: str,
    seller: str,
    lot_id: str,
    target: str = "exalted",
    status: str = "any",
    preferred_stat_ids: Any = None,
    ignored_stat_ids: Any = None,
    base_mode: Any = None,
    tier_stat_ids: Any = None,
    stat_value_ranges: Any = None,
    base_only: Any = None,
) -> dict[str, Any]:
    seller = seller.strip()
    profile = _manual_stat_profile(preferred_stat_ids, ignored_stat_ids, base_mode, tier_stat_ids, stat_value_ranges, base_only)
    seller_snapshot = await asyncio.wait_for(
        _get_seller_lots_snapshot(league, seller, status),
        timeout=SELLER_SNAPSHOT_TIMEOUT,
    )
    lot = next((item for item in seller_snapshot.get("lots") or [] if item.get("id") == lot_id), None)
    if not lot:
        raise ValueError("lot not found in seller cache")
    try:
        currency_rates = await asyncio.wait_for(
            get_category_rates(league=league, category="Currency", target=target, status="any"),
            timeout=SELLER_CURRENCY_RATES_TIMEOUT,
        )
        rates = _currency_rates_by_id(currency_rates, target)
    except (asyncio.TimeoutError, httpx.HTTPError):
        currency_rates = {"rows": [], "cached": False}
        rates = {target: 1.0}
    _apply_target_price(lot, rates, target)
    try:
        try:
            static_lookup = _static_entry_lookup(await asyncio.wait_for(get_trade_static(), timeout=SELLER_CURRENCY_RATES_TIMEOUT))
        except (asyncio.TimeoutError, httpx.HTTPError):
            static_lookup = {}
        market = await asyncio.wait_for(
            _stackable_market_payload(
                league,
                lot,
                target,
                status,
                static_lookup,
                {"Currency": currency_rates},
            ),
            timeout=SELLER_CURRENCY_RATES_TIMEOUT,
        )
        if market is None:
            market = await asyncio.wait_for(
                _get_cached_similar_market(league, lot, seller, target, status, rates, profile),
                timeout=SELLER_MARKET_PER_LOT_TIMEOUT,
            )
    except (asyncio.TimeoutError, httpx.TimeoutException):
        market = _empty_market_payload(lot, "market analysis timeout")
    lot_market = {
        "query_id": market.get("query_id"),
        "total": market.get("total"),
        "candidate_count": market.get("candidate_count"),
        "filtered_count": market.get("filtered_count"),
        "cached": market.get("cached", False),
        "comparison": market.get("comparison"),
        **market.get("stats", {}),
    }
    return {
        "lot_id": lot_id,
        "target": target,
        "price_target": lot.get("price_target"),
        "market": lot_market,
        "verdict": _verdict_for_lot(lot, lot_market),
        "sample_lots": (market.get("lots") or [])[:10],
    }


async def get_pasted_item_market(
    league: str,
    text: str,
    target: str = "exalted",
    status: str = "any",
) -> dict[str, Any]:
    parsed = parse_item_text(text)
    lot = _parsed_item_lot(parsed)
    if not lot.get("base_type"):
        market = _empty_market_payload(lot, "item text has no base type")
        return {
            "schema_version": "poe2-pasted-item-market/v1",
            "league": league,
            "target": target,
            "status": status,
            "parsed": parsed,
            "market": {**market.get("stats", {}), "comparison": market.get("comparison")},
            "sample_lots": [],
            "source": "pasted-text",
        }

    try:
        currency_rates = await asyncio.wait_for(
            get_category_rates(league=league, category="Currency", target=target, status="any"),
            timeout=SELLER_CURRENCY_RATES_TIMEOUT,
        )
        rates = _currency_rates_by_id(currency_rates, target)
    except (asyncio.TimeoutError, httpx.HTTPError):
        rates = {target: 1.0}

    try:
        market = await asyncio.wait_for(
            _fetch_similar_market(league, lot, "", target, status, rates),
            timeout=SELLER_MARKET_PER_LOT_TIMEOUT * 2,
        )
    except (asyncio.TimeoutError, httpx.TimeoutException):
        market = _empty_market_payload(lot, "market analysis timeout")
    except Exception as exc:
        market = _empty_market_payload(lot, str(exc))

    lot_market = {
        "query_id": market.get("query_id"),
        "total": market.get("total"),
        "candidate_count": market.get("candidate_count"),
        "filtered_count": market.get("filtered_count"),
        "cached": market.get("cached", False),
        "comparison": market.get("comparison"),
        **market.get("stats", {}),
    }
    return {
        "schema_version": "poe2-pasted-item-market/v1",
        "league": league,
        "target": target,
        "status": status,
        "parsed": parsed,
        "market": lot_market,
        "sample_lots": (market.get("lots") or [])[:10],
        "source": "trade2/search+fetch",
    }

def _rate_stats(rows: list[dict[str, Any]], item_id: str) -> dict[str, Any]:
    ratios = [row["ratio"] for row in rows if row.get("have_currency") == item_id and isinstance(row.get("ratio"), float)]
    if not ratios:
        return {"best": None, "median": None, "offers": 0, "volume": 0}
    volume = 0
    for row in rows:
        if row.get("have_currency") == item_id:
            try:
                volume += float(row.get("have_amount") or 0)
            except (TypeError, ValueError):
                pass
    return {
        "best": max(ratios),
        "median": statistics.median(ratios),
        "offers": len(ratios),
        "volume": volume,
    }


def _chunked(items: list[str], size: int) -> list[list[str]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def _target_factor(core: dict[str, Any], target: str) -> float | None:
    primary = core.get("primary")
    if target == primary:
        return 1.0
    rates = core.get("rates") or {}
    value = rates.get(target)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _price_sparkline_from_change(data: list[Any], current_value: float | None) -> list[float]:
    try:
        current = float(current_value or 0)
    except (TypeError, ValueError):
        return []
    if current <= 0:
        return []
    changes = []
    for point in data:
        try:
            change = float(point)
        except (TypeError, ValueError):
            continue
        if change <= -99.9:
            continue
        changes.append(change)
    if len(changes) < 2:
        return []
    last_factor = 1 + (changes[-1] / 100)
    if last_factor <= 0:
        return []
    baseline = current / last_factor
    return [baseline * (1 + change / 100) for change in changes]


def normalize_poe_ninja_overview(payload: dict[str, Any], target: str) -> dict[str, Any]:
    factor = _target_factor(payload.get("core") or {}, target)
    if factor is None:
        return {"rows": [], "target_supported": False}
    rows = []
    for line in payload.get("lines") or []:
        primary_value = line.get("primaryValue")
        volume_primary = line.get("volumePrimaryValue")
        try:
            value = float(primary_value) * factor
        except (TypeError, ValueError):
            value = None
        try:
            volume = float(volume_primary) * factor
        except (TypeError, ValueError):
            volume = 0
        sparkline = line.get("sparkline") or {}
        rows.append(
            {
                "id": line.get("id"),
                "best": value,
                "median": value,
                "offers": 0,
                "volume": volume,
                "change": sparkline.get("totalChange"),
                "sparkline": _price_sparkline_from_change(sparkline.get("data") or [], value),
                "sparkline_kind": "price",
                "max_volume_currency": line.get("maxVolumeCurrency"),
                "max_volume_rate": line.get("maxVolumeRate"),
            }
        )
    return {"rows": rows, "target_supported": True}


async def _get_poe_ninja_rates(league: str, category: str, target: str) -> dict[str, Any] | None:
    category_type = POE_NINJA_CATEGORY_TYPES.get(category)
    if not category_type:
        return None
    async with httpx.AsyncClient(headers=_headers(), timeout=30) as client:
        response = await client.get(
            f"{BASE_URL}/poe2/api/economy/exchange/current/overview",
            params={"league": league, "type": category_type},
        )
        response.raise_for_status()
    normalized = normalize_poe_ninja_overview(response.json(), target)
    if not normalized["target_supported"]:
        return None
    return normalized


def build_category_meta(categories: dict[str, list[dict[str, str | None]]]) -> list[dict[str, Any]]:
    return [
        {
            "id": category_id,
            "label": category_id,
            "label_ru": CATEGORY_RU.get(category_id, category_id),
            "count": len(entries),
            "icon": next((entry.get("image") for entry in entries if entry.get("image")), None),
        }
        for category_id, entries in categories.items()
        if entries
    ]


def build_trade_advice(
    category: str,
    rows: list[dict[str, Any]],
    target: str,
    snapshot_ts: float | None = None,
) -> list[dict[str, Any]]:
    if category != "Delirium":
        if category == "Fragments":
            return [
                {
                    "kind": "note",
                    "title_ru": "Проходки требуют ручной модели",
                    "title_en": "Boss entry items need a manual model",
                    "message_ru": "Цены проходок показаны, но цепочки фрагмент -> приглашение пока не рассчитаны: нужны точные рецепты/составы для каждого босса.",
                    "message_en": "Prices are shown, but fragment-to-invitation chains are not calculated yet: each boss needs exact recipe inputs.",
                }
            ]
        return []

    by_id = {row["id"]: row for row in rows}
    advice = []
    for source_index, source in enumerate(EMOTION_CHAIN):
        source_row = by_id.get(source)
        if not source_row:
            continue
        for result_index in range(source_index + 1, len(EMOTION_CHAIN)):
            result = EMOTION_CHAIN[result_index]
            result_row = by_id.get(result)
            if not result_row:
                continue
            path_steps = result_index - source_index
            input_count = 3**path_steps
            path_advice = _build_emotion_path_advice(
                source=source,
                result=result,
                source_row=source_row,
                result_row=result_row,
                input_count=input_count,
                path_steps=path_steps,
                target=target,
            )
            if path_advice:
                advice.append(path_advice)
    enriched_advice = enrich_trade_advice(advice, rows, snapshot_ts=snapshot_ts)
    filtered_advice = filter_dominated_emotion_paths(enriched_advice)
    return rank_opportunities(filtered_advice)


def _build_emotion_path_advice(
    source: str,
    result: str,
    source_row: dict[str, Any],
    result_row: dict[str, Any],
    input_count: int,
    path_steps: int,
    target: str,
) -> dict[str, Any] | None:
    source_value = source_row.get("median")
    result_value = result_row.get("median")
    if source_value is None or result_value is None:
        return None
    craft_cost = source_value * input_count
    profit = result_value - craft_cost
    margin = profit / craft_cost if craft_cost else 0
    try:
        source_volume = float(source_row.get("volume") or 0)
    except (TypeError, ValueError):
        source_volume = 0
    try:
        result_volume = float(result_row.get("volume") or 0)
    except (TypeError, ValueError):
        result_volume = 0
    min_volume = min(source_volume, result_volume)
    low_volume = min_volume < LOW_VOLUME_THRESHOLD
    if margin >= SIGNAL_MARGIN_THRESHOLD and not low_volume:
        severity = "signal"
        title_ru = "Сигнал"
        title_en = "Signal"
        risk_ru = "Объем достаточный, маржа заметная."
        risk_en = "Volume is acceptable and margin is meaningful."
    elif profit > 0 and margin >= WEAK_MARGIN_THRESHOLD:
        severity = "weak"
        title_ru = "Слабый сигнал"
        title_en = "Weak signal"
        risk_ru = "Есть расчетная прибыль, но проверь стакан и свежесть цены."
        risk_en = "Estimated profit exists, but check the order book and price freshness."
        if low_volume:
            risk_ru = "Объем низкий: проверь стакан вручную перед сделкой."
            risk_en = "Low volume: check the order book manually before trading."
    else:
        severity = "watch"
        title_ru = "Наблюдать"
        title_en = "Watch"
        risk_ru = "Маржа слишком мала или отрицательная для действия."
        risk_en = "Margin is too small or negative for action."
    source_name_ru = source_row.get("text_ru") or source_row.get("text") or source
    result_name_ru = result_row.get("text_ru") or result_row.get("text") or result
    source_name_en = source_row.get("text") or source_row.get("text_ru") or source
    result_name_en = result_row.get("text") or result_row.get("text_ru") or result
    return {
        "kind": "emotion_path",
        "severity": severity,
        "source": source,
        "result": result,
        "path_steps": path_steps,
        "input_count": input_count,
        "source_name_ru": source_name_ru,
        "result_name_ru": result_name_ru,
        "source_name_en": source_name_en,
        "result_name_en": result_name_en,
        "craft_cost": craft_cost,
        "result_value": result_value,
        "profit": profit,
        "margin": margin,
        "source_volume": source_volume,
        "result_volume": result_volume,
        "min_volume": min_volume,
        "low_volume": low_volume,
        "source_sparkline": source_row.get("sparkline") or [],
        "result_sparkline": result_row.get("sparkline") or [],
        "basis_ru": "График конечной позиции за 7 дней.",
        "basis_en": "7-day chart of the result item.",
        "target": target,
        "title_ru": title_ru,
        "title_en": title_en,
        "message_ru": (
            f"{input_count} x {source_name_ru} -> {result_name_ru} "
            f"({path_steps} шаг.): "
            f"прибыль {profit:.4f} {target}, маржа {margin:.1%}, "
            f"минимальный объем {min_volume:.1f}. {risk_ru}"
        ),
        "message_en": (
            f"{input_count} x {source_name_en} -> {result_name_en} "
            f"({path_steps} step{'s' if path_steps != 1 else ''}): "
            f"profit {profit:.4f} {target}, margin {margin:.1%}, "
            f"minimum volume {min_volume:.1f}. {risk_en}"
        ),
    }


def read_history(*args, **kwargs):
    kwargs.setdefault("history_path", HISTORY_PATH)
    return read_market_history(*args, **kwargs)

def read_latest_rates(league: str, category: str, target: str = "exalted", status: str = "any"):  # noqa: E302
    snapshot = _read_history_latest_rates(
        league=league,
        category=category,
        target=target,
        status=status,
        history_path=HISTORY_PATH,
    )
    if snapshot and "advice" not in snapshot:
        snapshot["advice"] = build_trade_advice(category, snapshot.get("rows") or [], target, snapshot_ts=snapshot.get("created_ts"))
    if snapshot and "recipes" not in snapshot:
        snapshot["recipes"] = analyze_recipes(category, snapshot.get("rows") or [], target, snapshot_ts=snapshot.get("created_ts"))
    if snapshot:
        for row in snapshot.get("rows") or []:
            if "execution" not in row:
                row["execution"] = execution_quality(row, snapshot_ts=snapshot.get("created_ts"))
    return snapshot


def read_item_history(
    league: str,
    category: str,
    item_id: str,
    target: str = "exalted",
    status: str = "any",
    metric: str = "price",
    limit: int = 1500,
):  # noqa: E302
    return _read_history_item(
        league=league,
        category=category,
        target=target,
        status=status,
        item_id=item_id,
        metric=metric,
        limit=limit,
        history_path=HISTORY_PATH,
    )
