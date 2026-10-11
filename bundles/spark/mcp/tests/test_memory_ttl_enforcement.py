"""Tests for TTL enforcement in SqliteMemoryStore. _reap_expired() runs
only at store construction, so an expired memory would keep being
returned by get/get_by_id/list_all/search (and kept being injected into
prompts) for as long as the container stayed up if reads trusted it.
Expiry is therefore enforced unconditionally on every read path via the
_NOT_EXPIRED_SQL predicate; the reaper only reclaims space + writes an
audit trail.

Also covers the reaper's epoch math: it uses calendar.timegm, because
time.mktime(upd) - time.timezone interprets a UTC struct_time as LOCAL
time and subtracts a DST-naive constant, which is off by exactly one
hour for any updated_at that falls within a DST period on a
DST-observing host.
"""

from __future__ import annotations

import calendar
import time
from pathlib import Path

import pytest

from src.usecase.memory_store import SqliteMemoryStore, TextHashEmbedder


def _make_store(tmp_path: Path) -> SqliteMemoryStore:
    return SqliteMemoryStore(data_root=tmp_path, embedder=TextHashEmbedder(dims=768))


def _row_count(store: SqliteMemoryStore, key: str) -> int:
    import sqlite3

    with sqlite3.connect(str(store._db_path)) as c:
        return c.execute(
            "SELECT count(*) FROM memories WHERE key = ?", (key,)
        ).fetchone()[0]


def _backdate(store: SqliteMemoryStore, memory_id: str, seconds_ago: int) -> None:
    """Rewrite updated_at directly so a test can force expiry without a
    real sleep(). SQLite's datetime('now') has only whole-SECOND
    precision, so a real-time test needs a wide margin over the TTL to
    avoid flaking on the rounding edge (ttl=1s + sleep=1.2s is NOT
    enough margin). A generous backdate sidesteps the granularity
    question entirely."""
    import sqlite3

    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - seconds_ago))
    with sqlite3.connect(str(store._db_path)) as c:
        c.execute("UPDATE memories SET updated_at = ? WHERE id = ?", (ts, memory_id))


# ─── read-path enforcement ──────────────────────────────────────────


def test_expired_row_invisible_to_get(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    m = store.store(key="eph", value="v", scope="agent", ttl_seconds=5)
    _backdate(store, m.id, seconds_ago=60)
    assert store.get(key="eph", scope="agent") is None


def test_expired_row_invisible_to_get_by_id(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    m = store.store(key="eph", value="v", scope="agent", ttl_seconds=5)
    _backdate(store, m.id, seconds_ago=60)
    assert store.get_by_id(m.id) is None


def test_expired_row_excluded_from_list_all(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    m = store.store(key="eph", value="v", scope="agent", ttl_seconds=5)
    store.store(key="perm", value="v2", scope="agent")  # no TTL
    _backdate(store, m.id, seconds_ago=60)
    keys = [mem.key for mem in store.list_all(scope="agent")]
    assert "eph" not in keys
    assert "perm" in keys


def test_expired_row_excluded_from_search(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    m = store.store(key="eph", value="a distinctive marker phrase", scope="agent", ttl_seconds=5)
    _backdate(store, m.id, seconds_ago=60)
    hits = [mem.key for mem, _score in store.search("distinctive marker phrase", scope="agent")]
    assert "eph" not in hits


def test_unexpired_ttl_row_still_visible(tmp_path: Path) -> None:
    # Negative control — a guard that hides everything with a TTL set
    # would pass the tests above for the wrong reason.
    store = _make_store(tmp_path)
    store.store(key="fresh", value="v", scope="agent", ttl_seconds=3600)
    assert store.get(key="fresh", scope="agent") is not None
    assert "fresh" in [m.key for m in store.list_all(scope="agent")]


# ─── reap-on-read vs reap-on-write (the load-bearing distinction) ──


def test_expired_row_stays_physically_present_until_reaped(tmp_path: Path) -> None:
    """The assertion that distinguishes read-time TTL filtering from a
    boot-only reap: reads must filter WITHOUT deleting. If a read
    accidentally deleted on the way, the visibility checks would still
    pass — the row count check is what catches that."""
    store = _make_store(tmp_path)
    m = store.store(key="eph", value="v", scope="agent", ttl_seconds=5)
    _backdate(store, m.id, seconds_ago=60)

    assert store.get(key="eph", scope="agent") is None  # invisible to reads
    assert _row_count(store, "eph") == 1  # but still on disk

    n = store._reap_expired()
    assert n == 1
    assert _row_count(store, "eph") == 0  # now actually gone


def test_reaper_is_idempotent_on_no_expired_rows(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    store.store(key="perm", value="v", scope="agent")
    assert store._reap_expired() == 0


# ─── DST correctness in the reaper's epoch math ─────────────────────


def test_reaper_epoch_math_is_dst_independent() -> None:
    """calendar.timegm must treat the parsed struct_time as pure UTC
    fields, with no timezone/DST adjustment. Empirically verified: the
    prior form (time.mktime(upd) - time.timezone) drifts by exactly
    one hour for a July date under a DST-observing TZ like
    America/New_York — this test pins the correct, TZ-independent
    result regardless of which TZ pytest happens to run under."""
    upd = time.strptime("2026-07-15T12:00:00Z", "%Y-%m-%dT%H:%M:%SZ")
    assert calendar.timegm(upd) == 1784116800


def test_reaper_deletes_expired_row_regardless_of_local_tz(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End-to-end DST check: store a row, backdate its updated_at to
    just past a short TTL, and confirm the reaper deletes it under a
    DST-observing TZ. A time.mktime(upd) - time.timezone form could
    read the row as still-alive (or already-expired the wrong way)
    depending on time of year; calendar.timegm is correct
    unconditionally."""
    store = _make_store(tmp_path)
    m = store.store(key="eph", value="v", scope="agent", ttl_seconds=5)
    _backdate(store, m.id, seconds_ago=10)  # past the 5s TTL

    monkeypatch.setenv("TZ", "America/New_York")
    time.tzset()
    try:
        assert store._reap_expired() == 1
    finally:
        monkeypatch.delenv("TZ", raising=False)
        time.tzset()
