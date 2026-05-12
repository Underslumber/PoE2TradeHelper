import json

import app.trade2 as trade2
from app.trade2 import build_trade_advice, normalize_exchange_result, normalize_poe_ninja_overview, normalize_static_entries


def test_normalize_static_entries_skips_separators_and_expands_images():
    payload = {
        "result": [
            {
                "id": "Currency",
                "entries": [
                    {"id": "sep", "text": "Currency"},
                    {"id": "divine", "text": "Divine Orb", "image": "/image.png"},
                ],
            }
        ]
    }

    categories = normalize_static_entries(payload)

    assert categories["Currency"] == [
        {
            "id": "divine",
            "text": "Divine Orb",
            "text_ru": "Божественная сфера",
            "image": "https://www.pathofexile.com/image.png",
        }
    ]


def test_normalize_static_entries_prefers_official_russian_payload():
    payload = {
        "result": [
            {
                "id": "Currency",
                "entries": [
                    {"id": "transmute", "text": "Orb of Transmutation", "image": "/image.png"},
                ],
            }
        ]
    }
    localized_payload = {
        "result": [
            {
                "id": "Currency",
                "entries": [
                    {"id": "transmute", "text": "Сфера превращения"},
                ],
            }
        ]
    }

    categories = normalize_static_entries(payload, localized_payload)

    assert categories["Currency"][0]["text_ru"] == "Сфера превращения"


def test_normalize_exchange_result_flattens_offers():
    payload = {
        "id": "query123",
        "total": 1,
        "result": {
            "abc": {
                "listing": {
                    "indexed": "2026-05-12T10:00:00+00:00",
                    "account": {"name": "Seller#1234", "online": {"league": "Fate"}},
                    "offers": [
                        {
                            "exchange": {"currency": "exalted", "amount": 10},
                            "item": {"currency": "divine", "amount": 1, "stock": 4},
                        }
                    ],
                }
            }
        },
    }

    result = normalize_exchange_result(payload)

    assert result["query_id"] == "query123"
    assert result["total"] == 1
    assert result["rows"][0]["seller"] == "Seller#1234"
    assert result["rows"][0]["ratio"] == 0.1


def test_normalize_poe_ninja_overview_converts_primary_value_to_target():
    payload = {
        "core": {"primary": "divine", "rates": {"exalted": 175, "chaos": 30}},
        "lines": [
            {
                "id": "liquid-paranoia",
                "primaryValue": 0.02,
                "volumePrimaryValue": 4,
                "sparkline": {"totalChange": 12.5, "data": [1, 2, 3]},
            }
        ],
    }

    result = normalize_poe_ninja_overview(payload, "exalted")

    assert result["target_supported"] is True
    assert result["rows"][0]["id"] == "liquid-paranoia"
    assert result["rows"][0]["best"] == 3.5
    assert result["rows"][0]["median"] == 3.5
    assert result["rows"][0]["volume"] == 700
    assert result["rows"][0]["change"] == 12.5
    assert result["rows"][0]["sparkline"] == [175, 350, 525]


def test_build_trade_advice_marks_low_volume_emotion_upgrade():
    rows = [
        {
            "id": "diluted-liquid-ire",
            "text": "Diluted Liquid Ire",
            "text_ru": "Разбавленный жидкий гнев",
            "median": 1,
            "volume": 3,
        },
        {
            "id": "diluted-liquid-guilt",
            "text": "Diluted Liquid Guilt",
            "text_ru": "Разбавленная жидкая вина",
            "median": 4,
            "volume": 20,
        },
    ]

    advice = build_trade_advice("Delirium", rows, "divine")

    assert len(advice) == 1
    assert advice[0]["profit"] == 1
    assert advice[0]["margin"] == 1 / 3
    assert advice[0]["severity"] == "weak"
    assert advice[0]["min_volume"] == 3
    assert advice[0]["low_volume"] is True
    assert "Объем низкий" in advice[0]["message_ru"]


def test_build_trade_advice_classifies_signal_and_watch():
    rows = [
        {
            "id": "diluted-liquid-ire",
            "text": "Diluted Liquid Ire",
            "text_ru": "Разбавленный жидкий гнев",
            "median": 1,
            "volume": 30,
        },
        {
            "id": "diluted-liquid-guilt",
            "text": "Diluted Liquid Guilt",
            "text_ru": "Разбавленная жидкая вина",
            "median": 3.5,
            "volume": 30,
        },
        {
            "id": "diluted-liquid-greed",
            "text": "Diluted Liquid Greed",
            "text_ru": "Разбавленная жидкая жадность",
            "median": 9,
            "volume": 30,
        },
    ]

    advice = build_trade_advice("Delirium", rows, "divine")

    assert [item["severity"] for item in advice] == ["signal", "watch", "watch"]
    assert advice[0]["source"] == "diluted-liquid-ire"
    assert advice[0]["result"] == "diluted-liquid-guilt"
    assert advice[0]["path_steps"] == 1
    assert advice[0]["input_count"] == 3
    assert advice[0]["profit"] == 3.5 - 1 * 3
    assert "Объем достаточный" in advice[0]["message_ru"]


def test_build_trade_advice_finds_best_full_emotion_path():
    rows = [
        {
            "id": "diluted-liquid-ire",
            "text": "Diluted Liquid Ire",
            "text_ru": "Разбавленный жидкий гнев",
            "median": 1,
            "volume": 30,
        },
        {
            "id": "diluted-liquid-guilt",
            "text": "Diluted Liquid Guilt",
            "text_ru": "Разбавленная жидкая вина",
            "median": 4,
            "volume": 30,
        },
        {
            "id": "diluted-liquid-greed",
            "text": "Diluted Liquid Greed",
            "text_ru": "Разбавленная жидкая жадность",
            "median": 20,
            "volume": 30,
            "sparkline": [10, 15, 20],
        },
    ]

    advice = build_trade_advice("Delirium", rows, "divine")

    assert advice[0]["source"] == "diluted-liquid-ire"
    assert advice[0]["result"] == "diluted-liquid-greed"
    assert advice[0]["path_steps"] == 2
    assert advice[0]["input_count"] == 9
    assert advice[0]["profit"] == 11
    assert advice[0]["result_sparkline"] == [10, 15, 20]
    assert "9 x" in advice[0]["message_ru"]


def test_read_latest_rates_returns_newest_matching_snapshot(tmp_path, monkeypatch):
    history = tmp_path / "history.jsonl"
    snapshots = [
        {
            "created_ts": 1,
            "league": "Fate",
            "category": "Currency",
            "target": "divine",
            "status": "any",
            "source": "poe.ninja",
            "rows": [{"id": "exalted", "median": 0.01}],
        },
        {
            "created_ts": 2,
            "league": "Fate",
            "category": "Currency",
            "target": "divine",
            "status": "online",
            "source": "trade2",
            "rows": [{"id": "exalted", "median": 0.02}],
        },
    ]
    history.write_text("\n".join(json.dumps(item) for item in snapshots), encoding="utf-8")
    monkeypatch.setattr(trade2, "HISTORY_PATH", history)

    latest = trade2.read_latest_rates("Fate", "Currency", target="divine", status="online")

    assert latest["cached"] is True
    assert latest["created_ts"] == 2
    assert latest["source"] == "trade2"
    assert latest["rows"][0]["median"] == 0.02
