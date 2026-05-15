from __future__ import annotations

import json
import re
import subprocess
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import DATA_DIR

ASSESSMENT_SCHEMA_VERSION = "poe2-market-ai-assessment/v1"
DEFAULT_ANALYSIS_DIR = DATA_DIR / "ai_market_analyses"
ALLOWED_ACTIONS = {
    "buy_candidate",
    "sell_candidate",
    "hold",
    "watch",
    "avoid",
    "insufficient_data",
}
ALLOWED_CONFIDENCE = {"low", "medium", "high"}


def build_codex_market_prompt(context: dict[str, Any]) -> str:
    max_candidates = (context.get("request") or {}).get("max_candidates") or 10
    market_context_json = json.dumps(context, ensure_ascii=False, indent=2)
    return f"""Ты рыночный аналитик для Path of Exile 2.
Анализируй только JSON ниже: не выдумывай цены, объемы, патчноуты, популярность билдов или новости.
Не редактируй файлы и не запускай команды; используй только переданный market context.

Правила:
- Учитывай фазу лиги, ликвидность, listing_count, volume, source, freshness и risk_flags.
- Stackable-позиции можно оценивать по poe.ninja/trade2 агрегатам, если они есть.
- Если schema_version = poe2-currency-trend-context/v1, оценивай только переданные price_history, trend и forecast; forecast - модельный ориентир, а не факт.
- Rare/unique/equipment нельзя уверенно оценивать без сравнения похожих trade2 listings.
- Не превращай buy_candidate в автопокупку: это только кандидат для ручной проверки.
- Если данных мало, используй action=insufficient_data или action=watch и confidence=low.

Ответ верни строго JSON без Markdown по схеме:
{{
  "schema_version": "{ASSESSMENT_SCHEMA_VERSION}",
  "summary": {{
    "phase": "day_0_1|day_2_7|day_8_21|late_league|unknown",
    "market_read": "короткая русская сводка",
    "overall_risk": "low|medium|high",
    "data_quality": "full|partial|poor"
  }},
  "signals": [
    {{
      "item_id": "id",
      "item_name": "русское название или id",
      "category": "category",
      "action": "buy_candidate|sell_candidate|hold|watch|avoid|insufficient_data",
      "confidence": "low|medium|high",
      "time_horizon": "короткий горизонт",
      "thesis": "проверяемая гипотеза",
      "evidence": {{
        "price_action": "что видно по цене",
        "liquidity": "что видно по объему/листингам",
        "demand_driver": "известен или unknown",
        "benchmark_view": "что видно в валюте оценки"
      }},
      "risks": ["ключевые риски"],
      "suggested_checks": ["что проверить перед сделкой"],
      "invalidation": ["что ломает гипотезу"]
    }}
  ],
  "missing_data": ["каких метрик не хватает"],
  "do_not_trade": [
    {{"item_id": "id", "reason": "почему не трогать"}}
  ]
}}

Верни не больше {max_candidates} signals.

JSON market context:
{market_context_json}
"""


def _json_from_fenced_text(text: str) -> str:
    stripped = text.strip()
    match = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", stripped, flags=re.DOTALL | re.IGNORECASE)
    return match.group(1).strip() if match else stripped


def _extract_json_object(text: str) -> dict[str, Any]:
    candidate = _json_from_fenced_text(text)
    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError:
        payload = None
    if isinstance(payload, dict):
        return payload

    start = candidate.find("{")
    if start < 0:
        raise ValueError("Codex response does not contain a JSON object.")

    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(candidate)):
        char = candidate[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                payload = json.loads(candidate[start : index + 1])
                if not isinstance(payload, dict):
                    raise ValueError("Codex response JSON root is not an object.")
                return payload
    raise ValueError("Codex response contains an incomplete JSON object.")


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if item not in (None, "")]


