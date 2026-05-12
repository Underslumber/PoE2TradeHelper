from app.trade2 import normalize_exchange_result, normalize_poe_ninja_overview, normalize_static_entries


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
