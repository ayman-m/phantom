"""phantom_mcp_tool_calls_total is incremented once per real tool dispatch.

Drives a real FastMCP server through an in-process fastmcp.Client (the same
path the job scheduler and agent_batch_propose use), so the middleware sees
exactly what it sees in production.
"""
from __future__ import annotations

import asyncio

import pytest
from fastmcp import Client, FastMCP

from usecase.metrics_registry import MetricsRegistry, set_metrics_registry
from usecase.tool_call_metrics import METRIC_NAME, ToolCallMetricsMiddleware


@pytest.fixture
def registry():
    reg = MetricsRegistry()
    # main.py pre-declares the counter; the middleware must work either way.
    reg.counter(METRIC_NAME, "Total tool dispatches. Labels: tool, status.")
    set_metrics_registry(reg)
    yield reg
    set_metrics_registry(None)


def _server() -> FastMCP:
    mcp = FastMCP("t")
    mcp.add_middleware(ToolCallMetricsMiddleware())

    @mcp.tool(name="builtin_ok")
    def builtin_ok() -> str:
        return "fine"

    @mcp.tool(name="xlog.list_workers")
    async def connector_style() -> str:
        return "[]"

    @mcp.tool(name="always_fails")
    def always_fails() -> str:
        raise RuntimeError("boom")

    return mcp


def _lines(reg: MetricsRegistry) -> str:
    return "\n".join(reg.get(METRIC_NAME).lines())


def _call(mcp: FastMCP, name: str) -> None:
    async def go() -> None:
        async with Client(mcp) as c:
            try:
                await c.call_tool(name, {})
            except Exception:
                pass

    asyncio.run(go())


def test_successful_builtin_and_connector_calls_are_counted(registry):
    mcp = _server()
    _call(mcp, "builtin_ok")
    _call(mcp, "builtin_ok")
    _call(mcp, "xlog.list_workers")
    out = _lines(registry)
    assert 'phantom_mcp_tool_calls_total{status="success",tool="builtin_ok"} 2' in out
    assert 'phantom_mcp_tool_calls_total{status="success",tool="xlog.list_workers"} 1' in out


def test_raising_tool_counts_as_failure(registry):
    _call(_server(), "always_fails")
    out = _lines(registry)
    assert 'phantom_mcp_tool_calls_total{status="failure",tool="always_fails"} 1' in out
    assert 'status="success",tool="always_fails"' not in out


def test_unregistered_tool_name_is_bucketed_as_unknown(registry):
    _call(_server(), "model_invented_tool_name")
    out = _lines(registry)
    assert "model_invented_tool_name" not in out
    assert 'phantom_mcp_tool_calls_total{status="failure",tool="unknown"} 1' in out


def test_counter_is_created_when_not_predeclared():
    reg = MetricsRegistry()
    set_metrics_registry(reg)
    try:
        _call(_server(), "builtin_ok")
        assert 'tool="builtin_ok"' in "\n".join(reg.get(METRIC_NAME).lines())
    finally:
        set_metrics_registry(None)


def test_no_registry_does_not_break_the_call():
    set_metrics_registry(None)
    mcp = _server()

    async def go():
        async with Client(mcp) as c:
            return await c.call_tool("builtin_ok", {})

    res = asyncio.run(go())
    assert "fine" in str(res)
