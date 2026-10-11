"""Worker-rate REST endpoints — proxies xlog's generation ceilings to the UI.

xlog enforces generation ceilings (per-worker sustained rate, declared-burst
allowance, aggregate rate, worker population) in its admission gate. Until this
module, none of that was visible outside container logs: an operator could have
a worker refused and no way to see what was consuming the budget.

The UI cannot call xlog directly — it is not exposed outside the docker
network, and its bearer token must not reach the browser. So the chain is:

    browser -> /api/agent/worker-rates (Next.js proxy)
            -> /api/v1/worker-rates    (this module, MCP_TOKEN-gated)
            -> xlog /api/v1/worker-rates (XLOG_API_TOKEN-gated)

Surface (all require `Authorization: Bearer <MCP_TOKEN>`):

  GET  /api/v1/worker-rates                 → live rates + ceilings
  POST /api/v1/worker-rates/{worker}/stop   → stop one worker, free its budget
"""

from __future__ import annotations

import logging

import httpx
from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from api.auth import require_bearer
from config.config import get_config

logger = logging.getLogger("phantom.api.worker_rates")

# xlog is on the same docker network; these calls are a loopback hop, not a
# WAN request. Short timeout: the panel polls, so a slow answer is worse than
# a quick failure it can render as "unreachable".
_TIMEOUT = 5.0


def _xlog_headers() -> dict[str, str]:
    """Bearer header for xlog, or empty when no token is configured.

    xlog refuses unauthenticated requests with 503, so an empty header here
    surfaces as a clean auth_error rather than silently returning nothing.
    """
    cfg = get_config()
    token = getattr(cfg, "xlog_api_token", None)
    return {"Authorization": token} if token else {}


def _base() -> str:
    return str(get_config().xlog_url).rstrip("/")


def _translate(resp: httpx.Response) -> JSONResponse:
    """Map an xlog response to something the panel can render honestly.

    The three failure modes are deliberately distinguishable, because they have
    completely different fixes and a single generic error would send an
    operator looking in the wrong place:

      401/503 -> the MCP's own xlog token is missing or wrong
      404     -> the worker is already gone (benign; it may have self-stopped)
      other   -> xlog answered but not usefully
    """
    if resp.status_code in (401, 403, 503):
        logger.warning("xlog rejected the worker-rates call: %s", resp.status_code)
        return JSONResponse(
            {
                "error": "auth_error",
                "detail": (
                    "xlog refused this request. Check XLOG_API_TOKEN on the "
                    "agent matches XLOG_API_KEY on xlog."
                ),
                "status": resp.status_code,
            },
            status_code=502,
        )
    if resp.status_code == 404:
        return JSONResponse({"error": "not_found"}, status_code=404)
    if resp.status_code >= 400:
        return JSONResponse(
            {"error": "xlog_error", "status": resp.status_code},
            status_code=502,
        )
    return JSONResponse(resp.json())


def _unreachable(exc: Exception) -> JSONResponse:
    logger.warning("xlog unreachable for worker-rates: %s", exc)
    return JSONResponse(
        {
            "error": "unreachable",
            "detail": "xlog did not respond. It may be restarting.",
        },
        status_code=502,
    )


def register_worker_rate_routes(mcp: FastMCP) -> None:
    """Register the worker-rate REST endpoints on the FastMCP app."""

    @mcp.custom_route(
        "/api/v1/worker-rates",
        methods=["GET"],
        include_in_schema=False,
    )
    async def get_worker_rates(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT, verify=False) as c:
                r = await c.get(f"{_base()}/api/v1/worker-rates",
                                headers=_xlog_headers())
        except Exception as exc:  # network, TLS, DNS
            return _unreachable(exc)
        return _translate(r)

    @mcp.custom_route(
        "/api/v1/worker-rates/{worker}/stop",
        methods=["POST"],
        include_in_schema=False,
    )
    async def stop_worker_rate(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        worker = request.path_params.get("worker", "")
        if not worker:
            return JSONResponse({"error": "worker required"}, status_code=400)
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT, verify=False) as c:
                r = await c.post(
                    f"{_base()}/api/v1/worker-rates/{worker}/stop",
                    headers=_xlog_headers(),
                )
        except Exception as exc:
            return _unreachable(exc)
        return _translate(r)
