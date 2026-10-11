"""Hooks HTTP endpoints.

The Next.js agent's chat-route loads registered hooks at every event
fire-site (PreToolUse, PostToolUse, etc.) via these endpoints. The
/settings/hooks UI also reads/writes here.

Endpoints (all require `Authorization: Bearer <MCP_TOKEN>`):

  GET    /api/v1/hooks                 → list all hooks
  GET    /api/v1/hooks?event=<name>    → list hooks for one event
                                         (priority asc, enabled-only)
  GET    /api/v1/hooks/{id}            → fetch one hook
  POST   /api/v1/hooks                 → create or upsert
  PATCH  /api/v1/hooks/{id}            → partial update (toggles
                                         enabled, modify fields)
  DELETE /api/v1/hooks/{id}            → remove

Audit:

  Every hook lifecycle write emits a `hook_*` audit row so an
  operator can answer "who registered the prod-block hook?" /
  "when did the slack hook get disabled?" via /observability/events.
"""

from __future__ import annotations

import logging
import uuid
import time
from typing import Any

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from api.auth import require_bearer
from usecase.hook_store import SqliteHookStore
from usecase.audit_log import SqliteAuditLog, set_current_actor, reset_current_actor

logger = logging.getLogger("Phantom MCP")

# Mirror the agent-side HOOK_EVENTS const so the MCP can reject
# writes with unknown event names. Kept in sync manually; if the
# agent adds a new event, add it here too.
KNOWN_HOOK_EVENTS = {
    "PreToolUse",
    "PostToolUse",
    "PostToolUseFailure",
    "UserPromptSubmit",
    "PreCompact",
    "PostCompact",
    "RunStart",
    "RunEnd",
    "SubagentStart",
    "SubagentEnd",
    # Registered MCP-side so POST /api/v1/hooks accepts them; the MCP
    # code paths that emit Notification / PermissionRequest dispatch them.
    "Notification",
    "PermissionRequest",
}


