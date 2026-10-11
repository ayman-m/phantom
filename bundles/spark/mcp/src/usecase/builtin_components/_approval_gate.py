"""Approval gate helper for chat-driven self-modification tools.

Wraps any Tier-2/3/4 write operation in an approvals dance:

  if tool_name in manifest.approvals.humanRequired:
      bus.request(...)            # pending row, audit event
      await bus.wait_async(...)   # blocks until operator clicks
      if denied: raise ApprovalDeniedError
      if timeout: raise ApprovalTimeoutError
      executor()                  # run the underlying mutation
  else:
      executor()                  # ungated, run immediately

This module is the per-built-in equivalent of `_wrap_with_instance`'s
gate logic in `connector_loader.py` — connector tools get gated by
the wrapper FastMCP applies; built-in tools (skills_*, memory_*,
agent self-mod) call this helper inline. Both paths use the same
InProcessApprovalsBus, so the operator UI sees uniform approval rows
regardless of which side initiated.

# Why a separate module

Importing the gate inside `self_mod_tools.py` directly would couple
the tool functions to a single import order. Lifting it into a small
shared module lets other built-in modules (credential ops,
agent_skills_create overrides, etc.) reuse the same
wrapper without circular imports.

# Audit

Two events bracket every gated call (manifest.audit.events declares
both):

  agent_self_mod_requested  → emitted on bus.request(); status=pending
  agent_self_mod_executed   → emitted post-execution; status one of
                                {success, failed, denied, timeout}

Operators can audit the agent's self-modification activity by
filtering action ∈ {agent_self_mod_*}.
"""

from __future__ import annotations

import asyncio
import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Awaitable, Callable

logger = logging.getLogger("Phantom MCP")


@lru_cache(maxsize=1)
def _human_required_set() -> frozenset[str]:
    """Read manifest.approvals.humanRequired[] from the bundle.

    Cached on first call (process lifetime) — the manifest is
    immutable at runtime per spec, so re-reading is wasted I/O. Tests
    that need to reset use `_human_required_set.cache_clear()`.
    """
    bundle_root = Path(os.getenv("BUNDLE_ROOT", "/app/bundle"))
    manifest_path = bundle_root / "manifest.yaml"
    if not manifest_path.is_file():
        return frozenset()
    try:
        import yaml
        m = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    except Exception as exc:  # noqa: BLE001
        logger.warning("approval gate: could not parse manifest (%s)", exc)
        return frozenset()
    raw = (m.get("approvals") or {}).get("humanRequired") or []
    out = frozenset(s for s in raw if isinstance(s, str))
    logger.info(
        "approval gate: %d tool(s) require human approval: %s",
        len(out), sorted(out),
    )
    return out


def is_gated(tool_name: str) -> bool:
    """Public API: does this tool require approval?"""
    return tool_name in _human_required_set()


