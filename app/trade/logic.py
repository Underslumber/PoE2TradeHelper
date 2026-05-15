import re
from typing import Any, Dict, List, Optional, Set, Tuple

from app.trade.math_utils import to_float, to_int, price_sparkline_from_change, target_factor

POE_SITE_BASE = "https://www.pathofexile.com"

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


def image_url(path: Optional[str]) -> Optional[str]:
    if not path:
        return None
    if path.startswith("http://") or path.startswith("https://"):
        return path
    return f"{POE_SITE_BASE}{path}"

def localized_entry_texts(payload: Optional[Dict[str, Any]]) -> Dict[str, Dict[str, str]]:
    localized: Dict[str, Dict[str, str]] = {}
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
    payload: Dict[str, Any],
    localized_payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, List[Dict[str, Optional[str]]]]:
    localized = localized_entry_texts(localized_payload)
    categories: Dict[str, List[Dict[str, Optional[str]]]] = {}
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
                    "image": image_url(entry.get("image")),
                }
            )
        categories[category_id] = entries
    return categories

def normalize_exchange_result(payload: Dict[str, Any], limit: int = 50) -> Dict[str, Any]:
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

def normalize_poe_ninja_overview(payload: Dict[str, Any], target: str) -> Dict[str, Any]:
    factor = target_factor(payload.get("core") or {}, target)
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
                "sparkline": price_sparkline_from_change(sparkline.get("data") or [], value),
                "sparkline_kind": "price",
                "max_volume_currency": line.get("maxVolumeCurrency"),
                "max_volume_rate": line.get("maxVolumeRate"),
            }
        )
    return {"rows": rows, "target_supported": True}

def item_display_name(item: Dict[str, Any]) -> str:
    name = (item.get("name") or "").strip()
    type_line = (item.get("typeLine") or "").strip()
    if name and type_line:
        return f"{name} {type_line}"
    return name or type_line or item.get("baseType") or "-"

def clean_trade_text(value: Any) -> str:
    text = str(value or "")
    return re.sub(r"\[[^\]|]*\|([^\]]+)\]", r"\1", text).strip()

def to_float_from_mod(value: Any) -> Optional[float]:
    return to_float(value)

def item_stat_mods(item: Dict[str, Any]) -> List[Dict[str, Any]]:
    extended = item.get("extended") or {}
    extended_mods = extended.get("mods") or {}
    extended_hashes = extended.get("hashes") or {}
    lines_by_kind = {
        "implicit": item.get("implicitMods") or [],
        "explicit": item.get("explicitMods") or [],
        "rune": item.get("runeMods") or [],
        "desecrated": item.get("desecratedMods") or [],
    }

    result: List[Dict[str, Any]] = []
    seen: Set[Tuple[str, str]] = set()
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
                        "min": to_float_from_mod(magnitude.get("min")),
                        "max": to_float_from_mod(magnitude.get("max")),
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

def normalize_item_listing(entry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    listing = entry.get("listing") or {}
    item = entry.get("item") or {}
    price = listing.get("price") or {}
    stash = listing.get("stash") or {}
    amount = to_float(price.get("amount"))
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
        "stack_size": to_int(item.get("stackSize")) or 1,
        "display_name": item_display_name(item),
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
        "stat_mods": item_stat_mods(item),
    }

def currency_rates_by_id(currency_rates: Dict[str, Any], target: str) -> Dict[str, float]:
    rates = {target: 1.0}
    for row in currency_rates.get("rows") or []:
        value = to_float(row.get("median") if row.get("median") is not None else row.get("best"))
        if row.get("id") and value:
            rates[row["id"]] = value
    return rates

def apply_target_price(lot: Dict[str, Any], rates: Dict[str, float], target: str) -> Dict[str, Any]:
    currency = lot.get("price_currency")
    amount = to_float(lot.get("price_amount"))
    factor = rates.get(currency)
    lot["target"] = target
    lot["price_target"] = amount * factor if amount and factor else None
    stack_size = to_int(lot.get("stack_size")) or 1
    lot["price_unit_target"] = lot["price_target"] / stack_size if lot.get("price_target") and stack_size > 1 else lot.get("price_target")
    return lot

def build_trade_advice(category: str, rows: List[Dict[str, Any]], target: str) -> List[Dict[str, Any]]:
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
            path_advice = build_emotion_path_advice(
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

def build_emotion_path_advice(
    source: str,
    result: str,
    source_row: Dict[str, Any],
    result_row: Dict[str, Any],
    input_count: int,
    path_steps: int,
    target: str,
) -> Optional[Dict[str, Any]]:
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

def chunked(items: List[str], size: int) -> List[List[str]]:
    return [items[i : i + size] for i in range(0, len(items), size)]
