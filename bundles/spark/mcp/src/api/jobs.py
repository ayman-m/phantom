"""Jobs HTTP endpoints.

The Next.js agent's "scheduled tasks" view calls these to render the
state of `manifest.yaml:jobs[]` at runtime — what's enabled, when each
is next due, and how the last run went. Operators can also manually
fire a job to test it without waiting for its cron.

Endpoints (all require `Authorization: Bearer <MCP_TOKEN>`):

  GET    /api/v1/jobs                          → list all jobs
  GET    /api/v1/jobs/{name}                   → fetch one
  GET    /api/v1/jobs/{name}/runs              → recent run history
  POST   /api/v1/jobs/{name}/run               → fire now (out of band)
  POST   /api/v1/jobs/{name}/disable           → pause cron
  POST   /api/v1/jobs/{name}/enable            → resume cron

The "run now" endpoint is the most important for verification:
operators can tell the system "fire this job right now" without having
to wait for the cron expression to come due. It dispatches through the
SAME tool registry the cron tick uses, so any failure mode (instance
not configured, approval pending, exception) shows up identically.
"""

from __future__ import annotations

import logging

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from api.auth import require_bearer
from usecase.audit_log import reset_current_actor, set_current_actor
from usecase.job_scheduler import CompletedRunOnceError, CroniterJobScheduler

logger = logging.getLogger("Phantom MCP")


