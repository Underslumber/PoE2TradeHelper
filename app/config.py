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
MARKET_SNAPSHOT_ENABLED: Final = os.environ.get("MARKET_SNAPSHOT_ENABLED", "true").lower() not in {"0", "false", "no", "off"}
MARKET_SNAPSHOT_LEAGUE: Final = os.environ.get("MARKET_SNAPSHOT_LEAGUE", "")
MARKET_SNAPSHOT_TARGET: Final = os.environ.get("MARKET_SNAPSHOT_TARGET", "exalted")
MARKET_SNAPSHOT_STATUS: Final = os.environ.get("MARKET_SNAPSHOT_STATUS", "any")
MARKET_SNAPSHOT_CATEGORIES: Final = os.environ.get("MARKET_SNAPSHOT_CATEGORIES", "")
MARKET_SNAPSHOT_CURRENCY_TARGETS: Final = os.environ.get("MARKET_SNAPSHOT_CURRENCY_TARGETS", "divine,chaos")
MARKET_SNAPSHOT_INTERVAL_MINUTES: Final = float(os.environ.get("MARKET_SNAPSHOT_INTERVAL_MINUTES", "15"))
MARKET_SNAPSHOT_EARLY_INTERVAL_MINUTES: Final = float(os.environ.get("MARKET_SNAPSHOT_EARLY_INTERVAL_MINUTES", "5"))
MARKET_SNAPSHOT_EARLY_DAYS: Final = float(os.environ.get("MARKET_SNAPSHOT_EARLY_DAYS", "2"))
MARKET_SNAPSHOT_LEAGUE_START: Final = os.environ.get("MARKET_SNAPSHOT_LEAGUE_START", "")
MARKET_SNAPSHOT_LEAGUE_CHECK_MINUTES: Final = float(os.environ.get("MARKET_SNAPSHOT_LEAGUE_CHECK_MINUTES", "10"))
MARKET_SNAPSHOT_PAUSE_SECONDS: Final = float(os.environ.get("MARKET_SNAPSHOT_PAUSE_SECONDS", "1"))
MARKET_SNAPSHOT_INCLUDE_UNSUPPORTED: Final = os.environ.get("MARKET_SNAPSHOT_INCLUDE_UNSUPPORTED", "true").lower() not in {
    "0",
    "false",
    "no",
    "off",
}
FUNPAY_RUB_SNAPSHOT_ENABLED: Final = os.environ.get("FUNPAY_RUB_SNAPSHOT_ENABLED", "true").lower() not in {
    "0",
    "false",
    "no",
    "off",
}
FUNPAY_RUB_SNAPSHOT_TARGET: Final = os.environ.get("FUNPAY_RUB_SNAPSHOT_TARGET", "divine")

for path in [DATA_DIR, STORAGE_DIR, RAW_DIR / "xhr", RAW_DIR / "html", RAW_DIR / "dom", ICONS_DIR]:
    path.mkdir(parents=True, exist_ok=True)
