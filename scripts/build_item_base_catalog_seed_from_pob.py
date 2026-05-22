from __future__ import annotations

import argparse
import asyncio
import json
import re
import time
from pathlib import Path
from typing import Any

import httpx
from bs4 import BeautifulSoup

SCHEMA_VERSION = "poe2-item-base-catalog/v1"
DEFAULT_POB_ROOT = Path(r"D:\Soft\PathOfBuilding-PoE2")
DEFAULT_OUTPUT = Path("app/resources/item_base_catalog_seed.json")
DEFAULT_RUNTIME_OUTPUT = Path("data/item_base_catalog.json")
POE2DB_RU_BASE = "https://poe2db.tw/ru"
USER_AGENT = "PoE2TradeHelper item-base seed builder"

ALLOWED_BASE_FILES = {
    "amulet",
    "axe",
    "belt",
    "body",
    "boots",
    "bow",
    "claw",
    "crossbow",
    "dagger",
    "flail",
    "focus",
    "gloves",
    "helmet",
    "mace",
    "quiver",
    "ring",
    "sceptre",
    "shield",
    "spear",
    "staff",
    "sword",
    "talisman",
    "wand",
}
ACCESSORY_FILES = {"amulet", "belt", "ring", "talisman"}
ARMOUR_FILES = {"body", "boots", "focus", "gloves", "helmet", "quiver", "shield"}
WEAPON_FILES = ALLOWED_BASE_FILES - ACCESSORY_FILES - ARMOUR_FILES
ENTRY_RE = re.compile(r'itemBases\["((?:\\.|[^"])*)"\]\s*=\s*\{(.*?)\n\}', re.S)
BASE_CLASS_LABELS = {
    "amulet": ("Amulets", "Амулеты"),
    "axe": ("Axes", "Топоры"),
    "belt": ("Belts", "Пояса"),
    "body": ("Body Armours", "Нательная броня"),
    "boots": ("Boots", "Обувь"),
    "bow": ("Bows", "Луки"),
    "claw": ("Claws", "Когти"),
    "crossbow": ("Crossbows", "Арбалеты"),
    "dagger": ("Daggers", "Кинжалы"),
    "flail": ("Flails", "Цепы"),
    "focus": ("Foci", "Фокусы"),
    "gloves": ("Gloves", "Перчатки"),
    "helmet": ("Helmets", "Шлемы"),
    "mace": ("Maces", "Булавы"),
    "quiver": ("Quivers", "Колчаны"),
    "ring": ("Rings", "Кольца"),
    "sceptre": ("Sceptres", "Скипетры"),
    "shield": ("Shields", "Щиты"),
    "spear": ("Spears", "Копья"),
    "staff": ("Staves", "Посохи"),
    "sword": ("Swords", "Мечи"),
    "talisman": ("Talismans", "Талисманы"),
    "wand": ("Wands", "Жезлы"),
}


def _clean_lua_string(value: str) -> str:
    return value.replace(r"\"", '"').replace(r"\\", "\\")


def _base_market_item_id(value: str) -> str:
    text = value.strip().lower()
    text = re.sub(r"[^0-9a-zа-яё]+", "-", text, flags=re.IGNORECASE)
    return f"base:{text.strip('-') or 'unknown'}"


def _generated_icon_url(icon_key: str) -> str:
    safe_key = re.sub(r"[^a-z0-9_-]+", "-", icon_key.lower()).strip("-") or "base"
    return f"/icons/item-bases/generated/{safe_key}.svg"


def _poe2db_slug(base_type: str) -> str:
    return re.sub(r"[^0-9A-Za-z]+", "_", base_type).strip("_")


def _category_for_file(file_stem: str) -> dict[str, str]:
    class_label, class_label_ru = BASE_CLASS_LABELS.get(file_stem, ("Item Bases", "Основы"))
    if file_stem in ACCESSORY_FILES:
        return {
            "category": "accessory",
            "category_label": "Accessories",
            "category_label_ru": "Бижутерия",
            "base_class": file_stem,
            "base_class_label": class_label,
            "base_class_label_ru": class_label_ru,
        }
    if file_stem in ARMOUR_FILES:
        return {
            "category": "armour",
            "category_label": "Armour",
            "category_label_ru": "Броня",
            "base_class": file_stem,
            "base_class_label": class_label,
            "base_class_label_ru": class_label_ru,
        }
    if file_stem in WEAPON_FILES:
        return {
            "category": "weapon",
            "category_label": "Weapons",
            "category_label_ru": "Оружие",
            "base_class": file_stem,
            "base_class_label": class_label,
            "base_class_label_ru": class_label_ru,
        }
    return {
        "category": "base",
        "category_label": "Item Bases",
        "category_label_ru": "Основы",
        "base_class": file_stem,
        "base_class_label": class_label,
        "base_class_label_ru": class_label_ru,
    }


def _icon_key_for_file(file_stem: str, base_type: str) -> str:
    value = base_type.lower()
    if file_stem in {"ring", "amulet", "belt", "boots", "helmet", "focus", "shield", "bow", "crossbow", "sceptre", "wand"}:
        return file_stem
    if file_stem == "body":
        return "robe" if "robe" in value or "raiment" in value or "garb" in value or "vestment" in value else "armour"
    if file_stem == "staff":
        return "staff"
    return "base"


