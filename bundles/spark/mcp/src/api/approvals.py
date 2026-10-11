"""Approval HTTP endpoints.

The Next.js agent's "pending approvals" view polls these to render
human-in-the-loop decisions for tools listed in the manifest's
`approvals.humanRequired`. When the operator clicks Approve/Deny, the
UI POSTs to /api/v1/approvals/{id}/resolve and the blocked tool call
in `connector_loader._wrap_with_instance` unblocks.

Endpoints (all require `Authorization: Bearer <MCP_TOKEN>`):

  GET  /api/v1/approvals                  → list (filterable by status)
  GET  /api/v1/approvals/{id}             → fetch one
  POST /api/v1/approvals/{id}/resolve     → approve or deny

Resolve body:
  {
    "decision": "approved" | "denied",
    "reason":   "optional human note"
  }

Resolution is idempotent — POSTing twice with different decisions
returns the original decision (the bus.resolve logic refuses to
overwrite a non-pending row). UIs that want to re-poll after a
network blip can therefore retry safely.
"""

from __future__ import annotations

import logging

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from api.auth import require_bearer
from usecase.approvals_bus import (
    InProcessApprovalsBus,
    STATUS_APPROVED,
    STATUS_DENIED,
    STATUS_PENDING,
    STATUS_TIMEOUT,
)
from usecase.audit_log import reset_current_actor, set_current_actor

logger = logging.getLogger("Phantom MCP")

_VALID_STATUS_FILTERS = {
    STATUS_PENDING, STATUS_APPROVED, STATUS_DENIED, STATUS_TIMEOUT
}


def register_approval_routes(mcp: FastMCP, bus: InProcessApprovalsBus) -> None:
    """Register /api/v1/approvals/* routes on the FastMCP server."""

    @mcp.custom_route(
        "/api/v1/approvals", methods=["GET"], include_in_schema=False
    )
    async def list_approvals(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        status = request.query_params.get("status")
        if status and status not in _VALID_STATUS_FILTERS:
            return JSONResponse(
                {
                    "error": f"invalid status {status!r}",
                    "allowed": sorted(_VALID_STATUS_FILTERS),
                },
                status_code=400,
            )
        try:
            limit = int(request.query_params.get("limit") or 100)
        except ValueError:
            limit = 100
        # Optional `origin=` filter so the chat-side poll loop
        # can scope to its session's pending rows ("chat:<sid>") and
        # not trip on job-fired approvals landing concurrently. Server-
        # side filter is faster + smaller payload than client-side.
        origin = request.query_params.get("origin")
        if status == STATUS_PENDING:
            rows = bus.list_pending()
        else:
            rows = bus.list_recent(status=status, limit=limit)
        if origin:
            rows = [r for r in rows if r.origin == origin]
        return JSONResponse(
            {"approvals": [r.to_dict() for r in rows], "count": len(rows)}
        )

    @mcp.custom_route(
        "/api/v1/approvals/{approval_id}",
        methods=["GET"],
        include_in_schema=False,
    )
    async def get_approval(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        approval_id = request.path_params["approval_id"]
        approval = bus.get(approval_id)
        if approval is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        return JSONResponse({"approval": approval.to_dict()})

    @mcp.custom_route(
        "/api/v1/approvals/{approval_id}/resolve",
        methods=["POST"],
        include_in_schema=False,
    )
    async def resolve_approval(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        # The resolver is the human operator who hit Approve/Deny.
        # Tag actor so the audit row attributes correctly. (The
        # ACTION_APPROVAL_RESOLVED audit record itself is written from
        # inside _wrap_with_instance after wait_async unblocks; here we
        # just set the actor for any auxiliary records.)
        actor_token = set_current_actor("user:operator")
        try:
            approval_id = request.path_params["approval_id"]
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
            decision = body.get("decision")
            if not isinstance(decision, str) or not decision:
                return JSONResponse(
                    {
                        "error": "'decision' is required (string)",
                        "allowed": ["approved", "denied"],
                    },
                    status_code=400,
                )
            reason = body.get("reason")
            if reason is not None and not isinstance(reason, str):
                return JSONResponse(
                    {"error": "'reason' must be a string when provided"},
                    status_code=400,
                )

            try:
                approval = bus.resolve(
                    approval_id,
                    resolver="user:operator",
                    decision=decision,
                    reason=reason,
                )
            except ValueError as exc:
                return JSONResponse({"error": str(exc)}, status_code=400)

            if approval is None:
                return JSONResponse({"error": "not found"}, status_code=404)

            logger.info(
                "Approval %s resolved via API: status=%s",
                approval_id, approval.status,
            )
            return JSONResponse({"approval": approval.to_dict()})
        finally:
            reset_current_actor(actor_token)
