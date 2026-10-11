"""Skills HTTP endpoints — operator-direct REST surface for the
Next.js agent's `/skills` page.

The agent's `/skills` page calls these to render the skills catalog,
read MD content, edit it, create new skills, and delete stale ones.
Operators clicking buttons in the UI ARE the approver — they don't
need the chat-agent approval gate that exists to catch
self-modification attempts by the agent.

Endpoints (all require `Authorization: Bearer <MCP_TOKEN>`):

  GET    /api/v1/skills                          → list all skills
  GET    /api/v1/skills/{file_path:path}         → read one skill
  POST   /api/v1/skills                          → create new skill
                                                   (body: category,
                                                   filename, content)
  PUT    /api/v1/skills/{file_path:path}         → update content
                                                   (body: content)
  DELETE /api/v1/skills/{file_path:path}         → soft-delete one
                                                   (file moves to
                                                   /app/skills/.deleted/)

Why this module exists

The MCP exposes two surfaces for skills mutation:

  1. Tool path — `tools/call name=skills_delete`. Goes through the
     gated wrapper at
     `usecase/builtin_components/self_mod_tools.skills_delete` →
     `gate_and_execute()` blocks waiting for operator approval. The
     wrapper exists because the agent (chat-driven) might decide to
     delete a skill mid-conversation; operators want a chance to
     intervene before that happens.
  2. REST path — these endpoints. Bypass the gate by calling
     `skills_crud.skills_delete` (and friends) directly. The Next.js
     agent's `/api/skills` route proxies operator-direct UI clicks to
     this REST surface, so clicking the trash icon in `/skills` does
     NOT require a separate approval-queue acknowledgement (the click
     IS the approval).

The same dual-surface pattern already exists for jobs, instances,
providers, settings, personality, etc. — see `api/jobs.py`,
`api/instances.py`, etc.

Bypassing the gate by sending `X-Phantom-Approval-Bypass: 1` from the
Next.js side does not work: that relies on the trigger_context
middleware setting a contextvar that `gate_and_execute` reads, and the
contextvar does NOT propagate from the Starlette middleware into
FastMCP's streamable-HTTP tool dispatcher (suspected cause: FastMCP
spawns the tool execution in a child asyncio task whose context was
captured before the middleware ran). The REST-endpoint approach in
this module sidesteps the contextvar propagation question entirely by
avoiding the gate altogether — same way the other resources do.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from api.auth import require_bearer
from usecase.audit_log import reset_current_actor, set_current_actor
from usecase.builtin_components import skills_crud

logger = logging.getLogger("Phantom MCP")


def _decode(raw: Any) -> Any:
    """`skills_crud.*` functions return JSON-encoded strings. Decode
    so the route returns a structured dict instead of a string-in-a-
    string. Falls through to the raw value for any function that
    already returns a dict — defensive against future refactors of
    skills_crud's return types.
    """
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return {"raw": raw}
    return raw


def register_skill_routes(mcp: FastMCP) -> None:
    """Register /api/v1/skills/* routes on the FastMCP server.

    Called once during server boot from main.py, after the FastMCP
    instance has been built and the bundled tool registry has been
    loaded. No further setup required — skills_crud is stateless and
    reads/writes the on-disk markdown files directly under the
    SKILLS_PATH config (default `/app/skills/`).
    """

    @mcp.custom_route(
        "/api/v1/skills", methods=["GET"], include_in_schema=False
    )
    async def list_skills(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        result = _decode(skills_crud.skills_list_all())
        return JSONResponse({"skills": result, "count": len(result)})

    @mcp.custom_route(
        "/api/v1/skills/{file_path:path}",
        methods=["GET"],
        include_in_schema=False,
    )
    async def read_skill(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        file_path = request.path_params["file_path"]
        result = _decode(skills_crud.skills_read(file_path))
        if not result.get("success"):
            return JSONResponse(result, status_code=404)
        return JSONResponse(result)

    @mcp.custom_route(
        "/api/v1/skills", methods=["POST"], include_in_schema=False
    )
    async def create_skill(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        actor_token = set_current_actor("user:operator")
        try:
            body = await request.json()
            category = (body or {}).get("category")
            filename = (body or {}).get("filename")
            content = (body or {}).get("content")
            if not category or not filename or not content:
                return JSONResponse(
                    {
                        "success": False,
                        "error": "category, filename, and content are required",
                    },
                    status_code=400,
                )
            result = _decode(
                skills_crud.skills_create(
                    category=category, filename=filename, content=content,
                )
            )
            status = 200 if result.get("success") else 400
            return JSONResponse(result, status_code=status)
        finally:
            reset_current_actor(actor_token)

    @mcp.custom_route(
        "/api/v1/skills/{file_path:path}",
        methods=["PUT"],
        include_in_schema=False,
    )
    async def update_skill(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        actor_token = set_current_actor("user:operator")
        try:
            file_path = request.path_params["file_path"]
            body = await request.json()
            content = (body or {}).get("content")
            if not content:
                return JSONResponse(
                    {"success": False, "error": "content is required"},
                    status_code=400,
                )
            result = _decode(
                skills_crud.skills_update(file_path=file_path, content=content)
            )
            status = 200 if result.get("success") else 400
            return JSONResponse(result, status_code=status)
        finally:
            reset_current_actor(actor_token)

    @mcp.custom_route(
        "/api/v1/skills/{file_path:path}",
        methods=["DELETE"],
        include_in_schema=False,
    )
    async def delete_skill(request: Request) -> JSONResponse:
        """Operator-direct skill deletion. Bypasses the Phase-11
        gated `skills_delete` MCP tool wrapper — clicks from the
        operator's `/skills` UI ARE the approval, no separate
        approvals-queue acknowledgement needed.
        """
        if (resp := require_bearer(request)) is not None:
            return resp
        actor_token = set_current_actor("user:operator")
        try:
            file_path = request.path_params["file_path"]
            result = _decode(skills_crud.skills_delete(file_path))
            status = 200 if result.get("success") else 404
            return JSONResponse(result, status_code=status)
        finally:
            reset_current_actor(actor_token)

    logger.info(
        "Skills REST routes registered: GET/POST /api/v1/skills, "
        "GET/PUT/DELETE /api/v1/skills/{file_path:path}"
    )
