"""Task registry HTTP endpoints.

Exposes the SqliteTaskStore for the agent UI's /tasks page, the
/tasks slash command, and external integrations (cron jobs that
need to enqueue work).

Endpoints (all require `Authorization: Bearer <MCP_TOKEN>`):

  GET    /api/v1/tasks                  → paginated list
  GET    /api/v1/tasks?active_only=1    → only pending+running
  GET    /api/v1/tasks?status=running   → filter by status
  GET    /api/v1/tasks?session=<id>     → tasks spawned by a session
  GET    /api/v1/tasks/{id}             → fetch one
  POST   /api/v1/tasks                  → create. Body: {kind, title,
                                          parent_session_id?, meta?}
  PATCH  /api/v1/tasks/{id}/progress    → {progress, progress_label,
                                          meta_patch}
  POST   /api/v1/tasks/{id}/transition  → {status, output?}
  POST   /api/v1/tasks/{id}/abort       → {reason?}

Audit:

  Every state change emits a `task_*` audit row with the kind,
  status, and parent_session_id in metadata. Workers that
  transition through a few states emit ~3-4 rows per lifecycle.
"""

from __future__ import annotations

import logging
from typing import Any

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from api.auth import require_bearer
from usecase.task_store import (
    SqliteTaskStore,
    TERMINAL_STATUS,
    VALID_STATUS,
)
from usecase.audit_log import (
    SqliteAuditLog,
    set_current_actor,
    reset_current_actor,
)

logger = logging.getLogger("Phantom MCP")


