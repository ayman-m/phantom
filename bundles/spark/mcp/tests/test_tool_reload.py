"""Tests for register_all_tools() idempotency and reload_tools_now()
wiring. Doesn't exercise the FastMCP HTTP surface — that's covered
in live end-to-end checks."""

from __future__ import annotations

from typing import Any

import pytest

from usecase.connector_loader import (
    register_all_tools,
    reload_tools_now,
    set_reload_state,
    ToolRegistration,
)


class _FakeMCP:
    """Records every (name, callable) pair `mcp.tool()(callable)` would
    register. Mimics the FastMCP API surface enough that
    register_all_tools() runs end-to-end."""

    def __init__(self) -> None:
        self.registrations: list[tuple[str, Any]] = []

    def tool(self, name: str):
        def decorator(fn):
            self.registrations.append((name, fn))
            return fn
        return decorator


@pytest.fixture(autouse=True)
def reset_module_state(monkeypatch):
    """Each test starts from a fresh _reload_state."""
    import usecase.connector_loader as loader
    monkeypatch.setattr(loader, "_reload_state", None)


def test_register_all_tools_first_pass(monkeypatch):
    """First call registers everything yielded by iter_registrations.

    Patch iter_registrations to emit a controlled set so we don't
    need a real bundle on disk."""
    import usecase.connector_loader as loader

    def fake_iter(**kw):
        # Yield 3 connector-like tools + 1 built-in (no legacy alias).
        yield ToolRegistration(
            namespaced_name="caldera.start", legacy_name="caldera_start",
            callable=lambda: None, connector_id="caldera",
        )
        yield ToolRegistration(
            namespaced_name="caldera.stop", legacy_name="caldera_stop",
            callable=lambda: None, connector_id="caldera",
        )
        yield ToolRegistration(
            namespaced_name="xsiam.run_xql", legacy_name="xsiam_run_xql_query",
            callable=lambda: None, connector_id="xsiam",
        )
        yield ToolRegistration(
            namespaced_name="builtin_tool", legacy_name=None,
            callable=lambda: None, connector_id=None,
        )

    monkeypatch.setattr(loader, "iter_registrations", fake_iter)

    mcp = _FakeMCP()
    registry: dict[str, Any] = {}
    ns, legacy = register_all_tools(
        mcp=mcp, store=None, secret_store=None,
        tool_registry=registry, include_legacy=True,
    )
    # 4 namespaced (caldera.start, caldera.stop, xsiam.run_xql, builtin_tool)
    # 3 legacy aliases (caldera_start, caldera_stop, xsiam_run_xql_query)
    # builtin_tool has no legacy alias (legacy_name=None).
    assert ns == 4
    assert legacy == 3
    assert len(registry) == 4 + 3
    assert "caldera.start" in registry
    assert "caldera_start" in registry  # legacy alias
    assert "builtin_tool" in registry


def test_register_all_tools_re_registers_each_call(monkeypatch):
    """Second call with the same iter_registrations output re-registers
    everything (NOT idempotent skip-mode). This is intentional: when
    setup replace:true recreates instances, the OLD wrappers held
    closure refs to deleted instance objects and must be replaced.
    FastMCP overrides on duplicate-name; the warning it logs is benign."""
    import usecase.connector_loader as loader

    def fake_iter(**kw):
        yield ToolRegistration(
            namespaced_name="xsiam.run_xql", legacy_name="xsiam_run_xql_query",
            callable=lambda: None, connector_id="xsiam",
        )

    monkeypatch.setattr(loader, "iter_registrations", fake_iter)
    mcp = _FakeMCP()
    registry: dict[str, Any] = {}

    ns1, lg1 = register_all_tools(
        mcp=mcp, store=None, secret_store=None,
        tool_registry=registry, include_legacy=True,
    )
    assert (ns1, lg1) == (1, 1)

    ns2, lg2 = register_all_tools(
        mcp=mcp, store=None, secret_store=None,
        tool_registry=registry, include_legacy=True,
    )
    # Both passes register the full set. Counts are TOTAL not delta.
    assert (ns2, lg2) == (1, 1)
    # mcp.tool() called twice on first pass + twice on second = 4 total.
    assert len(mcp.registrations) == 4


