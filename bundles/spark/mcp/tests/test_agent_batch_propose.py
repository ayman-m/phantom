"""Tests for the multi-action batch tool
(self_mod_tools.agent_batch_propose).

Covers:
  - Validation: empty list / oversize / malformed / missing fields /
    unbatchable tool names / unknown tools
  - Built-in dispatch (fast path) with both happy + failing actions
  - Connector-tool dispatch through the tool_dispatcher
    singleton
  - Bypass contextvar set during execute and reset after (even on
    exception)
  - Partial-success: per-action failures don't abort the loop; the
    final per_action_results map is complete
  - Approve / deny path coverage via the same fixture pattern as
    test_approval_gate.py

The bus is mocked with InProcessApprovalsBus and the test auto-approves
via a background task. This mirrors the pattern in
test_approval_gate.py to keep the test surface uniform.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

import pytest

from usecase.approvals_bus import (
    ApprovalDeniedError,
    InProcessApprovalsBus,
    set_approvals_bus,
)
from usecase.builtin_components import _approval_gate, self_mod_tools
from usecase import audit_log, tool_dispatcher as tool_dispatcher_module
from usecase import metrics_registry as metrics_registry_module


def _seed_manifest_with_gated(tmp_path: Path, gated: list[str]) -> None:
    """Same helper as test_approval_gate.py — write a minimal manifest
    that declares which tools require approval, then point
    BUNDLE_ROOT at it."""
    bundle = tmp_path / "bundle"
    bundle.mkdir(exist_ok=True)
    (bundle / "manifest.yaml").write_text(
        "approvals:\n"
        "  policy: hybrid\n"
        "  humanRequired:\n"
        + "".join(f"    - {g!r}\n" for g in gated),
        encoding="utf-8",
    )
    os.environ["BUNDLE_ROOT"] = str(bundle)


@pytest.fixture(autouse=True)
def _reset_caches(tmp_path):
    """Per-test isolation: fresh approvals bus, fresh dispatcher,
    cleared LRU cache, fresh metrics registry. Anything the test
    leaves behind would break the next one without this."""
    bus = InProcessApprovalsBus(
        data_root=tmp_path, default_timeout_seconds=1,
    )
    set_approvals_bus(bus)
    _approval_gate._human_required_set.cache_clear()
    # _BATCHABLE_TOOLS is a module-level dict populated lazily on first
    # call. Re-population is idempotent, but clearing it gives tests
    # the freedom to monkeypatch the contents.
    self_mod_tools._BATCHABLE_TOOLS.clear()
    tool_dispatcher_module.set_tool_dispatcher(None)
    # Per-test fresh metrics registry so batch counters from
    # one test don't bleed into the next.
    metrics_registry_module.set_metrics_registry(
        metrics_registry_module.MetricsRegistry()
    )
    yield
    set_approvals_bus(None)
    _approval_gate._human_required_set.cache_clear()
    self_mod_tools._BATCHABLE_TOOLS.clear()
    tool_dispatcher_module.set_tool_dispatcher(None)
    metrics_registry_module.set_metrics_registry(None)


async def _auto_approve_after_delay(delay: float = 0.05) -> None:
    """Helper: wait briefly, then approve the single pending row."""
    await asyncio.sleep(delay)
    from usecase.approvals_bus import approvals_bus
    bus = approvals_bus()
    pending = bus.list_pending()
    assert len(pending) == 1, f"expected 1 pending, got {len(pending)}"
    bus.resolve(
        pending[0].id, resolver="user:operator", decision="approved",
    )


async def _auto_deny_after_delay(delay: float = 0.05) -> None:
    """Helper: wait briefly, then deny the single pending row."""
    await asyncio.sleep(delay)
    from usecase.approvals_bus import approvals_bus
    bus = approvals_bus()
    pending = bus.list_pending()
    assert len(pending) == 1
    bus.resolve(
        pending[0].id, resolver="user:operator",
        decision="denied", reason="test denial",
    )


# ─── Validation tests ──────────────────────────────────────────────


def test_empty_actions_rejected(tmp_path):
    """An empty action list never fires an approval card — it's a
    no-op that should be caught before the operator sees anything."""
    _seed_manifest_with_gated(tmp_path, gated=["agent_batch_propose"])
    out = asyncio.run(self_mod_tools.agent_batch_propose(actions=[]))
    assert out["ok"] is False
    assert "non-empty list" in out["error"]


def test_oversize_batch_rejected(tmp_path):
    """26+ actions should bounce with a 'split the request' error.
    The 25-cap protects the approval-card UI from a wall of rows."""
    _seed_manifest_with_gated(tmp_path, gated=["agent_batch_propose"])
    actions = [
        {"tool": "jobs_create", "args": {"name": f"j-{i}"}}
        for i in range(26)
    ]
    out = asyncio.run(self_mod_tools.agent_batch_propose(actions=actions))
    assert out["ok"] is False
    assert "batch too large" in out["error"]


def test_malformed_action_rejected(tmp_path):
    """Each action must be a dict — passing a bare string should
    bounce."""
    _seed_manifest_with_gated(tmp_path, gated=["agent_batch_propose"])
    out = asyncio.run(self_mod_tools.agent_batch_propose(
        actions=["not a dict"],
    ))
    assert out["ok"] is False
    assert "action[0] must be an object" in out["error"]


def test_missing_tool_field_rejected(tmp_path):
    _seed_manifest_with_gated(tmp_path, gated=["agent_batch_propose"])
    out = asyncio.run(self_mod_tools.agent_batch_propose(
        actions=[{"args": {"name": "j"}}],
    ))
    assert out["ok"] is False
    assert "action[0].tool is required" in out["error"]


def test_non_dict_args_rejected(tmp_path):
    _seed_manifest_with_gated(tmp_path, gated=["agent_batch_propose"])
    out = asyncio.run(self_mod_tools.agent_batch_propose(
        actions=[{"tool": "jobs_create", "args": "should be dict"}],
    ))
    assert out["ok"] is False
    assert "action[0].args must be an object" in out["error"]


def test_unbatchable_self_propose_rejected(tmp_path):
    """agent_batch_propose cannot appear inside a batch (no nesting)."""
    _seed_manifest_with_gated(tmp_path, gated=["agent_batch_propose"])
    out = asyncio.run(self_mod_tools.agent_batch_propose(
        actions=[{"tool": "agent_batch_propose", "args": {"actions": []}}],
    ))
    assert out["ok"] is False
    assert "cannot appear inside a batch" in out["error"]


def test_unbatchable_approvals_resolve_rejected(tmp_path):
    """approvals_resolve cannot appear in a batch (loop hazard —
    resolving approvals as part of a batch under approval)."""
    _seed_manifest_with_gated(tmp_path, gated=["agent_batch_propose"])
    out = asyncio.run(self_mod_tools.agent_batch_propose(
        actions=[{"tool": "approvals_resolve", "args": {"id": "x"}}],
    ))
    assert out["ok"] is False
    assert "cannot appear inside a batch" in out["error"]


def test_unknown_tool_rejected(tmp_path):
    """A tool name not in the built-in dispatch table AND not in the
    tool registry should bounce with a descriptive error before any
    approval card fires."""
    _seed_manifest_with_gated(tmp_path, gated=["agent_batch_propose"])
    # No dispatcher installed → connector tools can't be resolved.
    out = asyncio.run(self_mod_tools.agent_batch_propose(
        actions=[{"tool": "completely_unknown_tool", "args": {}}],
    ))
    assert out["ok"] is False
    assert "is not a known tool" in out["error"]


# ─── Built-in dispatch (fast path) ─────────────────────────────────


def test_builtin_happy_path(tmp_path, monkeypatch):
    """Batch of 2 built-in tools, both succeed. Asserts both run +
    the result aggregation is correct."""
    _seed_manifest_with_gated(tmp_path, gated=["agent_batch_propose"])

    calls: list[tuple[str, dict[str, Any]]] = []

    async def _fake_jobs_create(**kw: Any) -> dict[str, Any]:
        calls.append(("jobs_create", kw))
        return {"name": kw.get("name"), "created": True}

    async def _fake_jobs_run_now(**kw: Any) -> dict[str, Any]:
        calls.append(("jobs_run_now", kw))
        return {"name": kw.get("name"), "ran": True}

    self_mod_tools._BATCHABLE_TOOLS.update({
        "jobs_create": _fake_jobs_create,
        "jobs_run_now": _fake_jobs_run_now,
    })
    # Skip the lazy populate by pre-populating with the mocks.
    monkeypatch.setattr(self_mod_tools, "_populate_batchable_tools", lambda: None)

    async def _race() -> dict[str, Any]:
        asyncio.create_task(_auto_approve_after_delay())
        return await self_mod_tools.agent_batch_propose(actions=[
            {"tool": "jobs_create", "args": {"name": "j1"}},
            {"tool": "jobs_run_now", "args": {"name": "j1"}},
        ])

    out = asyncio.run(_race())
    assert out["ok"] is True
    assert out["approved"] is True
    assert out["executed"] == 2
    assert out["succeeded"] == 2
    assert out["failed"] == 0
    assert len(calls) == 2
    assert calls[0] == ("jobs_create", {"name": "j1"})
    assert calls[1] == ("jobs_run_now", {"name": "j1"})
    # Per-action results carry the underlying return shape.
    assert out["per_action_results"][0]["ok"] is True
    assert out["per_action_results"][0]["result"]["created"] is True


def test_builtin_partial_success(tmp_path, monkeypatch):
    """Built-in batch where action 1 succeeds and action 2 returns an
    error dict — the loop continues; final tally is 1/1."""
    _seed_manifest_with_gated(tmp_path, gated=["agent_batch_propose"])

    async def _ok(**kw: Any) -> dict[str, Any]:
        return {"ok": True}

    async def _err(**kw: Any) -> dict[str, Any]:
        return {"error": "synthetic failure"}

    self_mod_tools._BATCHABLE_TOOLS.update({
        "jobs_create": _ok,
        "jobs_update": _err,
    })
    monkeypatch.setattr(self_mod_tools, "_populate_batchable_tools", lambda: None)

    async def _race() -> dict[str, Any]:
        asyncio.create_task(_auto_approve_after_delay())
        return await self_mod_tools.agent_batch_propose(actions=[
            {"tool": "jobs_create", "args": {"name": "j1"}},
            {"tool": "jobs_update", "args": {"name": "j2"}},
        ])

    out = asyncio.run(_race())
    assert out["ok"] is False  # any failure flips overall ok
    assert out["succeeded"] == 1
    assert out["failed"] == 1
    assert out["per_action_results"][0]["ok"] is True
    assert out["per_action_results"][1]["ok"] is False
    assert "synthetic failure" in out["per_action_results"][1]["error"]


def test_builtin_exception_caught(tmp_path, monkeypatch):
    """A built-in tool that raises mid-execute is captured into
    per_action_results as a failure — the rest of the batch continues."""
    _seed_manifest_with_gated(tmp_path, gated=["agent_batch_propose"])

    async def _boom(**kw: Any) -> dict[str, Any]:
        raise RuntimeError("boom")

    async def _ok(**kw: Any) -> dict[str, Any]:
        return {"ok": True}

    self_mod_tools._BATCHABLE_TOOLS.update({
        "jobs_create": _boom,
        "jobs_update": _ok,
    })
    monkeypatch.setattr(self_mod_tools, "_populate_batchable_tools", lambda: None)

    async def _race() -> dict[str, Any]:
        asyncio.create_task(_auto_approve_after_delay())
        return await self_mod_tools.agent_batch_propose(actions=[
            {"tool": "jobs_create", "args": {}},
            {"tool": "jobs_update", "args": {}},
        ])

    out = asyncio.run(_race())
    assert out["succeeded"] == 1
    assert out["failed"] == 1
    # The error envelope captures the exception type + message.
    assert "RuntimeError" in out["per_action_results"][0]["error"]
    assert "boom" in out["per_action_results"][0]["error"]


# ─── Deny + lifecycle ───────────────────────────────────────────────


def test_batch_denied_raises_does_not_execute(tmp_path, monkeypatch):
    """Operator denies the batch → no actions run, error envelope
    returned with ok=False."""
    _seed_manifest_with_gated(tmp_path, gated=["agent_batch_propose"])

    calls: list[str] = []

    async def _fn(**_: Any) -> dict[str, Any]:
        calls.append("ran")
        return {"ok": True}

    self_mod_tools._BATCHABLE_TOOLS.update({"jobs_create": _fn})
    monkeypatch.setattr(self_mod_tools, "_populate_batchable_tools", lambda: None)

    async def _race() -> dict[str, Any]:
        asyncio.create_task(_auto_deny_after_delay())
        return await self_mod_tools.agent_batch_propose(actions=[
            {"tool": "jobs_create", "args": {}},
        ])

    out = asyncio.run(_race())
    # On deny, the gate raises ApprovalDeniedError which the tool
    # catches into a structured envelope.
    assert out["ok"] is False
    assert "denied" in out.get("error", "").lower()
    assert calls == []  # underlying tool never ran


def test_bypass_contextvar_cycle(tmp_path, monkeypatch):
    """The executor sets the approval-bypass
    contextvar before dispatching actions, then resets it after.
    Asserted by sampling get_current_approval_bypass() inside the
    tool function (which sees True while the batch is running) and
    after the batch returns (which is back to False)."""
    _seed_manifest_with_gated(tmp_path, gated=["agent_batch_propose"])

    bypass_seen_during_action: list[bool] = []

    async def _record_bypass(**_: Any) -> dict[str, Any]:
        bypass_seen_during_action.append(
            audit_log.get_current_approval_bypass()
        )
        return {"ok": True}

    self_mod_tools._BATCHABLE_TOOLS.update({"jobs_create": _record_bypass})
    monkeypatch.setattr(self_mod_tools, "_populate_batchable_tools", lambda: None)

    async def _race() -> dict[str, Any]:
        asyncio.create_task(_auto_approve_after_delay())
        return await self_mod_tools.agent_batch_propose(actions=[
            {"tool": "jobs_create", "args": {}},
        ])

    asyncio.run(_race())
    # Inside the action, bypass should be True (the batch's approval
    # covers the nested per-tool gate).
    assert bypass_seen_during_action == [True]
    # After the batch finishes, the contextvar is reset.
    assert audit_log.get_current_approval_bypass() is False


def test_bypass_reset_on_exception(tmp_path, monkeypatch):
    """The bypass contextvar must be reset even if an action raises —
    the try/finally guards against a leaked-bypass state that would
    affect subsequent unrelated tool calls in the same async context."""
    _seed_manifest_with_gated(tmp_path, gated=["agent_batch_propose"])

    async def _boom(**_: Any) -> dict[str, Any]:
        raise RuntimeError("intentional")

    self_mod_tools._BATCHABLE_TOOLS.update({"jobs_create": _boom})
    monkeypatch.setattr(self_mod_tools, "_populate_batchable_tools", lambda: None)

    async def _race() -> dict[str, Any]:
        asyncio.create_task(_auto_approve_after_delay())
        return await self_mod_tools.agent_batch_propose(actions=[
            {"tool": "jobs_create", "args": {}},
        ])

    asyncio.run(_race())
    # Exception was captured per-action, so the outer call returns
    # cleanly with failed=1. The contextvar must still be reset.
    assert audit_log.get_current_approval_bypass() is False


# ─── Connector-tool dispatch ──────────────────────────────


def test_connector_tool_routes_through_dispatcher(tmp_path, monkeypatch):
    """A tool not in _BATCHABLE_TOOLS but present in the
    tool_registry should dispatch via tool_dispatcher (the same
    fastmcp.Client path the scheduler uses)."""
    _seed_manifest_with_gated(tmp_path, gated=["agent_batch_propose"])

    # Fake registry — the connector_loader's private _reload_state
    # holds tool_registry; agent_batch_propose's validation peeks at it.
    from usecase import connector_loader
    monkeypatch.setattr(
        connector_loader, "_reload_state",
        {"tool_registry": {"xsiam.send_webhook_log": None}},
        raising=False,
    )

    # Fake dispatcher records calls.
    dispatched: list[tuple[str, dict[str, Any]]] = []

    async def _fake_dispatch(name: str, kwargs: dict[str, Any]) -> Any:
        dispatched.append((name, kwargs))
        return {"sent": True, "tool": name}

    tool_dispatcher_module.set_tool_dispatcher(_fake_dispatch)
    monkeypatch.setattr(self_mod_tools, "_populate_batchable_tools", lambda: None)

    async def _race() -> dict[str, Any]:
        asyncio.create_task(_auto_approve_after_delay())
        return await self_mod_tools.agent_batch_propose(actions=[
            {"tool": "xsiam.send_webhook_log", "args": {"payload": {"x": 1}}},
        ])

    out = asyncio.run(_race())
    assert out["ok"] is True
    assert out["succeeded"] == 1
    assert len(dispatched) == 1
    assert dispatched[0][0] == "xsiam.send_webhook_log"
    assert dispatched[0][1] == {"payload": {"x": 1}}
    assert out["per_action_results"][0]["result"]["sent"] is True


def test_connector_tool_not_in_registry_rejected(tmp_path):
    """Pre-flight check — if the tool isn't in the registry
    AND isn't a built-in, fail fast BEFORE the approval card fires."""
    _seed_manifest_with_gated(tmp_path, gated=["agent_batch_propose"])

    # No dispatcher installed; no registry → connector tools can't
    # resolve.
    out = asyncio.run(self_mod_tools.agent_batch_propose(actions=[
        {"tool": "xsiam.nonexistent_tool", "args": {}},
    ]))
    assert out["ok"] is False
    assert "is not a known tool" in out["error"]