def register_task_routes(
    mcp: FastMCP,
    tasks: SqliteTaskStore,
    audit: SqliteAuditLog,
) -> None:
    """Register /api/v1/tasks/* routes."""

    @mcp.custom_route(
        "/api/v1/tasks", methods=["GET"], include_in_schema=False
    )
    async def list_tasks(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        q = request.query_params

        def _int(name: str, default: int) -> int:
            raw = q.get(name)
            if raw is None or raw == "":
                return default
            try:
                return int(raw)
            except ValueError:
                return default

        active_only = q.get("active_only") in ("1", "true", "yes")
        status = q.get("status") or None
        kind = q.get("kind") or None
        session = q.get("session") or None
        if status is not None and status not in VALID_STATUS:
            return JSONResponse(
                {
                    "error": (
                        f"unknown status '{status}'. Valid: "
                        f"{sorted(VALID_STATUS)}"
                    )
                },
                status_code=400,
            )
        rows = tasks.list(
            status=status,
            kind=kind,
            parent_session_id=session,
            active_only=active_only,
            limit=_int("limit", 100),
            offset=_int("offset", 0),
        )
        return JSONResponse(
            {"tasks": [r.to_dict() for r in rows], "count": len(rows)}
        )

    @mcp.custom_route(
        "/api/v1/tasks/{task_id}",
        methods=["GET"],
        include_in_schema=False,
    )
    async def get_task(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        t = tasks.get(request.path_params["task_id"])
        if t is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        return JSONResponse({"task": t.to_dict()})

    @mcp.custom_route(
        "/api/v1/tasks", methods=["POST"], include_in_schema=False
    )
    async def create_task(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        actor_token = set_current_actor("user:operator")
        try:
            body = await _json_body(request)
            if isinstance(body, JSONResponse):
                return body
            kind = body.get("kind")
            title = body.get("title")
            if not isinstance(kind, str) or not kind.strip():
                return JSONResponse(
                    {"error": "'kind' is required (non-empty string)"},
                    status_code=400,
                )
            if not isinstance(title, str) or not title.strip():
                return JSONResponse(
                    {"error": "'title' is required (non-empty string)"},
                    status_code=400,
                )
            initial_status = body.get("initial_status") or "pending"
            if initial_status not in ("pending", "running"):
                return JSONResponse(
                    {
                        "error": (
                            "'initial_status' must be 'pending' or "
                            "'running'"
                        )
                    },
                    status_code=400,
                )
            try:
                t = tasks.create(
                    kind=kind.strip(),
                    title=title.strip(),
                    parent_session_id=body.get("parent_session_id"),
                    meta=body.get("meta") or {},
                    initial_status=initial_status,
                    task_id=body.get("id"),
                )
            except ValueError as exc:
                return JSONResponse({"error": str(exc)}, status_code=400)
            audit.record(
                action="task_created",
                target=f"task:{t.id}",
                status="success",
                metadata={
                    "kind": t.kind,
                    "title": t.title,
                    "parent_session_id": t.parent_session_id,
                    "initial_status": t.status,
                },
            )
            return JSONResponse({"task": t.to_dict()}, status_code=201)
        finally:
            reset_current_actor(actor_token)

    @mcp.custom_route(
        "/api/v1/tasks/{task_id}/progress",
        methods=["PATCH"],
        include_in_schema=False,
    )
    async def patch_progress(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        task_id = request.path_params["task_id"]
        body = await _json_body(request)
        if isinstance(body, JSONResponse):
            return body
        progress = body.get("progress")
        if progress is not None and not isinstance(
            progress, (int, float)
        ):
            return JSONResponse(
                {"error": "'progress' must be a number in [0, 1]"},
                status_code=400,
            )
        progress_label = body.get("progress_label")
        if progress_label is not None and not isinstance(
            progress_label, str
        ):
            return JSONResponse(
                {"error": "'progress_label' must be a string"},
                status_code=400,
            )
        meta_patch = body.get("meta_patch")
        if meta_patch is not None and not isinstance(meta_patch, dict):
            return JSONResponse(
                {"error": "'meta_patch' must be an object"},
                status_code=400,
            )
        t = tasks.update_progress(
            task_id,
            progress=(
                None if progress is None else float(progress)
            ),
            progress_label=progress_label,
            meta_patch=meta_patch,
        )
        if t is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        # Progress patches are high-volume — don't audit each one.
        # Only audit lifecycle transitions.
        return JSONResponse({"task": t.to_dict()})

    @mcp.custom_route(
        "/api/v1/tasks/{task_id}/transition",
        methods=["POST"],
        include_in_schema=False,
    )
    async def transition_task(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        actor_token = set_current_actor("user:operator")
        try:
            task_id = request.path_params["task_id"]
            body = await _json_body(request)
            if isinstance(body, JSONResponse):
                return body
            new_status = body.get("status")
            if new_status not in VALID_STATUS:
                return JSONResponse(
                    {
                        "error": (
                            f"'status' must be one of "
                            f"{sorted(VALID_STATUS)}"
                        )
                    },
                    status_code=400,
                )
            output = body.get("output")
            if output is not None and not isinstance(output, str):
                return JSONResponse(
                    {"error": "'output' must be a string"},
                    status_code=400,
                )
            existing = tasks.get(task_id)
            if existing is None:
                return JSONResponse(
                    {"error": "not found"}, status_code=404
                )
            try:
                t = tasks.transition(
                    task_id,
                    new_status=new_status,
                    output=output,
                )
            except ValueError as exc:
                return JSONResponse({"error": str(exc)}, status_code=400)
            if t is None:
                return JSONResponse(
                    {"error": "not found"}, status_code=404
                )
            audit.record(
                action=_transition_audit_action(new_status),
                target=f"task:{t.id}",
                status=(
                    "success" if new_status == "succeeded"
                    else "failure" if new_status == "failed"
                    else "skipped" if new_status == "aborted"
                    else None
                ),
                metadata={
                    "kind": t.kind,
                    "from_status": existing.status,
                    "to_status": new_status,
                    "parent_session_id": t.parent_session_id,
                    "progress": t.progress,
                },
            )
            return JSONResponse({"task": t.to_dict()})
        finally:
            reset_current_actor(actor_token)

    @mcp.custom_route(
        "/api/v1/tasks/{task_id}/abort",
        methods=["POST"],
        include_in_schema=False,
    )
    async def abort_task(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        actor_token = set_current_actor("user:operator")
        try:
            task_id = request.path_params["task_id"]
            body = await _json_body(request, allow_empty=True)
            reason = (
                body.get("reason") if isinstance(body, dict) else None
            )
            existing = tasks.get(task_id)
            if existing is None:
                return JSONResponse(
                    {"error": "not found"}, status_code=404
                )
            t = tasks.abort(task_id, reason=reason)
            if t is None:
                return JSONResponse(
                    {"error": "not found"}, status_code=404
                )
            if existing.status not in TERMINAL_STATUS:
                audit.record(
                    action="task_aborted",
                    target=f"task:{t.id}",
                    status="skipped",
                    metadata={
                        "kind": t.kind,
                        "from_status": existing.status,
                        "reason": reason,
                        "parent_session_id": t.parent_session_id,
                    },
                )
            return JSONResponse({"task": t.to_dict()})
        finally:
            reset_current_actor(actor_token)


# ─── Helpers ───────────────────────────────────────────────────────


def _transition_audit_action(new_status: str) -> str:
    """Map a status to its audit action name. Keeps observability
    queries clean: action:task_started for run-starts, action:
    task_completed for the success terminal, etc."""
    return {
        "running": "task_started",
        "succeeded": "task_completed",
        "failed": "task_failed",
        "aborted": "task_aborted",
        "pending": "task_pending",  # rare; usually the create row
    }.get(new_status, "task_transitioned")


async def _json_body(
    request: Request, allow_empty: bool = False
) -> dict[str, Any] | JSONResponse:
    """Parse JSON body with friendly error responses."""
    try:
        body = await request.json()
    except Exception as exc:
        if allow_empty:
            return {}
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
