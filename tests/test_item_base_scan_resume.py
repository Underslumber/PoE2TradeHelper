import asyncio
import json
import sqlite3
import time
import uuid
from contextlib import closing
from pathlib import Path

import pytest

from app import trade2


@pytest.fixture
def isolated_scan(monkeypatch):
    trade2.ITEM_BASE_MARKET_CACHE.clear()
    trade2.ITEM_BASE_MARKET_JOBS.clear()
    trade2.ITEM_BASE_MARKET_SCAN_CURSORS.clear()
    cache_dir = Path(__file__).parent / f".scan-cache-{uuid.uuid4().hex}"
    cache_dir.mkdir()
    cache_path = cache_dir / "scan-cache.sqlite"

    def cache_get(key):
        with closing(sqlite3.connect(cache_path)) as connection:
            with connection:
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS cache_entries (key TEXT PRIMARY KEY, data_json TEXT NOT NULL, expires_ts REAL NOT NULL)"
                )
                row = connection.execute("SELECT data_json, expires_ts FROM cache_entries WHERE key = ?", (key,)).fetchone()
                if row is None or row[1] < time.time():
                    return None
                return json.loads(row[0])

    def cache_set(key, data, ttl):
        with closing(sqlite3.connect(cache_path)) as connection:
            with connection:
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS cache_entries (key TEXT PRIMARY KEY, data_json TEXT NOT NULL, expires_ts REAL NOT NULL)"
                )
                connection.execute(
                    "INSERT OR REPLACE INTO cache_entries(key, data_json, expires_ts) VALUES (?, ?, ?)",
                    (key, json.dumps(data), time.time() + ttl),
                )

    monkeypatch.setattr(trade2.SQLiteCacheManager, "get", staticmethod(cache_get))
    monkeypatch.setattr(trade2.SQLiteCacheManager, "set", staticmethod(cache_set))
    monkeypatch.setattr(trade2, "_read_item_base_market_history_snapshot", lambda **kwargs: None)
    monkeypatch.setattr(trade2, "read_latest_rates", lambda **kwargs: None)
    monkeypatch.setattr(trade2, "_item_base_market_recent_demand_map", lambda **kwargs: {})
    monkeypatch.setattr(trade2, "log_market_history", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        trade2,
        "_currency_rates_for_target",
        lambda *args, **kwargs: asyncio.sleep(0, result=({"rows": []}, {"exalted": 1.0})),
    )
    yield cache_path
    if cache_path.exists():
        cache_path.unlink()
    cache_dir.rmdir()


def _bases(*names):
    return {
        "source": "test",
        "total": len(names),
        "bases": [
            {"id": f"base:{name}", "type": name, "type_ru": name, "query_type": name, "base_class": "ring"}
            for name in names
        ],
    }


def _priced_row(base, query):
    row = trade2._base_market_row_from_base(base)
    lot = {"price_amount": 2.0, "price_currency": "exalted", "price_target": 2.0}
    return {
        **row,
        **trade2._base_market_stats([lot], 1),
        "query_id": query["id"],
        "total": query.get("total", 1),
        "total_scope": "exact",
        "fetched_count": 1,
        "sample_lots": [lot],
    }


def test_scan_row_merge_keeps_latest_overlapping_key_owners(monkeypatch):
    rows = [
        {"id": "first", "text": "A", "text_ru": "Общее первое", "query_type": "a"},
        {"id": "unaffected", "text": "Z", "text_ru": "Без изменений", "query_type": "z"},
        {"id": "second", "text": "B", "text_ru": "Общее второе", "query_type": "b"},
        {"id": "replace-first", "text": "C", "text_ru": "Общее первое", "query_type": "c"},
        {"id": "replace-second", "text": "D", "text_ru": "Общее второе", "query_type": "d"},
        {"id": "latest", "text": "C", "text_ru": "D", "query_type": "latest"},
    ]
    calls = []
    original_row_keys = trade2._base_market_row_keys

    def count_row_keys(row):
        calls.append(row["id"])
        return original_row_keys(row)

    monkeypatch.setattr(trade2, "_base_market_row_keys", count_row_keys)

    merged = trade2._merge_item_base_market_scan_rows(rows[:3], rows[3:])

    assert [row["id"] for row in merged] == ["unaffected", "latest"]
    assert calls == [row["id"] for row in rows]