def register_job_routes(mcp: FastMCP, sched: CroniterJobScheduler) -> None:
    """Register /api/v1/jobs/* routes on the FastMCP server."""

    @mcp.custom_route("/api/v1/jobs", methods=["GET"], include_in_schema=False)
    async def list_jobs(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        include_removed = (
            request.query_params.get("include_removed", "").lower()
            in ("1", "true", "yes")
        )
        rows = sched.list_jobs(include_removed=include_removed)
        return JSONResponse(
            {"jobs": [r.to_dict() for r in rows], "count": len(rows)}
        )

    @mcp.custom_route(
        "/api/v1/jobs/yaml-issues",
        methods=["GET"],
        include_in_schema=False,
    )
    async def list_yaml_issues(request: Request) -> JSONResponse:
        """Surface YAML-load failures that would otherwise be buried as
        WARN-per-file lines in docker compose logs.

        The /jobs UI page reads this on every load; when count > 0 it
        shows a banner pointing the operator at the file list. Each
        entry's basename + error reason is enough for the operator to
        either fix the YAML in place (docker exec phantom_agent vi
        /app/data/jobs/<basename>) or delete it if it's stale.

        Read-only — no auto-quarantine, no auto-delete, no operator-
        invisible state changes. The data files in /app/data/jobs/
        belong to the operator and we leave them alone.
        """
        if (resp := require_bearer(request)) is not None:
            return resp
        issues = list(getattr(sched, "yaml_load_issues", []) or [])
        return JSONResponse({
            "issues": issues,
            "count": len(issues),
        })

    # ─── Path-param resolver ─────────────────────────────────────
    #
    # The `{name}` path parameter name is retained for URL stability. Routes
    # accept EITHER an opaque UUID (the id-based URL the UI emits) or
    # the operator-facing name. resolve_ident() short-circuits
    # to id-lookup when the path looks like a UUID and falls back to
    # name otherwise — see CroniterJobScheduler.resolve_ident for
    # the precedence rules. The path-param key stays "name" to avoid
    # churning every route definition; semantically it's now "ident".
    def _ident_to_name(ident: str) -> str | None:
        row = sched.resolve_ident(ident)
        return row.name if row is not None else None

    @mcp.custom_route(
        "/api/v1/jobs/{name}", methods=["GET"], include_in_schema=False
    )
    async def get_job(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        ident = request.path_params["name"]
        row = sched.resolve_ident(ident)
        if row is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        return JSONResponse({"job": row.to_dict()})

    @mcp.custom_route(
        "/api/v1/jobs/{name}/runs",
        methods=["GET"],
        include_in_schema=False,
    )
    async def list_runs(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        ident = request.path_params["name"]
        canonical = _ident_to_name(ident)
        if canonical is None:
            return JSONResponse({"error": "job not found"}, status_code=404)
        try:
            limit = int(request.query_params.get("limit", "20"))
        except ValueError:
            limit = 20
        runs = sched.list_runs(canonical, limit=limit)
        return JSONResponse(
            {
                "job_name": canonical,
                "runs": [r.to_dict() for r in runs],
                "count": len(runs),
            }
        )

    @mcp.custom_route(
        "/api/v1/jobs/{name}/run",
        methods=["POST"],
        include_in_schema=False,
    )
    async def trigger_run(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        actor_token = set_current_actor("user:operator")
        try:
            ident = request.path_params["name"]
            canonical = _ident_to_name(ident)
            if canonical is None:
                return JSONResponse(
                    {"error": "job not found or removed"}, status_code=404
                )
            run = await sched.trigger_now(canonical)
            if run is None:
                return JSONResponse(
                    {"error": "job not found or removed"}, status_code=404
                )
            # Don't surface raw `result` payload — it may be huge
            # (a coverage report can be MBs). Operators retrieve it
            # via /api/v1/jobs/{name}/runs.
            d = run.to_dict()
            return JSONResponse(
                {
                    "run": {
                        k: v for k, v in d.items()
                        if k != "result"
                    },
                    "result_size_chars": (
                        len(run.result_json) if run.result_json else 0
                    ),
                },
                status_code=202,
            )
        finally:
            reset_current_actor(actor_token)

    @mcp.custom_route(
        "/api/v1/jobs/{name}/enable",
        methods=["POST"],
        include_in_schema=False,
    )
    async def enable_job(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        actor_token = set_current_actor("user:operator")
        try:
            ident = request.path_params["name"]
            canonical = _ident_to_name(ident)
            if canonical is None:
                return JSONResponse({"error": "not found"}, status_code=404)
            try:
                row = sched.set_enabled(canonical, True)
            except CompletedRunOnceError as exc:
                return JSONResponse({"error": str(exc)}, status_code=409)
            if row is None:
                return JSONResponse({"error": "not found"}, status_code=404)
            return JSONResponse({"job": row.to_dict()})
        finally:
            reset_current_actor(actor_token)

    @mcp.custom_route(
        "/api/v1/jobs/{name}/disable",
        methods=["POST"],
        include_in_schema=False,
    )
    async def disable_job(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        actor_token = set_current_actor("user:operator")
        try:
            ident = request.path_params["name"]
            canonical = _ident_to_name(ident)
            if canonical is None:
                return JSONResponse({"error": "not found"}, status_code=404)
            row = sched.set_enabled(canonical, False)
            if row is None:
                return JSONResponse({"error": "not found"}, status_code=404)
            return JSONResponse({"job": row.to_dict()})
        finally:
            reset_current_actor(actor_token)

    # ─── Runtime CRUD ──────────────────────────────────────────
    #
    # Jobs declared in manifest.yaml:jobs[] are reconciled at boot
    # (manifest is source of truth). Operators can ALSO create jobs
    # at runtime via these endpoints — those carry source='runtime'
    # and survive boot reconciliation untouched.

    @mcp.custom_route(
        "/api/v1/jobs", methods=["POST"], include_in_schema=False
    )
    async def create_job(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        actor_token = set_current_actor("user:operator")
        try:
            try:
                body = await request.json()
            except Exception:
                return JSONResponse(
                    {"error": "request body must be JSON"}, status_code=400
                )
            if not isinstance(body, dict):
                return JSONResponse(
                    {"error": "request body must be an object"}, status_code=400
                )
            try:
                row = sched.add_job(
                    name=body.get("name", ""),
                    cron=body.get("cron", ""),
                    timezone_name=body.get("timezone", "UTC"),
                    action=body.get("action") or {},
                    enabled=bool(body.get("enabled", True)),
                    run_once=bool(body.get("run_once", False)),
                    bypass_approvals=bool(body.get("bypass_approvals", False)),
                    # Per-job model override.
                    # Empty / missing → None (use runtime default).
                    model_id=body.get("model_id") or None,
                    thinking_enabled=bool(body.get("thinking_enabled", False)),
                    # Per-job permission policy.
                    # Accept dict directly OR omit / null. Empty dict
                    # has the same effect as None at create-time
                    # (no policy stored).
                    permission_policy=(
                        body.get("permission_policy")
                        if isinstance(body.get("permission_policy"), dict)
                        and body.get("permission_policy")
                        else None
                    ),
                    # Operator's note on the job (the form's Description).
                    description=body.get("description"),
                )
            except ValueError as exc:
                return JSONResponse({"error": str(exc)}, status_code=400)
            return JSONResponse({"job": row.to_dict()}, status_code=201)
        finally:
            reset_current_actor(actor_token)

    @mcp.custom_route(
        "/api/v1/jobs/{name}", methods=["PATCH"], include_in_schema=False
    )
    async def patch_job(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        actor_token = set_current_actor("user:operator")
        try:
            ident = request.path_params["name"]
            canonical = _ident_to_name(ident)
            if canonical is None:
                return JSONResponse({"error": "job not found"}, status_code=404)
            try:
                body = await request.json()
            except Exception:
                return JSONResponse(
                    {"error": "request body must be JSON"}, status_code=400
                )
            if not isinstance(body, dict):
                return JSONResponse(
                    {"error": "request body must be an object"}, status_code=400
                )
            try:
                row = sched.update_job(
                    canonical,
                    cron=body.get("cron"),
                    timezone_name=body.get("timezone"),
                    action=body.get("action"),
                    enabled=body.get("enabled"),
                    # Pass through only when present so PATCH
                    # without the field doesn't accidentally clobber an
                    # existing bypass setting (None means "leave alone").
                    bypass_approvals=body.get("bypass_approvals"),
                    # model_id: None=preserve,
                    # ""=clear, other string=set. thinking_enabled is
                    # tri-state None/True/False.
                    model_id=body.get("model_id"),
                    thinking_enabled=body.get("thinking_enabled"),
                    # permission policy: None=
                    # preserve, {}=clear, non-empty dict=set.
                    permission_policy=body.get("permission_policy"),
                    # description: None=preserve, ""=clear, text=set.
                    description=body.get("description"),
                )
            except ValueError as exc:
                return JSONResponse({"error": str(exc)}, status_code=400)
            if row is None:
                return JSONResponse(
                    {"error": "job not found"}, status_code=404
                )
            return JSONResponse({"job": row.to_dict()})
        finally:
            reset_current_actor(actor_token)

    @mcp.custom_route(
        "/api/v1/jobs/{name}", methods=["DELETE"], include_in_schema=False
    )
    async def delete_job(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        actor_token = set_current_actor("user:operator")
        try:
            ident = request.path_params["name"]
            canonical = _ident_to_name(ident)
            if canonical is None:
                return JSONResponse({"error": "job not found"}, status_code=404)
            ok = sched.delete_job(canonical)
            if not ok:
                return JSONResponse(
                    {"error": "job not found"}, status_code=404
                )
            return JSONResponse({"deleted": True, "name": canonical})
        finally:
            reset_current_actor(actor_token)