def test_mixed_builtin_and_connector_batch(tmp_path, monkeypatch):
    """A batch with both built-in and connector tools dispatches each
    via the correct route."""
    _seed_manifest_with_gated(tmp_path, gated=["agent_batch_propose"])

    # Built-in.
    builtin_calls: list[str] = []

    async def _builtin(**_: Any) -> dict[str, Any]:
        builtin_calls.append("ok")
        return {"ok": True}

    self_mod_tools._BATCHABLE_TOOLS.update({"jobs_create": _builtin})

    # Connector + dispatcher.
    from usecase import connector_loader
    monkeypatch.setattr(
        connector_loader, "_reload_state",
        {"tool_registry": {"caldera.list_agents": None}},
        raising=False,
    )

    dispatched: list[str] = []

    async def _fake_dispatch(name: str, kwargs: dict[str, Any]) -> Any:
        dispatched.append(name)
        return {"agents": []}

    tool_dispatcher_module.set_tool_dispatcher(_fake_dispatch)
    monkeypatch.setattr(self_mod_tools, "_populate_batchable_tools", lambda: None)

    async def _race() -> dict[str, Any]:
        asyncio.create_task(_auto_approve_after_delay())
        return await self_mod_tools.agent_batch_propose(actions=[
            {"tool": "jobs_create", "args": {"name": "j1"}},
            {"tool": "caldera.list_agents", "args": {}},
        ])

    out = asyncio.run(_race())
    assert out["succeeded"] == 2
    assert out["failed"] == 0
    # Each route fired exactly once.
    assert builtin_calls == ["ok"]
    assert dispatched == ["caldera.list_agents"]


