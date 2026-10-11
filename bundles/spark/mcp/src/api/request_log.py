"""HTTP request-log middleware — observability's request-log pillar.

Wraps every HTTP request with structured access logs + metrics
recording. Drops into the FastMCP-built Starlette app via
`app.add_middleware(RequestLogMiddleware)`.

Per-request output (one line per request, JSON if any structured
sink picks it up — readable as text in `docker logs phantom_agent`):

    [http] method=GET path=/api/v1/audit status=200 dur_ms=12 actor=mcp_token

Counters + histogram observed:
    phantom_mcp_http_requests_total{method, path, status_class}
    phantom_mcp_http_request_duration_seconds{method, path, status_class}

The `path` label is the route TEMPLATE (e.g. /api/v1/api_keys/{key_id})
not the literal URL — Prometheus would otherwise blow up its label
cardinality on every uuid path param. We extract this from
Starlette's request.scope["route"] when available, falling back to
the literal path.

# Sensitive paths

Bearer tokens never appear in the log (only the 4-char prefix when
operator wants to correlate, controlled by REQUEST_LOG_TOKEN_PREFIX
env). Request bodies are NEVER logged — payloads can carry
operator-supplied secrets at setup time.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Match

from usecase.metrics_registry import metrics_registry

logger = logging.getLogger("Phantom MCP.http")


class RequestLogMiddleware(BaseHTTPMiddleware):
    """Structured request log + metrics observation per HTTP call."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        method = request.method
        # Resolve the route TEMPLATE (low cardinality) instead of the
        # literal URL path (would explode Prometheus label cardinality
        # on uuid path params, etc). Walks the app's routes looking
        # for a match; falls back to literal path if none found.
        path_template = _route_template(request)

        t0 = time.monotonic()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        except Exception:
            # Re-raise after metrics + log so the upstream handler's
            # exception path still surfaces.
            status_code = 500
            raise
        finally:
            dur_s = time.monotonic() - t0
            status_class = _status_class(status_code)

            # Structured access log line. Operators who want JSON output
            # can pipe this through a json-line filter; for human reading
            # the key=value form is good enough.
            actor = getattr(request.state, "auth_principal", None) or "anon"
            logger.info(
                "[http] method=%s path=%s status=%d dur_ms=%d actor=%s",
                method, path_template, status_code, int(dur_s * 1000), actor,
            )

            reg = metrics_registry()
            if reg is not None:
                req_counter = reg.get("phantom_mcp_http_requests_total")
                dur_hist = reg.get("phantom_mcp_http_request_duration_seconds")
                if req_counter is not None and hasattr(req_counter, "inc"):
                    try:
                        req_counter.inc(
                            method=method, path=path_template,
                            status_class=status_class,
                        )
                    except Exception as exc:  # pragma: no cover
                        logger.debug("metric inc failed: %s", exc)
                if dur_hist is not None and hasattr(dur_hist, "observe"):
                    try:
                        dur_hist.observe(
                            dur_s,
                            method=method, path=path_template,
                            status_class=status_class,
                        )
                    except Exception as exc:  # pragma: no cover
                        logger.debug("metric observe failed: %s", exc)


def _status_class(code: int) -> str:
    """Bucket HTTP status into 1xx/2xx/3xx/4xx/5xx for label cardinality."""
    if 100 <= code < 200:
        return "1xx"
    if 200 <= code < 300:
        return "2xx"
    if 300 <= code < 400:
        return "3xx"
    if 400 <= code < 500:
        return "4xx"
    return "5xx"


def _route_template(request: Request) -> str:
    """Best-effort: find the matching route's path template.

    Starlette doesn't expose this directly on Request, so we walk the
    app's routes ourselves. Falls back to request.url.path when no
    template matches (404, custom mounts, etc.).
    """
    try:
        app = request.app
        for route in getattr(app, "routes", []) or []:
            try:
                match, _ = route.matches(request.scope)
            except Exception:
                continue
            if match == Match.FULL:
                # Starlette routes carry a `path` attribute that
                # IS the template (e.g. "/api/v1/api_keys/{key_id}").
                tmpl = getattr(route, "path", None)
                if isinstance(tmpl, str) and tmpl:
                    return tmpl
    except Exception:
        pass
    return request.url.path or "/"


def install(app, *, enabled: bool = True) -> None:
    """Attach the middleware to the FastMCP-built Starlette app.

    Toggleable via PHANTOM_REQUEST_LOG=0 in case an operator wants
    to silence access logs without rebuilding the bundle.
    """
    if not enabled:
        logger.info("Request-log middleware disabled via flag.")
        return
    if os.getenv("PHANTOM_REQUEST_LOG", "1") not in {"1", "true", "yes"}:
        logger.info("Request-log middleware disabled via PHANTOM_REQUEST_LOG env.")
        return
    app.add_middleware(RequestLogMiddleware)
    logger.info("Request-log middleware attached.")
