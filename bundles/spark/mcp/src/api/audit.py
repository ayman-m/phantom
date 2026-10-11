"""Audit query HTTP endpoints.

The Next.js agent's admin/security view calls these to render the
audit feed (recent events, action breakdown, search). External SOC
tools can also poll them for SIEM ingestion.

Endpoints (all require `Authorization: Bearer <MCP_TOKEN>`):

  GET /api/v1/audit               → paginated events (filterable)
  GET /api/v1/audit/summary       → counts-by-action posture rollup
  GET /api/v1/audit/stream        → SSE feed of new audit events

Read-only by design — the audit log is append-only at the storage
layer (no DELETE/UPDATE in SqliteAuditLog). Even with admin token, an
operator can't tamper with the log via HTTP. The only way to clear
audit history is to delete `<data_root>/audit.db` from the host (with
the corresponding ops/forensic implications).

Query params for GET /api/v1/audit:
    action          one of the manifest's audit.events (or the
                    instance/secret/provider events recorded by the
                    SqliteAuditLog itself)
    actor           "agent" | "user:operator" | "system"
    target          exact match, e.g. "tool:xsiam.execute_xql_query"
    target_prefix   LIKE prefix, e.g. "tool:" or "instance:"
    since, until    ISO8601 timestamps
    limit           default 100, max 1000
    offset          for paging
"""

from __future__ import annotations

import asyncio
import json
import logging

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse

from api.auth import require_bearer
from usecase.audit_log import SqliteAuditLog

logger = logging.getLogger("Phantom MCP")


