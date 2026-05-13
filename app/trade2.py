from __future__ import annotations

import asyncio
import json
import re
import statistics
import time
from typing import Any
from urllib.parse import quote

import httpx

from app.config import BASE_URL, DATA_DIR, DEFAULT_RATE_LIMIT_DELAY, USER_AGENT

TRADE2_BASE = "https://www.pathofexile.com/api/trade2"
TRADE2_RU_BASE = "https://ru.pathofexile.com/api/trade2"
POE_SITE_BASE = "https://www.pathofexile.com"
HISTORY_PATH = DATA_DIR / "trade_rate_history.jsonl"
RATE_CACHE_TTL = 300
RATE_CACHE: dict[tuple[str, str, str, str], dict[str, Any]] = {}
SELLER_LOTS_CACHE_TTL = 900
SELLER_LOTS_FETCH_LIMIT = 100
SELLER_MARKET_CACHE_TTL = 600
SELLER_MARKET_FETCH_LIMIT = 60
SELLER_MARKET_MIN_COMPARABLES = 3
SELLER_MARKET_MAX_STAT_FILTERS = 12
SELLER_LOTS_CACHE: dict[tuple[str, str, str], dict[str, Any]] = {}
SELLER_MARKET_CACHE: dict[tuple[Any, ...], dict[str, Any]] = {}

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
    async with httpx.AsyncClient(headers=_headers(), timeout=30) as client:
        response = await client.get(f"{TRADE2_BASE}/data/leagues")
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


async def get_trade_static() -> dict[str, list[dict[str, str | None]]]:
    async with httpx.AsyncClient(headers=_headers(), timeout=30) as client:
        response, ru_response = await asyncio.gather(
            client.get(f"{TRADE2_BASE}/data/static"),
            client.get(f"{TRADE2_RU_BASE}/data/static"),
        )
        response.raise_for_status()
        ru_response.raise_for_status()
    return normalize_static_entries(response.json(), ru_response.json())


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
            retry_after = response.headers.get("Retry-After")
            wait = int(retry_after) if retry_after and retry_after.isdigit() else 4
            await asyncio.sleep(wait)
            response = await client.post(f"{TRADE2_BASE}/exchange/poe2/{quote(league, safe='')}", json=body)
        response.raise_for_status()
    return response.json()


async def get_exchange_offers(
    league: str,
    have: str,
    want: str,
    status: str = "online",
) -> dict[str, Any]:
    return normalize_exchange_result(await _post_exchange(league, [have], [want], status=status))


async def _post_search(
    league: str,
    query: dict[str, Any],
    sort: dict[str, str] | None = None,
) -> dict[str, Any]:
    body = {"query": query, "sort": sort or {"price": "asc"}}
    async with httpx.AsyncClient(headers=_headers({"Content-Type": "application/json"}), timeout=30) as client:
        response = await client.post(f"{TRADE2_RU_BASE}/search/poe2/{quote(league, safe='')}", json=body)
        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After")
            wait = int(retry_after) if retry_after and retry_after.isdigit() else 4
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
                retry_after = response.headers.get("Retry-After")
                wait = int(retry_after) if retry_after and retry_after.isdigit() else 4
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


def _stat_filter(stat_id: str, weight: float | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"id": stat_id, "disabled": False}
    if weight is not None:
        payload["value"] = {"weight": weight}
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


def _lot_key_stat_mods(lot: dict[str, Any], max_count: int = SELLER_MARKET_MAX_STAT_FILTERS) -> list[dict[str, Any]]:
    seen: set[str] = set()
    candidates: list[dict[str, Any]] = []
    for mod in lot.get("stat_mods") or []:
        stat_id = mod.get("id")
        kind = mod.get("type")
        if not stat_id or stat_id in seen or kind not in COMPARABLE_STAT_TYPES:
            continue
        seen.add(stat_id)
        candidates.append(mod)

    candidates.sort(key=_stat_mod_priority, reverse=True)
    return candidates[:max_count]


def _similar_lot_stat_group(lot: dict[str, Any], looseness: int) -> dict[str, Any]:
    mods = _lot_key_stat_mods(lot)
    if not mods:
        return {"type": "and", "filters": []}

    filters = [_stat_filter(mod["id"]) for mod in mods]
    if looseness == 0 or len(filters) == 1:
        return {"type": "and", "filters": filters}
    if looseness == 1:
        return {"type": "count", "value": {"min": max(1, len(filters) - 1)}, "filters": filters}

    weighted_filters = [
        _stat_filter(mod["id"], max(1.0, round(_stat_mod_priority(mod) / 20, 2)))
        for mod in mods
    ]
    return {
        "type": "weight",
        "value": {"min": max(1, len(weighted_filters))},
        "filters": weighted_filters,
    }


