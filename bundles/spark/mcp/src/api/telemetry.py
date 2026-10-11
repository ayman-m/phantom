"""Telemetry HTTP endpoints — opt-in usage counters.

  GET  /api/v1/telemetry             → status snapshot:
        {enabled, declared_events, total_recorded, counts_by_event}
  POST /api/v1/telemetry/enable      → toggle on/off
        body: {"enabled": true|false, "actor": "operator"}
  POST /api/v1/telemetry/record      → record one event (admin/internal)
        body: {"event": "simulation_run_count_per_day", "count": 1, "payload": {...}}
  GET  /api/v1/telemetry/daily       → per-day counts for charting
        ?event=simulation_run_count_per_day
        ?days=30

Privacy posture: telemetry starts OFF (manifest.telemetry.default ==
"off"). The operator must explicitly enable it via /enable. Even when
on, only events declared in manifest.telemetry.events are recorded —
arbitrary callers can't slip new event names through.
"""

from __future__ import annotations

import logging
from typing import Any

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from api.auth import require_bearer
from usecase.telemetry import SqliteTelemetryStore

logger = logging.getLogger("Phantom MCP")


def register_telemetry_routes(mcp: FastMCP, store: SqliteTelemetryStore) -> None:
    @mcp.custom_route(
        "/api/v1/telemetry", methods=["GET"], include_in_schema=False
    )
    async def status(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        return JSONResponse(store.status().to_dict())

    @mcp.custom_route(
        "/api/v1/telemetry/enable", methods=["POST"], include_in_schema=False
    )
    async def enable(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        try:
            body: dict[str, Any] = await request.json()
        except Exception:
            return JSONResponse({"error": "Body must be JSON"}, status_code=400)
        if not isinstance(body.get("enabled"), bool):
            return JSONResponse(
                {"error": "`enabled` must be true or false"}, status_code=400
            )
        changed = store.set_enabled(body["enabled"], actor=body.get("actor"))
        return JSONResponse(
            {"enabled": store.is_enabled(), "changed": changed}
        )

    @mcp.custom_route(
        "/api/v1/telemetry/record", methods=["POST"], include_in_schema=False
    )
    async def record(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        try:
            body: dict[str, Any] = await request.json()
        except Exception:
            return JSONResponse({"error": "Body must be JSON"}, status_code=400)
        event = body.get("event")
        if not isinstance(event, str) or not event:
            return JSONResponse({"error": "`event` is required"}, status_code=400)
        count = body.get("count", 1)
        if not isinstance(count, int) or count < 1:
            return JSONResponse({"error": "`count` must be a positive int"}, status_code=400)
        payload = body.get("payload") or {}
        recorded = store.record(event, count=count, payload=payload)
        return JSONResponse(
            {
                "recorded": recorded,
                "skipped_reason": (
                    None if recorded else
                    "telemetry disabled" if not store.is_enabled() else
                    "event not declared in manifest"
                ),
            }
        )

    @mcp.custom_route(
        "/api/v1/telemetry/daily", methods=["GET"], include_in_schema=False
    )
    async def daily(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        q = request.query_params
        try:
            days = int(q.get("days") or "30")
        except ValueError:
            days = 30
        return JSONResponse(
            {
                "buckets": store.daily_counts(
                    event_name=q.get("event") or None, days=days
                )
            }
        )