def test_register_all_tools_picks_up_new_instances(monkeypatch):
    """Simulate the hot-reload scenario: first call sees 1 connector,
    operator creates a second instance, second call sees 2 connectors."""
    import usecase.connector_loader as loader

    def fake_iter_v1(**kw):
        yield ToolRegistration(
            namespaced_name="caldera.start", legacy_name="caldera_start",
            callable=lambda: None, connector_id="caldera",
        )

    monkeypatch.setattr(loader, "iter_registrations", fake_iter_v1)
    mcp = _FakeMCP()
    registry: dict[str, Any] = {}

    ns1, lg1 = register_all_tools(
        mcp=mcp, store=None, secret_store=None,
        tool_registry=registry, include_legacy=True,
    )
    assert ns1 == 1

    # Operator just materialized an xsiam instance; iter_registrations
    # now yields more.
    def fake_iter_v2(**kw):
        yield ToolRegistration(
            namespaced_name="caldera.start", legacy_name="caldera_start",
            callable=lambda: None, connector_id="caldera",
        )
        yield ToolRegistration(
            namespaced_name="xsiam.run_xql", legacy_name="xsiam_run_xql_query",
            callable=lambda: None, connector_id="xsiam",
        )

    monkeypatch.setattr(loader, "iter_registrations", fake_iter_v2)
    ns2, lg2 = register_all_tools(
        mcp=mcp, store=None, secret_store=None,
        tool_registry=registry, include_legacy=True,
    )
    # Both connectors are now live; counts reflect total registrations.
    assert (ns2, lg2) == (2, 2)
    assert "xsiam.run_xql" in registry
    assert "xsiam_run_xql_query" in registry
    # caldera was re-registered too (FastMCP overrides on duplicate).
    assert sum(1 for n, _ in mcp.registrations if n == "caldera.start") == 2


def test_legacy_alias_off_skips_aliases(monkeypatch):
    """include_legacy=False suppresses the alias registration."""
    import usecase.connector_loader as loader

    def fake_iter(**kw):
        # Helper passes include_legacy_aliases through to iter_registrations,
        # so a real iter_registrations would yield no legacy_name when it's
        # off. We model that here.
        legacy = "caldera_start" if kw.get("include_legacy_aliases") else None
        yield ToolRegistration(
            namespaced_name="caldera.start", legacy_name=legacy,
            callable=lambda: None, connector_id="caldera",
        )

    monkeypatch.setattr(loader, "iter_registrations", fake_iter)
    mcp = _FakeMCP()
    registry: dict[str, Any] = {}
    ns, lg = register_all_tools(
        mcp=mcp, store=None, secret_store=None,
        tool_registry=registry, include_legacy=False,
    )
    assert (ns, lg) == (1, 0)
    assert "caldera_start" not in registry


def test_reload_tools_now_returns_none_when_not_wired():
    """Without set_reload_state(), reload_tools_now() must safely
    return None instead of crashing — admin endpoint surfaces a 503."""
    assert reload_tools_now() is None


def test_reload_tools_now_uses_wired_state(monkeypatch):
    """set_reload_state() captures the args; reload_tools_now() uses
    them on every call. New tools added between calls show up."""
    import usecase.connector_loader as loader

    yielded: list[ToolRegistration] = [
        ToolRegistration(
            namespaced_name="a", legacy_name=None,
            callable=lambda: None, connector_id="x",
        )
    ]

    def fake_iter(**kw):
        for r in yielded:
            yield r

    monkeypatch.setattr(loader, "iter_registrations", fake_iter)
    mcp = _FakeMCP()
    registry: dict[str, Any] = {}

    set_reload_state(
        mcp=mcp, store=None, secret_store=None,
        tool_registry=registry, include_legacy=False,
    )

    result1 = reload_tools_now()
    assert result1 == (1, 0)
    assert "a" in registry

    # Add another tool; reload picks it up. Returns total counts.
    yielded.append(ToolRegistration(
        namespaced_name="b", legacy_name=None,
        callable=lambda: None, connector_id="y",
    ))
    result2 = reload_tools_now()
    assert result2 == (2, 0)
    assert "b" in registry
    assert "a" in registry