def test_rough_scan_resumes_pending_bases_after_rate_limit(isolated_scan, monkeypatch):
    monkeypatch.setattr(trade2, "ITEM_BASE_MARKET_SCAN_BATCH_SIZE", 3)
    monkeypatch.setattr(trade2, "ITEM_BASE_MARKET_PRIORITY_SCAN_BATCH_SIZE", 3)
    monkeypatch.setattr(trade2, "get_item_base_catalog", lambda **kwargs: asyncio.sleep(0, result=_bases("A", "B", "C")))
    attempted = []
    rate_limited_once = {"base:B"}

    async def fake_search(league, query, sort=None, api_base=None):
        return {"id": "search", "total": 1, "result": ["listing"]}

    async def fake_fetch(base, search, target, rates, min_ilvl=None, fetch_limit=None):
        attempted.append(base["id"])
        if base["id"] in rate_limited_once:
            rate_limited_once.remove(base["id"])
            row = trade2._base_market_row_from_base(base)
            return {**row, **trade2._base_market_stats([], 0), "sample_lots": [], "error": "trade2 fetch rate limited; retry after 299s"}
        return _priced_row(base, search)

    monkeypatch.setattr(trade2, "_post_search", fake_search)
    monkeypatch.setattr(trade2, "_fetch_item_base_market_row_from_search", fake_fetch)
    captured_history = []
    monkeypatch.setattr(trade2, "log_market_history", lambda snapshot, **kwargs: captured_history.append(snapshot))
    priority_calls = []
    original_priority = trade2._item_base_market_priority_bases

    def track_priority(*args, **kwargs):
        priority_calls.append(True)
        return original_priority(*args, **kwargs)

    monkeypatch.setattr(trade2, "_item_base_market_priority_bases", track_priority)

    first_job, first_coroutine = trade2.start_item_base_market_refresh_job(
        league="PoE2 - Resume Test", target="exalted", status="securable", q="", sample_limit=100
    )
    first_result = asyncio.run(first_coroutine)
    assert first_result["refresh_job"]["status"] == "rate_limited"
    assert attempted == ["base:A", "base:B"]
    assert [row["id"] for row in captured_history[-1]["rows"]] == ["base:A"]
    first_observation_ts = captured_history[-1]["created_ts"]
    assert captured_history[-1]["rows"][0]["stored_created_ts"] == first_observation_ts

    trade2.ITEM_BASE_MARKET_JOBS.clear()  # Имитируем перезапуск процесса после сохранения checkpoint.
    waiting_job, waiting_coroutine = trade2.start_item_base_market_refresh_job(
        league="PoE2 - Resume Test", target="exalted", status="securable", q="", sample_limit=100
    )
    assert waiting_job["status"] == "rate_limited"
    assert waiting_coroutine is None
    checkpoint_key = trade2._item_base_market_scan_checkpoint_key(
        trade2._item_base_market_scan_cursor_key("PoE2 - Resume Test", "exalted", "securable", None)
    )
    saved_checkpoint = trade2.SQLiteCacheManager.get(checkpoint_key)
    assert saved_checkpoint["retry_at"] > time.time()
    assert [row["id"] for row in saved_checkpoint["partial_rows"]] == ["base:A"]
    assert saved_checkpoint["partial_rows"][0]["low"] == 2.0
    saved_checkpoint["retry_at"] = time.time() - 1
    trade2.SQLiteCacheManager.set(checkpoint_key, saved_checkpoint, trade2.ITEM_BASE_MARKET_SCAN_CHECKPOINT_TTL)
    trade2.ITEM_BASE_MARKET_JOBS.clear()
    trade2.ITEM_BASE_MARKET_SCAN_CURSORS.clear()

    resumed_job, resumed_coroutine = trade2.start_item_base_market_refresh_job(
        league="PoE2 - Resume Test", target="exalted", status="securable", q="", sample_limit=100
    )
    assert resumed_job is not first_job
    result = asyncio.run(resumed_coroutine)

    assert result["refresh_job"]["status"] == "done"
    assert attempted == ["base:A", "base:B", "base:C", "base:B"]
    assert any(row["id"] == "base:A" for row in result["rows"])
    assert [row["id"] for row in captured_history[-1]["rows"]] == ["base:C", "base:B"]
    result_rows_by_id = {row["id"]: row for row in result["rows"]}
    assert result_rows_by_id["base:A"]["stored_created_ts"] == first_observation_ts
    assert all(row["stored_created_ts"] == captured_history[-1]["created_ts"] for row in captured_history[-1]["rows"])
    assert sum(row["id"] == "base:A" for snapshot in captured_history for row in snapshot["rows"]) == 1
    assert len(priority_calls) == 1  # При возобновлении pending повторная приоритизация не нужна.
    saved = trade2.SQLiteCacheManager.get(checkpoint_key)
    assert saved["pending"] == []
    assert saved["cursor"] == 2


