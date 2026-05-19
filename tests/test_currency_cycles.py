from __future__ import annotations

from app.currency_cycles import best_exchange_edge, find_currency_cycles_from_edges


def _edge(source: str, target: str, rate: float) -> dict:
    return {
        "from": source,
        "to": target,
        "rate": rate,
        "raw_rate": rate,
        "effective_rate": rate,
        "available_from": 10,
        "available_to": 10 * rate,
        "offer_count": 3,
    }


def test_currency_cycles_find_profitable_multi_hop_route() -> None:
    cycles = find_currency_cycles_from_edges(
        [
            _edge("exalted", "divine", 0.01),
            _edge("divine", "chaos", 100),
            _edge("chaos", "exalted", 1.2),
        ],
        base="exalted",
        max_steps=4,
        min_margin=0.01,
    )

    assert cycles[0]["route"] == ["exalted", "divine", "chaos", "exalted"]
    assert cycles[0]["step_count"] == 3
    assert round(cycles[0]["finish_amount"], 4) == 1.2
    assert cycles[0]["severity"] == "signal"


def test_currency_cycles_respect_fee_adjusted_margin() -> None:
    cycles = find_currency_cycles_from_edges(
        [
            {"from": "exalted", "to": "divine", "effective_rate": 0.01 * 0.99},
            {"from": "divine", "to": "exalted", "effective_rate": 101 * 0.99},
        ],
        base="exalted",
        max_steps=2,
        min_margin=0.001,
    )

    assert cycles == []


def test_best_exchange_edge_prefers_liquid_offer_over_tiny_best_price() -> None:
    edge = best_exchange_edge(
        {
            "total": 2,
            "rows": [
                {
                    "have_currency": "exalted",
                    "want_currency": "divine",
                    "ratio": 0.011,
                    "stock": 0.1,
                    "have_amount": 90,
                    "want_amount": 1,
                },
                {
                    "have_currency": "exalted",
                    "want_currency": "divine",
                    "ratio": 0.01,
                    "stock": 5,
                    "have_amount": 100,
                    "want_amount": 1,
                },
            ],
        },
        have="exalted",
        want="divine",
        fee_pct=0,
        min_volume=50,
    )

    assert edge is not None
    assert edge["rate"] == 0.01
    assert edge["offer_count"] == 2
    assert edge["available_from"] == 500
