import json

from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker

from app.db.models import Base, MarketHistory
from app.db import migrate_jsonl_to_sqlite


def test_migrate_history_is_idempotent_on_temp_sqlite(tmp_path, monkeypatch):
    history_path = tmp_path / "trade_rate_history.jsonl"
    history_path.write_text(
        json.dumps(
            {
                "created_ts": 1000,
                "league": "Fate",
                "category": "Currency",
                "target": "exalted",
                "status": "any",
                "source": "poe.ninja",
                "rows": [
                    {"id": "chaos", "median": 4, "volume": 100, "offers": 0},
                    {"id": "divine", "best": 180, "volume": 20, "offers": 0},
                ],
            }
        ),
        encoding="utf-8",
    )
    engine = create_engine(f"sqlite:///{tmp_path / 'test.sqlite'}", future=True)
    Base.metadata.create_all(bind=engine)
    session_local = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)

    def get_test_session():
        return session_local()

    monkeypatch.setattr(migrate_jsonl_to_sqlite, "DATA_DIR", tmp_path)
    monkeypatch.setattr(migrate_jsonl_to_sqlite, "get_session", get_test_session)

    migrate_jsonl_to_sqlite.migrate_history(verbose=False)
    migrate_jsonl_to_sqlite.migrate_history(verbose=False)

    with get_test_session() as db:
        assert db.scalar(func.count(MarketHistory.id)) == 2
        rows = {row.item_id: row for row in db.query(MarketHistory).all()}
        assert rows["chaos"].source == "poe.ninja"
        assert rows["chaos"].price == 4
        assert rows["divine"].price == 180
