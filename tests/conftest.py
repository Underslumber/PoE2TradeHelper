import os
import sys
import tempfile
from pathlib import Path

# Изоляция действует до импорта app.config и создания глобального SQLite engine.
_test_workspace = tempfile.TemporaryDirectory(prefix="poe2-tests-", ignore_cleanup_errors=True)
_test_root = Path(_test_workspace.name)
(_test_root / "data").mkdir()
(_test_root / "storage").mkdir()
os.environ["PYTHON_DOTENV_DISABLED"] = "1"
os.environ["DATA_DIR"] = str(_test_root / "data")
os.environ["STORAGE_DIR"] = str(_test_root / "storage")
os.environ["SQLITE_PATH"] = str(_test_root / "data" / "test.sqlite")
for _flag in (
    "MARKET_SNAPSHOT_ENABLED", "FUNPAY_RUB_SNAPSHOT_ENABLED",
    "NOTIFICATION_WORKER_ENABLED", "MARKET_HISTORY_COMPACTION_ENABLED",
):
    os.environ[_flag] = "false"

os.environ["PUBLIC_CANONICAL_ORIGIN"] = "https://public.example.test:9443"
os.environ["PUBLIC_API_ORIGIN"] = "https://public.example.test"
os.environ.pop("PUBLIC_REDIRECT_HOSTS", None)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
