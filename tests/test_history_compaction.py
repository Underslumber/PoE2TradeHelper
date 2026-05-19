from __future__ import annotations

from app.db.models import Base, MarketHistory
from app.history_compaction import HOURLY_GRANULARITY, RAW_GRANULARITY, CompactionPolicy, compact_market_history


def test_compact_market_history_writes_hourly_aggregates(tmp_path, monkeypatch):
    sqlite_path = tmp_path / "history.sqlite"
    monkeypatch.setenv("SQLITE_PATH", str(sqlite_path))

    from app.db import session as session_module
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(f"sqlite:///{sqlite_path}", connect_args={"check_same_thread": False})
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    monkeypatch.setattr(session_module, "engine", engine)
    monkeypatch.setattr(session_module, "SessionLocal", SessionLocal)
    import app.history_compaction as compaction_module

    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(compaction_module, "get_session", session_module.get_session)

    with session_module.get_session() as db:
        db.add_all(
            [
                MarketHistory(
                    league="Fate",
                    category="Currency",
                    target="exalted",
                    status="any",
                    item_id="divine",
                    price=100,
                    volume=10,
                    timestamp=1000,
                    created_at="1970-01-01T00:16:40+00:00",
                    granularity=RAW_GRANULARITY,
                    samples=1,
                ),
                MarketHistory(
                    league="Fate",
                    category="Currency",
                    target="exalted",
                    status="any",
                    item_id="divine",
                    price=120,
                    volume=20,
                    timestamp=1200,
                    created_at="1970-01-01T00:20:00+00:00",
                    granularity=RAW_GRANULARITY,
                    samples=1,
                ),
            ]
        )
        db.commit()

    summary = compact_market_history(CompactionPolicy(raw_days=7, hourly_days=30), now_ts=10 * 86400)

    with session_module.get_session() as db:
        rows = db.query(MarketHistory).all()

    assert summary["hourly_written"] == 1
    assert len(rows) == 1
    assert rows[0].granularity == HOURLY_GRANULARITY
    assert rows[0].price == 110
    assert rows[0].samples == 2

    with session_module.get_session() as db:
        db.add(
            MarketHistory(
                league="Fate",
                category="Currency",
                target="exalted",
                status="any",
                item_id="divine",
                price=140,
                volume=30,
                timestamp=1300,
                created_at="1970-01-01T00:21:40+00:00",
                granularity=RAW_GRANULARITY,
                samples=1,
            )
        )
        db.commit()

    compact_market_history(CompactionPolicy(raw_days=7, hourly_days=30), now_ts=10 * 86400)

    with session_module.get_session() as db:
        rows = db.query(MarketHistory).all()

    assert len(rows) == 1
    assert rows[0].granularity == HOURLY_GRANULARITY
    assert rows[0].price == 120
    assert rows[0].volume == 20
    assert rows[0].samples == 3
