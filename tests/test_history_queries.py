import json
from contextlib import contextmanager

from sqlalchemy import create_engine, event, inspect
from sqlalchemy.orm import sessionmaker

from app.db.models import MarketHistory
from app.db import migrate as db_migrate
from app.history_compaction import _aggregate
from app.trade import history


@contextmanager
def _session_factory(engine):
    session = sessionmaker(bind=engine, expire_on_commit=False, future=True)()
    try:
        yield session
    finally:
        session.close()


def _record(
    ts,
    item_id,
    price,
    *,
    source="trade2",
    volume=1,
    league="Fate",
    category="ItemBases",
    granularity="raw",
    min_ilvl=None,
):
    return MarketHistory(
        league=league,
        category=category,
        target="exalted",
        status="securable",
        source=source,
        item_id=item_id,
        min_ilvl=min_ilvl,
        price=price,
        volume=volume,
        timestamp=ts,
        created_at=str(ts),
        granularity=granularity,
        samples=1,
    )


def _bind_database(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'history.sqlite'}", future=True)
    MarketHistory.__table__.create(engine)
    monkeypatch.setattr(history, "get_session", lambda: _session_factory(engine))
    return engine


def test_item_query_matches_limited_category_window_and_reads_only_target_rows(monkeypatch, tmp_path):
    engine = _bind_database(monkeypatch, tmp_path)
    with _session_factory(engine) as db:
        db.add_all(
            [
                _record(10, "Heavy Belt", 1, source="old"),
                _record(20, "Heavy Belt", 2),
                _record(20, "Other Base", 9),
                _record(30, "Other Base", 8),
                _record(40, "Other Base", 7),
            ]
        )
        db.commit()

    statements = []

    def capture(_conn, _cursor, statement, parameters, _context, _executemany):
        if "FROM market_history" in statement:
            statements.append((statement, parameters))

    event.listen(engine, "before_cursor_execute", capture)
    result = history.read_item_history(
        "Fate", "ItemBases", "exalted", "securable", "Heavy Belt", limit=3
    )
    event.remove(engine, "before_cursor_execute", capture)

    assert result == [
        {
            "created_ts": 20.0,
            "value": 2.0,
            "price": 2.0,
            "volume": 1,
            "offers": 0,
            "raw_count": None,
            "clean_count": None,
            "stale_count": None,
            "recent_listing_count": None,
            "high_demand": False,
            "recent_high_demand": None,
            "recent_high_demand_count": None,
            "recent_high_demand_age_seconds": None,
            "weak_activity": False,
            "change": None,
            "source": "trade2",
            "granularity": "raw",
        }
    ]
    target_queries = [(sql, params) for sql, params in statements if "item_id = ?" in sql]
    assert len(target_queries) == 1
    assert "Heavy Belt" in target_queries[0][1]
    assert len(result) == 1  # Метки 40 и 30 входят в окно категории, хотя у них нет этого предмета.
    assert history.read_item_history(
        "Fate", "ItemBases", "exalted", "securable", "Heavy Belt", limit=0
    ) == []


def test_duplicate_timestamps_keep_first_item_and_category_source(monkeypatch, tmp_path):
    engine = _bind_database(monkeypatch, tmp_path)
    with _session_factory(engine) as db:
        db.add_all(
            [
                _record(20, "Other Base", 90),
                _record(20, "Heavy Belt", 2),
                _record(20, "Heavy Belt", 3),
            ]
        )
        db.commit()

    result = history.read_item_history("Fate", "ItemBases", "exalted", "securable", "Heavy Belt")
    assert [(point["created_ts"], point["value"], point["source"]) for point in result] == [
        (20.0, 2.0, "trade2")
    ]


def test_readers_keep_source_and_granularity_separate_at_same_timestamp(monkeypatch, tmp_path):
    engine = _bind_database(monkeypatch, tmp_path)
    with _session_factory(engine) as db:
        db.add_all(
            [
                _record(20, "Heavy Belt", 2, source="poe.ninja", granularity="raw"),
                _record(20, "Heavy Belt", 3, source="trade2", granularity="raw"),
                _record(20, "Heavy Belt", 4, source="trade2", granularity="hourly"),
            ]
        )
        db.commit()

    snapshots = history.read_market_history(
        limit=1, league="Fate", category="ItemBases", target="exalted", status="securable"
    )
    series = history.read_item_history("Fate", "ItemBases", "exalted", "securable", "Heavy Belt", limit=1)

    assert {(item["source"], item["granularity"], item["rows"][0]["median"]) for item in snapshots} == {
        ("poe.ninja", "raw", 2.0),
        ("trade2", "raw", 3.0),
        ("trade2", "hourly", 4.0),
    }
    assert {(item["source"], item["granularity"], item["value"]) for item in series} == {
        ("poe.ninja", "raw", 2.0),
        ("trade2", "raw", 3.0),
        ("trade2", "hourly", 4.0),
    }


