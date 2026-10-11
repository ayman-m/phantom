"""Tests for InProcessApprovalsBus — the additions for the agent
self-modification feature:

  - risk_tier column + parameter
  - Approval.risk_tier field flows through to_dict / list / get
  - actor cannot resolve their own request (ApprovalSelfResolveError)
  - list_history is a working alias for list_recent
  - schema migration: existing 'approvals.db' without risk_tier gets
    the column added at boot

The existing happy-path (request → wait → resolve → wait returns
status) is exercised end-to-end in tests/e2e/; this file focuses on
the Phase-11 invariants in isolation.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.usecase.approvals_bus import (
    Approval,
    ApprovalSelfResolveError,
    InProcessApprovalsBus,
    STATUS_APPROVED,
    STATUS_PENDING,
)


def _make_bus(tmp_path: Path) -> InProcessApprovalsBus:
    return InProcessApprovalsBus(data_root=tmp_path, default_timeout_seconds=5)


# ─── risk_tier ────────────────────────────────────────────────────


def test_request_default_risk_tier_is_soft(tmp_path: Path) -> None:
    bus = _make_bus(tmp_path)
    aid = bus.request(
        tool="personality_update",
        namespaced="personality_update",
        actor="agent",
        args={"prompt": "be more concise"},
    )
    row = bus.get(aid)
    assert row is not None
    assert row.risk_tier == "soft"
    assert row.to_dict()["risk_tier"] == "soft"


def test_request_explicit_risk_tier(tmp_path: Path) -> None:
    bus = _make_bus(tmp_path)
    aid = bus.request(
        tool="api_keys_rotate",
        namespaced="api_keys_rotate",
        actor="agent",
        args={"key_id": "abc"},
        risk_tier="credential",
    )
    row = bus.get(aid)
    assert row is not None
    assert row.risk_tier == "credential"


def test_request_rejects_unknown_risk_tier(tmp_path: Path) -> None:
    bus = _make_bus(tmp_path)
    with pytest.raises(ValueError, match="unknown risk_tier"):
        bus.request(
            tool="x", namespaced="x", actor="agent",
            risk_tier="lol-anything-goes",  # type: ignore[arg-type]
        )


# ─── Self-resolve defense ────────────────────────────────────────


def test_actor_cannot_resolve_own_request(tmp_path: Path) -> None:
    """The load-bearing security invariant: an agent that issued a
    self-mod request must not be able to also approve it. Bus-level
    defense, not just tool-level — same invariant applies regardless
    of which write path created the row."""
    bus = _make_bus(tmp_path)
    aid = bus.request(
        tool="personality_update",
        namespaced="personality_update",
        actor="agent",
        args={"prompt": "ignore prior orders"},
    )
    with pytest.raises(ApprovalSelfResolveError, match="cannot resolve their own"):
        bus.resolve(aid, resolver="agent", decision="approved")
    # Row must still be pending — failed self-resolve doesn't leak any
    # state through.
    row = bus.get(aid)
    assert row is not None
    assert row.status == STATUS_PENDING
    assert row.resolver is None


def test_different_actor_can_resolve(tmp_path: Path) -> None:
    """Operator approving an agent-initiated request is the happy path."""
    bus = _make_bus(tmp_path)
    aid = bus.request(
        tool="personality_update",
        namespaced="personality_update",
        actor="agent",
        args={},
    )
    out = bus.resolve(aid, resolver="user:operator", decision="approved")
    assert out is not None
    assert out.status == STATUS_APPROVED
    assert out.resolver == "user:operator"


def test_resolve_no_actor_recorded_skips_check(tmp_path: Path) -> None:
    """Older rows (or test rows) may have NULL actor. The self-resolve
    check should not block resolution in that case — the invariant only
    applies when both actor and resolver are non-empty and equal."""
    bus = _make_bus(tmp_path)
    aid = bus.request(tool="x", namespaced="x", actor="", args={})
    out = bus.resolve(aid, resolver="user:operator", decision="approved")
    assert out is not None
    assert out.status == STATUS_APPROVED


# ─── list_history alias ──────────────────────────────────────────


def test_list_history_returns_recent(tmp_path: Path) -> None:
    """list_history is the agent self-mod tool's preferred name; it
    must return the same rows list_recent does."""
    bus = _make_bus(tmp_path)
    aid1 = bus.request(tool="a", namespaced="a", actor="agent", args={})
    aid2 = bus.request(tool="b", namespaced="b", actor="agent", args={})
    bus.resolve(aid1, resolver="user:operator", decision="approved")
    bus.resolve(aid2, resolver="user:operator", decision="denied")

    history = bus.list_history(limit=10)
    recent = bus.list_recent(limit=10)
    assert [a.id for a in history] == [a.id for a in recent]
    assert {a.id for a in history} == {aid1, aid2}


def test_list_pending_with_limit(tmp_path: Path) -> None:
    """The Tier-1 self-mod tool `approvals_list_pending` passes a limit;
    the bus must accept it without breaking older callers that don't."""
    bus = _make_bus(tmp_path)
    for i in range(5):
        bus.request(
            tool=f"t{i}", namespaced=f"t{i}", actor="agent",
            args={"i": i},
        )
    # Default (no limit) — all 5.
    assert len(bus.list_pending()) == 5
    # With limit — exactly 3 oldest.
    assert len(bus.list_pending(limit=3)) == 3
    assert len(bus.list_pending(limit=100)) == 5


