"""Tests for SqliteEventLog — runtime telemetry events."""

from __future__ import annotations

import pytest

from src.usecase.event_log import SqliteEventLog


DECLARED = [
    "rt.simulation.started",
    "rt.simulation.completed",
    "rt.validation.completed",
    "rt.coverage.generated",
    "rt.caldera.operation_created",
]


@pytest.fixture
def store(tmp_path) -> SqliteEventLog:
    return SqliteEventLog(declared_events=DECLARED, data_root=tmp_path)


def test_record_persists_declared_event(store: SqliteEventLog) -> None:
    row_id = store.record("rt.simulation.started", payload={"sim_id": "abc"}, actor="ayman")
    assert row_id is not None
    rows = store.query()
    assert len(rows) == 1
    assert rows[0].event_name == "rt.simulation.started"
    assert rows[0].payload == {"sim_id": "abc"}
    assert rows[0].actor == "ayman"


def test_record_rejects_undeclared_event(store: SqliteEventLog) -> None:
    # Undeclared events return None — caller can detect skip.
    assert store.record("totally-not-declared") is None
    assert store.summary() == {}


def test_query_filter_by_event_name(store: SqliteEventLog) -> None:
    store.record("rt.simulation.started", payload={"id": "a"})
    store.record("rt.simulation.completed", payload={"id": "a"})
    store.record("rt.simulation.started", payload={"id": "b"})

    starts = store.query(event_name="rt.simulation.started")
    assert len(starts) == 2
    assert all(e.event_name == "rt.simulation.started" for e in starts)


def test_query_filter_by_actor(store: SqliteEventLog) -> None:
    store.record("rt.simulation.started", actor="ayman")
    store.record("rt.simulation.started", actor="bob")
    store.record("rt.simulation.completed", actor="ayman")
    rows = store.query(actor="ayman")
    assert len(rows) == 2


def test_query_orders_newest_first(store: SqliteEventLog) -> None:
    a = store.record("rt.simulation.started", payload={"order": 1})
    b = store.record("rt.simulation.started", payload={"order": 2})
    c = store.record("rt.simulation.started", payload={"order": 3})
    rows = store.query()
    assert [r.id for r in rows] == [c, b, a]


def test_summary_counts_by_event(store: SqliteEventLog) -> None:
    store.record("rt.simulation.started")
    store.record("rt.simulation.started")
    store.record("rt.validation.completed")
    s = store.summary()
    assert s == {
        "rt.simulation.started": 2,
        "rt.validation.completed": 1,
    }


def test_declared_events_property(store: SqliteEventLog) -> None:
    assert store.declared_events == sorted(DECLARED)


def test_persistence_across_reopen(tmp_path) -> None:
    s1 = SqliteEventLog(declared_events=DECLARED, data_root=tmp_path)
    s1.record("rt.simulation.started", payload={"hello": "world"})

    s2 = SqliteEventLog(declared_events=DECLARED, data_root=tmp_path)
    rows = s2.query()
    assert len(rows) == 1
    assert rows[0].payload == {"hello": "world"}


def test_retention_sweep_drops_old_rows(tmp_path) -> None:
    """Synthesize an "old" row by writing directly with a stale ts,
    then verify the boot-time sweep on a fresh instance reaps it."""
    import sqlite3
    import json
    import uuid

    s = SqliteEventLog(declared_events=DECLARED, data_root=tmp_path)
    s.record("rt.simulation.started", payload={"recent": True})

    # Inject a fake event from 30 days ago — older than the 7d retention.
    db = tmp_path / "events.db"
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO runtime_events (id, event_name, ts, actor, payload_json) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                str(uuid.uuid4()),
                "rt.simulation.completed",
                "2020-01-01T00:00:00.000000Z",
                None,
                json.dumps({"old": True}),
            ),
        )

    # Reopening triggers _reap_old() in __init__.
    s2 = SqliteEventLog(
        declared_events=DECLARED, data_root=tmp_path, retention_days=7,
    )
    rows = s2.query()
    # The fake old event should have been reaped; the recent one survives.
    assert len(rows) == 1
    assert rows[0].payload == {"recent": True}


def test_metrics_counter_bumped_on_record(tmp_path) -> None:
    """The structured event log should increment the
    phantom_mcp_runtime_events_total counter on every successful record.

    IMPORTANT: import via the unprefixed `usecase.metrics_registry`
    path here, not `src.usecase.metrics_registry`. Inside event_log.py
    the metric-bump block does `from usecase.metrics_registry import
    metrics_registry`, which under PYTHONPATH=src resolves to the
    unprefixed module. If the test set the singleton via the prefixed
    path, the test's `_metrics` and event_log's `_metrics` would be
    DIFFERENT module-level globals (both are valid imports; pytest +
    PYTHONPATH=src lets both shapes resolve, creating two parallel
    module objects in sys.modules with independent state). The test
    must talk to the SAME module event_log talks to.
    """
    from usecase.metrics_registry import MetricsRegistry, set_metrics_registry
    reg = MetricsRegistry()
    set_metrics_registry(reg)
    try:
        s = SqliteEventLog(declared_events=DECLARED, data_root=tmp_path)
        s.record("rt.simulation.started")
        s.record("rt.simulation.started")
        s.record("rt.validation.completed")

        c = reg.get("phantom_mcp_runtime_events_total")
        assert c is not None
        # Counter values render as floats per Prometheus exposition
        # format ("2.0" not "2"). Assert with the .0 suffix so future
        # readers don't mistake this for an integer count.
        rendered = "\n".join(c.lines())
        assert 'event_name="rt.simulation.started"} 2.0' in rendered
        assert 'event_name="rt.validation.completed"} 1.0' in rendered
    finally:
        set_metrics_registry(None)