def _similar_lots_query(lot: dict[str, Any], status: str, looseness: int = 0) -> dict[str, Any]:
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
        "stats": [_similar_lot_stat_group(lot, looseness)],
        "filters": filters,
    }
    if rarity == "unique" and lot.get("name"):
        query["term"] = lot["name"]
    else:
        query["type"] = lot.get("base_type") or lot.get("type_line") or lot.get("display_name")
    return query


def _to_float(value: Any) -> float | None:
    try:
        number = float(value)
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


def _lot_affix_keys(lot: dict[str, Any]) -> tuple[str, ...]:
    stat_ids = {
        f"stat:{mod.get('id')}"
        for mod in lot.get("stat_mods") or []
        if mod.get("id") and mod.get("type") in COMPARABLE_STAT_TYPES
    }
    if stat_ids:
        return tuple(sorted(stat_ids))
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


def _comparable_lot_profile(lot: dict[str, Any], looseness: int) -> dict[str, Any]:
    affixes = _lot_affix_keys(lot)
    if looseness == 0:
        mode = "type-level-stat-ids"
        required_affixes = len(affixes)
        level_tolerance = 5
    elif looseness == 1:
        mode = "type-level-stat-ids-minus-one"
        required_affixes = max(0, len(affixes) - 1)
        level_tolerance = 10
    else:
        mode = "type-level-weighted-stats"
        required_affixes = max(0, min(len(affixes), 2))
        level_tolerance = 15
    key_stats = _lot_key_stat_mods(lot)
    return {
        "mode": mode,
        "base_type": lot.get("base_type") or lot.get("type_line") or lot.get("display_name"),
        "rarity": lot.get("rarity") or "",
        "item_level": lot.get("item_level"),
        "level_tolerance": level_tolerance,
        "affixes": list(affixes),
        "required_affixes": required_affixes,
        "stat_ids": [mod["id"] for mod in key_stats],
    }


def _filter_comparable_lots(target: dict[str, Any], lots: list[dict[str, Any]], looseness: int) -> list[dict[str, Any]]:
    target_rarity = _rarity_option(target.get("rarity"))
    target_base = _lot_base_key(target)
    target_name = _clean_trade_text(target.get("name")).lower()
    target_affixes = set(_lot_affix_keys(target))
    profile = _comparable_lot_profile(target, looseness)
    required_affixes = profile["required_affixes"]
    comparable: list[dict[str, Any]] = []

    for lot in lots:
        candidate_rarity = _rarity_option(lot.get("rarity"))
        if target_rarity and candidate_rarity != target_rarity:
            continue
        if target_rarity == "unique":
            candidate_name = _clean_trade_text(lot.get("name")).lower()
            if target_name and candidate_name != target_name:
                continue
        elif target_base and _lot_base_key(lot) != target_base:
            continue
        if not _item_level_matches(target.get("item_level"), lot.get("item_level"), profile["level_tolerance"]):
            continue
        if required_affixes:
            overlap = len(target_affixes & set(_lot_affix_keys(lot)))
            if overlap < required_affixes:
                continue
        comparable.append(lot)
    return comparable


def _normalize_item_listing(entry: dict[str, Any]) -> dict[str, Any] | None:
    listing = entry.get("listing") or {}
    item = entry.get("item") or {}
    price = listing.get("price") or {}
    stash = listing.get("stash") or {}
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
        "price_type": price.get("type") or "",
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


def _market_confidence(count: int, comparison: dict[str, Any] | None = None) -> str:
    mode = (comparison or {}).get("mode") or ""
    if count >= 8 and mode == "type-level-stat-ids":
        return "high"
    if count >= 5 and mode in {"type-level-stat-ids", "type-level-stat-ids-minus-one"}:
        return "medium"
    if count >= SELLER_MARKET_MIN_COMPARABLES:
        return "low"
    return "insufficient"


def _market_price_stats(lots: list[dict[str, Any]], seller: str) -> dict[str, Any]:
    seller_key = seller.lower()
    raw_values = sorted(
        lot["price_target"]
        for lot in lots
        if isinstance(lot.get("price_target"), float) and lot.get("seller", "").lower() != seller_key
    )
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
    }


