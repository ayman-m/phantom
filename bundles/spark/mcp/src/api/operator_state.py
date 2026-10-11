"""Operator workflow state API — canonical surface.

Persists operator workflow state (journey-tested marks, metrics
bookmarks) through an MCP-side REST surface backed by operator_state_store,
so it follows the operator across devices rather than living in browser
localStorage.

Endpoints (all require `Authorization: Bearer <MCP_TOKEN>`):

  GET    /api/v1/operator-state           → list all keys + values
  GET    /api/v1/operator-state/{key}     → one key (404 if unset)
  PUT    /api/v1/operator-state/{key}     → upsert {value: <json>}
  DELETE /api/v1/operator-state/{key}     → remove (204 idempotent)

# Body shape for PUT

The body is a JSON object with a single `value` field carrying the
hook's payload. Wrapping in `value` (rather than raw body == payload)
lets us add metadata later (e.g. updated_at echo, version tag) without
breaking the schema. Same pattern providers / instances use for their
config blocks.

  PUT /api/v1/operator-state/tested_journeys
  Content-Type: application/json
  Authorization: Bearer <MCP_TOKEN>
  Body: { "value": ["v050-test-default-state", "v050-test-install-via-ui"] }

# Why "operator workflow state" is a separate surface

Per CLAUDE.md's catalog-vs-credential boundary: credentials
are forbidden for the agent, catalog is permitted. Operator workflow
state is a THIRD category — it's NOT a secret AND it's NOT platform
catalogue. It's the operator's personal workflow markers: tested
journeys, bookmarked queries, eventually saved search filters,
favorite skills, etc.

This surface is operator-only (cookie-authenticated via the Next.js
proxy), NOT agent-accessible. The agent has no reason to read
"which journeys did the operator mark tested" — that's the
operator's own progress tracking. If/when a use case for agent
visibility emerges (e.g. "which tests did the human complete so I
can summarize"), we add a read-only agent tool then. Default closed
matches the default-closed posture.
"""

from __future__ import annotations

import logging
from typing import Any

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from api.auth import require_bearer
from usecase.audit_log import (
    record_event,
    reset_current_actor,
    set_current_actor,
)
from usecase.operator_state_store import (
    OperatorState,
    OperatorStateStore,
)

logger = logging.getLogger("Phantom MCP")


def _row_to_dict(row: OperatorState | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "key": row.key,
        "value": row.value,
        "updated_at": row.updated_at,
    }


def register_operator_state_routes(
    mcp: FastMCP,
    store: OperatorStateStore,
) -> None:
    """Wire the operator-state HTTP surface onto the given FastMCP."""

    @mcp.custom_route(
        "/api/v1/operator-state", methods=["GET"], include_in_schema=False,
    )
    async def list_operator_state(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        rows = store.list_all()
        return JSONResponse(
            {"entries": [_row_to_dict(r) for r in rows], "count": len(rows)},
        )

    @mcp.custom_route(
        "/api/v1/operator-state/{key}",
        methods=["GET"],
        include_in_schema=False,
    )
    async def get_operator_state(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        key = request.path_params["key"]
        row = store.get(key)
        if row is None:
            return JSONResponse(
                {"error": f"operator-state key {key!r} not set"},
                status_code=404,
            )
        return JSONResponse(_row_to_dict(row))

    @mcp.custom_route(
        "/api/v1/operator-state/{key}",
        methods=["PUT"],
        include_in_schema=False,
    )
    async def put_operator_state(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        key = request.path_params["key"]

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
        if "value" not in body:
            return JSONResponse(
                {"error": "body must contain a 'value' field"},
                status_code=400,
            )

        actor_token = set_current_actor("user:operator")
        try:
            try:
                row = store.put(key, body["value"])
            except ValueError as err:
                return JSONResponse(
                    {"error": str(err)}, status_code=400,
                )
            # Audit-log the mutation. Each hook will produce one of
            # these per change so the operator's "tested marks" or
            # "saved bookmarks" history is auditable like everything
            # else.
            record_event(
                action="operator_state_set",
                target=f"operator-state:{key}",
                status="success",
                metadata={"updated_at": row.updated_at},
            )
            return JSONResponse(_row_to_dict(row))
        finally:
            reset_current_actor(actor_token)

    @mcp.custom_route(
        "/api/v1/operator-state/{key}",
        methods=["DELETE"],
        include_in_schema=False,
    )
    async def delete_operator_state(request: Request) -> Response:
        if (resp := require_bearer(request)) is not None:
            return resp
        key = request.path_params["key"]

        actor_token = set_current_actor("user:operator")
        try:
            removed = store.delete(key)
            record_event(
                action="operator_state_delete",
                target=f"operator-state:{key}",
                status="success" if removed else "noop",
                metadata={},
            )
            # 204 on success (whether or not a row was actually
            # deleted — idempotent semantics). 404 would be wrong
            # since the caller's intent ("ensure this key is unset")
            # is satisfied either way.
            return Response(status_code=204)
        finally:
            reset_current_actor(actor_token)