def test_missing_and_zero_item_values_do_not_fall_back_from_existing_sqlite_category(monkeypatch, tmp_path):
    engine = _bind_database(monkeypatch, tmp_path)
    with _session_factory(engine) as db:
        db.add(_record(10, "Heavy Belt", 2, volume=0))
        db.commit()

    jsonl = tmp_path / "trade_rate_history.jsonl"
    jsonl.write_text(
        json.dumps(
            {
                "created_ts": 10,
                "league": "Fate",
                "category": "ItemBases",
                "target": "exalted",
                "status": "securable",
                "rows": [{"id": "Heavy Belt", "median": 100, "volume": 10}],
            }
        ),
        encoding="utf-8",
    )
    # Явно переданный нестандартный путь JSONL сохраняет прежний приоритет.
    assert history.read_item_history(
        "Fate", "ItemBases", "exalted", "securable", "Heavy Belt", metric="demand", history_path=jsonl
    )[0]["value"] == 10
    monkeypatch.setattr(history, "DEFAULT_HISTORY_PATH", jsonl)

    assert history.read_item_history(
        "Fate", "ItemBases", "exalted", "securable", "Heavy Belt", metric="demand", history_path=jsonl
    ) == []
    assert history.read_item_history(
        "Fate", "ItemBases", "exalted", "securable", "Missing", history_path=jsonl
    ) == []


def test_absent_sqlite_category_uses_default_jsonl_fallback(monkeypatch, tmp_path):
    engine = _bind_database(monkeypatch, tmp_path)
    jsonl = tmp_path / "trade_rate_history.jsonl"
    jsonl.write_text(
        json.dumps(
            {
                "created_ts": 10,
                "league": "Fate",
                "category": "ItemBases",
                "target": "exalted",
                "status": "securable",
                "source": "legacy-jsonl",
                "rows": [{"id": "Heavy Belt", "median": 2, "volume": 5}],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(history, "DEFAULT_HISTORY_PATH", jsonl)

    result = history.read_item_history(
        "Fate", "ItemBases", "exalted", "securable", "Heavy Belt", history_path=jsonl
    )
    assert [(point["value"], point["source"]) for point in result] == [(2, "legacy-jsonl")]


def test_market_history_indexes_are_migrated_after_columns_and_idempotently(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.sqlite'}", future=True)
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE market_history (id INTEGER PRIMARY KEY, league VARCHAR NOT NULL, "
            "category VARCHAR NOT NULL, target VARCHAR NOT NULL, item_id VARCHAR NOT NULL, "
            "timestamp FLOAT NOT NULL)"
        )
    monkeypatch.setattr(db_migrate, "engine", engine)

    db_migrate._migrate_market_history_table()
    first_columns = {column["name"] for column in inspect(engine).get_columns("market_history")}
    first_indexes = {index["name"] for index in inspect(engine).get_indexes("market_history")}
    db_migrate._migrate_market_history_table()
    second_indexes = {index["name"] for index in inspect(engine).get_indexes("market_history")}

    assert {"status", "granularity", "samples", "min_ilvl"}.issubset(first_columns)
    assert {
        "ix_market_history_scope_timestamp",
        "ix_market_history_scope_item_timestamp",
    }.issubset(first_indexes)
    assert second_indexes == first_indexes


def test_item_base_history_roundtrip_preserves_known_min_ilvl_and_unknown_remains_unknown(monkeypatch, tmp_path):
    engine = _bind_database(monkeypatch, tmp_path)
    history.log_market_history(
        {
            "created_ts": 10,
            "league": "Fate",
            "category": "ItemBases",
            "target": "exalted",
            "status": "securable",
            "source": "trade2/search+fetch:rough",
            "rows": [
                {"id": "known", "min_ilvl": 78, "median": 2},
                {"id": "legacy", "median": 3},
            ],
        }
    )

    snapshots = history.read_market_history(
        limit=1, league="Fate", category="ItemBases", target="exalted", status="securable"
    )
    by_id = {row["id"]: row for row in snapshots[0]["rows"]}

    assert by_id["known"]["min_ilvl"] == 78
    assert by_id["legacy"]["min_ilvl"] is None


def test_compaction_keeps_minimum_known_ilvl_and_drops_unknown_proof():
    known = [_record(1, "known", 2, min_ilvl=78), _record(2, "known", 3, min_ilvl=82)]
    unknown = [_record(1, "unknown", 2, min_ilvl=78), _record(2, "unknown", 3)]

    assert _aggregate(known, "hourly").min_ilvl == 78
    assert _aggregate(unknown, "hourly").min_ilvl is None