def _verdict_for_lot(lot: dict[str, Any], market: dict[str, Any]) -> dict[str, Any]:
    seller_price = lot.get("price_target")
    current = market.get("current")
    count = market.get("count") or 0
    if not isinstance(seller_price, float) or not isinstance(current, float) or count < 3:
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
) -> dict[str, Any]:
    rarity = _rarity_option(lot.get("rarity"))
    looseness_steps = [0] if rarity == "unique" else [0, 1, 2]
    last_payload: dict[str, Any] = {}
    for looseness in looseness_steps:
        comparison = _comparable_lot_profile(lot, looseness)
        try:
            market_search = await _post_search(league, _similar_lots_query(lot, status, looseness=looseness))
        except httpx.HTTPStatusError as exc:
            last_payload = {
                "query_id": None,
                "total": 0,
                "candidate_count": 0,
                "filtered_count": 0,
                "lots": [],
                "stats": {
                    "count": 0,
                    "raw_count": 0,
                    "outliers": 0,
                    "current": None,
                    "min": None,
                    "median": None,
                    "p25": None,
                    "p75": None,
                    "confidence": "insufficient",
                    "error": f"search failed: {exc.response.status_code}",
                },
                "looseness": looseness,
                "comparison": comparison,
            }
            await asyncio.sleep(DEFAULT_RATE_LIMIT_DELAY)
            continue
        market_items = await _fetch_trade_items(
            market_search.get("result") or [],
            market_search.get("id") or "",
            limit=SELLER_MARKET_FETCH_LIMIT,
        )
        market_lots = [_normalize_item_listing(item) for item in market_items]
        market_lots = [_apply_target_price(item, rates, target) for item in market_lots if item]
        comparable_lots = _filter_comparable_lots(lot, market_lots, looseness)
        stats = _market_price_stats(comparable_lots, seller)
        stats["confidence"] = _market_confidence(stats.get("count", 0), comparison)
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
    return last_payload or {
        "query_id": None,
        "total": 0,
        "lots": [],
        "stats": {
            "count": 0,
            "raw_count": 0,
            "outliers": 0,
            "current": None,
            "min": None,
            "median": None,
            "p25": None,
            "p75": None,
            "confidence": "insufficient",
        },
        "comparison": _comparable_lot_profile(lot, 2),
    }


async def _get_cached_similar_market(
    league: str,
    lot: dict[str, Any],
    seller: str,
    target: str,
    status: str,
    rates: dict[str, float],
) -> dict[str, Any]:
    market_key = (
        league,
        status,
        target,
        seller.strip().lower(),
        lot.get("name") if lot.get("rarity") == "Unique" else "",
        lot.get("base_type"),
        lot.get("rarity"),
        lot.get("item_level") // 5 if isinstance(lot.get("item_level"), int) else None,
        _lot_affix_keys(lot),
    )
    cached = SELLER_MARKET_CACHE.get(market_key)
    if cached and time.time() - cached["created_ts"] < SELLER_MARKET_CACHE_TTL:
        payload = _cache_copy(cached["data"])
        payload["cached"] = True
        return payload
    payload = await _fetch_similar_market(league, lot, seller, target, status, rates)
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
) -> dict[str, Any]:
    seller = seller.strip()
    text = text.strip()
    limit = max(1, min(limit, 20))
    if not seller:
        raise ValueError("seller is required")

    seller_snapshot = await _get_seller_lots_snapshot(league, seller, status)
    lots = list(seller_snapshot.get("lots") or [])
    if text:
        lowered = text.lower()
        lots = [lot for lot in lots if lowered in _listing_text_blob(lot)]
    matched_total = len(lots)
    lots = lots[:limit]

    currency_rates = await get_category_rates(league=league, category="Currency", target=target, status="any")
    rates = _currency_rates_by_id(currency_rates, target)
    for lot in lots:
        _apply_target_price(lot, rates, target)

    for lot in lots:
        try:
            market = await _get_cached_similar_market(league, lot, seller, target, status, rates)
        except Exception as exc:
            market = {
                "query_id": None,
                "total": 0,
                "candidate_count": 0,
                "filtered_count": 0,
                "lots": [],
                "stats": {
                    "count": 0,
                    "raw_count": 0,
                    "outliers": 0,
                    "current": None,
                    "min": None,
                    "median": None,
                    "p25": None,
                    "p75": None,
                    "confidence": "insufficient",
                    "error": str(exc),
                },
                "comparison": _comparable_lot_profile(lot, 2),
                "cached": False,
            }
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
        "lots": lots,
        "source": "trade2/search+fetch",
        "search_mode": "cache-filter" if text else "account-cache",
        "basis": "priced stash listings only",
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


