"""Tests for SqliteNotificationStore + dispatch hook."""

from __future__ import annotations

from typing import Any

import pytest

from src.usecase.notifications import (
    SqliteNotificationStore,
    TopicSpec,
)


SAMPLE_TOPICS = [
    TopicSpec(name="setup-required", severity="warning", target="user:operator"),
    TopicSpec(name="simulation-complete", severity="info", target="user:operator"),
    TopicSpec(name="detection-miss", severity="warning", target="channel:soc"),
]


@pytest.fixture
def store(tmp_path) -> SqliteNotificationStore:
    return SqliteNotificationStore(topics=SAMPLE_TOPICS, data_root=tmp_path)


def test_publish_persists_with_topic_metadata(store: SqliteNotificationStore) -> None:
    n = store.publish("simulation-complete", payload={"sim_id": "abc"})
    assert n.topic == "simulation-complete"
    assert n.severity == "info"
    assert n.target == "user:operator"
    assert n.payload == {"sim_id": "abc"}
    assert n.dispatch_status == "stored"  # no dispatch_hook
    assert n.read_at is None


def test_publish_rejects_undeclared_topic(store: SqliteNotificationStore) -> None:
    # Spec compliance: only manifest-declared topics are emittable.
    with pytest.raises(ValueError):
        store.publish("totally-made-up-topic")


def test_topic_severity_normalized(tmp_path) -> None:
    with pytest.raises(ValueError):
        # Invalid severity rejected at TopicSpec construction.
        TopicSpec.from_manifest(
            {"name": "x", "severity": "loud", "target": "user:operator"}
        )


def test_list_filters_by_target(store: SqliteNotificationStore) -> None:
    store.publish("setup-required")
    store.publish("simulation-complete")
    store.publish("detection-miss", payload={"miss_count": 3})

    user_only = store.list(target="user:operator")
    assert {n.topic for n in user_only} == {"setup-required", "simulation-complete"}

    channel_only = store.list(target="channel:soc")
    assert {n.topic for n in channel_only} == {"detection-miss"}


def test_list_unread_only(store: SqliteNotificationStore) -> None:
    a = store.publish("simulation-complete")
    store.publish("setup-required")
    assert store.ack(a.id) is True
    pending = store.list(unread_only=True)
    assert {n.topic for n in pending} == {"setup-required"}


def test_unread_count_per_target(store: SqliteNotificationStore) -> None:
    store.publish("setup-required")
    store.publish("setup-required")
    store.publish("detection-miss")
    assert store.unread_count(target="user:operator") == 2
    assert store.unread_count(target="channel:soc") == 1
    assert store.unread_count() == 3


def test_ack_returns_false_on_unknown_id(store: SqliteNotificationStore) -> None:
    assert store.ack("not-a-real-id") is False


def test_ack_idempotent(store: SqliteNotificationStore) -> None:
    n = store.publish("simulation-complete")
    assert store.ack(n.id) is True
    assert store.ack(n.id) is False  # already read


def test_dispatch_hook_called_for_channel_targets(tmp_path) -> None:
    calls: list[str] = []

    def hook(notif):
        calls.append(notif.topic)

    s = SqliteNotificationStore(
        topics=SAMPLE_TOPICS, data_root=tmp_path, dispatch_hook=hook
    )
    user_n = s.publish("simulation-complete")
    channel_n = s.publish("detection-miss")

    # Hook fires only for channel:* targets.
    assert calls == ["detection-miss"]
    assert user_n.dispatch_status == "stored"
    assert channel_n.dispatch_status == "dispatched"


def test_dispatch_failure_recorded_but_persists(tmp_path) -> None:
    def hook(_):
        raise RuntimeError("slack down")

    s = SqliteNotificationStore(
        topics=SAMPLE_TOPICS, data_root=tmp_path, dispatch_hook=hook
    )
    n = s.publish("detection-miss", payload={"x": 1})
    # Dispatch failed but the row persists with the failure recorded.
    assert n.dispatch_status == "failed"
    assert n.dispatch_error and "slack down" in n.dispatch_error
    rows = s.list(target="channel:soc")
    assert rows[0].dispatch_status == "failed"