def register_audit_routes(mcp: FastMCP, audit: SqliteAuditLog) -> None:
    """Register /api/v1/audit/* routes on the FastMCP server."""

    @mcp.custom_route("/api/v1/audit", methods=["GET"], include_in_schema=False)
    async def list_audit(request: Request) -> JSONResponse:
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

        # Filter set is shared between query() and count() so the
        # response can include both the page (events) and the unbounded
        # match count (total) — UI uses the latter for pagination
        # controls.
        filters = dict(
            action=q.get("action") or None,
            actor=q.get("actor") or None,
            target=q.get("target") or None,
            target_prefix=q.get("target_prefix") or None,
            since=q.get("since") or None,
            until=q.get("until") or None,
            trigger=q.get("trigger") or None,
            trigger_prefix=q.get("trigger_prefix") or None,
        )
        # Pass None when ?limit= is absent to get every event, so
        # /observability/events is never silently truncated. Pagination
        # is opt-in.
        raw_limit = q.get("limit")
        try:
            limit_arg = int(raw_limit) if raw_limit not in (None, "") else None
        except ValueError:
            limit_arg = None
        events = audit.query(
            **filters,
            limit=limit_arg,
            offset=_int("offset", 0),
        )
        total = audit.count(**filters)
        return JSONResponse(
            {"events": events, "count": len(events), "total": total}
        )

    @mcp.custom_route(
        "/api/v1/audit/summary", methods=["GET"], include_in_schema=False
    )
    async def audit_summary(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        return JSONResponse(audit.summary())

    @mcp.custom_route(
        "/api/v1/audit/stream", methods=["GET"], include_in_schema=False
    )
    async def audit_stream(request: Request) -> StreamingResponse:
        """SSE feed of new audit events.

        On connect, replays the most recent N events as a baseline so
        a fresh client sees context (configurable via `?initial=`,
        default 50, max 200). Then polls the audit log every 1s for
        events with id > the last seen id, and emits any new rows as
        SSE frames. Heartbeat every 25s to keep proxies happy.

        Why polling vs. an in-process pub/sub: the producer side hooks
        (the surface_bus.publish() calls deleted in 4e51b29) added
        complexity for a feed that doesn't need sub-second latency.
        SQLite is plenty fast at SELECT WHERE id > ? LIMIT 50 — the
        whole audit table is in-memory after the first read, and 1s
        polling plus an event volume of <100/min means each tick
        either finds nothing (fast no-op) or finds 1-2 rows.

        Disconnect / reconnect is the client's responsibility (the
        agent's /activity page handles it with exponential backoff).
        Rows are emitted in chronological order (oldest first within
        a single tick's batch).
        """
        if (resp := require_bearer(request)) is not None:
            return resp

        try:
            initial = int(request.query_params.get("initial", "50"))
        except ValueError:
            initial = 50
        initial = max(0, min(initial, 200))

        async def event_generator():
            # Baseline: most recent N events, oldest-first so the client
            # gets them in chronological order.
            #
            # initial=0 must mean NO replay. It cannot be passed through to
            # query(), which maps any limit <= 0 to SQL `LIMIT -1` — and in
            # SQLite that means UNLIMITED. So `?initial=0`, intended by the
            # chat sidebar to suppress the backlog, instead dumped the entire
            # audit table down the SSE pipe on every connect and reconnect.
            baseline = (
                list(reversed(audit.query(limit=initial))) if initial > 0 else []
            )
            last_ts = ""
            for row in baseline:
                last_ts = row["ts"]
                yield f"data: {json.dumps(row)}\n\n"

            # Live poll loop.
            heartbeat_counter = 0
            while True:
                if await request.is_disconnected():
                    break
                # Pull anything strictly newer than last_ts. Use a small
                # limit so a sudden burst doesn't lock the loop on one
                # tick — leftovers will arrive on the next tick.
                if last_ts:
                    new_rows = list(reversed(audit.query(since=last_ts, limit=50)))
                    # query(since=) is inclusive, so drop any whose ts
                    # equals last_ts (we already sent them).
                    new_rows = [r for r in new_rows if r["ts"] > last_ts]
                else:
                    new_rows = []
                for row in new_rows:
                    last_ts = row["ts"]
                    yield f"data: {json.dumps(row)}\n\n"

                # Heartbeat every 25 polls (~25s) — SSE comment frames
                # are ignored by parsers but keep nginx/cloudflare from
                # killing the connection as idle.
                heartbeat_counter += 1
                if heartbeat_counter >= 25:
                    yield ": heartbeat\n\n"
                    heartbeat_counter = 0

                await asyncio.sleep(1.0)

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "X-Accel-Buffering": "no",
            },
        )

    @mcp.custom_route(
        "/api/v1/audit", methods=["POST"], include_in_schema=False
    )
    async def write_audit(request: Request) -> JSONResponse:
        """Write an audit row from outside the
        MCP's own state-changing handlers.

        Use case: the Next.js agent's chat handler emits SSE events
        for compaction lifecycle, context-window warnings, and Vertex
        cache hits — none of which are tool calls (so no `tool_call`
        audit row is auto-written) and none of which mutate MCP state
        directly (so no other audit hook fires either). Without this
        endpoint those events stay live-only — they don't show up in
        /observability/events on subsequent loads. After this, the
        operator can run `action:chat_compaction_end` (etc.) queries
        against the audit DB and see the historical pattern.

        Body shape:
          {
            "action":      "chat_compaction_end" | ... ,   # required
            "target":      "session:<uuid>" | ... ,        # optional
            "status":      "success" | "failure",          # optional
            "duration_ms": 1234,                           # optional
            "metadata":    { ... arbitrary JSON-serializable ... }
          }

        The actor is fixed to "user:operator" because the bearer
        token already authenticates the caller. The trigger is
        inherited from the X-Phantom-Trigger header (handled by the
        trigger_context middleware via the contextvar).

        We intentionally don't constrain `action` to a closed enum —
        callers can introduce new action names freely. The
        observability page already accepts arbitrary action strings.
        """
        if (resp := require_bearer(request)) is not None:
            return resp
        from usecase.audit_log import set_current_actor, reset_current_actor
        actor_token = set_current_actor("user:operator")
        try:
            try:
                body = await request.json()
            except Exception as exc:
                return JSONResponse(
                    {"error": f"invalid JSON body: {exc}"}, status_code=400
                )
            if not isinstance(body, dict):
                return JSONResponse(
                    {"error": "body must be a JSON object"}, status_code=400
                )
            action = body.get("action")
            if not isinstance(action, str) or not action.strip():
                return JSONResponse(
                    {"error": "'action' is required and must be a non-empty string"},
                    status_code=400,
                )
            metadata = body.get("metadata") or {}
            if not isinstance(metadata, dict):
                return JSONResponse(
                    {"error": "'metadata' must be an object"}, status_code=400
                )
            duration_ms = body.get("duration_ms")
            if duration_ms is not None and not isinstance(duration_ms, int):
                return JSONResponse(
                    {"error": "'duration_ms' must be an integer if provided"},
                    status_code=400,
                )
            row_id = audit.record(
                action=action.strip(),
                target=body.get("target") or None,
                status=body.get("status") or None,
                duration_ms=duration_ms,
                metadata=metadata,
            )
            return JSONResponse({"id": row_id}, status_code=201)
        finally:
            reset_current_actor(actor_token)
