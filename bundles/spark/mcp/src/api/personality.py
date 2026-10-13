"""Personality HTTP endpoints — operator-tunable agent persona,
served from the MCP's SqlitePersonalityStore.

The agent UI's personality page (`/settings/personality`) and the
chat-driven self-mod tools (`personality_get`, `personality_update`)
both go through these endpoints. Single source of truth — no more
agent-side `setup.json:values.personality`.

  GET  /api/v1/personality          → {personality, updated_at, updated_by, version}
  PUT  /api/v1/personality          → replace blob; body = {personality: {...}}
  GET  /api/v1/personality/defaults → the bundle default document (no store read)
  POST /api/v1/personality/reset    → reset to bundle default
  GET  /api/v1/personality/history  → recent versions for diff rendering

All endpoints require `Authorization: Bearer <MCP_TOKEN>`.

Approval gating happens at the TOOL layer (Tier 2 `personality_update`
tool dispatches through approvals_bus). REST is the *operator-direct*
surface — operators submitting via the UI page already have UI auth;
asking them to approve themselves would be silly.
"""

from __future__ import annotations

import logging

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from api.auth import require_bearer
from usecase.personality_store import SqlitePersonalityStore, default_personality

logger = logging.getLogger("Phantom MCP")


def register_personality_routes(
    mcp: FastMCP, store: SqlitePersonalityStore
) -> None:
    """Register /api/v1/personality* on the FastMCP server."""

    @mcp.custom_route(
        "/api/v1/personality", methods=["GET"], include_in_schema=False
    )
    async def get_personality(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        p = store.get_or_default()
        return JSONResponse(p.to_dict())

    @mcp.custom_route(
        "/api/v1/personality", methods=["PUT"], include_in_schema=False
    )
    async def put_personality(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        try:
            body = await request.json()
        except Exception as exc:  # noqa: BLE001
            return JSONResponse(
                {"error": f"invalid JSON body: {exc}"}, status_code=400,
            )
        if not isinstance(body, dict):
            return JSONResponse(
                {"error": "body must be a JSON object"}, status_code=400,
            )
        blob = body.get("personality")
        if not isinstance(blob, dict):
            return JSONResponse(
                {
                    "error": (
                        "body must include a `personality` object — "
                        "got " + type(blob).__name__
                    ),
                },
                status_code=400,
            )
        actor = body.get("actor") or "user:operator"
        try:
            updated = store.put(blob, actor=str(actor))
        except (TypeError, ValueError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return JSONResponse(updated.to_dict())

    @mcp.custom_route(
        "/api/v1/personality/defaults",
        methods=["GET"],
        include_in_schema=False,
    )
    async def personality_defaults(request: Request) -> JSONResponse:
        """The bundle default document. The personality page fills keys a
        stored blob lacks from it and uses it for Reset Defaults, so the
        UI carries no copy of its own."""
        if (resp := require_bearer(request)) is not None:
            return resp
        return JSONResponse({"personality": default_personality()})

    @mcp.custom_route(
        "/api/v1/personality/reset",
        methods=["POST"],
        include_in_schema=False,
    )
    async def reset_personality(request: Request) -> JSONResponse:
        """Revert to the bundle's default personality. The Tier-3
        `personality_reset` tool (Commit 4) gates this via approvals;
        direct REST is operator-only."""
        if (resp := require_bearer(request)) is not None:
            return resp
        try:
            body = await request.json()
        except Exception:
            body = {}
        actor = (body.get("actor") if isinstance(body, dict) else None) or "user:operator"
        updated = store.reset_to_default(actor=str(actor))
        return JSONResponse(updated.to_dict())

    @mcp.custom_route(
        "/api/v1/personality/history",
        methods=["GET"],
        include_in_schema=False,
    )
    async def personality_history(request: Request) -> JSONResponse:
        """Recent personality versions, newest first. Used by the diff
        renderer in Commit 6's chat UI."""
        if (resp := require_bearer(request)) is not None:
            return resp
        try:
            limit = int(request.query_params.get("limit") or 10)
        except ValueError:
            limit = 10
        rows = store.history(limit=limit)
        return JSONResponse(
            {
                "versions": [r.to_dict() for r in rows],
                "count": len(rows),
            }
        )