# ─── Approval card payload shape ────────────────────────────────────


def test_approval_row_contains_actions_list(tmp_path, monkeypatch):
    """The approval row's args payload includes the actions array
    (so the UI can render the batch list view). The summary string
    is also present for audit-log readability."""
    _seed_manifest_with_gated(tmp_path, gated=["agent_batch_propose"])

    async def _fn(**_: Any) -> dict[str, Any]:
        return {"ok": True}

    self_mod_tools._BATCHABLE_TOOLS.update({
        "jobs_create": _fn, "jobs_update": _fn,
    })
    monkeypatch.setattr(self_mod_tools, "_populate_batchable_tools", lambda: None)

    captured_args: dict[str, Any] = {}

    async def _race() -> dict[str, Any]:
        async def _capture_then_approve() -> None:
            await asyncio.sleep(0.05)
            from usecase.approvals_bus import approvals_bus
            bus = approvals_bus()
            pending = bus.list_pending()
            assert len(pending) == 1
            # Grab the args from the pending approval row for assertion.
            captured_args.update(pending[0].args)
            bus.resolve(
                pending[0].id, resolver="user:operator",
                decision="approved",
            )

        asyncio.create_task(_capture_then_approve())
        return await self_mod_tools.agent_batch_propose(actions=[
            {"tool": "jobs_create", "args": {"name": "j1"}},
            {"tool": "jobs_update", "args": {"name": "j2"}},
        ])

    asyncio.run(_race())
    assert "actions" in captured_args
    assert len(captured_args["actions"]) == 2
    assert captured_args["actions"][0]["tool"] == "jobs_create"
    assert captured_args["actions"][1]["tool"] == "jobs_update"
    assert captured_args["action_count"] == 2
    # Summary string is pre-computed by _summarize_batch.
    assert "batch of 2" in captured_args["summary"]
    assert "jobs_create" in captured_args["summary"]
    assert "jobs_update" in captured_args["summary"]
    # batch_id is a UUID-shaped string.
    assert len(captured_args["batch_id"]) == 36  # UUID4 hex+dashes


