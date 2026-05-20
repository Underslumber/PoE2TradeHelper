from __future__ import annotations

from typing import Any

from app.profitability import combined_execution_quality, number, rank_opportunities, row_price


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

BREACHSTONE_RECIPE = {
    "source": "breach-splinter",
    "result": "breachstone",
    "input_count": 300,
    "label_ru": "Осколки Разлома -> Камень Разлома",
}

RITUAL_INVITATION_RECIPE = {
    "source": "petition-splinter",
    "result": "an-audience-with-the-king",
    "input_count": 300,
    "label_ru": "Осколки прошения -> Встреча с Хозяином",
}

KULEMAK_INVITATION_RECIPE = {
    "source": "runic-splinter",
    "result": "kulemaks-invitation",
    "input_count": 300,
    "label_ru": "Рунические осколки -> Приглашение Кулемака",
}

ENTRY_SET_RECIPES = {
    "Fragments": [
        {
            "kind": "entry_set",
            "set_id": "ultimatum-fate-set",
            "label_ru": "Комплект ключей Испытаний",
            "label_en": "Ultimatum fate set",
            "inputs": [
                {"source": "cowardly-fate", "count": 1},
                {"source": "deadly-fate", "count": 1},
                {"source": "victorious-fate", "count": 1},
            ],
        },
        {
            "kind": "entry_set",
            "set_id": "crisis-fragment-set",
            "label_ru": "Комплект переломных фрагментов",
            "label_en": "Crisis fragment set",
            "inputs": [
                {"source": "ancient-crisis-fragment", "count": 1},
                {"source": "faded-crisis-fragment", "count": 1},
                {"source": "weathered-crisis-fragment", "count": 1},
            ],
        },
        {
            "kind": "entry_set",
            "set_id": "calamity-fragment-set",
            "label_ru": "Комплект фрагментов бедствия",
            "label_en": "Calamity fragment set",
            "inputs": [
                {"source": "primary-calamity-fragment", "count": 1},
                {"source": "secondary-calamity-fragment", "count": 1},
                {"source": "tertiary-calamity-fragment", "count": 1},
            ],
        },
    ],
}

SEVERITY_RANK = {"signal": 0, "weak": 1, "watch": 2}
EXECUTION_QUALITY_RANK = {"good": 0, "partial": 1, "poor": 2}


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
    "Breach": [BREACHSTONE_RECIPE],
    "Ritual": [RITUAL_INVITATION_RECIPE],
    "Fragments": [SIMULACRUM_RECIPE, KULEMAK_INVITATION_RECIPE],
    "Delirium": [SIMULACRUM_RECIPE, *_emotion_path_recipes()],
}


