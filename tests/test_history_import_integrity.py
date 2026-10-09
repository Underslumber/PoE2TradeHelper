import json

from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker

from app.db.models import Base, CacheEntry, MarketHistory
from app.db import migrate_jsonl_to_sqlite


def _prepare_import_db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'history-import.sqlite'}", future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    monkeypatch.setattr(migrate_jsonl_to_sqlite, "get_session", session_factory)
    monkeypatch.setattr(migrate_jsonl_to_sqlite, "DATA_DIR", tmp_path)
    return engine, session_factory


def _snapshot(ts, source, rows, *, league="Fate"):
    return {
        "created_ts": ts,
        "league": league,
        "category": "ItemBases",
        "target": "exalted",
        "status": "securable",
        "source": source,
        "rows": rows,
    }


def _write_jsonl(path, snapshots):
    path.write_text("\n".join(json.dumps(item, allow_nan=True) for item in snapshots) + "\n", encoding="utf-8")


def test_import_sanitizes_nonfinite_values_and_keeps_fractional_volume(tmp_path, monkeypatch):
    engine, session_factory = _prepare_import_db(tmp_path, monkeypatch)
    _write_jsonl(
        tmp_path / "trade_rate_history.jsonl",
        [
            _snapshot(
                1000,
                "poe.ninja",
                [
                    {
                        "id": "valid",
                        "median": 5,
                        "volume": 0.125,
                        "offers": float("inf"),
                        "change": -2.5,
                        "max_volume_rate": float("nan"),
                    },
                    {"id": "infinite-price", "median": float("inf")},
                    {"id": "nan-price", "median": float("nan")},
                ],
            )
        ],
    )

    migrate_jsonl_to_sqlite.migrate_history(verbose=False)

    with session_factory() as db:
        rows = db.scalars(select(MarketHistory)).all()
        assert len(rows) == 1
        row = rows[0]
        assert (row.item_id, row.price, row.volume, row.offers, row.change, row.max_volume_rate) == (
            "valid",
            5,
            0.125,
            None,
            -2.5,
            None,
        )
        marker = db.get(CacheEntry, migrate_jsonl_to_sqlite.MIGRATION_MARKER_KEY)
        assert marker is not None
        assert json.loads(marker.data_json)["ambiguous_compacted_rows"] == 0

    migrate_jsonl_to_sqlite.migrate_history(verbose=False)
    with session_factory() as db:
        assert db.scalar(select(func.count(MarketHistory.id))) == 1
    engine.dispose()


def test_import_uses_source_raw_identity_and_scans_older_missing_scope(tmp_path, monkeypatch, capsys):
    engine, session_factory = _prepare_import_db(tmp_path, monkeypatch)
    with session_factory() as db:
        db.add(
            MarketHistory(
                league="Other League",
                category="Currency",
                target="divine",
                status="any",
                source="existing-source",
                item_id="divine",
                price=99,
                timestamp=999999,
                created_at="later",
                granularity="raw",
                samples=1,
            )
        )
        db.commit()

    path = tmp_path / "trade_rate_history.jsonl"
    _write_jsonl(
        path,
        [
            _snapshot(1000, "poe.ninja", [{"id": "base:heavy-belt", "median": 10}]),
            _snapshot(1000, "trade2", [{"id": "base:heavy-belt", "median": 20}]),
            _snapshot(1000, "poe.ninja", [{"id": "base:heavy-belt", "median": 10}]),
        ],
    )

    migrate_jsonl_to_sqlite.migrate_history(verbose=False)
    with session_factory() as db:
        rows = db.scalars(
            select(MarketHistory).where(
                MarketHistory.league == "Fate", MarketHistory.item_id == "base:heavy-belt"
            )
        ).all()
        assert {(row.source, row.price, row.granularity) for row in rows} == {
            ("poe.ninja", 10, "raw"),
            ("trade2", 20, "raw"),
        }
        assert all(row.samples == 1 for row in rows)
        assert db.scalar(select(func.count(MarketHistory.id))) == 3

    migrate_jsonl_to_sqlite.migrate_history(verbose=True)
    assert "уже импортирован" in capsys.readouterr().out
    with session_factory() as db:
        assert db.scalar(select(func.count(MarketHistory.id))) == 3

    _write_jsonl(
        path,
        [
            _snapshot(1000, "poe.ninja", [{"id": "base:heavy-belt", "median": 11}]),
            _snapshot(900, "poe.ninja", [{"id": "base:gold-ring", "median": 4}]),
        ],
    )
    migrate_jsonl_to_sqlite.migrate_history(verbose=False)
    with session_factory() as db:
        rows = db.scalars(
            select(MarketHistory).where(
                MarketHistory.league == "Fate", MarketHistory.source == "poe.ninja"
            )
        ).all()
        assert {row.item_id: row.price for row in rows} == {"base:heavy-belt": 11, "base:gold-ring": 4}
        assert db.scalar(select(func.count(MarketHistory.id))) == 4
    engine.dispose()


