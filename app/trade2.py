from __future__ import annotations

import asyncio
import json
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