def _numeric_value(value: Any, default: float = 0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _signal_rank(item: dict[str, Any]) -> int:
    return SEVERITY_RANK.get(str(item.get("severity") or "watch"), SEVERITY_RANK["watch"])


def _execution_rank(item: dict[str, Any]) -> int:
    execution = item.get("execution") or {}
    return EXECUTION_QUALITY_RANK.get(str(execution.get("quality") or "partial"), EXECUTION_QUALITY_RANK["partial"])


def _dominates_emotion_path(shorter: dict[str, Any], longer: dict[str, Any]) -> bool:
    if shorter is longer:
        return False
    if shorter.get("kind") != "emotion_path" or longer.get("kind") != "emotion_path":
        return False
    if shorter.get("source") != longer.get("source"):
        return False
    shorter_steps = int(shorter.get("path_steps") or 0)
    longer_steps = int(longer.get("path_steps") or 0)
    if shorter_steps <= 0 or longer_steps <= 0 or shorter_steps >= longer_steps:
        return False
    if (number(shorter.get("profit")) or 0) <= 0:
        return False
    if _signal_rank(shorter) > _signal_rank(longer):
        return False
    if _execution_rank(shorter) > _execution_rank(longer):
        return False
    shorter_margin = _numeric_value(shorter.get("margin"))
    longer_margin = _numeric_value(longer.get("margin"))
    return shorter_margin >= longer_margin


def filter_dominated_emotion_paths(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        item
        for item in items
        if not any(_dominates_emotion_path(other, item) for other in items)
    ]


def _row_map(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(row.get("id")): row for row in rows if row.get("id")}


def _recipe_inputs(recipe: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(recipe.get("inputs"), list):
        return [
            {"source": item.get("source"), "count": int(item.get("count") or 1)}
            for item in recipe["inputs"]
            if isinstance(item, dict) and item.get("source")
        ]
    return [{"source": recipe["source"], "count": int(recipe.get("input_count") or 1)}]


def _input_component_payload(source_row: dict[str, Any], source_id: str, count: int) -> dict[str, Any]:
    price = row_price(source_row) or 0
    return {
        "source": source_id,
        "input_count": count,
        "source_name_ru": source_row.get("text_ru") or source_id,
        "source_name_en": source_row.get("text") or source_id,
        "price": price,
        "cost": price * count,
        "sparkline": source_row.get("sparkline") or [],
    }


def _recipe_input_components(
    recipe: dict[str, Any],
    by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]] | None:
    components: list[dict[str, Any]] = []
    for item in _recipe_inputs(recipe):
        source_id = item["source"]
        count = item["count"]
        source_row = by_id.get(source_id)
        if not source_row or row_price(source_row) is None or count <= 0:
            return None
        components.append(_input_component_payload(source_row, source_id, count))
    return components


def _component_label(components: list[dict[str, Any]], lang: str) -> str:
    name_key = "source_name_ru" if lang == "ru" else "source_name_en"
    return " + ".join(
        f"{component['input_count']} x {component.get(name_key) or component['source']}"
        for component in components
    )


def _recipe_payload(recipe: dict[str, Any], by_id: dict[str, dict[str, Any]], target: str, snapshot_ts: float | None = None) -> dict[str, Any] | None:
    components = _recipe_input_components(recipe, by_id)
    result = by_id.get(recipe["result"])
    result_price = row_price(result)
    if not components or result_price is None:
        return None
    cost = sum(component["cost"] for component in components)
    profit = result_price - cost
    margin = profit / cost if cost > 0 else 0
    execution_rows = [by_id[component["source"]] for component in components]
    execution = combined_execution_quality(*execution_rows, result, snapshot_ts=snapshot_ts)
    if profit > 0 and margin >= 0.08 and execution.get("quality") == "good":
        severity = "signal"
    elif profit > 0 and margin >= 0.02 and execution.get("quality") != "poor":
        severity = "weak"
    else:
        severity = "watch"
    first_component = components[0]
    input_count = first_component["input_count"] if len(components) == 1 else sum(component["input_count"] for component in components)
    source_id = first_component["source"] if len(components) == 1 else "+".join(component["source"] for component in components)
    source_name_ru = first_component["source_name_ru"] if len(components) == 1 else _component_label(components, "ru")
    source_name_en = first_component["source_name_en"] if len(components) == 1 else _component_label(components, "en")
    return {
        "kind": recipe.get("kind") or "recipe",
        "source": source_id,
        "result": recipe["result"],
        "input_count": input_count,
        "path_steps": recipe.get("path_steps") or 1,
        "components": components,
        "source_name_ru": source_name_ru,
        "result_name_ru": (result or {}).get("text_ru") or recipe["result"],
        "source_name_en": source_name_en,
        "result_name_en": (result or {}).get("text") or recipe["result"],
        "target": target,
        "craft_cost": cost,
        "result_value": result_price,
        "profit": profit,
        "margin": margin,
        "source_sparkline": first_component.get("sparkline") or [],
        "result_sparkline": (result or {}).get("sparkline") or [],
        "min_volume": execution.get("volume") or 0,
        "execution": execution,
        "risk_flags": execution.get("risk_flags") or [],
        "severity": severity,
        "message_ru": (
            f"{source_name_ru} -> "
            f"{(result or {}).get('text_ru') or recipe['result']} "
            f"({recipe.get('path_steps') or 1} шаг.): прибыль {profit:.4f} {target}, "
            f"маржа {margin:.1%}."
        ),
        "message_en": (
            f"{source_name_en} -> "
            f"{(result or {}).get('text') or recipe['result']} "
            f"({recipe.get('path_steps') or 1} step{'s' if (recipe.get('path_steps') or 1) != 1 else ''}): "
            f"profit {profit:.4f} {target}, "
            f"margin {margin:.1%}."
        ),
    }


def _entry_set_payload(
    recipe: dict[str, Any],
    by_id: dict[str, dict[str, Any]],
    target: str,
    snapshot_ts: float | None = None,
) -> dict[str, Any] | None:
    components = _recipe_input_components(recipe, by_id)
    if not components:
        return None
    rows = [by_id[component["source"]] for component in components]
    execution = combined_execution_quality(*rows, snapshot_ts=snapshot_ts)
    return {
        "kind": recipe.get("kind") or "entry_set",
        "set_id": recipe.get("set_id"),
        "label_ru": recipe.get("label_ru") or _component_label(components, "ru"),
        "label_en": recipe.get("label_en") or _component_label(components, "en"),
        "components": components,
        "target": target,
        "set_cost": sum(component["cost"] for component in components),
        "min_volume": execution.get("volume") or 0,
        "execution": execution,
        "risk_flags": execution.get("risk_flags") or [],
    }


def analyze_recipes(category: str, rows: list[dict[str, Any]], target: str, snapshot_ts: float | None = None) -> dict[str, Any]:
    by_id = _row_map(rows)
    recipes = KNOWN_STACK_RECIPES.get(category, [])
    entry_sets = ENTRY_SET_RECIPES.get(category, [])
    opportunities = [
        item
        for recipe in recipes
        for item in [_recipe_payload(recipe, by_id, target, snapshot_ts=snapshot_ts)]
        if item
    ]
    set_costs = [
        item
        for recipe in entry_sets
        for item in [_entry_set_payload(recipe, by_id, target, snapshot_ts=snapshot_ts)]
        if item
    ]
    missing = [
        {
            "source": recipe.get("source"),
            "result": recipe.get("result"),
            "input_count": recipe.get("input_count"),
            "inputs": recipe.get("inputs"),
        }
        for recipe in [*recipes, *entry_sets]
        if any(item["source"] not in by_id for item in _recipe_inputs(recipe))
        or (recipe.get("result") and recipe.get("result") not in by_id)
    ]
    priced_rows = [row for row in rows if number(row.get("median")) or number(row.get("best"))]
    filtered_opportunities = filter_dominated_emotion_paths(opportunities)
    return {
        "schema_version": "poe2-recipe-analysis/v1",
        "category": category,
        "target": target,
        "known_recipes": len(recipes),
        "known_sets": len(entry_sets),
        "opportunities": rank_opportunities(filtered_opportunities),
        "set_costs": sorted(set_costs, key=lambda item: (item["set_cost"], item["label_en"])),
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