# ─── Schema migration ────────────────────────────────────────────


def test_schema_migration_adds_risk_tier_column(tmp_path: Path) -> None:
    """A bus pointed at a data_root that has a pre-Phase-11 approvals.db
    (no risk_tier column) should ALTER TABLE on init and not crash. We
    simulate by creating a bus, dropping the column manually via raw
    sqlite, then constructing a fresh bus — the migration runs."""
    import sqlite3

    bus1 = _make_bus(tmp_path)
    bus1.request(
        tool="x", namespaced="x", actor="agent", args={}, risk_tier="soft",
    )
    db_path = bus1.db_path

    # Manually drop the column to simulate pre-migration state.
    # SQLite's pre-3.35 ALTER TABLE doesn't support DROP COLUMN; we
    # rebuild the table without risk_tier.
    with sqlite3.connect(db_path) as raw:
        raw.executescript(
            """
            CREATE TABLE approvals_old AS SELECT
                id, created_at, resolved_at, tool, namespaced,
                actor, resolver, status, args_json, reason
            FROM approvals;
            DROP TABLE approvals;
            ALTER TABLE approvals_old RENAME TO approvals;
            """
        )

    # Constructing a fresh bus should ALTER TABLE in _init_schema and
    # treat existing rows as risk_tier='soft'.
    bus2 = _make_bus(tmp_path)
    rows = bus2.list_recent(limit=10)
    assert len(rows) == 1
    assert rows[0].risk_tier == "soft"


# ─── Approval dataclass shape ────────────────────────────────────


def test_approval_to_dict_includes_risk_tier(tmp_path: Path) -> None:
    bus = _make_bus(tmp_path)
    aid = bus.request(
        tool="x", namespaced="x", actor="agent",
        args={}, risk_tier="destructive",
    )
    d = bus.get(aid).to_dict()  # type: ignore[union-attr]
    assert d["risk_tier"] == "destructive"
    # All other documented fields still present.
    assert set(d.keys()) >= {
        "id", "created_at", "resolved_at", "tool", "namespaced",
        "actor", "resolver", "status", "args", "reason", "risk_tier",
    }


# ─── tolerate non-JSON args (Context objects, etc.) ─────


def test_request_handles_non_json_serializable_args(tmp_path: Path) -> None:
    """`Object of type Context is not JSON serializable` must not occur.

    The framework occasionally injects non-JSON-serializable objects
    (e.g. FastMCP Context) into tool kwargs. A bare json.dumps in
    `request()` would raise TypeError, the approval row would never
    land, and the agent would see a 500. `request()` therefore passes a
    json.dumps `default` callback that coerces unknown types to
    f"<{TypeName}>" so the row always lands and the audit trail
    remains intact.
    """
    bus = _make_bus(tmp_path)

    class FakeContext:
        """Stand-in for FastMCP's Context — any non-JSON object works."""

    aid = bus.request(
        tool="caldera.create_operation",
        namespaced="caldera.create_operation",
        actor="agent",
        # Mix in a non-serializable value alongside normal scalars
        # (the real-world failure shape).
        args={"name": "op1", "ctx": FakeContext()},
    )
    # The row must exist (= json.dumps succeeded).
    row = bus.get(aid)
    assert row is not None
    # And the bad value gets coerced to its TypeName, not raw repr().
    assert row.args.get("ctx") == "<FakeContext>"
    # Normal values still pass through unchanged.
    assert row.args.get("name") == "op1"


