from __future__ import annotations

from typing import Any

from app.profitability import combined_execution_quality, number, row_price


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

SIMULACRUM_RECIPE = {
    "source": "simulacrum-splinter",
    "result": "simulacrum",
    "input_count": 300,
    "label_ru": "Осколки Симулякра -> Симулякр",
}


def _emotion_path_recipes() -> list[dict[str, Any]]:
    recipes: list[dict[str, Any]] = []
    for source_index, source in enumerate(EMOTION_CHAIN):
        for result_index in range(source_index + 1, len(EMOTION_CHAIN)):
            path_steps = result_index - source_index
            recipes.append(
                {
                    "kind": "emotion_path",
                    "source": source,
                    "result": EMOTION_CHAIN[result_index],
                    "input_count": 3**path_steps,
                    "path_steps": path_steps,
                    "label_ru": "цепочка жидких эмоций 3-в-1",
                }
            )
    return recipes


KNOWN_STACK_RECIPES = {
    "Fragments": [SIMULACRUM_RECIPE],
    "Delirium": [SIMULACRUM_RECIPE, *_emotion_path_recipes()],
}


def _row_map(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(row.get("id")): row for row in rows if row.get("id")}


def _recipe_payload(recipe: dict[str, Any], by_id: dict[str, dict[str, Any]], target: str, snapshot_ts: float | None = None) -> dict[str, Any] | None:
    source = by_id.get(recipe["source"])
    result = by_id.get(recipe["result"])
    source_price = row_price(source)
    result_price = row_price(result)
    input_count = int(recipe.get("input_count") or 1)
    if source_price is None or result_price is None or input_count <= 0:
        return None
    cost = source_price * input_count
    profit = result_price - cost
    margin = profit / cost if cost > 0 else 0
    execution = combined_execution_quality(source, result, snapshot_ts=snapshot_ts)
    if profit > 0 and margin >= 0.08 and execution.get("quality") == "good":
        severity = "signal"
    elif profit > 0 and margin >= 0.02 and execution.get("quality") != "poor":
        severity = "weak"
    else:
        severity = "watch"
    return {
        "kind": recipe.get("kind") or "recipe",
        "source": recipe["source"],
        "result": recipe["result"],
        "input_count": input_count,
        "path_steps": recipe.get("path_steps") or 1,
        "source_name_ru": (source or {}).get("text_ru") or recipe["source"],
        "result_name_ru": (result or {}).get("text_ru") or recipe["result"],
        "source_name_en": (source or {}).get("text") or recipe["source"],
        "result_name_en": (result or {}).get("text") or recipe["result"],
        "target": target,
        "craft_cost": cost,
        "result_value": result_price,
        "profit": profit,
        "margin": margin,
        "source_sparkline": (source or {}).get("sparkline") or [],
        "result_sparkline": (result or {}).get("sparkline") or [],
        "min_volume": execution.get("volume") or 0,
        "execution": execution,
        "risk_flags": execution.get("risk_flags") or [],
        "severity": severity,
        "message_ru": (
            f"{input_count} x {(source or {}).get('text_ru') or recipe['source']} -> "
            f"{(result or {}).get('text_ru') or recipe['result']} "
            f"({recipe.get('path_steps') or 1} шаг.): прибыль {profit:.4f} {target}, "
            f"маржа {margin:.1%}."
        ),
        "message_en": (
            f"{input_count} x {(source or {}).get('text') or recipe['source']} -> "
            f"{(result or {}).get('text') or recipe['result']} "
            f"({recipe.get('path_steps') or 1} step{'s' if (recipe.get('path_steps') or 1) != 1 else ''}): "
            f"profit {profit:.4f} {target}, "
            f"margin {margin:.1%}."
        ),
    }


def analyze_recipes(category: str, rows: list[dict[str, Any]], target: str, snapshot_ts: float | None = None) -> dict[str, Any]:
    by_id = _row_map(rows)
    recipes = KNOWN_STACK_RECIPES.get(category, [])
    opportunities = [
        item
        for recipe in recipes
        for item in [_recipe_payload(recipe, by_id, target, snapshot_ts=snapshot_ts)]
        if item
    ]
    missing = [
        {
            "source": recipe.get("source"),
            "result": recipe.get("result"),
            "input_count": recipe.get("input_count"),
        }
        for recipe in recipes
        if recipe.get("source") not in by_id or recipe.get("result") not in by_id
    ]
    priced_rows = [row for row in rows if number(row.get("median")) or number(row.get("best"))]
    return {
        "schema_version": "poe2-recipe-analysis/v1",
        "category": category,
        "target": target,
        "known_recipes": len(recipes),
        "opportunities": sorted(opportunities, key=lambda item: item.get("margin") or 0, reverse=True),
        "missing": missing,
        "coverage": {
            "rows": len(rows),
            "priced_rows": len(priced_rows),
        },
        "notes": [
            "Recipe analysis only uses explicitly modeled recipes.",
            "Liquid Emotions are evaluated as full 3-to-1 transformation paths, not only adjacent upgrades.",
            "Unmodeled fragments stay as market rows until their exact composition is added.",
        ],
    }
