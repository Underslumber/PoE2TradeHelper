import json
import time
from typing import Any, Dict, Optional

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.db.models import CacheEntry
from app.db.session import get_session


class SQLiteCacheManager:
    """Manages ephemeral API responses caching in SQLite"""

    @staticmethod
    def get(key: str) -> Optional[Dict[str, Any]]:
        try:
            with get_session() as db:
                entry = db.scalar(select(CacheEntry).where(CacheEntry.key == key))
                if entry:
                    if time.time() > entry.expires_ts:
                        db.delete(entry)
                        db.commit()
                        return None
                    try:
                        return json.loads(entry.data_json)
                    except json.JSONDecodeError:
                        return None
        except SQLAlchemyError:
            return None
        return None

    @staticmethod
    def set(key: str, data: Dict[str, Any], ttl: int) -> None:
        created_ts = time.time()
        expires_ts = created_ts + ttl
        data_json = json.dumps(data, ensure_ascii=False)

        try:
            with get_session() as db:
                entry = db.scalar(select(CacheEntry).where(CacheEntry.key == key))
                if entry:
                    entry.data_json = data_json
                    entry.created_ts = created_ts
                    entry.expires_ts = expires_ts
                else:
                    db.add(CacheEntry(key=key, data_json=data_json, created_ts=created_ts, expires_ts=expires_ts))
                db.commit()
        except SQLAlchemyError:
            return

    @staticmethod
    def get_dict_key(*args) -> str:
        """Create a consistent string key from arguments"""
        return "|".join(str(arg).strip().lower() for arg in args if arg is not None)
