"""xlog API auth — bearer-token check against XLOG_API_KEY.

The check, in order:

  1. `/health` bypasses unconditionally, so docker healthchecks work
     without baking a token into the probe URL. It is the ONLY bypass.
  2. If XLOG_API_KEY is unset, every other request gets 503. xlog refuses
     to run unauthenticated rather than serving work to anyone who can
     reach it.
  3. Otherwise the request must carry `Authorization: Bearer <token>` or
     the bare `Authorization: <token>` form. Constant-time compare.
  4. Missing header or mismatch → 401.

Two invariants worth knowing:

  * The agent's xlog connector instance presents the API token as an
    Authorization header on every call — see
    bundles/spark/connectors/xlog/src/_graphql_client.py. A connector that
    sent no header would be rejected here with 401.
  * "/" is NOT whitelisted. It is the entire GraphQL surface, so exempting it
    (e.g. to preserve schema introspection) would leave every
    worker-creating mutation reachable unauthenticated by anything on the
    network.

The expected token is snapshotted at boot, so rotation is restart-bound.
The installer generates the key on fresh install and refuses to upgrade
without it, which is what makes the fail-closed branch above safe.
"""

from __future__ import annotations

import hmac
import logging
import os

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from typing import Awaitable, Callable

logger = logging.getLogger("xlog.auth")

# Paths that bypass the bearer check.
#
# ONLY /health. It is the docker healthcheck probe, so it must answer without
# baking a token into the probe URL, and it exposes no data.
#
# "/" is deliberately NOT here: it is the ENTIRE GraphQL surface (xlog/main.py
# mounts the schema at exactly that path), so whitelisting it, even to preserve
# schema introspection, would leave every worker-creating mutation reachable
# unauthenticated by anything with network access to this container. The xlog
# connector therefore has to send its token on every call.
SKIP_AUTH_PATHS = {"/health"}

ENV_VAR = "XLOG_API_KEY"


class XLogBearerAuthMiddleware(BaseHTTPMiddleware):
    """Reject requests without a matching `Authorization: Bearer <token>`."""

    def __init__(self, app, *, expected_token: str | None = None) -> None:
        super().__init__(app)
        # Snapshot the expected token at middleware construction (boot time).
        # Reading per-request would let an operator hot-rotate without a
        # restart; we explicitly want restart-bound rotation so audit/
        # log correlation stays consistent with deploy events.
        self._expected = (expected_token or os.getenv(ENV_VAR) or "").strip()
        if not self._expected:
            logger.error(
                "%s is NOT set. xlog will serve /health and REFUSE every other "
                "request with 503 rather than run unauthenticated. Set %s in "
                "/opt/phantom/.env and restart this container.",
                ENV_VAR, ENV_VAR,
            )
        else:
            logger.info(
                "xlog bearer auth ENABLED (token length: %d chars). "
                "Requests must carry `Authorization: Bearer <token>`.",
                len(self._expected),
            )

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        # Whitelist pass-through.
        if request.url.path in SKIP_AUTH_PATHS:
            return await call_next(request)

        # No expected token configured → FAIL CLOSED.
        #
        # Falling through permissively "for upgrade compatibility" would mean a
        # misconfigured deploy serves every worker-creating mutation to anyone
        # on the network, silently and indefinitely.
        #
        # 503, not 401: the client did nothing wrong and no credential would
        # help — the SERVER is misconfigured. A 401 would send an operator
        # hunting for a bad token instead of a missing env var.
        #
        # This is safe to fail closed ONLY because the installer guarantees the
        # key: it generates one on fresh install and refuses to upgrade without
        # it (see installer/phantom-installer.template.sh — the missing_secrets
        # check and the XLOG_API_KEY generation). If a future change drops
        # XLOG_API_KEY from that required-vars list or from the .env heredoc,
        # this branch starts bricking real installs. Keep them coupled.
        #
        # The /health whitelist is checked ABOVE this, deliberately: the
        # container stays healthy and diagnosable instead of crash-looping,
        # so the operator sees a running service refusing work rather than a
        # restart loop with the cause buried in logs.
        if not self._expected:
            return JSONResponse(
                {
                    "error": "xlog is not configured for authentication",
                    "detail": (
                        f"{ENV_VAR} is unset, so xlog refuses requests rather "
                        f"than serving them unauthenticated. Set {ENV_VAR} in "
                        f"/opt/phantom/.env and restart the xlog container."
                    ),
                },
                status_code=503,
            )

        header = request.headers.get("authorization") or ""
        if not header:
            return JSONResponse(
                {"error": "missing Authorization header"}, status_code=401,
            )

        # Accept both "Bearer <token>" and bare "<token>" forms — the
        # phantom-agent's xlog connector has historically used the bare
        # form. Strip the "Bearer " prefix when present.
        if header.lower().startswith("bearer "):
            presented = header[len("bearer "):].strip()
        else:
            presented = header.strip()

        if not hmac.compare_digest(presented, self._expected):
            return JSONResponse(
                {"error": "invalid xlog API token"}, status_code=401,
            )
        return await call_next(request)