def test_checkpoint_catalog_fingerprint_invalidates_changed_catalog(isolated_scan, monkeypatch):
    cursor_key = trade2._item_base_market_scan_cursor_key("PoE2 - Fingerprint", "exalted", "securable", None)
    old_bases = _bases("A", "B")["bases"]
    trade2._save_item_base_market_scan_checkpoint(
        cursor_key,
        fingerprint=trade2._item_base_market_scan_catalog_fingerprint(old_bases),
        cursor=1,
        pending=[{"id": "base:OLD", "priority": False}],
    )
    monkeypatch.setattr(trade2, "ITEM_BASE_MARKET_SCAN_BATCH_SIZE", 1)
    monkeypatch.setattr(trade2, "ITEM_BASE_MARKET_PRIORITY_SCAN_BATCH_SIZE", 1)
    monkeypatch.setattr(trade2, "get_item_base_catalog", lambda **kwargs: asyncio.sleep(0, result=_bases("A", "C")))
    searches = []

    async def fake_search(league, query, sort=None, api_base=None):
        searches.append("called")
        return {"id": "search", "total": 0, "result": []}

    async def fake_fetch(base, search, target, rates, min_ilvl=None, fetch_limit=None):
        return {**trade2._base_market_row_from_base(base), **trade2._base_market_stats([], 0), "sample_lots": []}

    monkeypatch.setattr(trade2, "_post_search", fake_search)
    monkeypatch.setattr(trade2, "_fetch_item_base_market_row_from_search", fake_fetch)
    job, coroutine = trade2.start_item_base_market_refresh_job(
        league="PoE2 - Fingerprint", target="exalted", status="securable", q="", sample_limit=100
    )
    asyncio.run(coroutine)

    assert job["scan_batch_size"] == 1
    assert searches == ["called"]
    assert trade2.SQLiteCacheManager.get(trade2._item_base_market_scan_checkpoint_key(cursor_key))["pending"] == []