def normalize_market_assessment(payload: dict[str, Any]) -> dict[str, Any]:
    raw_signals = payload.get("signals") if isinstance(payload.get("signals"), list) else []
    signals: list[dict[str, Any]] = []
    dropped = 0
    for item in raw_signals:
        if not isinstance(item, dict):
            dropped += 1
            continue
        action = item.get("action")
        confidence = item.get("confidence")
        if action not in ALLOWED_ACTIONS or confidence not in ALLOWED_CONFIDENCE:
            dropped += 1
            continue
        signals.append(item)

    do_not_trade = payload.get("do_not_trade") if isinstance(payload.get("do_not_trade"), list) else []
    return {
        "schema_version": ASSESSMENT_SCHEMA_VERSION,
        "summary": payload.get("summary") if isinstance(payload.get("summary"), dict) else {},
        "signals": signals,
        "missing_data": _string_list(payload.get("missing_data")),
        "do_not_trade": [item for item in do_not_trade if isinstance(item, dict)],
        "validation": {
            "input_schema_version": payload.get("schema_version"),
            "signals_total": len(raw_signals),
            "signals_kept": len(signals),
            "signals_dropped": dropped,
        },
    }


def parse_codex_market_assessment(response_text: str) -> dict[str, Any]:
    return normalize_market_assessment(_extract_json_object(response_text))


def _safe_slug(value: Any) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value or "").strip()).strip("-._")
    return slug[:80] or "market"


def _analysis_file_path(context: dict[str, Any], output_dir: Path) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    league = _safe_slug((context.get("league") or {}).get("id"))
    category = _safe_slug(((context.get("category_summaries") or [{}])[0] or {}).get("category"))
    target = _safe_slug((context.get("benchmarks") or {}).get("target_currency"))
    suffix = uuid.uuid4().hex[:8]
    return output_dir / f"{timestamp}-{league}-{category}-{target}-{suffix}.json"


def save_codex_market_analysis(
    *,
    context: dict[str, Any],
    prompt: str,
    raw_response: str,
    assessment: dict[str, Any],
    output_dir: Path | None = None,
) -> Path:
    target_dir = Path(output_dir) if output_dir else DEFAULT_ANALYSIS_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    path = _analysis_file_path(context, target_dir)
    payload = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "context": context,
        "prompt": prompt,
        "raw_response": raw_response,
        "assessment": assessment,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def call_codex_cli(
    prompt: str,
    *,
    codex_bin: str = "codex",
    model: str | None = None,
    timeout_seconds: int = 600,
    cwd: Path | str = ".",
    output_dir: Path | None = None,
) -> str:
    temp_dir = Path(output_dir) if output_dir else DEFAULT_ANALYSIS_DIR
    temp_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".txt", dir=temp_dir, delete=False) as handle:
        last_message_path = Path(handle.name)

    command = [
        codex_bin,
        "exec",
        "--sandbox",
        "read-only",
        "--ephemeral",
        "--color",
        "never",
        "--cd",
        str(Path(cwd).resolve()),
        "--output-last-message",
        str(last_message_path),
    ]
    if model:
        command.extend(["--model", model])
    command.append("-")

    try:
        result = subprocess.run(
            command,
            input=prompt,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
        )
        raw_response = last_message_path.read_text(encoding="utf-8").strip() if last_message_path.exists() else ""
    finally:
        last_message_path.unlink(missing_ok=True)

    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        stdout = (result.stdout or "").strip()
        detail = stderr or stdout or f"exit code {result.returncode}"
        raise RuntimeError(f"Codex CLI failed: {detail}")
    return raw_response or (result.stdout or "").strip()


def run_codex_market_analysis(
    context: dict[str, Any],
    *,
    codex_bin: str = "codex",
    model: str | None = None,
    timeout_seconds: int = 600,
    cwd: Path | str = ".",
    output_dir: Path | None = None,
    save: bool = True,
) -> dict[str, Any]:
    prompt = build_codex_market_prompt(context)
    raw_response = call_codex_cli(
        prompt,
        codex_bin=codex_bin,
        model=model,
        timeout_seconds=timeout_seconds,
        cwd=cwd,
        output_dir=output_dir,
    )
    assessment = parse_codex_market_assessment(raw_response)
    analysis_path = None
    if save:
        analysis_path = save_codex_market_analysis(
            context=context,
            prompt=prompt,
            raw_response=raw_response,
            assessment=assessment,
            output_dir=output_dir,
        )
    return {
        "assessment": assessment,
        "analysis_path": str(analysis_path) if analysis_path else None,
    }