def register_hook_routes(
    mcp: FastMCP,
    hooks: SqliteHookStore,
    audit: SqliteAuditLog,
) -> None:
    """Register /api/v1/hooks/* routes on the FastMCP server."""

    @mcp.custom_route(
        "/api/v1/hooks", methods=["GET"], include_in_schema=False
    )
    async def list_hooks(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        q = request.query_params
        event = q.get("event") or None
        enabled_only = q.get("enabled_only") in ("1", "true", "yes")
        if event is not None and event not in KNOWN_HOOK_EVENTS:
            return JSONResponse(
                {
                    "error": (
                        f"unknown event '{event}'. Known: "
                        f"{sorted(KNOWN_HOOK_EVENTS)}"
                    )
                },
                status_code=400,
            )
        rows = hooks.list(event=event, enabled_only=enabled_only)
        return JSONResponse(
            {"hooks": [r.to_dict() for r in rows], "count": len(rows)}
        )

    @mcp.custom_route(
        "/api/v1/hooks/{hook_id}",
        methods=["GET"],
        include_in_schema=False,
    )
    async def get_hook(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        h = hooks.get(request.path_params["hook_id"])
        if h is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        return JSONResponse({"hook": h.to_dict()})

    @mcp.custom_route(
        "/api/v1/hooks", methods=["POST"], include_in_schema=False
    )
    async def create_or_upsert_hook(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        actor_token = set_current_actor("user:operator")
        try:
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
            err = _validate_hook_payload(body)
            if err is not None:
                return JSONResponse({"error": err}, status_code=400)
            # Mint id if absent. Allow caller-provided id for
            # idempotent upsert.
            if not body.get("id"):
                body["id"] = str(uuid.uuid4())
            now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            body.setdefault("createdAt", now)
            body["updatedAt"] = now
            try:
                created = hooks.upsert(body)
            except ValueError as exc:
                return JSONResponse({"error": str(exc)}, status_code=400)
            audit.record(
                action="hook_upsert",
                target=f"hook:{created.id}",
                status="success",
                metadata={
                    "event": created.event,
                    "name": body.get("name"),
                    "enabled": created.enabled,
                    "priority": created.priority,
                    "transport_type": (
                        body.get("transport", {}).get("type")
                    ),
                },
            )
            return JSONResponse(
                {"hook": created.to_dict()}, status_code=201
            )
        finally:
            reset_current_actor(actor_token)

    @mcp.custom_route(
        "/api/v1/hooks/{hook_id}",
        methods=["PATCH"],
        include_in_schema=False,
    )
    async def patch_hook(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        actor_token = set_current_actor("user:operator")
        try:
            hook_id = request.path_params["hook_id"]
            existing = hooks.get(hook_id)
            if existing is None:
                return JSONResponse(
                    {"error": "not found"}, status_code=404
                )
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
            # Fast path: enabled-only toggle (the most common edit
            # from the UI).
            if (
                set(body.keys()) <= {"enabled"}
                and "enabled" in body
            ):
                if not isinstance(body["enabled"], bool):
                    return JSONResponse(
                        {"error": "'enabled' must be a boolean"},
                        status_code=400,
                    )
                updated = hooks.set_enabled(hook_id, body["enabled"])
                if updated is None:
                    return JSONResponse(
                        {"error": "not found"}, status_code=404
                    )
                audit.record(
                    action=(
                        "hook_enabled" if body["enabled"]
                        else "hook_disabled"
                    ),
                    target=f"hook:{hook_id}",
                    status="success",
                    metadata={"event": updated.event},
                )
                return JSONResponse({"hook": updated.to_dict()})
            # Full upsert path: merge body onto existing payload +
            # validate the result.
            merged = {
                **existing.to_dict(),
                **body,
                "id": existing.id,  # id is immutable
                "createdAt": existing.created_at,
            }
            err = _validate_hook_payload(merged)
            if err is not None:
                return JSONResponse({"error": err}, status_code=400)
            try:
                updated = hooks.upsert(merged)
            except ValueError as exc:
                return JSONResponse({"error": str(exc)}, status_code=400)
            audit.record(
                action="hook_upsert",
                target=f"hook:{updated.id}",
                status="success",
                metadata={
                    "event": updated.event,
                    "name": merged.get("name"),
                    "enabled": updated.enabled,
                },
            )
            return JSONResponse({"hook": updated.to_dict()})
        finally:
            reset_current_actor(actor_token)

    @mcp.custom_route(
        "/api/v1/hooks/{hook_id}",
        methods=["DELETE"],
        include_in_schema=False,
    )
    async def delete_hook(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        actor_token = set_current_actor("user:operator")
        try:
            hook_id = request.path_params["hook_id"]
            existing = hooks.get(hook_id)
            ok = hooks.delete(hook_id)
            if not ok:
                return JSONResponse(
                    {"error": "not found"}, status_code=404
                )
            audit.record(
                action="hook_deleted",
                target=f"hook:{hook_id}",
                status="success",
                metadata={
                    "event": existing.event if existing else None,
                },
            )
            return JSONResponse({"deleted": True, "id": hook_id})
        finally:
            reset_current_actor(actor_token)


# ─── Validators ────────────────────────────────────────────────────


def _validate_hook_payload(body: dict[str, Any]) -> str | None:
    """Minimal validation. The agent UI does the heavy lifting in
    `lib/hooks.ts:validateHook`; we only block obvious tampering and
    unknown events here.

    Transport shapes (the agent-side `validateHook` validates richer
    rules — for `builtin` the agent confirms `transport.name` resolves
    in its registry + invokes the spec's `validateConfig`):

      command  → transport.command: str
      http     → transport.url: str
      agent    → transport.toolName: str
      builtin  → transport.name: str (registered in
                 mcp/agent/lib/hook-builtins/index.ts),
                 transport.config: dict (shape governed by the
                 builtin's spec; we accept any dict here and trust
                 the agent-side validateConfig).
    """
    name = body.get("name")
    if not isinstance(name, str) or not name.strip():
        return "'name' is required and must be a non-empty string"
    event = body.get("event")
    if not isinstance(event, str) or event not in KNOWN_HOOK_EVENTS:
        return (
            f"'event' must be one of {sorted(KNOWN_HOOK_EVENTS)}; "
            f"got {event!r}"
        )
    transport = body.get("transport")
    if not isinstance(transport, dict):
        return "'transport' is required and must be an object"
    t_type = transport.get("type")
    if t_type not in ("command", "http", "agent", "builtin", "plugin"):
        return (
            "'transport.type' must be 'command' | 'http' | 'agent' | "
            f"'builtin' | 'plugin'; got {t_type!r}"
        )
    if t_type == "command" and not isinstance(
        transport.get("command"), str
    ):
        return "'transport.command' is required for command transport"
    if t_type == "http" and not isinstance(
        transport.get("url"), str
    ):
        return "'transport.url' is required for http transport"
    if t_type == "agent" and not isinstance(
        transport.get("toolName"), str
    ):
        return "'transport.toolName' is required for agent transport"
    if t_type == "builtin":
        b_name = transport.get("name")
        if not isinstance(b_name, str) or not b_name.strip():
            return (
                "'transport.name' is required and must be a non-empty "
                "string for builtin transport"
            )
        b_config = transport.get("config")
        if not isinstance(b_config, dict):
            return (
                "'transport.config' is required and must be an object "
                "for builtin transport (the agent's hook-builtins "
                "registry governs the field shape)"
            )
    if t_type == "plugin":
        # Plugin-handler transport. Lighter validation than
        # builtin: we don't know the plugin's config schema from
        # MCP-side either (entry-points are loaded lazily by the
        # invoker). Just confirm handlerName is non-empty + config is
        # either omitted or an object.
        h_name = transport.get("handlerName")
        if not isinstance(h_name, str) or not h_name.strip():
            return (
                "'transport.handlerName' is required and must be a "
                "non-empty string for plugin transport (the name of "
                "an entry-point in the phantom.hooks group; see "
                "/api/v1/plugin-hooks for the discovered list)"
            )
        p_config = transport.get("config")
        if p_config is not None and not isinstance(p_config, dict):
            return (
                "'transport.config' must be an object or omitted "
                "for plugin transport"
            )
        timeout_s = transport.get("timeoutS")
        if timeout_s is not None and (
            not isinstance(timeout_s, (int, float)) or timeout_s <= 0
        ):
            return (
                "'transport.timeoutS' must be a positive number or "
                "omitted for plugin transport"
            )
    if (timeout := body.get("timeoutMs")) is not None:
        if not isinstance(timeout, int) or timeout < 100 or timeout > 60000:
            return (
                "'timeoutMs' must be an integer in [100, 60000]; "
                f"got {timeout!r}"
            )
    failure = body.get("failurePolicy")
    if (
        failure is not None
        and failure not in ("block", "allow", "warn")
    ):
        return (
            "'failurePolicy' must be 'block' | 'allow' | 'warn'; "
            f"got {failure!r}"
        )
    return None
