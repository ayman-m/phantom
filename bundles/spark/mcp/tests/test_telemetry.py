"""Tests for SqliteTelemetryStore — opt-in usage counters."""

from __future__ import annotations

from typing import Any

import pytest

from src.usecase.telemetry import SqliteTelemetryStore


DECLARED = ["install", "uninstall", "version_pin",
            "simulation_run_count_per_day", "validation_count_per_day"]


@pytest.fixture
def store_off(tmp_path) -> SqliteTelemetryStore:
    """Default privacy-respecting state: starts disabled."""
    return SqliteTelemetryStore(
        declared_events=DECLARED, default_enabled=False, data_root=tmp_path
    )


@pytest.fixture
def store_on(tmp_path) -> SqliteTelemetryStore:
    """Operator opted in upfront."""
    return SqliteTelemetryStore(
        declared_events=DECLARED, default_enabled=True, data_root=tmp_path
    )


def test_default_off_record_returns_false(store_off: SqliteTelemetryStore) -> None:
    assert store_off.is_enabled() is False
    assert store_off.record("install") is False
    # Status reports zero recorded — even an "install" was no-op.
    assert store_off.status().total_recorded == 0


def test_set_enabled_persists_across_reopen(tmp_path) -> None:
    s1 = SqliteTelemetryStore(
        declared_events=DECLARED, default_enabled=False, data_root=tmp_path
    )
    s1.set_enabled(True, actor="ayman")
    assert s1.is_enabled() is True

    # Fresh instance picks up persisted state — set_enabled is durable.
    s2 = SqliteTelemetryStore(
        declared_events=DECLARED, default_enabled=False, data_root=tmp_path
    )
    assert s2.is_enabled() is True


def test_record_works_when_enabled(store_on: SqliteTelemetryStore) -> None:
    assert store_on.record("install") is True
    assert store_on.record("simulation_run_count_per_day", count=3) is True
    s = store_on.status()
    assert s.counts_by_event["install"] == 1
    assert s.counts_by_event["simulation_run_count_per_day"] == 3
    assert s.total_recorded == 4


def test_record_rejects_undeclared_event(store_on: SqliteTelemetryStore) -> None:
    # Even with telemetry on, unknown events are silently dropped —
    # we never let a caller slip new event names through.
    assert store_on.record("nope-not-declared") is False
    assert store_on.status().total_recorded == 0


def test_set_enabled_audits_only_on_change(tmp_path) -> None:
    class _SpyAudit:
        def __init__(self) -> None:
            self.events: list[dict[str, Any]] = []

        def record(self, action: str, **kw: Any) -> str:
            self.events.append({"action": action, **kw})
            return "id"

    spy = _SpyAudit()
    s = SqliteTelemetryStore(
        declared_events=DECLARED, default_enabled=False,
        data_root=tmp_path, audit_log=spy,
    )
    # No-op: already disabled.
    assert s.set_enabled(False) is False
    assert spy.events == []

    # First real change emits an audit row.
    assert s.set_enabled(True, actor="ayman") is True
    assert len(spy.events) == 1
    assert spy.events[0]["action"] == "telemetry_toggled"
    assert spy.events[0]["actor"] == "ayman"
    assert spy.events[0]["metadata"]["enabled"] is True
    assert spy.events[0]["metadata"]["previous"] is False

    # Second toggle still on → no-op, no extra audit row.
    assert s.set_enabled(True) is False
    assert len(spy.events) == 1


def test_status_aggregates_correctly(store_on: SqliteTelemetryStore) -> None:
    store_on.record("install")
    store_on.record("install")
    store_on.record("validation_count_per_day", count=5)
    s = store_on.status()
    assert s.total_recorded == 7
    assert s.counts_by_event == {
        "install": 2,
        "validation_count_per_day": 5,
    }
    assert sorted(s.declared_events) == sorted(DECLARED)


def test_daily_counts_buckets_by_date(store_on: SqliteTelemetryStore) -> None:
    store_on.record("install")
    store_on.record("install")
    store_on.record("simulation_run_count_per_day", count=2)
    buckets = store_on.daily_counts(days=7)
    # Same day, two distinct events:
    by_event = {b["event_name"]: b["total"] for b in buckets}
    assert by_event["install"] == 2
    assert by_event["simulation_run_count_per_day"] == 2


def test_daily_counts_event_filter(store_on: SqliteTelemetryStore) -> None:
    store_on.record("install")
    store_on.record("validation_count_per_day", count=4)
    buckets = store_on.daily_counts(event_name="install")
    assert all(b["event_name"] == "install" for b in buckets)
