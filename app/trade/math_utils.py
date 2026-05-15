from typing import Any, List, Optional, Tuple
import statistics

def to_float(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None

def to_int(value: Any) -> Optional[int]:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None

def percentile(sorted_values: List[float], position: float) -> Optional[float]:
    if not sorted_values:
        return None
    index = min(len(sorted_values) - 1, max(0, round((len(sorted_values) - 1) * position)))
    return sorted_values[index]

def trim_price_outliers(values: List[float]) -> Tuple[List[float], int]:
    if len(values) < 5:
        return values, 0
    q1 = percentile(values, 0.25)
    q3 = percentile(values, 0.75)
    if q1 is None or q3 is None:
        return values, 0
    iqr = q3 - q1
    if iqr <= 0:
        return values, 0
    low = q1 - 1.5 * iqr
    high = q3 + 1.5 * iqr
    trimmed = [value for value in values if low <= value <= high]
    return trimmed or values, len(values) - len(trimmed)

def market_price_stats(lots: List[dict], seller: str) -> dict:
    seller_key = seller.lower()
    raw_values = sorted(
        lot["price_target"]
        for lot in lots
        if isinstance(lot.get("price_target"), float) and lot.get("seller", "").lower() != seller_key
    )
    values, outliers = trim_price_outliers(raw_values)
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
        "p25": percentile(values, 0.25),
        "p75": percentile(values, 0.75),
    }

def target_factor(core: dict, target: str) -> Optional[float]:
    primary = core.get("primary")
    if target == primary:
        return 1.0
    rates = core.get("rates") or {}
    value = rates.get(target)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

def price_sparkline_from_change(data: List[Any], current_value: Optional[float]) -> List[float]:
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

def rate_stats(rows: List[dict], item_id: str) -> dict:
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
