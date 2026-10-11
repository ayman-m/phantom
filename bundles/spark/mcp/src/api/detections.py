"""Detection inventory + coverage REST endpoints.

  GET  /api/v1/detections                      → list rules with aggregated fire counts
  GET  /api/v1/detections/{rule_id}            → single rule summary
  GET  /api/v1/detections/{rule_id}/fires      → recent fires for one rule
  GET  /api/v1/detections/coverage/techniques  → per-MITRE-T-code aggregation
  POST /api/v1/detections/sync                 → upsert pre-fetched issues

The agent UI's `/coverage` page (future) consumes these. The agent
itself uses the equivalent built-in MCP tools (`detections_list`,
`technique_coverage`, etc) declared in
usecase/builtin_components/coverage_tools.py.
"""

from __future__ import annotations

import logging

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from api.auth import require_bearer
from usecase.detection_inventory import SqliteDetectionInventory

logger = logging.getLogger("Phantom MCP")


def register_detection_routes(
    mcp: FastMCP, inventory: SqliteDetectionInventory
) -> None:
    """Register /api/v1/detections* routes."""

    @mcp.custom_route(
        "/api/v1/detections", methods=["GET"], include_in_schema=False
    )
    async def list_rules(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        q = request.query_params
        try:
            limit = int(q.get("limit") or 100)
        except ValueError:
            limit = 100
        rows = inventory.list_rules(
            severity=q.get("severity") or None,
            technique=q.get("technique") or None,
            limit=limit,
        )
        return JSONResponse({
            "rules": [r.to_dict() for r in rows],
            "count": len(rows),
        })

    @mcp.custom_route(
        "/api/v1/detections/coverage/techniques",
        methods=["GET"],
        include_in_schema=False,
    )
    async def coverage_techniques(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        out = inventory.technique_coverage()
        return JSONResponse({
            "techniques": out,
            "total_techniques": len(out),
        })

    @mcp.custom_route(
        "/api/v1/detections/{rule_id}",
        methods=["GET"],
        include_in_schema=False,
    )
    async def get_rule(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        rule_id = request.path_params["rule_id"]
        summary = inventory.rule_summary(rule_id)
        if summary is None:
            return JSONResponse(
                {
                    "error": f"rule {rule_id!r} not found in inventory",
                    "hint": "Sync first via POST /api/v1/detections/sync, or "
                            "the rule may have never fired in this deploy.",
                },
                status_code=404,
            )
        return JSONResponse({"rule": summary.to_dict()})

    @mcp.custom_route(
        "/api/v1/detections/{rule_id}/fires",
        methods=["GET"],
        include_in_schema=False,
    )
    async def list_rule_fires(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        rule_id = request.path_params["rule_id"]
        q = request.query_params
        try:
            limit = int(q.get("limit") or 50)
        except ValueError:
            limit = 50
        rows = inventory.list_fires(
            rule_id=rule_id,
            since=q.get("since") or None,
            limit=limit,
        )
        return JSONResponse({
            "rule_id": rule_id,
            "fires": [r.to_dict() for r in rows],
            "count": len(rows),
        })

    @mcp.custom_route(
        "/api/v1/detections/sync",
        methods=["POST"],
        include_in_schema=False,
    )
    async def sync_issues(request: Request) -> JSONResponse:
        """Operator-direct ingest path (mirrors the `detections_sync`
        MCP tool). Body: {issues: [{...XSIAM issue dict}, ...]}.

        Used by the agent UI's coverage page when an operator pastes
        XSIAM JSON for backfill, AND by the closed-loop scheduled
        job (Commit 4) which posts here after fetching from XSIAM.
        """
        if (resp := require_bearer(request)) is not None:
            return resp
        try:
            body = await request.json()
        except Exception as exc:  # noqa: BLE001
            return JSONResponse(
                {"error": f"invalid JSON body: {exc}"},
                status_code=400,
            )
        if not isinstance(body, dict):
            return JSONResponse(
                {"error": "body must be a JSON object"},
                status_code=400,
            )
        issues = body.get("issues")
        if not isinstance(issues, list):
            return JSONResponse(
                {"error": "body.issues must be an array of issue dicts"},
                status_code=400,
            )
        result = inventory.upsert_fires(issues)
        return JSONResponse({"ok": True, **result})