def _scaled_sparkline(data: list[Any], factor: float) -> list[float]:
    values = []
    for point in data:
        try:
            values.append(float(point) * factor)
        except (TypeError, ValueError):
            continue
    return values


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
                "sparkline": _scaled_sparkline(sparkline.get("data") or [], factor),
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


def _log_rates(snapshot: dict[str, Any]) -> None:
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with HISTORY_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(snapshot, ensure_ascii=False) + "\n")


async def get_category_rates(
    league: str,
    category: str,
    target: str = "divine",
    status: str = "any",
) -> dict[str, Any]:
    cache_key = (league, category, target, status)
    cached = RATE_CACHE.get(cache_key)
    if cached and time.time() - cached["created_ts"] < RATE_CACHE_TTL:
        data = dict(cached["data"])
        data["cached"] = True
        return data

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

    rows = []
    for entry in entries:
        item_id = entry["id"]
        stats = rate_by_id.get(item_id, {})
        rows.append(
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
                "max_volume_currency": stats.get("max_volume_currency"),
                "max_volume_rate": stats.get("max_volume_rate"),
            }
        )

    snapshot = {
        "created_ts": time.time(),
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
        "advice": build_trade_advice(category, rows, target),
        "errors": errors,
        "source": source,
        "cached": False,
    }
    _log_rates(snapshot)
    RATE_CACHE[cache_key] = {"created_ts": time.time(), "data": result}
    return result


def build_trade_advice(category: str, rows: list[dict[str, Any]], target: str) -> list[dict[str, Any]]:
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
    severity_rank = {"signal": 0, "weak": 1, "watch": 2}
    return sorted(advice, key=lambda item: (severity_rank.get(item.get("severity"), 9), -item.get("profit", 0)))


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
    return {
        "kind": "emotion_path",
        "severity": severity,
        "source": source,
        "result": result,
        "path_steps": path_steps,
        "input_count": input_count,
        "source_name_ru": source_row.get("text_ru"),
        "result_name_ru": result_row.get("text_ru"),
        "source_name_en": source_row.get("text"),
        "result_name_en": result_row.get("text"),
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
            f"{input_count} x {source_row.get('text_ru')} -> {result_row.get('text_ru')} "
            f"({path_steps} шаг.): "
            f"прибыль {profit:.4f} {target}, маржа {margin:.1%}, "
            f"минимальный объем {min_volume:.1f}. {risk_ru}"
        ),
        "message_en": (
            f"{input_count} x {source_row.get('text')} -> {result_row.get('text')} "
            f"({path_steps} step{'s' if path_steps != 1 else ''}): "
            f"profit {profit:.4f} {target}, margin {margin:.1%}, "
            f"minimum volume {min_volume:.1f}. {risk_en}"
        ),
    }


def read_history(limit: int = 30) -> list[dict[str, Any]]:
    if not HISTORY_PATH.exists():
        return []
    lines = HISTORY_PATH.read_text(encoding="utf-8").splitlines()[-limit:]
    history = []
    for line in lines:
        try:
            history.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return list(reversed(history))


def read_latest_rates(
    league: str,
    category: str,
    target: str = "exalted",
    status: str = "any",
) -> dict[str, Any] | None:
    if not HISTORY_PATH.exists():
        return None
    for line in reversed(HISTORY_PATH.read_text(encoding="utf-8").splitlines()):
        try:
            snapshot = json.loads(line)
        except json.JSONDecodeError:
            continue
        if (
            snapshot.get("league") == league
            and snapshot.get("category") == category
            and snapshot.get("target") == target
            and snapshot.get("status") == status
        ):
            rows = snapshot.get("rows") or []
            return {
                "created_ts": snapshot.get("created_ts"),
                "league": league,
                "category": category,
                "target": target,
                "status": status,
                "rows": rows,
                "advice": build_trade_advice(category, rows, target),
                "errors": snapshot.get("errors") or [],
                "source": snapshot.get("source") or "cache",
                "cached": True,
            }
    return None
