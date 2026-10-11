"""Notifications HTTP endpoints.

  GET  /api/v1/notifications/topics             → manifest topic catalog
  GET  /api/v1/notifications                    → list (filterable)
        ?target=user:operator
        ?unread=true
        ?limit=100
  GET  /api/v1/notifications/unread_count       → integer
        ?target=user:operator
  POST /api/v1/notifications                    → publish (admin)
        body: {"topic": "simulation-complete", "payload": {...}, "actor": "operator"}
  POST /api/v1/notifications/{id}/ack           → mark read

The agent UI's notification bell calls list() + unread_count() to
render. Tools call publish() at the end of long-running operations
(e.g. simulation_complete). External integrations could also publish
via API key with a future `notifications:write` scope.
"""

from __future__ import annotations

import logging
from typing import Any

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from api.auth import require_bearer
from usecase.notifications import SqliteNotificationStore

logger = logging.getLogger("Phantom MCP")


def register_notification_routes(
    mcp: FastMCP, store: SqliteNotificationStore
) -> None:
    @mcp.custom_route(
        "/api/v1/notifications/topics", methods=["GET"], include_in_schema=False
    )
    async def list_topics(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        return JSONResponse(
            {
                "topics": [
                    {"name": t.name, "severity": t.severity, "target": t.target}
                    for t in store.topics()
                ]
            }
        )

    @mcp.custom_route(
        "/api/v1/notifications", methods=["GET"], include_in_schema=False
    )
    async def list_notifications(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        q = request.query_params
        unread_only = (q.get("unread") or "").lower() in {"1", "true", "yes"}
        try:
            limit = int(q.get("limit") or "100")
        except ValueError:
            limit = 100
        results = store.list(
            target=q.get("target") or None,
            unread_only=unread_only,
            limit=limit,
        )
        return JSONResponse(
            {
                "notifications": [n.to_dict() for n in results],
                "count": len(results),
            }
        )

    @mcp.custom_route(
        "/api/v1/notifications/unread_count",
        methods=["GET"],
        include_in_schema=False,
    )
    async def count_unread(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        target = request.query_params.get("target") or None
        return JSONResponse(
            {"target": target, "unread": store.unread_count(target=target)}
        )

    @mcp.custom_route(
        "/api/v1/notifications", methods=["POST"], include_in_schema=False
    )
    async def publish(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        try:
            body: dict[str, Any] = await request.json()
        except Exception:
            return JSONResponse({"error": "Body must be JSON"}, status_code=400)
        topic = body.get("topic")
        payload = body.get("payload") or {}
        actor = body.get("actor")
        if not isinstance(topic, str) or not topic:
            return JSONResponse({"error": "`topic` is required"}, status_code=400)
        if not isinstance(payload, dict):
            return JSONResponse(
                {"error": "`payload` must be a JSON object"}, status_code=400
            )
        try:
            notif = store.publish(topic=topic, payload=payload, actor=actor)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        # Notify the agent's hook
        # dispatcher so operator-installed Notification hooks fire.
        # Fire-and-forget; a hook callback failure must NOT block
        # notification creation.
        from usecase.hook_dispatch_callback import fire_hook_event_async
        fire_hook_event_async(
            "Notification",
            {
                "event": "Notification",
                "notificationId": notif.id,
                "severity": (
                    payload.get("severity")
                    if isinstance(payload.get("severity"), str)
                    else "info"
                ),
                "category": topic,
                "title": (
                    payload.get("title")
                    if isinstance(payload.get("title"), str)
                    else topic
                ),
                "body": (
                    payload.get("body")
                    if isinstance(payload.get("body"), str)
                    else ""
                ),
                "createdAt": notif.created_at,
                "related": {
                    k: payload.get(k)
                    for k in ("session_id", "job_id", "instance_id")
                    if isinstance(payload.get(k), str)
                },
            },
        )
        return JSONResponse(notif.to_dict(), status_code=201)

    @mcp.custom_route(
        "/api/v1/notifications/{notif_id}/ack",
        methods=["POST"],
        include_in_schema=False,
    )
    async def ack(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        notif_id = request.path_params.get("notif_id", "")
        if not notif_id:
            return JSONResponse({"error": "id required"}, status_code=400)
        ok = store.ack(notif_id)
        return JSONResponse(
            {"acked": ok, "id": notif_id},
            status_code=200 if ok else 404,
        )