async def gate_and_execute(
    *,
    tool_name: str,
    args: dict[str, Any],
    risk_tier: str,
    executor: Callable[[], Any | Awaitable[Any]],
    actor: str = "agent",
    timeout_seconds: int | None = None,
) -> Any:
    """Run `executor()` under approval gating per manifest.

    Args:
        tool_name: bare tool name (matched against humanRequired[]).
        args: tool-input kwargs. Persisted on the approval row for the
            operator's UI; sanitized for credential leakage by the bus.
        risk_tier: "soft" | "destructive" | "credential" — drives UI
            rendering. (Reads use Tier 1 helpers, never this gate.)
        executor: zero-arg callable that performs the actual mutation.
            Sync or async; both supported. Result is returned
            unchanged on success.
        actor: who's invoking. "agent" for chat-driven self-mod.
            Operator-direct REST calls don't go through this helper.
        timeout_seconds: max wait for operator decision. None uses the
            bus's default (5 minutes).

    Returns:
        Whatever `executor()` returns when approved + executed.

    Raises:
        ApprovalDeniedError: operator clicked "deny".
        ApprovalTimeoutError: no decision within the timeout window.
        Whatever the executor itself raises.
    """
    from usecase.approvals_bus import (
        ApprovalDeniedError,
        ApprovalTimeoutError,
        STATUS_APPROVED,
        STATUS_DENIED,
        STATUS_TIMEOUT,
        approvals_bus,
    )
    from usecase.audit_log import (
        ACTION_AGENT_SELF_MOD_EXECUTED,
        ACTION_AGENT_SELF_MOD_REQUESTED,
        get_current_approval_bypass,
        get_current_trigger,
        record_event,
    )

    gated = is_gated(tool_name)
    approval_id: str | None = None

    # Bypass mode. When the inbound request carried
    # `X-Phantom-Approval-Bypass: 1` (set by chat sessions with the
    # bypass dropdown enabled, or jobs with bypass_approvals=true),
    # skip the operator-confirmation dance and execute immediately.
    # Still record a full audit pair so post-hoc review can surface
    # what happened — `auto_approved=true` + the bypass source so
    # operators can audit which sessions/jobs are running unattended.
    if gated and get_current_approval_bypass():
        trigger = get_current_trigger() or "unknown"
        record_event(
            ACTION_AGENT_SELF_MOD_REQUESTED,
            target=f"bypass:{tool_name}",
            status="auto_approved",
            actor=actor,
            metadata={
                "tool": tool_name,
                "risk_tier": risk_tier,
                "arg_keys": sorted(args.keys()),
                "auto_approved": True,
                "bypass_source": trigger,
            },
        )
        try:
            result = executor()
            if asyncio.iscoroutine(result):
                result = await result
        except Exception as exc:
            record_event(
                ACTION_AGENT_SELF_MOD_EXECUTED,
                target=f"bypass:{tool_name}",
                status="failed",
                actor=actor,
                metadata={
                    "tool": tool_name,
                    "auto_approved": True,
                    "bypass_source": trigger,
                    "error": type(exc).__name__,
                    "message": str(exc)[:200],
                },
            )
            raise
        record_event(
            ACTION_AGENT_SELF_MOD_EXECUTED,
            target=f"bypass:{tool_name}",
            status="success",
            actor=actor,
            metadata={
                "tool": tool_name,
                "auto_approved": True,
                "bypass_source": trigger,
            },
        )
        logger.info(
            "approval bypass: executed gated tool %r without operator "
            "confirmation (source=%s, risk_tier=%s)",
            tool_name, trigger, risk_tier,
        )
        return result

    if gated:
        bus = approvals_bus()
        if bus is None:
            # Fail-closed: better to refuse than to silently bypass the
            # gate. This case shouldn't happen in production (main.py
            # wires the bus at boot) but tests / partial builds might.
            raise ApprovalDeniedError(
                f"tool {tool_name!r} requires approval but the approvals "
                f"bus is not configured on this MCP runtime"
            )
        approval_id = bus.request(
            tool=tool_name,
            namespaced=tool_name,  # built-in: no connector prefix
            actor=actor,
            args=dict(args),
            risk_tier=risk_tier,
        )
        record_event(
            ACTION_AGENT_SELF_MOD_REQUESTED,
            target=f"approval:{approval_id}",
            status="pending",
            actor=actor,
            metadata={
                "approval_id": approval_id,
                "tool": tool_name,
                "risk_tier": risk_tier,
                "arg_keys": sorted(args.keys()),
            },
        )

        status, reason = await bus.wait_async(
            approval_id, timeout=timeout_seconds,
        )

        if status == STATUS_DENIED:
            record_event(
                ACTION_AGENT_SELF_MOD_EXECUTED,
                target=f"approval:{approval_id}",
                status="denied",
                actor=actor,
                metadata={
                    "approval_id": approval_id, "tool": tool_name,
                    "reason": reason,
                },
            )
            raise ApprovalDeniedError(
                f"tool {tool_name!r} denied (approval_id={approval_id}): "
                f"{reason or 'no reason given'}"
            )
        if status == STATUS_TIMEOUT:
            record_event(
                ACTION_AGENT_SELF_MOD_EXECUTED,
                target=f"approval:{approval_id}",
                status="timeout",
                actor=actor,
                metadata={"approval_id": approval_id, "tool": tool_name},
            )
            raise ApprovalTimeoutError(
                f"tool {tool_name!r} approval timeout "
                f"(approval_id={approval_id})"
            )
        if status != STATUS_APPROVED:
            # Defensive — should be unreachable per the bus contract.
            raise ApprovalDeniedError(
                f"tool {tool_name!r} approval ended in unexpected state "
                f"{status!r}"
            )
        # status == STATUS_APPROVED: fall through to execute.

    # Execute (gated-and-approved or ungated).
    try:
        result = executor()
        if asyncio.iscoroutine(result):
            result = await result
    except Exception as exc:
        if gated:
            record_event(
                ACTION_AGENT_SELF_MOD_EXECUTED,
                target=f"approval:{approval_id}",
                status="failed",
                actor=actor,
                metadata={
                    "approval_id": approval_id, "tool": tool_name,
                    "error": type(exc).__name__,
                    "message": str(exc)[:200],
                },
            )
        raise

    if gated:
        record_event(
            ACTION_AGENT_SELF_MOD_EXECUTED,
            target=f"approval:{approval_id}",
            status="success",
            actor=actor,
            metadata={
                "approval_id": approval_id, "tool": tool_name,
            },
        )

    return result
