from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError(f"expected one match: {old[:80]!r}")
    return text.replace(old, new, 1)


def replace_in_test(text, name, old, new):
    start = text.index(f"def {name}(")
    end = text.find("\ndef ", start + 5)
    if end < 0:
        end = len(text)
    section = text[start:end]
    if old not in section:
        raise RuntimeError(f"target not found in {name}")
    return text[:start] + section.replace(old, new) + text[end:]


path = ROOT / "tests/test_trade2.py"
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    'assert query["filters"]["type_filters"]["filters"]["ilvl"] == {"min": 70}',
    'assert query["filters"]["type_filters"]["filters"]["ilvl"] == {"min": 78}',
)
text = text.replace(
    '("PoE2 - Test", "exalted", "any", "", trade2.ITEM_BASE_MARKET_MAX_BASES, None)',
    '("PoE2 - Test", "exalted", "any", "", trade2.ITEM_BASE_MARKET_MAX_BASES, 78)',
)
text = text.replace(
    '("PoE2 - Test", "exalted", "securable", "", trade2.ITEM_BASE_MARKET_MAX_BASES, None)',
    '("PoE2 - Test", "exalted", "securable", "", trade2.ITEM_BASE_MARKET_MAX_BASES, 78)',
)
text = text.replace(
    '_item_base_market_job_key("PoE2 - Test", "exalted", "securable", "", None, 100)',
    '_item_base_market_job_key("PoE2 - Test", "exalted", "securable", "", 78, 100)',
)
text = replace_in_test(
    text,
    "test_item_base_market_min_ilvl_filters_cached_sample_lots",
    '("PoE2 - Test", "exalted", "any", "", trade2.ITEM_BASE_MARKET_MAX_BASES, 78)',
    '("PoE2 - Test", "exalted", "any", "", trade2.ITEM_BASE_MARKET_MAX_BASES, 82)',
)
text = replace_in_test(
    text,
    "test_item_base_market_refresh_restarts_stale_running_job",
    '_item_base_market_job_key("PoE2 - Test", "exalted", "securable", "", 78, 100)',
    '_item_base_market_job_key("PoE2 - Test", "exalted", "securable", "", 82, 100)',
)
for old, new in {
    '"text_ru": "Дешевая основа",': '"text_ru": "Дешевая основа",\n                    "min_ilvl": 78,',
    '"text_ru": "Дорогая основа",': '"text_ru": "Дорогая основа",\n                    "min_ilvl": 78,',
    '"text_ru": "Ниже порога",': '"text_ru": "Ниже порога",\n                    "min_ilvl": 78,',
    '"text_ru": "Выше порога",': '"text_ru": "Выше порога",\n                    "min_ilvl": 78,',
    '"text_ru": "Тонкая цена",': '"text_ru": "Тонкая цена",\n                    "min_ilvl": 78,',
    '"text_ru": "Подтвержденная цена",': '"text_ru": "Подтвержденная цена",\n                    "min_ilvl": 78,',
    '"text_ru": "Шелковая роба",': '"text_ru": "Шелковая роба",\n                    "min_ilvl": 78,',
}.items():
    text = replace_once(text, old, new)
text = replace_once(
    text,
    '{"id": "base:empty", "text_ru": "Пустая основа"}',
    '{"id": "base:empty", "text_ru": "Пустая основа", "min_ilvl": 78}',
)
text = replace_once(
    text,
    '{"id": "base:ghost", "text_ru": "Пустая цена", "low": 12.0, "offers": 0}',
    '{"id": "base:ghost", "text_ru": "Пустая цена", "min_ilvl": 78, "low": 12.0, "offers": 0}',
)
text = replace_in_test(
    text,
    "test_item_base_market_text_filter_can_use_cached_overview",
    '"text_ru": "Жемчужное кольцо",',
    '"text_ru": "Жемчужное кольцо",\n                    "min_ilvl": 78,',
)
text = replace_once(text, '"item_level": 12', '"item_level": 82')
text = replace_once(
    text,
    'assert result["rows"][0]["min_ilvl"] == 1',
    'assert result["rows"][0]["min_ilvl"] == 78',
)
text = replace_in_test(
    text,
    "test_item_base_market_running_partial_job_falls_back_to_stored_snapshot",
    '{"id": "base:amber-amulet", "best": 2.0, "offers": 2, "volume": 2}',
    '{"id": "base:amber-amulet", "best": 2.0, "offers": 2, "volume": 2, "min_ilvl": 78}',
)
text = replace_in_test(
    text,
    "test_item_base_market_running_partial_job_falls_back_to_stored_snapshot",
    '{"id": "base:pearl-ring", "best": 3.0, "offers": 3, "volume": 3}',
    '{"id": "base:pearl-ring", "best": 3.0, "offers": 3, "volume": 3, "min_ilvl": 78}',
)
path.write_text(text, encoding="utf-8")

path = ROOT / "tests/test_trade_routes.py"
text = path.read_text(encoding="utf-8")
text = replace_in_test(
    text,
    "test_item_base_market_refresh_starts_background_job",
    'assert kwargs["min_ilvl"] is None',
    'assert kwargs["min_ilvl"] == 82',
)
text = replace_in_test(
    text,
    "test_item_base_market_blank_refresh_starts_background_scan",
    'assert kwargs["min_ilvl"] is None',
    'assert kwargs["min_ilvl"] == 82',
)
path.write_text(text, encoding="utf-8")

path = ROOT / "app/web/routes.py"
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    "    ITEM_BASE_MARKET_DEFAULT_STATUS,\n",
    "    ITEM_BASE_MARKET_DEFAULT_STATUS,\n    ITEM_BASE_MARKET_MIN_ILVL,\n",
)
text = replace_once(
    text,
    "    min_ilvl: int | None = Query(None, ge=1, le=100),\n",
    "    min_ilvl: int = Query(ITEM_BASE_MARKET_MIN_ILVL, ge=ITEM_BASE_MARKET_MIN_ILVL, le=100),\n",
)
text = replace_once(text, "                min_ilvl=None,\n", "                min_ilvl=min_ilvl,\n")
path.write_text(text, encoding="utf-8")
