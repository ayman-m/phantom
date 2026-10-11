"""Plugins HTTP endpoints.

Read-only inventory + reload action over the filesystem-discovered
plugin tree.

Endpoints (all require `Authorization: Bearer <MCP_TOKEN>`):

  GET  /api/v1/plugins         → list every discovered plugin
                                 with contribution counts (READ-ONLY,
                                 no side effects)
  POST /api/v1/plugins/reload  → re-apply every enabled plugin's
                                 contributions. Idempotent — file
                                 copies skip when source <= dest;
                                 memory seeds skip existing keys.
"""

from __future__ import annotations

import logging

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from api.auth import require_bearer
from usecase.plugin_loader import PluginLoader
from usecase.audit_log import (
    SqliteAuditLog,
    set_current_actor,
    reset_current_actor,
)

logger = logging.getLogger("Phantom MCP")


def register_plugin_routes(
    mcp: FastMCP,
    loader: PluginLoader,
    memory_store,
    audit: SqliteAuditLog,
    agent_definition_store=None,
) -> None:
    """Register /api/v1/plugins/* routes."""

    @mcp.custom_route(
        "/api/v1/plugins", methods=["GET"], include_in_schema=False
    )
    async def list_plugins(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        # list_loaded does NOT apply contributions — that's
        # explicitly the reload endpoint's job. Operators can read
        # this freely.
        plugins = loader.list_loaded()
        return JSONResponse(
            {
                "plugins": [p.to_dict() for p in plugins],
                "count": len(plugins),
            }
        )

    @mcp.custom_route(
        "/api/v1/plugins/reload",
        methods=["POST"],
        include_in_schema=False,
    )
    async def reload_plugins(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        actor_token = set_current_actor("user:operator")
        try:
            results = loader.apply_all(
                memory_store=memory_store,
                agent_definition_store=agent_definition_store,
            )
            audit.record(
                action="plugins_reloaded",
                target="plugins:*",
                status="success",
                metadata={
                    "plugins_count": len(results),
                    "enabled_count": sum(
                        1 for r in results if r.enabled
                    ),
                    "total_seeded": sum(r.seeded_count for r in results),
                },
            )
            return JSONResponse(
                {
                    "plugins": [p.to_dict() for p in results],
                    "count": len(results),
                }
            )
        finally:
            reset_current_actor(actor_token)
