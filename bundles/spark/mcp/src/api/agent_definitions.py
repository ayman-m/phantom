"""Agent definitions HTTP endpoints.

Operator surface for the agent-definition registry. The /agents UI
reads/writes here; the chat-route's subagent_create tool resolves
agent definitions by id or name.

Endpoints (all require `Authorization: Bearer <MCP_TOKEN>`):

  GET    /api/v1/agent-definitions          → list (filter by origin
                                               or enabled_only)
  GET    /api/v1/agent-definitions/{id}     → fetch one
  GET    /api/v1/agent-definitions/by-name/{name} → resolve by name
  POST   /api/v1/agent-definitions          → create / upsert
  PATCH  /api/v1/agent-definitions/{id}     → partial update
  DELETE /api/v1/agent-definitions/{id}     → remove
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from api.auth import require_bearer
from usecase.agent_definition_store import (
    SqliteAgentDefinitionStore,
    VALID_ISOLATION,
)
from usecase.audit_log import (
    SqliteAuditLog,
    set_current_actor,
    reset_current_actor,
)

logger = logging.getLogger("Phantom MCP")


def register_agent_definition_routes(
    mcp: FastMCP,
    defs: SqliteAgentDefinitionStore,
    audit: SqliteAuditLog,
) -> None:
    """Register /api/v1/agent-definitions/* routes."""

    @mcp.custom_route(
        "/api/v1/agent-definitions",
        methods=["GET"],
        include_in_schema=False,
    )
    async def list_definitions(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        q = request.query_params
        origin = q.get("origin") or None
        enabled_only = q.get("enabled_only") in ("1", "true", "yes")
        rows = defs.list(origin=origin, enabled_only=enabled_only)
        return JSONResponse(
            {
                "agent_definitions": [r.to_dict() for r in rows],
                "count": len(rows),
            }
        )

    @mcp.custom_route(
        "/api/v1/agent-definitions/{agent_id}",
        methods=["GET"],
        include_in_schema=False,
    )
    async def get_definition(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        d = defs.get(request.path_params["agent_id"])
        if d is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        return JSONResponse({"agent_definition": d.to_dict()})

    @mcp.custom_route(
        "/api/v1/agent-definitions/by-name/{name}",
        methods=["GET"],
        include_in_schema=False,
    )
    async def get_definition_by_name(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        d = defs.get_by_name(request.path_params["name"])
        if d is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        return JSONResponse({"agent_definition": d.to_dict()})

    @mcp.custom_route(
        "/api/v1/agent-definitions",
        methods=["POST"],
        include_in_schema=False,
    )
    async def upsert_definition(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        actor_token = set_current_actor("user:operator")
        try:
            body = await _json_body(request)
            if isinstance(body, JSONResponse):
                return body
            err = _validate_definition(body)
            if err is not None:
                return JSONResponse({"error": err}, status_code=400)
            if not body.get("id"):
                body["id"] = str(uuid.uuid4())
            try:
                d = defs.upsert(body, origin="operator")
            except ValueError as exc:
                return JSONResponse({"error": str(exc)}, status_code=400)
            audit.record(
                action="agent_definition_upsert",
                target=f"agent:{d.id}",
                status="success",
                metadata={
                    "name": d.name,
                    "origin": d.origin,
                    "tools_allowed_count": len(d.tools_allowed),
                    "tools_denied_count": len(d.tools_denied),
                    "max_turns": d.max_turns,
                    "isolation": d.isolation,
                },
            )
            return JSONResponse(
                {"agent_definition": d.to_dict()}, status_code=201,
            )
        finally:
            reset_current_actor(actor_token)

    @mcp.custom_route(
        "/api/v1/agent-definitions/{agent_id}",
        methods=["PATCH"],
        include_in_schema=False,
    )
    async def patch_definition(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        actor_token = set_current_actor("user:operator")
        try:
            agent_id = request.path_params["agent_id"]
            existing = defs.get(agent_id)
            if existing is None:
                return JSONResponse(
                    {"error": "not found"}, status_code=404
                )
            body = await _json_body(request)
            if isinstance(body, JSONResponse):
                return body
            # Fast path: enabled-only toggle.
            if (
                set(body.keys()) <= {"enabled"}
                and "enabled" in body
            ):
                if not isinstance(body["enabled"], bool):
                    return JSONResponse(
                        {"error": "'enabled' must be a boolean"},
                        status_code=400,
                    )
                d = defs.set_enabled(
                    agent_id, enabled=body["enabled"]
                )
                if d is None:
                    return JSONResponse(
                        {"error": "not found"}, status_code=404
                    )
                audit.record(
                    action=(
                        "agent_definition_enabled" if body["enabled"]
                        else "agent_definition_disabled"
                    ),
                    target=f"agent:{agent_id}",
                    status="success",
                    metadata={"name": d.name},
                )
                return JSONResponse({"agent_definition": d.to_dict()})
            # Full upsert merge.
            merged = {
                **existing.to_dict(),
                **body,
                "id": existing.id,
                "created_at": existing.created_at,
            }
            err = _validate_definition(merged)
            if err is not None:
                return JSONResponse({"error": err}, status_code=400)
            try:
                d = defs.upsert(merged, origin=existing.origin)
            except ValueError as exc:
                return JSONResponse({"error": str(exc)}, status_code=400)
            audit.record(
                action="agent_definition_upsert",
                target=f"agent:{d.id}",
                status="success",
                metadata={"name": d.name, "origin": d.origin},
            )
            return JSONResponse({"agent_definition": d.to_dict()})
        finally:
            reset_current_actor(actor_token)

    @mcp.custom_route(
        "/api/v1/agent-definitions/{agent_id}",
        methods=["DELETE"],
        include_in_schema=False,
    )
    async def delete_definition(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        actor_token = set_current_actor("user:operator")
        try:
            agent_id = request.path_params["agent_id"]
            existing = defs.get(agent_id)
            ok = defs.delete(agent_id)
            if not ok:
                return JSONResponse(
                    {"error": "not found"}, status_code=404
                )
            audit.record(
                action="agent_definition_deleted",
                target=f"agent:{agent_id}",
                status="success",
                metadata={
                    "name": existing.name if existing else None,
                    "origin": existing.origin if existing else None,
                },
            )
            return JSONResponse({"deleted": True, "id": agent_id})
        finally:
            reset_current_actor(actor_token)


# ─── Validators / helpers ─────────────────────────────────────────


def _validate_definition(body: dict[str, Any]) -> str | None:
    name = body.get("name")
    if not isinstance(name, str) or not name.strip():
        return "'name' is required and must be a non-empty string"
    sp = body.get("system_prompt")
    if not isinstance(sp, str) or not sp.strip():
        return (
            "'system_prompt' is required and must be a non-empty string"
        )
    isolation = body.get("isolation") or "fresh_session"
    if isolation not in VALID_ISOLATION:
        return (
            f"'isolation' must be one of {sorted(VALID_ISOLATION)}; "
            f"got {isolation!r}"
        )
    max_turns = body.get("max_turns")
    if max_turns is not None:
        if not isinstance(max_turns, int) or max_turns < 1 or max_turns > 50:
            return "'max_turns' must be an integer in [1, 50]"
    for key in ("tools_allowed", "tools_denied"):
        v = body.get(key)
        if v is not None and not isinstance(v, list):
            return f"'{key}' must be a list of glob patterns"
    return None


async def _json_body(
    request: Request,
) -> dict[str, Any] | JSONResponse:
    try:
        body = await request.json()
    except Exception as exc:
        return JSONResponse(
            {"error": f"invalid JSON body: {exc}"},
            status_code=400,
        )
    if not isinstance(body, dict):
        return JSONResponse(
            {"error": "body must be a JSON object"},
            status_code=400,
        )
    return body
