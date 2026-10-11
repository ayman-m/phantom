"""Plugin hook invocation endpoints.

The agent's hook-runner (lib/hook-runner.ts) sees hooks with
`transport.type === "plugin"` and needs to call the plugin handler
server-side in MCP (plugin handlers are Python; hook-runner is TS).
This module bridges that gap:

  GET  /api/v1/plugin-hooks                — list discovered handlers
  POST /api/v1/plugin-hooks/{name}/invoke  — invoke handler with body
                                              {payload, config?, timeout_s?}

Both bearer-auth via MCP_TOKEN — only the agent (with the per-boot
random token) can invoke. No public exposure.

Audit: each invoke writes a `plugin_hook_invoked` event tagged with
the handler name + result category (allow/deny/no-op/error).
"""

from __future__ import annotations

import logging
from typing import Any

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from api.auth import require_bearer
from usecase.plugin_hook_runner import (
    invoke_handler,
    list_handlers,
    clear_cache,
)

logger = logging.getLogger("Phantom MCP")


def register_plugin_hook_invoke_routes(mcp: FastMCP) -> None:
    @mcp.custom_route(
        "/api/v1/plugin-hooks",
        methods=["GET"],
        include_in_schema=False,
    )
    async def list_plugin_hooks(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        # Optional ?refresh=1 — re-walk entry-points. Used after
        # /observability/plugins UI installs a new package.
        refresh = request.query_params.get("refresh") in {"1", "true", "yes"}
        if refresh:
            clear_cache()
        try:
            handlers = list_handlers()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "plugin_hook_invoke: list_handlers failed: %s", exc
            )
            return JSONResponse(
                {"error": f"discovery failed: {exc}", "handlers": []},
                status_code=500,
            )
        return JSONResponse({"handlers": handlers, "count": len(handlers)})

    @mcp.custom_route(
        "/api/v1/plugin-hooks/{name}/invoke",
        methods=["POST"],
        include_in_schema=False,
    )
    async def invoke_plugin_hook(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        name = request.path_params["name"]
        if not name or not isinstance(name, str):
            return JSONResponse(
                {"error": "handler name required in path"},
                status_code=400,
            )
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "body must be JSON"}, status_code=400)
        if not isinstance(body, dict):
            return JSONResponse(
                {"error": "body must be a JSON object"}, status_code=400
            )
        payload = body.get("payload")
        if not isinstance(payload, dict):
            return JSONResponse(
                {"error": "'payload' is required (JSON object)"},
                status_code=400,
            )
        config = body.get("config")
        if config is not None and not isinstance(config, dict):
            return JSONResponse(
                {"error": "'config' must be a JSON object or omitted"},
                status_code=400,
            )
        timeout_s = body.get("timeout_s", 5.0)
        if not isinstance(timeout_s, (int, float)) or timeout_s <= 0:
            return JSONResponse(
                {"error": "'timeout_s' must be a positive number"},
                status_code=400,
            )
        timeout_s = min(float(timeout_s), 60.0)  # cap at 60s

        outcome = invoke_handler(
            name=name,
            payload=payload,
            config=config or {},
            timeout_s=timeout_s,
        )

        # Audit the invocation regardless of success/failure. Result
        # category: ok-allow, ok-deny, ok-no-op, error.
        try:
            from usecase.audit_log import record_event
            category = _categorize_outcome(outcome)
            record_event(
                "plugin_hook_invoked",
                target=f"plugin-hook:{name}",
                status="success" if outcome.get("ok") else "failure",
                metadata={
                    "handler": outcome.get("handler", ""),
                    "category": category,
                    "duration_ms": outcome.get("duration_ms", 0),
                    "error_tail": str(outcome.get("error", ""))[:300],
                },
            )
        except Exception:
            # Auditing must never break the dispatch path.
            pass

        status_code = 200 if outcome.get("ok") else 500
        return JSONResponse(outcome, status_code=status_code)


def _categorize_outcome(outcome: dict[str, Any]) -> str:
    """Bucket the outcome for audit metadata."""
    if not outcome.get("ok"):
        return "error"
    result = outcome.get("result")
    if result is None:
        return "no-op"
    decision = result.get("decision") if isinstance(result, dict) else None
    if decision == "deny":
        return "deny"
    if decision == "allow":
        return "allow"
    if decision == "ask":
        return "ask"
    return "ok-other"