# ─── metric emission ───────────────────────────────────────


def _counter_total(reg, name: str) -> float:
    """Sum all label-keyed values for a counter — convenient for tests
    that don't care which label combo fired, just whether the metric
    incremented at all."""
    c = reg.get(name)
    if c is None:
        return 0.0
    return sum(c._values.values())  # type: ignore[attr-defined]


def _counter_value(reg, name: str, **labels: str) -> float:
    """Read the value at one specific label combination."""
    c = reg.get(name)
    if c is None:
        return 0.0
    key = tuple(sorted((k, str(v)) for k, v in labels.items()))
    return c._values.get(key, 0.0)  # type: ignore[attr-defined]


def test_metrics_emitted_on_approve(tmp_path, monkeypatch):
    """An approved batch increments
    phantom_batch_proposals_total{approved=true} once + observes the
    size in phantom_batch_size + increments
    phantom_batch_actions_total{tool=...,result=success} per action."""
    _seed_manifest_with_gated(tmp_path, gated=["agent_batch_propose"])

    async def _fn(**_: Any) -> dict[str, Any]:
        return {"ok": True}

    self_mod_tools._BATCHABLE_TOOLS.update({"jobs_create": _fn})
    monkeypatch.setattr(self_mod_tools, "_populate_batchable_tools", lambda: None)

    async def _race() -> dict[str, Any]:
        asyncio.create_task(_auto_approve_after_delay())
        return await self_mod_tools.agent_batch_propose(actions=[
            {"tool": "jobs_create", "args": {"name": "j1"}},
            {"tool": "jobs_create", "args": {"name": "j2"}},
        ])

    asyncio.run(_race())

    reg = metrics_registry_module.metrics_registry()
    # Proposal counter: one inc at approved=true.
    assert _counter_value(reg, "phantom_batch_proposals_total", approved="true") == 1
    assert _counter_value(reg, "phantom_batch_proposals_total", approved="false") == 0
    # Action counter: 2× jobs_create / success.
    assert _counter_value(
        reg, "phantom_batch_actions_total", tool="jobs_create", result="success",
    ) == 2
    # Histogram exists + has one observation (size=2).
    h = reg.get("phantom_batch_size")
    assert h is not None
    # The histogram's _data dict has one entry with count=1, sum=2.
    data = list(h._data.values())  # type: ignore[attr-defined]
    assert len(data) == 1
    assert data[0]["count"] == 1
    assert data[0]["sum"] == 2.0