def test_rate_limited_normal_base_rotates_behind_pending_and_keeps_catalog_cursor(isolated_scan, monkeypatch):
    bases = _bases("Ring 0", "Ring 1", "Ring 2", "Ring 3", "Ring 4")["bases"]
    cursor_key = trade2._item_base_market_scan_cursor_key("PoE2 - Sparse", "exalted", "securable", None)
    trade2.ITEM_BASE_MARKET_SCAN_CURSORS[cursor_key] = 3
    monkeypatch.setattr(trade2, "ITEM_BASE_MARKET_SCAN_BATCH_SIZE", 3)
    monkeypatch.setattr(trade2, "ITEM_BASE_MARKET_PRIORITY_SCAN_BATCH_SIZE", 3)
    monkeypatch.setattr(trade2, "get_item_base_catalog", lambda **kwargs: asyncio.sleep(0, result={"source": "test", "total": 5, "bases": bases}))
    monkeypatch.setattr(trade2, "_item_base_market_priority_bases", lambda scan_bases, previous_rows, target: [scan_bases[4]])
    attempted = []

    async def fake_search(league, query, sort=None, api_base=None):
        return {"id": "search", "total": 1, "result": ["listing"]}

    async def fake_fetch(base, search, target, rates, min_ilvl=None, fetch_limit=None):
        attempted.append(base["id"])
        if base["id"] == "base:Ring 3":
            row = trade2._base_market_row_from_base(base)
            return {**row, **trade2._base_market_stats([], 0), "sample_lots": [], "error": "HTTP 429 Too Many Requests"}
        return _priced_row(base, search)

    monkeypatch.setattr(trade2, "_post_search", fake_search)
    monkeypatch.setattr(trade2, "_fetch_item_base_market_row_from_search", fake_fetch)
    _job, coroutine = trade2.start_item_base_market_refresh_job(
        league="PoE2 - Sparse", target="exalted", status="securable", q="", sample_limit=100
    )
    asyncio.run(coroutine)

    checkpoint = trade2.SQLiteCacheManager.get(trade2._item_base_market_scan_checkpoint_key(cursor_key))
    assert attempted == ["base:Ring 4", "base:Ring 3"]
    assert checkpoint["cursor"] == 3
    assert checkpoint["pending"] == [
        {"id": "base:Ring 0", "priority": False},
        {"id": "base:Ring 3", "priority": False},
    ]


def test_fresh_prices_replace_recovered_partial_rows_during_resume(isolated_scan, monkeypatch):
    bases = _bases("A")["bases"]
    cursor_key = trade2._item_base_market_scan_cursor_key("PoE2 - Fresh", "exalted", "securable", None)
    old_row = _priced_row(bases[0], {"id": "old", "total": 1})
    trade2._save_item_base_market_scan_checkpoint(
        cursor_key,
        fingerprint=trade2._item_base_market_scan_catalog_fingerprint(bases),
        cursor=0,
        pending=[{"id": "base:A", "priority": True}],
        partial_rows=[old_row],
    )
    monkeypatch.setattr(trade2, "get_item_base_catalog", lambda **kwargs: asyncio.sleep(0, result={"source": "test", "total": 1, "bases": bases}))
    monkeypatch.setattr(trade2, "_post_search", lambda *args, **kwargs: asyncio.sleep(0, result={"id": "new", "total": 1, "result": ["listing"]}))
    monkeypatch.setattr(
        trade2,
        "_fetch_item_base_market_row_from_search",
        lambda base, search, target, rates, min_ilvl=None, fetch_limit=None: asyncio.sleep(
            0, result=_priced_row(base, search) | {"low": 9.0, "best": 9.0}
        ),
    )

    job, coroutine = trade2.start_item_base_market_refresh_job(
        league="PoE2 - Fresh", target="exalted", status="securable", q="", sample_limit=100
    )
    result = asyncio.run(coroutine)

    assert result["refresh_job"]["status"] == "done"
    assert next(row for row in result["rows"] if row["id"] == "base:A")["low"] == 9.0
    saved = trade2.SQLiteCacheManager.get(trade2._item_base_market_scan_checkpoint_key(cursor_key))
    assert [row["id"] for row in saved["partial_rows"]] == ["base:A"]
    assert saved["partial_rows"][0]["low"] == 9.0