def _read_previous_seed(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return {
        str(base.get("type")): base
        for base in payload.get("bases", [])
        if isinstance(base, dict) and base.get("type")
    }


def _parse_pob_bases(pob_root: Path) -> list[dict[str, Any]]:
    bases_dir = pob_root / "Data" / "Bases"
    if not bases_dir.exists():
        raise SystemExit(f"PoB bases directory not found: {bases_dir}")

    bases: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in sorted(bases_dir.glob("*.lua")):
        file_stem = path.stem
        if file_stem not in ALLOWED_BASE_FILES:
            continue
        text = path.read_text(encoding="utf-8")
        for match in ENTRY_RE.finditer(text):
            base_type = _clean_lua_string(match.group(1))
            body = match.group(2)
            lowered = f"{base_type} {body}".lower()
            if base_type in seen:
                continue
            if "[dnt" in lowered or "unused" in lowered:
                continue
            if re.search(r"not_for_sale\s*=\s*true", body):
                continue
            if re.search(r"hidden\s*=\s*true", body):
                continue
            if "(" in base_type or ")" in base_type:
                continue
            if not re.search(r"default\s*=\s*true", body):
                continue
            seen.add(base_type)
            req_match = re.search(r"req\s*=\s*\{[^}]*level\s*=\s*(\d+)", body)
            bases.append(
                {
                    "type": base_type,
                    "pob_file": file_stem,
                    "required_level": int(req_match.group(1)) if req_match else None,
                }
            )
    return bases


async def _fetch_poe2db_title(client: httpx.AsyncClient, base_type: str) -> str | None:
    response = await client.get(f"{POE2DB_RU_BASE}/{_poe2db_slug(base_type)}")
    if response.status_code != 200:
        return None
    soup = BeautifulSoup(response.text, "html.parser")
    title = soup.select_one("title")
    if not title:
        return None
    text = title.get_text(" ", strip=True).split(" - PoE2DB", 1)[0].strip()
    return text or None


async def _load_poe2db_translations(bases: list[dict[str, Any]], concurrency: int) -> dict[str, str]:
    semaphore = asyncio.Semaphore(concurrency)
    translations: dict[str, str] = {}
    async with httpx.AsyncClient(
        timeout=30,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    ) as client:

        async def fetch(base_type: str) -> None:
            async with semaphore:
                text = await _fetch_poe2db_title(client, base_type)
            if text:
                translations[base_type] = text

        await asyncio.gather(*(fetch(str(base["type"])) for base in bases))
    return translations


def _local_icon_from_previous(previous: dict[str, Any] | None) -> str:
    image = str((previous or {}).get("image") or "")
    if image.startswith("/icons/item-bases/generated/"):
        return ""
    if image.startswith(("/icons/item-bases/", "/static/item-base-icons/")):
        return image
    return ""


def _build_catalog(
    bases: list[dict[str, Any]],
    translations: dict[str, str],
    previous_by_type: dict[str, dict[str, Any]],
    *,
    allow_missing_translations: bool,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    missing: list[str] = []
    for base in bases:
        base_type = str(base["type"])
        file_stem = str(base["pob_file"])
        previous = previous_by_type.get(base_type)
        type_ru = translations.get(base_type) or str((previous or {}).get("type_ru") or "")
        if not type_ru:
            missing.append(base_type)
            if not allow_missing_translations:
                continue
            type_ru = base_type
        icon_key = _icon_key_for_file(file_stem, base_type)
        image = _local_icon_from_previous(previous) or _generated_icon_url(icon_key)
        rows.append(
            {
                "id": _base_market_item_id(base_type),
                "type": base_type,
                "type_ru": type_ru,
                "query_type": type_ru,
                **_category_for_file(file_stem),
                "icon_key": icon_key,
                "image": image,
            }
        )
    if missing and not allow_missing_translations:
        joined = ", ".join(missing[:20])
        raise SystemExit(f"Missing Russian names for {len(missing)} PoB bases: {joined}")
    rows.sort(key=lambda item: (str(item["category_label_ru"]), str(item["type_ru"]), str(item["type"])))
    return {
        "schema_version": SCHEMA_VERSION,
        "created_ts": time.time(),
        "source": "PathOfBuilding-PoE2/Data/Bases+poe2db/ru",
        "total": len(rows),
        "bases": rows,
        "errors": [],
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build ItemBases seed catalog from Path of Building PoE2 bases.")
    parser.add_argument("--pob-root", type=Path, default=DEFAULT_POB_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--runtime-output", type=Path, default=DEFAULT_RUNTIME_OUTPUT)
    parser.add_argument("--no-runtime-output", action="store_true")
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--allow-missing-translations", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    bases = _parse_pob_bases(args.pob_root)
    translations = asyncio.run(_load_poe2db_translations(bases, max(1, args.concurrency)))
    previous = _read_previous_seed(args.output)
    payload = _build_catalog(
        bases,
        translations,
        previous,
        allow_missing_translations=args.allow_missing_translations,
    )
    _write_json(args.output, payload)
    if not args.no_runtime_output:
        _write_json(args.runtime_output, payload)
    print(
        json.dumps(
            {
                "source": payload["source"],
                "total": payload["total"],
                "output": str(args.output),
                "runtime_output": None if args.no_runtime_output else str(args.runtime_output),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