def test_metrics_emitted_on_deny(tmp_path, monkeypatch):
    """A denied batch increments
    phantom_batch_proposals_total{approved=false}. No
    phantom_batch_actions_total increments (nothing ran).
    Size is still observed (operator denial of a 3-action batch is
    a meaningful data point)."""
    _seed_manifest_with_gated(tmp_path, gated=["agent_batch_propose"])

    async def _fn(**_: Any) -> dict[str, Any]:
        return {"ok": True}

    self_mod_tools._BATCHABLE_TOOLS.update({"jobs_create": _fn})
    monkeypatch.setattr(self_mod_tools, "_populate_batchable_tools", lambda: None)

    async def _race() -> dict[str, Any]:
        asyncio.create_task(_auto_deny_after_delay())
        return await self_mod_tools.agent_batch_propose(actions=[
            {"tool": "jobs_create", "args": {}},
            {"tool": "jobs_create", "args": {}},
            {"tool": "jobs_create", "args": {}},
        ])

    asyncio.run(_race())

    reg = metrics_registry_module.metrics_registry()
    # Denial recorded.
    assert _counter_value(reg, "phantom_batch_proposals_total", approved="false") == 1
    assert _counter_value(reg, "phantom_batch_proposals_total", approved="true") == 0
    # NO action increments (executor never ran).
    assert _counter_total(reg, "phantom_batch_actions_total") == 0
    # Size still observed.
    h = reg.get("phantom_batch_size")
    assert h is not None
    data = list(h._data.values())  # type: ignore[attr-defined]
    assert len(data) == 1
    assert data[0]["sum"] == 3.0