def test_audit_records_publish(tmp_path) -> None:
    class _SpyAudit:
        def __init__(self) -> None:
            self.events: list[dict[str, Any]] = []

        def record(
            self, action: str, *, target: str | None = None,
            status: str | None = None, actor: str | None = None,
            duration_ms: int | None = None, metadata: dict[str, Any] | None = None,
        ) -> str:
            self.events.append(
                {"action": action, "target": target, "actor": actor, "metadata": metadata}
            )
            return "row-id"

    spy = _SpyAudit()
    s = SqliteNotificationStore(
        topics=SAMPLE_TOPICS, data_root=tmp_path, audit_log=spy
    )
    s.publish("setup-required", actor="ayman")
    assert len(spy.events) == 1
    assert spy.events[0]["action"] == "notification_published"
    assert spy.events[0]["target"].startswith("notification:")
    assert spy.events[0]["actor"] == "ayman"
    md = spy.events[0]["metadata"]
    assert md["topic"] == "setup-required"
    assert md["severity"] == "warning"
    assert md["channel_target"] == "user:operator"


def test_persistence_across_reopen(tmp_path) -> None:
    s1 = SqliteNotificationStore(topics=SAMPLE_TOPICS, data_root=tmp_path)
    s1.publish("setup-required", payload={"step": 1})

    s2 = SqliteNotificationStore(topics=SAMPLE_TOPICS, data_root=tmp_path)
    rows = s2.list()
    assert len(rows) == 1
    assert rows[0].payload == {"step": 1}


# ── paging, date filter, mark-all-read (the /notifications page) ──────────


def _backdate(store: SqliteNotificationStore, notif_id: str, created_at: str) -> None:
    import sqlite3

    with sqlite3.connect(store._db_path) as conn:
        conn.execute("UPDATE notifications SET created_at = ? WHERE id = ?", (created_at, notif_id))


def test_list_pages_newest_first_without_gaps_or_repeats(store: SqliteNotificationStore) -> None:
    ids = [store.publish("simulation-complete", payload={"n": i}).id for i in range(5)]
    first = store.list(limit=2, offset=0)
    second = store.list(limit=2, offset=2)
    third = store.list(limit=2, offset=4)
    paged = [n.id for n in first + second + third]
    assert paged == list(reversed(ids))
    assert store.list(limit=2, offset=99) == []


def test_count_ignores_limit_and_offset_and_follows_the_filters(store: SqliteNotificationStore) -> None:
    a = store.publish("simulation-complete")
    store.publish("setup-required")
    store.publish("detection-miss")
    store.ack(a.id)
    assert store.count() == 3
    assert store.count(target="user:operator") == 2
    assert store.count(unread_only=True) == 2
    assert store.count(target="user:operator", unread_only=True) == 1


def test_since_keeps_only_rows_created_at_or_after_it(store: SqliteNotificationStore) -> None:
    old = store.publish("simulation-complete")
    recent = store.publish("setup-required")
    _backdate(store, old.id, "2026-01-01T00:00:00.000000Z")
    cutoff = "2026-06-01T00:00:00.000000Z"
    assert [n.id for n in store.list(since=cutoff)] == [recent.id]
    assert store.count(since=cutoff) == 1
    assert store.count() == 2


def test_ack_all_marks_every_unread_row_and_reports_how_many(store: SqliteNotificationStore) -> None:
    a = store.publish("simulation-complete")
    store.publish("setup-required")
    store.publish("detection-miss")
    store.ack(a.id)
    assert store.ack_all() == 2
    assert store.unread_count() == 0
    assert store.ack_all() == 0


def test_ack_all_can_be_limited_to_one_target(store: SqliteNotificationStore) -> None:
    store.publish("simulation-complete")
    store.publish("detection-miss")
    assert store.ack_all(target="channel:soc") == 1
    assert store.unread_count(target="user:operator") == 1
    assert store.unread_count(target="channel:soc") == 0
