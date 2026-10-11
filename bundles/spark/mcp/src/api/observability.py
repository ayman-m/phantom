"""Observability HTTP endpoints — runtime structured events.

  GET /api/v1/observability/events           → query runtime events
        ?event=<name>
        ?actor=<principal>
        ?since=<iso8601>
        ?until=<iso8601>
        ?limit=100
        ?offset=0
  GET /api/v1/observability/events/summary   → counts-by-name rollup
  POST /api/v1/observability/events          → record one event
        body: {"event": "rt.simulation.started", "payload": {...}}

The Prometheus endpoint at /api/v1/metrics is in api/metrics.py;
audit events are at /api/v1/audit. This module is specifically for
runtime telemetry events declared in manifest.observability.events[].
"""

from __future__ import annotations

import logging
from typing import Any

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from api.auth import require_bearer
from usecase.event_log import SqliteEventLog

logger = logging.getLogger("Phantom MCP")


def register_observability_routes(mcp: FastMCP, events: SqliteEventLog) -> None:
    @mcp.custom_route(
        "/api/v1/observability/events",
        methods=["GET"],
        include_in_schema=False,
    )
    async def list_events(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        q = request.query_params

        def _int(name: str, default: int) -> int:
            try:
                return int(q.get(name) or default)
            except ValueError:
                return default

        results = events.query(
            event_name=q.get("event") or None,
            actor=q.get("actor") or None,
            since=q.get("since") or None,
            until=q.get("until") or None,
            limit=_int("limit", 100),
            offset=_int("offset", 0),
        )
        return JSONResponse(
            {
                "events": [e.to_dict() for e in results],
                "count": len(results),
                "declared_events": events.declared_events,
            }
        )

    @mcp.custom_route(
        "/api/v1/observability/events/summary",
        methods=["GET"],
        include_in_schema=False,
    )
    async def summary(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        return JSONResponse(
            {
                "counts": events.summary(),
                "declared_events": events.declared_events,
            }
        )

    @mcp.custom_route(
        "/api/v1/observability/events",
        methods=["POST"],
        include_in_schema=False,
    )
    async def record_event(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        try:
            body: dict[str, Any] = await request.json()
        except Exception:
            return JSONResponse({"error": "Body must be JSON"}, status_code=400)
        event = body.get("event")
        if not isinstance(event, str) or not event:
            return JSONResponse({"error": "`event` is required"}, status_code=400)
        payload = body.get("payload") or {}
        if not isinstance(payload, dict):
            return JSONResponse(
                {"error": "`payload` must be a JSON object"}, status_code=400
            )
        actor = (
            getattr(request.state, "auth_principal", None)
            or body.get("actor")
            or None
        )
        row_id = events.record(event, payload=payload, actor=actor)
        if row_id is None:
            return JSONResponse(
                {
                    "recorded": False,
                    "reason": "event not declared in manifest.observability.events",
                    "declared_events": events.declared_events,
                },
                status_code=400,
            )
        return JSONResponse(
            {"recorded": True, "id": row_id, "event": event},
            status_code=201,
        )
