import os
from pathlib import Path
from typing import Final

BASE_URL: Final = "https://poe.ninja"
DATA_DIR: Final = Path(os.environ.get("DATA_DIR", "data"))
STORAGE_DIR: Final = Path(os.environ.get("STORAGE_DIR", "storage"))
RAW_DIR: Final = STORAGE_DIR / "raw"
ICONS_DIR: Final = STORAGE_DIR / "icons"
SOURCE_MAP_PATH: Final = STORAGE_DIR / "source_map.json"
INDEX_MAP_PATH: Final = STORAGE_DIR / "index_map.json"
SQLITE_PATH: Final = Path(os.environ.get("SQLITE_PATH", str(DATA_DIR / "poe2_ninja.sqlite")))
USER_AGENT: Final = os.environ.get("USER_AGENT", "poe2-trade-helper/0.1 (contact: local)")
DEFAULT_RATE_LIMIT_DELAY: Final = 1.0
MAX_CONCURRENCY: Final = 3

for path in [DATA_DIR, STORAGE_DIR, RAW_DIR / "xhr", RAW_DIR / "html", RAW_DIR / "dom", ICONS_DIR]:
    path.mkdir(parents=True, exist_ok=True)