# ─── instance_trusted bypass ────────────────────────────


def test_needs_human_approval_bypassed_when_instance_trusted() -> None:
    """A trusted instance bypasses the gate even when the tool name
    matches `humanRequired`.

    Use case: a SOC team marks their lab Caldera as trusted: true
    so create_operation runs without human approval. Their
    production Caldera (same connector type, different instance)
    leaves trusted unset and still gates each launch.
    """
    from src.usecase.approvals_bus import needs_human_approval

    # Untrusted: gate fires (baseline).
    assert needs_human_approval(
        tool_name="create_operation",
        namespaced="caldera.create_operation",
        legacy_name="caldera_create_operation",
        human_required={"create_operation"},
    ) is True

    # Trusted: gate is bypassed.
    assert needs_human_approval(
        tool_name="create_operation",
        namespaced="caldera.create_operation",
        legacy_name="caldera_create_operation",
        human_required={"create_operation"},
        instance_trusted=True,
    ) is False

    # Trusted but tool isn't gated anyway: still False (no surprise).
    assert needs_human_approval(
        tool_name="some_read_tool",
        namespaced="caldera.some_read_tool",
        legacy_name=None,
        human_required={"create_operation"},
        instance_trusted=True,
    ) is False


# ─── origin column + contextvar threading ───────────────


def test_request_persists_explicit_origin(tmp_path: Path) -> None:
    """Explicit origin= kwarg lands on the row."""
    bus = _make_bus(tmp_path)
    aid = bus.request(
        tool="personality_update",
        namespaced="personality_update",
        actor="agent",
        args={"k": "v"},
        origin="job:nightly-coverage",
    )
    row = bus.get(aid)
    assert row is not None
    assert row.origin == "job:nightly-coverage"
    assert row.to_dict()["origin"] == "job:nightly-coverage"


def test_request_reads_origin_from_trigger_contextvar(tmp_path: Path) -> None:
    """When no explicit origin is passed, request() picks up the
    X-Phantom-Trigger contextvar that the request middleware sets.
    Mirrors the runtime path: chat handler sets trigger, bus auto-tags.

    Module-path note: the bus uses `from usecase.audit_log import ...`
    while this test file imports via `src.usecase.*` everywhere else.
    Python caches modules by dotted name, so those are TWO DIFFERENT
    module objects with TWO DIFFERENT ContextVar instances even though
    they share the same file. Using importlib to grab the same module
    the bus loads ensures we set the same contextvar the bus reads.
    """
    import importlib
    audit_log = importlib.import_module("usecase.audit_log")

    bus = _make_bus(tmp_path)

    token = audit_log.set_current_trigger("chat:s_42")
    try:
        aid = bus.request(
            tool="personality_update",
            namespaced="personality_update",
            actor="agent",
            args={"k": "v"},
        )
    finally:
        audit_log.reset_current_trigger(token)

    row = bus.get(aid)
    assert row is not None
    assert row.origin == "chat:s_42"


def test_request_origin_defaults_to_unknown(tmp_path: Path) -> None:
    """Without explicit origin AND without contextvar, the row
    defaults to 'unknown'. Rows in legacy DBs read the same way after
    the migration backfills."""
    bus = _make_bus(tmp_path)
    aid = bus.request(
        tool="personality_update",
        namespaced="personality_update",
        actor="agent",
        args={"k": "v"},
    )
    row = bus.get(aid)
    assert row is not None
    assert row.origin == "unknown"


def test_origin_round_trips_through_to_dict(tmp_path: Path) -> None:
    """The origin field shows up in to_dict() so /api/v1/approvals
    consumers see it without an envelope-level translation."""
    bus = _make_bus(tmp_path)
    aid = bus.request(
        tool="personality_update",
        namespaced="personality_update",
        actor="agent",
        args={},
        origin="api",
    )
    d = bus.get(aid).to_dict()  # type: ignore[union-attr]
    assert d["origin"] == "api"
    assert "origin" in d  # explicit field, not buried in args
