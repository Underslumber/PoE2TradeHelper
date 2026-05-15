import json

import app.codex_market_analyzer as analyzer


def _context():
    return {
        "schema_version": "poe2-market-ai-context/v1",
        "league": {"id": "Fate of the Vaal", "day": 1, "phase": "day_0_1"},
        "benchmarks": {"target_currency": "exalted"},
        "category_summaries": [{"category": "Currency"}],
        "market_rows": [
            {
                "id": "divine",
                "name_ru": "Божественная сфера",
                "category": "Currency",
                "source": "poe.ninja",
                "target": "exalted",
                "best": 55,
                "volume": 120,
            }
        ],
        "request": {"max_candidates": 3, "language": "ru"},
    }


def test_build_codex_market_prompt_embeds_context_json():
    prompt = analyzer.build_codex_market_prompt(_context())

    assert "Ответ верни строго JSON" in prompt
    assert '"schema_version": "poe2-market-ai-context/v1"' in prompt
    assert "Верни не больше 3 signals" in prompt
    assert "Божественная сфера" in prompt


def test_parse_codex_market_assessment_filters_unknown_signal_values():
    response = {
        "schema_version": "poe2-market-ai-assessment/v1",
        "summary": {"market_read": "partial"},
        "signals": [
            {"item_id": "divine", "action": "watch", "confidence": "low"},
            {"item_id": "fake", "action": "buy_now", "confidence": "high"},
            {"item_id": "thin", "action": "avoid", "confidence": "certain"},
        ],
        "missing_data": ["spread_percent"],
        "do_not_trade": [{"item_id": "fake", "reason": "single listing"}],
    }

    payload = analyzer.parse_codex_market_assessment(f"```json\n{json.dumps(response)}\n```")

    assert payload["schema_version"] == "poe2-market-ai-assessment/v1"
    assert payload["signals"] == [{"item_id": "divine", "action": "watch", "confidence": "low"}]
    assert payload["validation"]["signals_total"] == 3
    assert payload["validation"]["signals_dropped"] == 2
    assert payload["missing_data"] == ["spread_percent"]


def test_run_codex_market_analysis_normalizes_without_saving(monkeypatch):
    def fake_call_codex_cli(prompt, **kwargs):
        assert "Fate of the Vaal" in prompt
        return json.dumps(
            {
                "schema_version": "poe2-market-ai-assessment/v1",
                "summary": {"phase": "day_0_1"},
                "signals": [{"item_id": "divine", "action": "watch", "confidence": "medium"}],
            }
        )

    monkeypatch.setattr(analyzer, "call_codex_cli", fake_call_codex_cli)

    result = analyzer.run_codex_market_analysis(_context(), save=False)

    assert result["analysis_path"] is None
    assert result["assessment"]["signals"][0]["confidence"] == "medium"