def test_action_metric_records_fail_on_error_dict(tmp_path, monkeypatch):
    """When an action returns {error: ...}, the action counter
    increments at result=fail (not success). Distinguishes per-tool
    flakiness from per-tool usage in dashboards."""
    _seed_manifest_with_gated(tmp_path, gated=["agent_batch_propose"])

    async def _ok(**_: Any) -> dict[str, Any]:
        return {"ok": True}

    async def _err(**_: Any) -> dict[str, Any]:
        return {"error": "store unavailable"}

    self_mod_tools._BATCHABLE_TOOLS.update({
        "jobs_create": _ok, "jobs_update": _err,
    })
    monkeypatch.setattr(self_mod_tools, "_populate_batchable_tools", lambda: None)

    async def _race() -> dict[str, Any]:
        asyncio.create_task(_auto_approve_after_delay())
        return await self_mod_tools.agent_batch_propose(actions=[
            {"tool": "jobs_create", "args": {}},
            {"tool": "jobs_update", "args": {}},
        ])

    asyncio.run(_race())

    reg = metrics_registry_module.metrics_registry()
    assert _counter_value(
        reg, "phantom_batch_actions_total", tool="jobs_create", result="success",
    ) == 1
    assert _counter_value(
        reg, "phantom_batch_actions_total", tool="jobs_update", result="fail",
    ) == 1


def test_metrics_silent_when_registry_unavailable(tmp_path, monkeypatch):
    """Metrics emission must NEVER affect the tool's primary
    path. When the registry is None (test harness, partial boot),
    the tool still completes successfully — silent no-op on metrics."""
    _seed_manifest_with_gated(tmp_path, gated=["agent_batch_propose"])

    # Drop the registry entirely.
    metrics_registry_module.set_metrics_registry(None)

    async def _fn(**_: Any) -> dict[str, Any]:
        return {"ok": True}

    self_mod_tools._BATCHABLE_TOOLS.update({"jobs_create": _fn})
    monkeypatch.setattr(self_mod_tools, "_populate_batchable_tools", lambda: None)

    async def _race() -> dict[str, Any]:
        asyncio.create_task(_auto_approve_after_delay())
        return await self_mod_tools.agent_batch_propose(actions=[
            {"tool": "jobs_create", "args": {}},
        ])

    out = asyncio.run(_race())
    # Primary path unaffected — batch completed cleanly.
    assert out["ok"] is True
    assert out["executed"] == 1
    assert out["succeeded"] == 1
