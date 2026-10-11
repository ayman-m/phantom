"""Unit tests for the process-wide tool_dispatcher singleton.

The singleton is small (set/get accessors for a module-level holder)
but it's load-bearing — agent_batch_propose and the job
scheduler both consume it. These tests assert
the lifecycle contract (uninstalled → installed → cleared → re-installed)
directly so future refactors that touch the accessors get a fast
signal if the contract drifts.

Why direct tests rather than relying on integration coverage:
  - test_agent_batch_propose's connector-dispatch cases install the
    singleton transitively, so a regression in set/get would be
    detected eventually. But the failure mode would be "the
    connector-dispatch test broke" — opaque debugging. A direct test
    that exercises set_tool_dispatcher(None) / get_tool_dispatcher()
    transitions catches the same regression with a 1-line diagnostic.
  - The boot-log signal `tool_dispatcher installed` is also asserted
    here so a logging refactor that drops it gets flagged.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import pytest

from usecase import tool_dispatcher as tool_dispatcher_module


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Reset the module-level singleton between tests so leaked state
    from one test can't break another. Same pattern as
    test_agent_batch_propose's fixture teardown."""
    tool_dispatcher_module.set_tool_dispatcher(None)
    yield
    tool_dispatcher_module.set_tool_dispatcher(None)


def test_initial_state_is_none():
    """Cold start: nothing installed, get returns None. Consumers
    detect this and return clean error envelopes instead of crashing."""
    assert tool_dispatcher_module.get_tool_dispatcher() is None


def test_set_installs_dispatcher():
    """set_tool_dispatcher(d) makes d the installed dispatcher."""
    async def _fake_dispatch(name: str, kwargs: dict[str, Any]) -> Any:
        return {"called": name}

    tool_dispatcher_module.set_tool_dispatcher(_fake_dispatch)
    assert tool_dispatcher_module.get_tool_dispatcher() is _fake_dispatch


def test_set_none_clears_dispatcher():
    """Passing None back through the setter clears the singleton —
    used in test teardown to avoid state leakage between tests."""
    async def _fake_dispatch(name: str, kwargs: dict[str, Any]) -> Any:
        return None

    tool_dispatcher_module.set_tool_dispatcher(_fake_dispatch)
    assert tool_dispatcher_module.get_tool_dispatcher() is not None
    tool_dispatcher_module.set_tool_dispatcher(None)
    assert tool_dispatcher_module.get_tool_dispatcher() is None


def test_set_overrides_existing():
    """Second set() call overrides the first. Same shape the
    post-setup-reload path uses when re-installing the dispatcher
    after register_all_tools re-runs."""
    async def _first(name: str, kwargs: dict[str, Any]) -> Any:
        return "first"

    async def _second(name: str, kwargs: dict[str, Any]) -> Any:
        return "second"

    tool_dispatcher_module.set_tool_dispatcher(_first)
    tool_dispatcher_module.set_tool_dispatcher(_second)
    assert tool_dispatcher_module.get_tool_dispatcher() is _second


def test_installed_dispatcher_is_awaitable():
    """The dispatcher protocol declares an Awaitable return shape.
    Installing a coroutine function + invoking it should yield a
    coroutine that runs to completion under asyncio.run."""
    async def _echo(name: str, kwargs: dict[str, Any]) -> dict[str, Any]:
        return {"tool": name, "args": kwargs}

    tool_dispatcher_module.set_tool_dispatcher(_echo)
    d = tool_dispatcher_module.get_tool_dispatcher()
    assert d is not None

    result = asyncio.run(d("xsiam.run_query", {"q": "preset_login_failed"}))
    assert result == {"tool": "xsiam.run_query",
                      "args": {"q": "preset_login_failed"}}


def test_set_emits_log_signal(caplog):
    """Boot-log signal contract: installing logs 'tool_dispatcher
    installed' at INFO. Post-deploy checks grep for this line to confirm
    the singleton is wired; a log-message refactor that
    drops it breaks operator dashboards."""
    caplog.set_level(logging.INFO, logger="Phantom MCP")

    async def _fake(name: str, kwargs: dict[str, Any]) -> Any:
        return None

    tool_dispatcher_module.set_tool_dispatcher(_fake)
    assert any(
        "tool_dispatcher installed" in r.message
        for r in caplog.records
    )


def test_clear_emits_log_signal(caplog):
    """Symmetric: clearing logs 'tool_dispatcher cleared'. Same
    contract as install — the operator-facing boot-log narrative
    stays consistent."""
    async def _fake(name: str, kwargs: dict[str, Any]) -> Any:
        return None

    # Install first so the subsequent None-set actually transitions.
    tool_dispatcher_module.set_tool_dispatcher(_fake)
    caplog.clear()
    caplog.set_level(logging.INFO, logger="Phantom MCP")
    tool_dispatcher_module.set_tool_dispatcher(None)
    assert any(
        "tool_dispatcher cleared" in r.message
        for r in caplog.records
    )
