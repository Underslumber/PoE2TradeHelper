from __future__ import annotations

from dataclasses import dataclass
from typing import Any


DEFAULT_BASKET_ID = "basket:liquid-core"
DEFAULT_BASKET_LABEL_RU = "Корзина ликвидности"
DEFAULT_BASKET_COMPONENTS = (
    ("exalted", 0.45),
    ("divine", 0.35),
    ("chaos", 0.20),
)


@dataclass(frozen=True)
class BasketComponent:
    currency_id: str
    weight: float


def is_basket_benchmark(value: str | None) -> bool:
    return str(value or "").startswith("basket:")


def basket_components(_basket_id: str | None = DEFAULT_BASKET_ID) -> list[BasketComponent]:
    return [BasketComponent(currency_id=item_id, weight=weight) for item_id, weight in DEFAULT_BASKET_COMPONENTS]


def _positive_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _row_price(row: dict[str, Any] | None) -> float | None:
    if not row:
        return None
    return _positive_number(row.get("median")) or _positive_number(row.get("best"))


def basket_price_from_snapshot(snapshot: dict[str, Any] | None, target_currency: str, basket_id: str | None = DEFAULT_BASKET_ID) -> dict[str, Any]:
    rows = {row.get("id"): row for row in (snapshot or {}).get("rows") or []}
    components = []
    weighted_sum = 0.0
    weight_sum = 0.0
    missing = []
    for component in basket_components(basket_id):
        if component.currency_id == target_currency:
            price = 1.0
        else:
            price = _row_price(rows.get(component.currency_id))
        if price is None:
            missing.append(component.currency_id)
            continue
        weighted_sum += price * component.weight
        weight_sum += component.weight
        components.append(
            {
                "id": component.currency_id,
                "weight": component.weight,
                "price": price,
                "target": target_currency,
            }
        )
    value = weighted_sum / weight_sum if weight_sum > 0 else None
    return {
        "id": basket_id or DEFAULT_BASKET_ID,
        "label_ru": DEFAULT_BASKET_LABEL_RU,
        "target": target_currency,
        "value": value,
        "components": components,
        "missing": missing,
        "coverage": weight_sum,
        "source": (snapshot or {}).get("source") or "",
        "created_ts": (snapshot or {}).get("created_ts"),
    }


def latest_benchmark_price(league: str, target_currency: str | None, benchmark: str | None, cache: dict | None = None) -> float | None:
    if not target_currency or not benchmark:
        return None
    if target_currency == benchmark:
        return 1.0
    if not is_basket_benchmark(benchmark):
        return None
    key = ("basket_benchmark", league, target_currency, benchmark)
    if cache is not None and key in cache:
        return cache[key]
    from app.trade2 import read_latest_rates

    snapshot = read_latest_rates(league=league, category="Currency", target=target_currency, status="any")
    if not snapshot:
        snapshot = read_latest_rates(league=league, category="Currency", target=target_currency, status="online")
    result = basket_price_from_snapshot(snapshot, target_currency, benchmark)
    value = _positive_number(result.get("value"))
    if cache is not None:
        cache[key] = value
    return value


def benchmark_price_at(
    league: str,
    target_currency: str | None,
    benchmark: str | None,
    timestamp: float | None,
    cache: dict | None = None,
) -> float | None:
    if not target_currency or not benchmark or timestamp is None:
        return None
    if target_currency == benchmark:
        return 1.0
    if not is_basket_benchmark(benchmark):
        return None
    key = ("basket_benchmark_history", league, target_currency, benchmark)
    if cache is not None and key in cache:
        snapshots = cache[key]
    else:
        from app.trade2 import read_history

        snapshots = read_history(limit=2000, league=league, category="Currency", target=target_currency, status="any")
        if not snapshots:
            snapshots = read_history(limit=2000, league=league, category="Currency", target=target_currency, status="online")
        if cache is not None:
            cache[key] = snapshots
    candidates: list[tuple[float, float]] = []
    for snapshot in snapshots:
        created_ts = _positive_number(snapshot.get("created_ts"))
        if created_ts is None:
            continue
        value = _positive_number(basket_price_from_snapshot(snapshot, target_currency, benchmark).get("value"))
        if value is not None:
            candidates.append((created_ts, value))
    if not candidates:
        return None
    before = [item for item in candidates if item[0] <= timestamp]
    if before:
        return max(before, key=lambda item: item[0])[1]
    nearest_ts, nearest_price = min(candidates, key=lambda item: abs(item[0] - timestamp))
    return nearest_price if abs(nearest_ts - timestamp) <= 36 * 60 * 60 else None
