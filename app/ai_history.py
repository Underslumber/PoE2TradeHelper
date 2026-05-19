from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.codex_market_analyzer import DEFAULT_ANALYSIS_DIR


def _safe_read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _analysis_summary(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    context = payload.get("context") if isinstance(payload.get("context"), dict) else {}
    assessment = payload.get("assessment") if isinstance(payload.get("assessment"), dict) else {}
    league = context.get("league") if isinstance(context.get("league"), dict) else {}
    category = ""
    summaries = context.get("category_summaries")
    if isinstance(summaries, list) and summaries and isinstance(summaries[0], dict):
        category = summaries[0].get("category") or ""
    currency = context.get("currency") if isinstance(context.get("currency"), dict) else {}
    if not category and currency:
        category = "Currency"
    summary = assessment.get("summary") if isinstance(assessment.get("summary"), dict) else {}
    signals = assessment.get("signals") if isinstance(assessment.get("signals"), list) else []
    return {
        "path": str(path),
        "file": path.name,
        "created_at": payload.get("created_at") or "",
        "league": league.get("id") or "",
        "category": category,
        "item": currency.get("id") or "",
        "target": (context.get("benchmarks") or {}).get("target_currency") or currency.get("target") or "",
        "market_read": summary.get("market_read") or "",
        "overall_risk": summary.get("overall_risk") or "",
        "data_quality": summary.get("data_quality") or "",
        "signals_count": len(signals),
        "signals": signals[:3],
    }


def list_ai_analyses(limit: int = 20, analysis_dir: Path | None = None) -> list[dict[str, Any]]:
    target_dir = Path(analysis_dir) if analysis_dir else DEFAULT_ANALYSIS_DIR
    if not target_dir.exists():
        return []
    items = []
    for path in sorted(target_dir.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
        payload = _safe_read_json(path)
        if payload:
            items.append(_analysis_summary(path, payload))
        if len(items) >= limit:
            break
    return items
