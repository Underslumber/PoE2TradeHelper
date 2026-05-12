import json

from app.collector.parse import build_row_id, extract_rows, normalize_row


def test_extract_rows_prefers_lines():
    payload = {"lines": [{"name": "Rune"}], "entries": []}
    rows = extract_rows(payload)
    assert rows == payload["lines"]


def test_extract_rows_uses_path():
    payload = {"items": [{"name": "Orb"}]}
    rows = extract_rows(payload, json_path="items")
    assert rows == payload["items"]


def test_build_row_id_stable():
    rid1 = build_row_id("vaal", "runes", {"name": "Rune"})
    rid2 = build_row_id("vaal", "runes", {"name": "Rune"})
    assert rid1 == rid2


def test_normalize_row_keeps_raw():
    row = {"name": "Orb", "icon": "http://example/icon.png", "value": 3}
    normalized = normalize_row(row)
    assert normalized["name"] == "Orb"
    assert normalized["columns"]["value"] == 3
    assert normalized["raw"] == row
