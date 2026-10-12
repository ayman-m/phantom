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

  GET  /api/v1/workers                      → the data workers xlog is running
                                              (the same list the agent's
                                              xlog.list_workers tool returns)
  GET  /api/v1/worker-rates                 → live rates + ceilings
  POST /api/v1/worker-rates/{worker}/stop   → stop one worker, free its budget
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlsplit

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


# xlog serves its GraphQL schema at "/" (xlog/main.py). Same fields the
# connector's list_workers tool selects, so /tasks and the agent agree.
_LIST_WORKERS_QUERY = (
    "query ListWorkers { listWorkers { worker type status count interval "
    "destination createdAt } }"
)


def redact_destination(destination: Any) -> str:
    """Strip credentials, path and query from a worker destination.

    A worker's destination is the address it ships to: ``udp:10.0.0.8:514``
    for a broker, or a full URL for an HTTP collector. A URL can carry
    userinfo, a token in its query string or a token in a path segment
    (``/services/collector/<token>``), and this value is rendered in the
    browser, so keep only scheme, host and port, plus ``/\u2026`` when a path
    existed. IPv6 hosts keep their brackets.
    """
    text = str(destination or "")
    if "://" not in text:
        return text
    try:
        parts = urlsplit(text)
        host = parts.hostname or ""
        if ":" in host:  # IPv6 literal: urlsplit strips the brackets
            host = f"[{host}]"
        if parts.port:
            host = f"{host}:{parts.port}"
        path = "/\u2026" if parts.path.strip("/") else ""
        return f"{parts.scheme}://{host}{path}"
    except ValueError:
        # Cannot be parsed, so cannot be trusted: show only the scheme.
        return f"{text.split('://', 1)[0]}://\u2026"


def parse_list_workers(body: Any) -> list[dict[str, Any]]:
    """Pull the worker rows out of a GraphQL response body.

    Raises ValueError on a GraphQL ``errors`` array or a malformed body, so
    the route can answer with a typed 502 rather than an empty list that
    reads as "no workers".
    """
    if not isinstance(body, dict):
        raise ValueError("xlog returned a non-object response")
    if body.get("errors"):
        raise ValueError("xlog rejected the listWorkers query")
    rows = (body.get("data") or {}).get("listWorkers")
    if not isinstance(rows, list):
        raise ValueError("xlog response had no listWorkers list")
    workers: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        workers.append(
            {
                "worker": str(row.get("worker") or ""),
                "type": str(row.get("type") or ""),
                "status": str(row.get("status") or ""),
                "count": str(row.get("count") or ""),
                "interval": str(row.get("interval") or ""),
                "destination": redact_destination(row.get("destination")),
                "created_at": str(row.get("createdAt") or ""),
            }
        )
    return workers


def register_worker_rate_routes(mcp: FastMCP) -> None:
    """Register the worker-rate REST endpoints on the FastMCP app."""

    @mcp.custom_route(
        "/api/v1/workers",
        methods=["GET"],
        include_in_schema=False,
    )
    async def list_workers(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT, verify=False) as c:
                r = await c.post(
                    f"{_base()}/",
                    json={"query": _LIST_WORKERS_QUERY},
                    headers=_xlog_headers(),
                )
        except Exception as exc:  # network, TLS, DNS
            return _unreachable(exc)
        if r.status_code != 200:
            return _translate(r)
        try:
            workers = parse_list_workers(r.json())
        except ValueError as exc:
            logger.warning("xlog listWorkers unusable: %s", exc)
            return JSONResponse(
                {"error": "xlog_error", "detail": str(exc)}, status_code=502
            )
        return JSONResponse({"workers": workers, "count": len(workers)})

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
