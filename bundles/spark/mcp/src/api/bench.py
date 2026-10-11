"""Benchmark HTTP endpoints.

Surfaces the BenchRunStore for the /observability/bench UI page.
Three endpoints:

  GET    /api/v1/bench/runs                  → list recent runs
  GET    /api/v1/bench/runs/{run_id}         → per-run detail
  POST   /api/v1/bench/runs                  → invoke bench_run tool

The POST is a thin convenience layer over the bench_run MCP tool —
operators can trigger a benchmark from the UI without going through
chat. Auth via bearer MCP_TOKEN like every other /api/v1/* endpoint.
"""

from __future__ import annotations

import logging

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from api.auth import require_bearer
from usecase.benchmark import BenchRunStore

logger = logging.getLogger("Phantom MCP")


def register_bench_routes(mcp: FastMCP, store: BenchRunStore) -> None:
    """Register /api/v1/bench/* routes on the FastMCP server."""

    @mcp.custom_route(
        "/api/v1/bench/runs", methods=["GET"], include_in_schema=False,
    )
    async def list_runs(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        # No default limit and no hard cap, so /observability/bench never
        # silently truncates the run history. Pagination is opt-in.
        raw = request.query_params.get("limit")
        try:
            limit: int | None = int(raw) if raw not in (None, "") else None
        except ValueError:
            limit = None
        if limit is not None and limit <= 0:
            limit = None
        rows = store.list_recent(limit=limit)
        return JSONResponse({"runs": rows, "count": len(rows)})

    @mcp.custom_route(
        "/api/v1/bench/runs/{run_id}",
        methods=["GET"],
        include_in_schema=False,
    )
    async def get_run(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        run_id = request.path_params["run_id"]
        row = store.get(run_id)
        if row is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        return JSONResponse({"run": row})

    @mcp.custom_route(
        "/api/v1/bench/runs",
        methods=["POST"],
        include_in_schema=False,
    )
    async def start_run(request: Request) -> JSONResponse:
        """Trigger a bench run from the UI. Returns the recorded
        summary. Synchronous — bench runs are typically 1-5 minutes
        for the bundled corpus, fits in HTTP request scope."""
        if (resp := require_bearer(request)) is not None:
            return resp
        try:
            body = await request.json()
        except Exception:
            return JSONResponse(
                {"error": "body must be JSON"}, status_code=400,
            )
        if not isinstance(body, dict):
            return JSONResponse(
                {"error": "body must be a JSON object"}, status_code=400,
            )
        manifest = body.get("manifest")
        if not isinstance(manifest, str) or not manifest.strip():
            return JSONResponse(
                {"error": "'manifest' is required (path or bundled id)"},
                status_code=400,
            )
        router_preset = body.get("router_preset_model")
        if router_preset is not None and not isinstance(router_preset, str):
            return JSONResponse(
                {"error": "router_preset_model must be a string"},
                status_code=400,
            )
        thinking_enabled = bool(body.get("thinking_enabled", False))

        from usecase.benchmark_runner import run_manifest
        try:
            summary = await run_manifest(
                manifest,
                router_preset_model=router_preset,
                thinking_enabled=thinking_enabled,
                record=True,
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except Exception as exc:  # noqa: BLE001
            logger.exception("bench run failed for manifest %s", manifest)
            return JSONResponse(
                {"error": f"run failed: {exc}"}, status_code=500,
            )
        return JSONResponse(
            {"run_id": summary.run_id, "summary": summary.to_dict()},
            status_code=201,
        )
