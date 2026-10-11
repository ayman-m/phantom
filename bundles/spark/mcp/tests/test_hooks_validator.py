"""MCP-side hook payload validator.

Covers `_validate_hook_payload` in `api/hooks.py`. The MCP validator is
intentionally minimal — the agent's `validateHook` in
`mcp/agent/lib/hooks.ts` does the heavy schema work. MCP-side blocks
obvious tampering (unknown events, missing transport fields) so a hand-
crafted POST can't inject malformed records into the SqliteHookStore.

These tests anchor the contract for the builtin transport shape AND the
command / http / agent shapes.
"""

from __future__ import annotations

import pytest

from src.api.hooks import _validate_hook_payload, KNOWN_HOOK_EVENTS


# ─── Shared fixtures ─────────────────────────────────────────────────


def _base_payload(**overrides):
    """A minimum-valid payload (http transport). Tests override the
    fields they care about; everything else stays valid by default."""
    payload = {
        "name": "test-hook",
        "event": "PreToolUse",
        "transport": {"type": "http", "url": "https://example.com/hook"},
    }
    payload.update(overrides)
    return payload


# ─── Required-field validation ───────────────────────────────────────


def test_missing_name_rejected():
    p = _base_payload()
    del p["name"]
    err = _validate_hook_payload(p)
    assert err is not None
    assert "name" in err


def test_empty_name_rejected():
    err = _validate_hook_payload(_base_payload(name="   "))
    assert err is not None
    assert "name" in err


def test_unknown_event_rejected():
    err = _validate_hook_payload(_base_payload(event="HypotheticalEvent"))
    assert err is not None
    assert "event" in err


def test_all_known_events_accepted():
    """Sanity check — every event listed in KNOWN_HOOK_EVENTS validates."""
    for ev in KNOWN_HOOK_EVENTS:
        err = _validate_hook_payload(_base_payload(event=ev))
        assert err is None, f"event {ev!r} should validate but got: {err}"


def test_missing_transport_rejected():
    p = _base_payload()
    del p["transport"]
    err = _validate_hook_payload(p)
    assert err is not None
    assert "transport" in err


# ─── Command / http / agent transport shapes ───────────────


def test_command_transport_valid():
    err = _validate_hook_payload(
        _base_payload(transport={"type": "command", "command": "/bin/echo"})
    )
    assert err is None


def test_command_transport_missing_command_rejected():
    err = _validate_hook_payload(_base_payload(transport={"type": "command"}))
    assert err is not None
    assert "command" in err


def test_http_transport_valid():
    err = _validate_hook_payload(
        _base_payload(transport={"type": "http", "url": "https://example.com"})
    )
    assert err is None


def test_http_transport_missing_url_rejected():
    err = _validate_hook_payload(_base_payload(transport={"type": "http"}))
    assert err is not None
    assert "url" in err


def test_agent_transport_valid():
    err = _validate_hook_payload(
        _base_payload(transport={"type": "agent", "toolName": "plugin_check"})
    )
    assert err is None


def test_agent_transport_missing_toolname_rejected():
    err = _validate_hook_payload(_base_payload(transport={"type": "agent"}))
    assert err is not None
    assert "toolName" in err


def test_unknown_transport_type_rejected():
    err = _validate_hook_payload(
        _base_payload(transport={"type": "telepathic", "command": "x"})
    )
    assert err is not None
    assert "transport.type" in err


# ─── Builtin transport ─────────────────────────


def test_builtin_transport_valid():
    """Minimal valid builtin transport — name + config object."""
    err = _validate_hook_payload(
        _base_payload(
            transport={
                "type": "builtin",
                "name": "slack-approval",
                "config": {"webhookUrl": "https://recv.example.com"},
            }
        )
    )
    assert err is None


def test_builtin_transport_missing_name_rejected():
    err = _validate_hook_payload(
        _base_payload(transport={"type": "builtin", "config": {}})
    )
    assert err is not None
    assert "transport.name" in err


def test_builtin_transport_empty_name_rejected():
    err = _validate_hook_payload(
        _base_payload(
            transport={"type": "builtin", "name": "   ", "config": {}}
        )
    )
    assert err is not None
    assert "transport.name" in err


def test_builtin_transport_missing_config_rejected():
    err = _validate_hook_payload(
        _base_payload(transport={"type": "builtin", "name": "slack-approval"})
    )
    assert err is not None
    assert "transport.config" in err


def test_builtin_transport_non_dict_config_rejected():
    """Config must be an object, not a string / array / null."""
    for bad in ("string", ["array"], 42, None):
        err = _validate_hook_payload(
            _base_payload(
                transport={
                    "type": "builtin",
                    "name": "slack-approval",
                    "config": bad,
                }
            )
        )
        assert err is not None, f"config {bad!r} should be rejected"
        assert "transport.config" in err


def test_builtin_transport_unknown_name_accepted_by_mcp():
    """MCP-side validator does NOT enforce that the builtin name is
    registered. That's the agent's job (it owns the registry). The MCP
    just stores the JSON blob — trusting the agent's richer
    validateConfig to gate writes from the UI/REST clients."""
    err = _validate_hook_payload(
        _base_payload(
            transport={
                "type": "builtin",
                "name": "hypothetical-future-builtin",
                "config": {},
            }
        )
    )
    assert err is None  # MCP accepts; agent-side validateHook would reject


# ─── Cross-cutting policy / timeout validation ───────────────────────


@pytest.mark.parametrize("timeout", [99, 60001, -1, "string"])
def test_invalid_timeouts_rejected(timeout):
    err = _validate_hook_payload(_base_payload(timeoutMs=timeout))
    assert err is not None
    assert "timeoutMs" in err


@pytest.mark.parametrize("timeout", [100, 5000, 60000])
def test_valid_timeouts_accepted(timeout):
    err = _validate_hook_payload(_base_payload(timeoutMs=timeout))
    assert err is None


@pytest.mark.parametrize("policy", ["block", "allow", "warn"])
def test_valid_failure_policy_accepted(policy):
    err = _validate_hook_payload(_base_payload(failurePolicy=policy))
    assert err is None


def test_invalid_failure_policy_rejected():
    err = _validate_hook_payload(_base_payload(failurePolicy="terminate"))
    assert err is not None
    assert "failurePolicy" in err