def test_completed_checkpoint_recovery_does_not_override_next_batch_price(isolated_scan, monkeypatch):
    bases = _bases("A")["bases"]
    league = "PoE2 - Completed Recovery"
    cursor_key = trade2._item_base_market_scan_cursor_key(league, "exalted", "securable", None)
    monkeypatch.setattr(trade2, "get_item_base_catalog", lambda **kwargs: asyncio.sleep(0, result={"source": "test", "total": 1, "bases": bases}))
    monkeypatch.setattr(trade2, "_post_search", lambda *args, **kwargs: asyncio.sleep(0, result={"id": "search", "total": 1, "result": ["listing"]}))
    price = {"low": 2.0, "best": 2.0}

    async def fetch(base, search, target, rates, min_ilvl=None, fetch_limit=None):
        row = _priced_row(base, search)
        return {**row, **price}

    monkeypatch.setattr(trade2, "_fetch_item_base_market_row_from_search", fetch)
    first_job, first_coroutine = trade2.start_item_base_market_refresh_job(
        league=league, target="exalted", status="securable", q="", sample_limit=100
    )
    first_result = asyncio.run(first_coroutine)
    old_row = next(row for row in first_result["rows"] if row["id"] == "base:A")
    assert old_row["low"] == 2.0

    # Восстанавливаем сохранённое частичное состояние из окна сбоя до записи истории.
    trade2._save_item_base_market_scan_checkpoint(
        cursor_key,
        fingerprint=trade2._item_base_market_scan_catalog_fingerprint(bases),
        cursor=0,
        pending=[],
        partial_rows=[old_row],
    )
    trade2.ITEM_BASE_MARKET_JOBS.clear()
    trade2.ITEM_BASE_MARKET_SCAN_CURSORS.clear()
    price["low"] = 9.0
    price["best"] = 9.0
    monkeypatch.setattr(trade2, "_item_base_market_priority_bases", lambda scan_bases, previous_rows, target: scan_bases)
    second_job, second_coroutine = trade2.start_item_base_market_refresh_job(
        league=league, target="exalted", status="securable", q="", sample_limit=100
    )
    second_result = asyncio.run(second_coroutine)

    assert second_job is not first_job
    assert next(row for row in second_result["rows"] if row["id"] == "base:A")["low"] == 9.0


def test_active_stale_runner_is_not_replaced(isolated_scan, monkeypatch):
    monkeypatch.setattr(trade2, "get_item_base_catalog", lambda **kwargs: asyncio.sleep(0, result=_bases("A")))

    async def scenario():
        key = trade2._item_base_market_job_key("PoE2 - Active", "exalted", "securable", "", None, 100)
        entered = asyncio.Event()
        release = asyncio.Event()

        async def blocked_catalog(**kwargs):
            entered.set()
            await release.wait()
            return _bases("A")

        monkeypatch.setattr(trade2, "get_item_base_catalog", blocked_catalog)
        job, coroutine = trade2.start_item_base_market_refresh_job(
            league="PoE2 - Active", target="exalted", status="securable", q="", sample_limit=100
        )
        task = asyncio.create_task(coroutine)
        await entered.wait()
        job["updated_ts"] = time.time() - trade2.ITEM_BASE_MARKET_STALE_JOB_SECONDS - 1
        job["created_ts"] = time.time() - trade2.ITEM_BASE_MARKET_JOB_TTL - 1
        same_job, duplicate = trade2.start_item_base_market_refresh_job(
            league="PoE2 - Active", target="exalted", status="securable", q="", sample_limit=100
        )
        assert same_job is job
        assert duplicate is None
        release.set()
        await task

    asyncio.run(scenario())


