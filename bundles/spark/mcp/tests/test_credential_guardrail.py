"""Credential guardrail regression tests (root CLAUDE.md, "Agent credential guardrail").

The agent must never reach a tool that reads, writes, mints or rotates
credentials. One canonical set of names (`usecase.credential_guardrail`)
backs every enforcement point:

  - connector_loader: no credential name in `_BUILTIN_LEGACY_TOOLS`
  - self_mod_tools: no credential name in the `agent_batch_propose` table
  - agent_batch_propose: refuses an action naming one, on both dispatch routes
  - job-scheduler tool dispatcher: refuses one (covers `tool_call` job actions)

`agent_batch_propose` used to dispatch `instances_delete`, `providers_delete`
and `api_keys_*` by name under the approval-bypass contextvar. Each test here
fails against that behaviour.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from usecase import audit_log
from usecase import connector_loader
from usecase import credential_guardrail
from usecase import tool_dispatcher as tool_dispatcher_module
from usecase.approvals_bus import InProcessApprovalsBus, set_approvals_bus
from usecase.builtin_components import _approval_gate, self_mod_tools
from usecase.credential_guardrail import (
    CREDENTIAL_SIDE_TOOLS,
    CredentialGuardrailError,
    assert_no_credential_tools,
    is_credential_tool,
)
from usecase.job_scheduler import make_tool_dispatcher

# The nine names the root CLAUDE.md lists. Spelled out here on purpose: the
# test must fail if someone edits the canonical set without editing the doc.
EXPECTED = {
    "providers_create", "providers_update", "providers_delete",
    "instances_create", "instances_update", "instances_delete",
    "api_keys_create", "api_keys_rotate", "api_keys_revoke",
}


@pytest.fixture(autouse=True)
def _isolation(tmp_path):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "manifest.yaml").write_text(
        "approvals:\n  policy: hybrid\n  humanRequired: []\n", encoding="utf-8",
    )
    prior = os.environ.get("BUNDLE_ROOT")
    os.environ["BUNDLE_ROOT"] = str(bundle)
    set_approvals_bus(InProcessApprovalsBus(data_root=tmp_path, default_timeout_seconds=1))
    _approval_gate._human_required_set.cache_clear()
    self_mod_tools._BATCHABLE_TOOLS.clear()
    tool_dispatcher_module.set_tool_dispatcher(None)
    yield
    set_approvals_bus(None)
    _approval_gate._human_required_set.cache_clear()
    self_mod_tools._BATCHABLE_TOOLS.clear()
    tool_dispatcher_module.set_tool_dispatcher(None)
    if prior is None:
        os.environ.pop("BUNDLE_ROOT", None)
    else:
        os.environ["BUNDLE_ROOT"] = prior


def test_canonical_set_matches_the_documented_list():
    assert set(CREDENTIAL_SIDE_TOOLS) == EXPECTED


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_is_credential_tool_matches_bare_and_namespaced(name):
    assert is_credential_tool(name)
    assert is_credential_tool(f"phantom.{name}")
    assert is_credential_tool(f"phantom/{name}")
    assert is_credential_tool(f"phantom__{name}")


def test_is_credential_tool_does_not_overmatch():
    for ok in ("api_keys_list", "providers_list", "instances_get", "jobs_delete",
               "agent_batch_propose", "", "not-a-str"):
        assert not is_credential_tool(ok)
    assert not is_credential_tool(None)  # type: ignore[arg-type]


def test_assert_no_credential_tools_raises():
    assert_no_credential_tools(["jobs_create"], where="x")
    with pytest.raises(CredentialGuardrailError):
        assert_no_credential_tools(["jobs_create", "api_keys_rotate"], where="x")


# ─── The batch whitelist ───────────────────────────────────────────


def test_no_credential_tool_is_batchable():
    self_mod_tools._populate_batchable_tools()
    leaked = set(self_mod_tools._BATCHABLE_TOOLS) & set(CREDENTIAL_SIDE_TOOLS)
    assert not leaked, f"credential-side tools batchable: {sorted(leaked)}"


def test_populating_the_table_fails_closed_on_overlap(monkeypatch):
    """If someone adds a credential name to the table later, building it raises."""
    monkeypatch.setattr(
        credential_guardrail, "CREDENTIAL_SIDE_TOOLS",
        frozenset(set(CREDENTIAL_SIDE_TOOLS) | {"jobs_create"}),
    )
    with pytest.raises(CredentialGuardrailError):
        self_mod_tools._populate_batchable_tools()
    assert not self_mod_tools._BATCHABLE_TOOLS


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_batch_rejects_each_credential_tool(name):
    out = asyncio.run(self_mod_tools.agent_batch_propose(
        actions=[{"tool": name, "args": {}}],
    ))
    assert out["ok"] is False
    assert "credential" in out["error"].lower()
    assert name in out["error"]
    # Refused before any approval card or execution.
    from usecase.approvals_bus import approvals_bus
    assert approvals_bus().list_pending() == []


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_batch_rejects_credential_tool_even_if_registered(name, monkeypatch):
    """Route 2 (any name in the tool registry, dispatched by name) is a second door."""
    called: list[str] = []

    async def _dispatcher(tool, args):
        called.append(tool)
        return {"ok": True}

    tool_dispatcher_module.set_tool_dispatcher(_dispatcher)
    monkeypatch.setattr(
        connector_loader, "_reload_state",
        {"tool_registry": {name: object(), f"phantom.{name}": object()}},
        raising=False,
    )
    for tool in (name, f"phantom.{name}"):
        out = asyncio.run(self_mod_tools.agent_batch_propose(
            actions=[{"tool": "jobs_create", "args": {}}, {"tool": tool, "args": {}}],
        ))
        assert out["ok"] is False
        assert "credential" in out["error"].lower()
    assert called == []


def test_batch_without_credential_tools_still_validates(tmp_path):
    """Sanity: the new check does not reject ordinary names."""
    out = asyncio.run(self_mod_tools.agent_batch_propose(
        actions=[{"tool": "completely_unknown_tool", "args": {}}],
    ))
    assert "is not a known tool" in out["error"]


# ─── The agent tool catalogue ──────────────────────────────────────


def test_no_credential_tool_in_builtin_legacy_tools():
    registered = {name for name, _fn in connector_loader._BUILTIN_LEGACY_TOOLS}
    assert not (registered & set(CREDENTIAL_SIDE_TOOLS))
    assert_no_credential_tools(registered, where="_BUILTIN_LEGACY_TOOLS")


def test_credential_functions_are_gone_from_the_agent_module():
    """Nothing in the agent-facing module defines these any more, so a later
    whitelist edit cannot re-expose them."""
    for name in ("instances_delete", "providers_delete",
                 "api_keys_create", "api_keys_rotate", "api_keys_revoke"):
        assert not hasattr(self_mod_tools, name), name


def test_read_only_credential_surface_is_still_there():
    registered = {name for name, _fn in connector_loader._BUILTIN_LEGACY_TOOLS}
    assert {"api_keys_list", "providers_list", "instances_list"} <= registered


# ─── The job scheduler / tool dispatcher ───────────────────────────


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_scheduler_dispatcher_refuses_credential_tools(name):
    ran: list[str] = []

    def _fn(**kw):
        ran.append(name)
        return {}

    dispatch = make_tool_dispatcher({name: _fn, f"phantom.{name}": _fn}, mcp=None)
    for tool in (name, f"phantom.{name}"):
        with pytest.raises(CredentialGuardrailError):
            asyncio.run(dispatch(tool, {}))
    assert ran == []


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_job_action_cannot_name_a_credential_tool(name, tmp_path):
    """A `tool_call` job naming one is refused when the job is created."""
    from usecase.job_scheduler import CroniterJobScheduler

    async def _noop(tool, args, **_k):
        return {}

    sched = CroniterJobScheduler(definitions=[], dispatcher=_noop, data_root=tmp_path)
    with pytest.raises(CredentialGuardrailError):
        sched._validate_action({"type": "tool_call", "name": name, "args": {}})
    sched._validate_action({"type": "tool_call", "name": "jobs_list", "args": {}})
