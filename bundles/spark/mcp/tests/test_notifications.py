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