def test_import_skips_raw_rows_ambiguous_with_existing_compacted_bucket(tmp_path, monkeypatch, capsys):
    engine, session_factory = _prepare_import_db(tmp_path, monkeypatch)
    with session_factory() as db:
        db.add(
            MarketHistory(
                league="Fate",
                category="ItemBases",
                target="exalted",
                status="securable",
                source="poe.ninja",
                item_id="base:heavy-belt",
                price=12,
                timestamp=0,
                created_at="1970-01-01T00:00:00+00:00",
                granularity="hourly",
                samples=3,
            )
        )
        db.commit()

    _write_jsonl(
        tmp_path / "trade_rate_history.jsonl",
        [
            _snapshot(82800, "poe.ninja", [{"id": "base:heavy-belt", "median": 100}]),
            _snapshot(1000, "poe.ninja", [{"id": "base:heavy-belt", "median": 90}]),
        ],
    )
    migrate_jsonl_to_sqlite.migrate_history(verbose=True)

    with session_factory() as db:
        rows = db.scalars(select(MarketHistory)).all()
        assert {(row.granularity, row.timestamp, row.price, row.samples) for row in rows} == {
            ("hourly", 0, 12, 3),
            ("raw", 82800, 100, 1),
        }
        assert "пропущено неоднозначных compacted строк 1" in capsys.readouterr().out
    engine.dispose()


def test_import_treats_non_object_marker_as_invalid_and_retries(tmp_path, monkeypatch):
    engine, session_factory = _prepare_import_db(tmp_path, monkeypatch)
    path = tmp_path / "trade_rate_history.jsonl"
    _write_jsonl(path, [_snapshot(1000, "poe.ninja", [{"id": "base:heavy-belt", "median": 10}])])
    with session_factory() as db:
        db.add(
            CacheEntry(
                key=migrate_jsonl_to_sqlite.MIGRATION_MARKER_KEY,
                data_json="[]",
                created_ts=0,
                expires_ts=migrate_jsonl_to_sqlite.MIGRATION_MARKER_EXPIRY_TS,
            )
        )
        db.commit()

    statements = []

    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement.strip().upper())

    event.listen(engine, "before_cursor_execute", capture)
    migrate_jsonl_to_sqlite.migrate_history(verbose=False)
    event.remove(engine, "before_cursor_execute", capture)

    with session_factory() as db:
        rows = db.scalars(select(MarketHistory)).all()
        marker = db.get(CacheEntry, migrate_jsonl_to_sqlite.MIGRATION_MARKER_KEY)
        assert [(row.item_id, row.price, row.granularity) for row in rows] == [
            ("base:heavy-belt", 10, "raw")
        ]
        assert isinstance(json.loads(marker.data_json), dict)
    immediate_begins = [index for index, statement in enumerate(statements) if statement == "BEGIN IMMEDIATE"]
    assert immediate_begins[0] == 0
    assert len(immediate_begins) >= 2
