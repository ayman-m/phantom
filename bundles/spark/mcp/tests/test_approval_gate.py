"""Tests for the agent self-modification approval gate
(_approval_gate.gate_and_execute).

Covers:
  - ungated tool runs immediately (no approval row created)
  - gated tool with approve happy-path: requests, waits, runs
  - gated tool with deny: raises ApprovalDeniedError, doesn't run
  - gated tool with timeout: raises ApprovalTimeoutError
  - bus not configured: raises ApprovalDeniedError (fail-closed)
  - both sync and async executors are supported
  - actor cannot resolve own request (integration with bus invariant)
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from usecase.approvals_bus import (
    ApprovalDeniedError,
    ApprovalTimeoutError,
    InProcessApprovalsBus,
    set_approvals_bus,
)
from usecase.builtin_components import _approval_gate


@pytest.fixture(autouse=True)
def _reset_caches(monkeypatch, tmp_path):
    bus = InProcessApprovalsBus(
        data_root=tmp_path, default_timeout_seconds=1,
    )
    set_approvals_bus(bus)
    _approval_gate._human_required_set.cache_clear()
    yield
    set_approvals_bus(None)
    _approval_gate._human_required_set.cache_clear()


def _seed_manifest_with_gated(tmp_path: Path, gated: list[str]) -> None:
    import os
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


def test_ungated_tool_runs_immediately(tmp_path):
    _seed_manifest_with_gated(tmp_path, gated=[])
    calls: list[int] = []

    def _run() -> dict[str, Any]:
        calls.append(1)
        return {"ok": True, "value": 42}

    out = asyncio.run(_approval_gate.gate_and_execute(
        tool_name="some_ungated_tool",
        args={"x": 1},
        risk_tier="soft",
        executor=_run,
    ))
    assert out == {"ok": True, "value": 42}
    assert calls == [1]


def test_gated_tool_runs_after_approval(tmp_path):
    _seed_manifest_with_gated(tmp_path, gated=["personality_update"])
    calls: list[int] = []

    def _run() -> dict[str, Any]:
        calls.append(1)
        return {"version": 5}

    async def _race() -> dict[str, Any]:
        async def _approve_after_delay() -> None:
            await asyncio.sleep(0.05)
            from usecase.approvals_bus import approvals_bus
            bus = approvals_bus()
            pending = bus.list_pending()
            assert len(pending) == 1
            bus.resolve(pending[0].id, resolver="user:operator", decision="approved")

        asyncio.create_task(_approve_after_delay())
        return await _approval_gate.gate_and_execute(
            tool_name="personality_update",
            args={"blob_keys": ["responseStyle"]},
            risk_tier="soft",
            executor=_run,
        )

    out = asyncio.run(_race())
    assert out == {"version": 5}
    assert calls == [1]


def test_gated_tool_denied_raises(tmp_path):
    _seed_manifest_with_gated(tmp_path, gated=["personality_update"])
    calls: list[int] = []

    def _run() -> Any:
        calls.append(1)
        return {"should not run": True}

    async def _race() -> Any:
        async def _deny_after_delay() -> None:
            await asyncio.sleep(0.05)
            from usecase.approvals_bus import approvals_bus
            bus = approvals_bus()
            pending = bus.list_pending()
            bus.resolve(
                pending[0].id, resolver="user:operator",
                decision="denied", reason="not now",
            )

        asyncio.create_task(_deny_after_delay())
        return await _approval_gate.gate_and_execute(
            tool_name="personality_update",
            args={"blob_keys": []},
            risk_tier="soft",
            executor=_run,
        )

    with pytest.raises(ApprovalDeniedError, match="denied"):
        asyncio.run(_race())
    assert calls == []


def test_gated_tool_timeout_raises(tmp_path):
    _seed_manifest_with_gated(tmp_path, gated=["personality_update"])

    def _run() -> Any:  # pragma: no cover
        raise AssertionError("must not run on timeout")

    with pytest.raises(ApprovalTimeoutError, match="timeout"):
        asyncio.run(_approval_gate.gate_and_execute(
            tool_name="personality_update",
            args={},
            risk_tier="soft",
            executor=_run,
            timeout_seconds=1,
        ))


def test_no_bus_fails_closed(tmp_path):
    _seed_manifest_with_gated(tmp_path, gated=["personality_update"])
    set_approvals_bus(None)

    def _run() -> Any:  # pragma: no cover
        raise AssertionError("must not run when bus missing")

    with pytest.raises(ApprovalDeniedError, match="bus is not configured"):
        asyncio.run(_approval_gate.gate_and_execute(
            tool_name="personality_update",
            args={},
            risk_tier="soft",
            executor=_run,
        ))


def test_async_executor_supported(tmp_path):
    _seed_manifest_with_gated(tmp_path, gated=[])

    async def _run_async() -> dict[str, Any]:
        await asyncio.sleep(0)
        return {"async": True}

    out = asyncio.run(_approval_gate.gate_and_execute(
        tool_name="anything",
        args={},
        risk_tier="soft",
        executor=_run_async,
    ))
    assert out == {"async": True}


def test_agent_cannot_self_resolve_via_gate(tmp_path):
    """Integration: bus invariant — agent that issued a request
    cannot resolve as the same actor."""
    _seed_manifest_with_gated(tmp_path, gated=["personality_update"])

    from usecase.approvals_bus import (
        ApprovalSelfResolveError, approvals_bus,
    )

    bus = approvals_bus()
    aid = bus.request(
        tool="personality_update",
        namespaced="personality_update",
        actor="agent",
        args={},
        risk_tier="soft",
    )
    with pytest.raises(ApprovalSelfResolveError):
        bus.resolve(aid, resolver="agent", decision="approved")
