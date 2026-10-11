"""Resolve the xlog GraphQL base URL for xlog connector tools.

The same xlog tool functions are invoked from two runtimes:

1. **Agent's embedded MCP** (`bundles/spark/mcp/`) — lifespan_context has
   a `get_xlog_url()` callable (set in
   `bundles/spark/mcp/src/service/phantom_mcp/server.py`) that reads from
   `InstanceStore.list_for("xlog")[0].config.baseUrl` live, so it picks
   up changes without restart.

2. **Per-instance connector container** (`phantom-connector-runtime`) — the
   runtime entrypoint stashes the connector's instance config in a
   contextvar via `config.set_current_instance(...)`. Tools read it via
   `config.get_config().<key>`. The `get_xlog_url` lifespan key is NOT
   populated here (the runtime is connector-agnostic; it doesn't know
   which connectors expose which keys).

Calling `lifespan_context["get_xlog_url"]()` directly works in the agent's
embedded MCP but raises KeyError in the per-instance container.
This helper detects which runtime is current and returns the right URL.

Recommended call site:

    from ._xlog_url_resolver import resolve_xlog_url
    client = PhantomGraphQLClient(resolve_xlog_url(ctx))

The function takes the FastMCP `Context` so it can probe lifespan_context
without callers having to do the dict lookup themselves.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("Phantom MCP")


def resolve_xlog_url(ctx: Any) -> str:
    """Return the xlog GraphQL base URL, working in either runtime.

    Resolution order:
      1. If lifespan_context has a `get_xlog_url` callable (agent runtime),
         call it and return the result.
      2. Otherwise (per-instance connector runtime), read `baseUrl` from
         the current instance's config via the runtime's contextvar.
      3. If neither succeeds, raise RuntimeError with a clear message so
         the operator sees what's wrong.

    Raises:
        RuntimeError: when both resolution paths fail. Common cause: the
            connector code is running outside the per-instance runtime
            AND outside the agent's MCP (e.g., a stand-alone test harness
            that didn't set up either).
    """
    # Path 1 — agent runtime: lifespan_context["get_xlog_url"] is a callable
    try:
        lifespan_context = ctx.request_context.lifespan_context
        getter = (
            lifespan_context.get("get_xlog_url")
            if isinstance(lifespan_context, dict)
            else None
        )
        if callable(getter):
            url = getter()
            if url:
                return url
    except (AttributeError, KeyError, TypeError) as exc:
        logger.debug("agent-runtime xlog URL lookup miss: %s", exc)

    # Path 2 — per-instance connector runtime: instance config has baseUrl
    try:
        # Late import — keeps this module importable when running tests
        # that don't have the phantom-connector-runtime config module
        # on PYTHONPATH (e.g., the agent's pytest suite, which has its
        # own `config` package with a different `get_config` shape).
        from config.config import get_config  # type: ignore[import-not-found]
        cfg = get_config()
        base_url = getattr(cfg, "baseUrl", None) or getattr(cfg, "base_url", None)
        if base_url:
            return str(base_url)
    except (ImportError, RuntimeError, AttributeError) as exc:
        logger.debug("per-instance xlog URL lookup miss: %s", exc)

    raise RuntimeError(
        "xlog URL not resolvable: neither agent-runtime "
        "lifespan_context['get_xlog_url'] nor per-instance "
        "config.get_config().baseUrl was available. Check that the xlog "
        "connector instance is configured (baseUrl='https://xlog:8000' or "
        "similar) and that the runtime entrypoint loaded the instance row."
    )
