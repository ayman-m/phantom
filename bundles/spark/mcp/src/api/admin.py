"""Admin HTTP endpoints — operator-driven runtime reloads.

Today this is just `/api/v1/admin/reload_tools`. Future additions:
log-level toggle, KB re-ingest, scheduler restart, etc.

  POST /api/v1/admin/reload_tools   → re-run register_all_tools()
        body: {} (no body needed)
        response: {"reloaded": true, "newly_namespaced": N, "newly_legacy": M}

Auth: requires MCP_TOKEN. We deliberately do NOT accept API keys on
this surface — runtime reloads are admin-only since they affect what
tools the agent can call.

# Why this exists

Before this endpoint, materializing a new connector instance via
/api/v1/setup required a process restart for the MCP to pick up
the new connector's tools (FastMCP's `mcp.tool()` registration only
runs in async_main()'s startup loop). The setup endpoint honestly
returned `requires_mcp_restart: true` and operators had to
`docker compose restart phantom-agent`.

The hot-reload makes that restart unnecessary: register_all_tools()
is idempotent (skips names already in tool_registry), so calling it
after a fresh /api/v1/setup picks up only the NEW tools without
disturbing existing registrations.

# What hot-reload doesn't do

  * Tool removal: FastMCP doesn't expose unregister, so tools whose
    instances were deleted stay registered. Their wrapper hits an
    InstanceStore lookup at call time and returns a clear error,
    which is acceptable: the tool advertise-list grows but never
    serves stale instances. A future improvement when FastMCP gains
    an unregister API would close this.
  * Provider hot-reload: providers contribute models, not tools, and
    are queried at chat-time anyway. No reload needed; just point at
    the new instance.
"""

from __future__ import annotations

import logging

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from api.auth import require_bearer
from usecase.connector_loader import reload_tools_now

logger = logging.getLogger("Phantom MCP")


def _is_mcp_token_principal(request: Request) -> bool:
    """Admin surface: refuse API keys, accept only MCP_TOKEN."""
    return getattr(request.state, "auth_principal", "") == "mcp_token"


def register_admin_routes(mcp: FastMCP) -> None:
    @mcp.custom_route(
        "/api/v1/admin/reload_tools",
        methods=["POST"],
        include_in_schema=False,
    )
    async def reload_tools(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        if not _is_mcp_token_principal(request):
            return JSONResponse(
                {"error": "tool reload requires MCP_TOKEN"},
                status_code=403,
            )
        result = reload_tools_now()
        if result is None:
            return JSONResponse(
                {
                    "error": (
                        "tool reloader not wired — set_reload_state() was "
                        "not called at boot (likely Spark-platform mode "
                        "where connector tools come from the platform)"
                    )
                },
                status_code=503,
            )
        newly_namespaced, newly_legacy = result
        logger.info(
            "Hot-reload: registered %d new namespaced tools + %d new legacy aliases",
            newly_namespaced, newly_legacy,
        )
        return JSONResponse(
            {
                "reloaded": True,
                "newly_namespaced": newly_namespaced,
                "newly_legacy": newly_legacy,
            }
        )
