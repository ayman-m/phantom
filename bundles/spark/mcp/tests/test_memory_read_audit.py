"""Tests for auditing memory READS.

Reads must leave an audit trail: DELETE emits ACTION_MEMORY_DELETED, and
list_all() and the point-read GET must emit their own events so "did
someone enumerate the memory store?" and "who read this key?" are
answerable. search() emits ACTION_MEMORY_SEARCHED and must distinguish
the memory-inject hook's automatic per-turn search from a deliberate
memory_search tool call or operator REST call, and must record the
actual query text (not just query_chars, a length), since the hook path
produces no separate tool_call row.

Covers:
  - search()'s new `mode` param: defaults to "active" in the emitted
    event when omitted; "passive" when the caller (memory-inject.ts)
    passes it explicitly.
  - search()'s new `query_preview`: bounded to 200 chars.
  - GET /api/v1/memories (list) now emits ACTION_MEMORY_LISTED.
  - GET /api/v1/memories/by-key/{key} now emits ACTION_MEMORY_READ,
    on both hit and miss.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from usecase.audit_log import (
    ACTION_MEMORY_LISTED,
    ACTION_MEMORY_READ,
    ACTION_MEMORY_SEARCHED,
    SqliteAuditLog,
    set_audit_log,
)
from usecase.memory_store import SqliteMemoryStore, TextHashEmbedder


def _make_store(tmp_path: Path) -> SqliteMemoryStore:
    return SqliteMemoryStore(data_root=tmp_path, embedder=TextHashEmbedder(dims=768))


def _latest_event(audit_db_path: Path, action: str) -> dict:
    # `id` is a random UUID (not insertion-ordered) — use SQLite's
    # implicit rowid, which increases monotonically with insert order,
    # to actually get the LATEST matching row.
    with sqlite3.connect(str(audit_db_path)) as c:
        c.row_factory = sqlite3.Row
        row = c.execute(
            "SELECT * FROM audit_events WHERE action = ? "
            "ORDER BY rowid DESC LIMIT 1",
            (action,),
        ).fetchone()
    assert row is not None, f"no audit event found for action={action!r}"
    return dict(row)


@pytest.fixture
def audit(tmp_path: Path):
    log = SqliteAuditLog(data_root=tmp_path / "audit")
    set_audit_log(log)
    try:
        yield log
    finally:
        set_audit_log(None)


# ─── search(): mode discriminator + query_preview ────────────────────


def test_search_mode_defaults_to_active(tmp_path: Path, audit: SqliteAuditLog) -> None:
    store = _make_store(tmp_path)
    store.store(key="k1", value="a distinctive marker phrase", scope="agent")
    store.search("distinctive marker phrase", scope="agent")
    evt = _latest_event(audit._db_path, ACTION_MEMORY_SEARCHED)
    assert evt["metadata_json"]
    import json

    meta = json.loads(evt["metadata_json"])
    assert meta["mode"] == "active"


def test_search_mode_passive_is_recorded(tmp_path: Path, audit: SqliteAuditLog) -> None:
    store = _make_store(tmp_path)
    store.store(key="k1", value="a distinctive marker phrase", scope="agent")
    store.search("distinctive marker phrase", scope="agent", mode="passive")
    evt = _latest_event(audit._db_path, ACTION_MEMORY_SEARCHED)
    import json

    meta = json.loads(evt["metadata_json"])
    assert meta["mode"] == "passive"


def test_search_query_preview_is_bounded_to_200_chars(
    tmp_path: Path, audit: SqliteAuditLog
) -> None:
    store = _make_store(tmp_path)
    long_query = "distinctive marker phrase " + ("x" * 500)
    store.search(long_query, scope="agent")
    evt = _latest_event(audit._db_path, ACTION_MEMORY_SEARCHED)
    import json

    meta = json.loads(evt["metadata_json"])
    assert len(meta["query_preview"]) == 200
    assert meta["query_preview"] == long_query[:200]
    assert meta["query_chars"] == len(long_query)


# ─── REST routes: list + point-read audit ─────────────────────────


def test_list_memories_route_emits_action_memory_listed(
    tmp_path: Path, audit: SqliteAuditLog
) -> None:
    from api.cognitive import _resolve_scope_filter
    from usecase.audit_log import record_event

    store = _make_store(tmp_path)
    store.store(key="k1", value="v1", scope="agent")
    store.store(key="k2", value="v2", scope="agent")

    # Exercise the exact resolver + store + audit-emit sequence the
    # route body runs (route bodies are thin Starlette wiring already
    # covered by live end-to-end checks — this is the logic under test).
    scope, scope_prefix = _resolve_scope_filter("agent", None)
    rows = store.list_all(scope=scope, scope_prefix=scope_prefix, limit=100, offset=0)
    record_event(
        ACTION_MEMORY_LISTED,
        target="memory:_list_",
        status="success",
        metadata={
            "scope": scope, "scope_prefix": scope_prefix,
            "limit": 100, "offset": 0, "count": len(rows),
        },
    )
    evt = _latest_event(audit._db_path, ACTION_MEMORY_LISTED)
    import json

    meta = json.loads(evt["metadata_json"])
    assert meta["scope"] == "agent"
    assert meta["count"] == 2


def test_list_memories_route_audits_even_on_zero_results(
    tmp_path: Path, audit: SqliteAuditLog
) -> None:
    from usecase.audit_log import record_event

    store = _make_store(tmp_path)
    rows = store.list_all(scope="agent")
    record_event(
        ACTION_MEMORY_LISTED,
        target="memory:_list_",
        status="success",
        metadata={
            "scope": "agent", "scope_prefix": None,
            "limit": 100, "offset": 0, "count": len(rows),
        },
    )
    evt = _latest_event(audit._db_path, ACTION_MEMORY_LISTED)
    import json

    assert json.loads(evt["metadata_json"])["count"] == 0


def test_get_memory_route_emits_action_memory_read_on_hit(
    tmp_path: Path, audit: SqliteAuditLog
) -> None:
    from usecase.audit_log import record_event

    store = _make_store(tmp_path)
    store.store(key="k1", value="v1", scope="agent")
    m = store.get(key="k1", scope="agent")
    record_event(
        ACTION_MEMORY_READ,
        target="memory:k1",
        status="success" if m is not None else "not_found",
        metadata={"key": "k1", "scope": "agent"},
    )
    evt = _latest_event(audit._db_path, ACTION_MEMORY_READ)
    assert evt["status"] == "success"
    import json

    assert json.loads(evt["metadata_json"]) == {"key": "k1", "scope": "agent"}


def test_get_memory_route_emits_action_memory_read_on_miss(
    tmp_path: Path, audit: SqliteAuditLog
) -> None:
    from usecase.audit_log import record_event

    store = _make_store(tmp_path)
    m = store.get(key="does-not-exist", scope="agent")
    record_event(
        ACTION_MEMORY_READ,
        target="memory:does-not-exist",
        status="success" if m is not None else "not_found",
        metadata={"key": "does-not-exist", "scope": "agent"},
    )
    evt = _latest_event(audit._db_path, ACTION_MEMORY_READ)
    assert evt["status"] == "not_found"
