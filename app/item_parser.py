from __future__ import annotations

import re
from typing import Any

RARITY_RE = re.compile(r"^(?:Rarity|Редкость):\s*(.+)$", re.IGNORECASE)
ILVL_RE = re.compile(r"^(?:Item Level|Уровень предмета):\s*(\d+)", re.IGNORECASE)
SECTION_RE = re.compile(r"^-{2,}$")
NUMERIC_RE = re.compile(r"[+-]?\d+(?:[.,]\d+)?")


def _clean_line(line: str) -> str:
    return line.strip().replace("\u00a0", " ")


def normalize_mod_text(value: str) -> str:
    text = NUMERIC_RE.sub("#", value.lower())
    text = re.sub(r"\s+", " ", text)
    return text.strip(" .;:,")


def parse_item_text(text: str) -> dict[str, Any]:
    lines = [_clean_line(line) for line in str(text or "").splitlines()]
    lines = [line for line in lines if line]
    sections: list[list[str]] = [[]]
    for line in lines:
        if SECTION_RE.match(line):
            if sections[-1]:
                sections.append([])
            continue
        sections[-1].append(line)
    sections = [section for section in sections if section]

    rarity = ""
    item_level: int | None = None
    header: list[str] = []
    mods: list[str] = []
    for section_index, section in enumerate(sections):
        for line in section:
            rarity_match = RARITY_RE.match(line)
            if rarity_match:
                rarity = rarity_match.group(1).strip()
                continue
            ilvl_match = ILVL_RE.match(line)
            if ilvl_match:
                item_level = int(ilvl_match.group(1))
                continue
            if section_index <= 1 and not header and not line.lower().startswith(("requirements", "требуется")):
                header.append(line)
            elif section_index <= 1 and len(header) < 2 and not any(token in line for token in (":", "+")):
                header.append(line)
            elif not line.lower().startswith(("requirements", "требуется", "sockets", "гнезд")):
                mods.append(line)

    name = header[0] if header else ""
    type_line = header[1] if len(header) > 1 else ""
    normalized_mods = [normalize_mod_text(mod) for mod in mods if normalize_mod_text(mod)]
    return {
        "schema_version": "poe2-pasted-item/v1",
        "name": name,
        "type_line": type_line,
        "display_name": " ".join(part for part in (name, type_line) if part) or (lines[0] if lines else ""),
        "rarity": rarity,
        "item_level": item_level,
        "mods": mods,
        "normalized_mods": normalized_mods,
        "mod_count": len(normalized_mods),
        "raw_line_count": len(lines),
        "pricing_hint": pricing_hint(rarity, item_level, normalized_mods),
    }


def pricing_hint(rarity: str, item_level: int | None, normalized_mods: list[str]) -> dict[str, Any]:
    rarity_lower = rarity.lower()
    if "unique" in rarity_lower or "уник" in rarity_lower:
        mode = "unique_name_market"
        confidence = "medium"
    elif normalized_mods:
        mode = "rare_stat_similarity"
        confidence = "low" if len(normalized_mods) < 3 else "medium"
    else:
        mode = "base_type_only"
        confidence = "low"
    return {
        "mode": mode,
        "confidence": confidence,
        "needs_trade2_comparison": True,
        "notes": [
            "Parser normalizes visible pasted text; official stat ids are available only from fetched listings.",
            "Rare pricing should compare base type, item level, rarity and overlapping normalized affixes.",
        ],
        "item_level": item_level,
    }