def test_superseded_runner_cannot_overwrite_new_owner(isolated_scan, monkeypatch):
    async def scenario():
        key = trade2._item_base_market_job_key("PoE2 - Owner", "exalted", "securable", "", None, 100)
        entered = asyncio.Event()
        release = asyncio.Event()

        async def fake_catalog(**kwargs):
            return _bases("A")

        async def blocked_fetch(*args, **kwargs):
            entered.set()
            await release.wait()
            return _priced_row(args[0], args[1])

        monkeypatch.setattr(trade2, "get_item_base_catalog", fake_catalog)
        monkeypatch.setattr(trade2, "_post_search", lambda *args, **kwargs: asyncio.sleep(0, result={"id": "search", "total": 1, "result": ["listing"]}))
        monkeypatch.setattr(trade2, "_fetch_item_base_market_row_from_search", blocked_fetch)
        old_job, coroutine = trade2.start_item_base_market_refresh_job(
            league="PoE2 - Owner", target="exalted", status="securable", q="", sample_limit=100
        )
        task = asyncio.create_task(coroutine)
        await entered.wait()
        checkpoint_key = trade2._item_base_market_scan_checkpoint_key(
            trade2._item_base_market_scan_cursor_key("PoE2 - Owner", "exalted", "securable", None)
        )
        original_checkpoint = trade2.SQLiteCacheManager.get(checkpoint_key)
        assert original_checkpoint["pending"] == [{"id": "base:A", "priority": False}]
        newer_checkpoint = {**original_checkpoint, "cursor": 7, "pending": []}
        new_job = {"status": "queued", "owner_token": "new-owner", "result": {"rows": []}}
        trade2.ITEM_BASE_MARKET_JOBS[key] = new_job
        trade2.SQLiteCacheManager.set(checkpoint_key, newer_checkpoint, trade2.ITEM_BASE_MARKET_SCAN_CHECKPOINT_TTL)
        release.set()
        await task

        assert new_job == {"status": "queued", "owner_token": "new-owner", "result": {"rows": []}}
        assert old_job["status"] == "running"
        assert trade2.SQLiteCacheManager.get(checkpoint_key) == newer_checkpoint

    asyncio.run(scenario())


def test_superseded_runner_during_history_enrichment_cannot_write_checkpoint(isolated_scan, monkeypatch):
    async def scenario():
        league = "PoE2 - Enrichment Owner"
        key = trade2._item_base_market_job_key(league, "exalted", "securable", "", None, 100)
        cursor_key = trade2._item_base_market_scan_cursor_key(league, "exalted", "securable", None)
        entered = asyncio.Event()
        release = asyncio.Event()

        async def blocked_enrichment(rows, **kwargs):
            entered.set()
            await release.wait()
            return rows

        monkeypatch.setattr(trade2, "get_item_base_catalog", lambda **kwargs: asyncio.sleep(0, result=_bases("A")))
        monkeypatch.setattr(
            trade2,
            "_read_item_base_market_history_snapshot",
            lambda **kwargs: {"source": "trade2/search+fetch:rough", "rows": [_priced_row(_bases("A")["bases"][0], {"id": "old"})]},
        )
        monkeypatch.setattr(trade2, "_item_base_market_can_reuse_previous_source", lambda source: True)
        monkeypatch.setattr(trade2, "_enrich_stored_item_base_market_rows", blocked_enrichment)
        old_job, coroutine = trade2.start_item_base_market_refresh_job(
            league=league, target="exalted", status="securable", q="", sample_limit=100
        )
        task = asyncio.create_task(coroutine)
        await entered.wait()
        sentinel = {
            "version": trade2.ITEM_BASE_MARKET_SCAN_CHECKPOINT_VERSION,
            "fingerprint": "owned-by-new-runner",
            "cursor": 7,
            "pending": [],
            "retry_at": None,
            "partial_rows": [],
        }
        new_job = {"status": "queued", "owner_token": "new-owner", "result": {"rows": []}}
        trade2.ITEM_BASE_MARKET_JOBS[key] = new_job
        trade2.SQLiteCacheManager.set(
            trade2._item_base_market_scan_checkpoint_key(cursor_key),
            sentinel,
            trade2.ITEM_BASE_MARKET_SCAN_CHECKPOINT_TTL,
        )
        release.set()
        await task

        assert trade2.ITEM_BASE_MARKET_JOBS[key] is new_job
        assert trade2.SQLiteCacheManager.get(trade2._item_base_market_scan_checkpoint_key(cursor_key)) == sentinel
        assert old_job["status"] == "running"

    asyncio.run(scenario())
