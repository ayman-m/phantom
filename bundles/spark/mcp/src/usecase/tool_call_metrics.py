"""Count every MCP tool dispatch into ``phantom_mcp_tool_calls_total``.

The counter was declared at boot (main.py, and the manifest's
``observability.metrics``) but nothing incremented it, so
/observability/metrics read 0 however many tool calls the chat made.

This is a FastMCP middleware rather than a counter inside
``connector_loader._wrap_with_instance`` because the wrapper only covers
connector tools. Built-in tools (``_BUILTIN_LEGACY_TOOLS``) are registered
unwrapped, so a counter in the wrapper would undercount exactly the tools the
chat uses most. ``on_call_tool`` sits on the one path every ``tools/call``
takes: the agent's chat route over the streamable-http transport, the job
scheduler and ``agent_batch_propose``'s connector dispatch (both go through an
in-process ``fastmcp.Client``).

Labels:
  tool    the tool name as called (namespaced or legacy alias). A call to a
          name that is not registered is recorded as ``unknown`` so a model
          that invents tool names cannot grow the label set without bound.
  status  ``success`` when the tool returned, ``failure`` when it raised. A
          tool that returns an error envelope instead of raising counts as
          ``success``; the audit log carries the finer outcome.

``agent_batch_propose`` runs its built-in actions with a direct function call
(no MCP round-trip), so those inner calls are counted by
``phantom_batch_actions_total``, not here.

Metrics must never affect a tool call: every metrics operation is guarded.
"""

from __future__ import annotations

import logging
from typing import Any

from fastmcp.server.middleware import Middleware, MiddlewareContext

from usecase.metrics_registry import metrics_registry

logger = logging.getLogger("Phantom MCP")

METRIC_NAME = "phantom_mcp_tool_calls_total"
METRIC_HELP = "Total tool dispatches. Labels: tool, status."
UNKNOWN_TOOL = "unknown"


def _is_not_found(exc: BaseException) -> bool:
    try:
        from fastmcp.exceptions import NotFoundError
    except ImportError:  # pragma: no cover - older fastmcp
        return False
    return isinstance(exc, NotFoundError)


def _record(tool: str, status: str) -> None:
    try:
        reg = metrics_registry()
        if reg is None:
            return
        reg.counter(METRIC_NAME, METRIC_HELP).inc(tool=tool, status=status)
    except Exception as exc:  # noqa: BLE001 - metrics never break a tool call
        logger.debug("tool-call metric suppressed: %s", exc)


class ToolCallMetricsMiddleware(Middleware):
    """Increment ``phantom_mcp_tool_calls_total{tool,status}`` per dispatch."""

    async def on_call_tool(self, context: MiddlewareContext[Any], call_next: Any) -> Any:
        tool = str(getattr(context.message, "name", "") or UNKNOWN_TOOL)
        try:
            result = await call_next(context)
        except Exception as exc:
            _record(UNKNOWN_TOOL if _is_not_found(exc) else tool, "failure")
            raise
        _record(tool, "success")
        return result
