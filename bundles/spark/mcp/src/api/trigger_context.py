"""Trigger-context middleware — populates the trigger contextvar from
the inbound `X-Phantom-Trigger` header for the duration of one HTTP
request.

The header is set by upstream callers that want their downstream
audit rows tagged with a stable identifier:

  - The job_scheduler sets `X-Phantom-Trigger: job:<name>` on its
    POST to /api/chat (see usecase/job_scheduler.py:_dispatch_chat).
  - The agent's chat route forwards the same header to every
    downstream MCP tool call so the trigger flows from "job fires"
    → "agent /api/chat handles" → "MCP tool dispatch" → "audit row".
  - Future per-operator session attribution can add
    `X-Phantom-Trigger: operator:<id>` here without further wiring.

Without this middleware, every audit row's `trigger` column would
be NULL and operators couldn't filter the audit feed by source.
With it, /observability/events grows a "trigger" column that
distinguishes scheduler-driven activity from interactive turns.

# Why a contextvar, not request.state

We could stash the trigger on `request.state.trigger` and have the
audit recorder read it from there — but the audit recorder is
called from deeply-nested code paths (SecretStore reads,
connector-loader tool wrappers) that don't have a Request object
in scope. ContextVars propagate naturally across `await` calls
within the same task without anyone having to pass them down.
That's exactly the same pattern actor attribution already uses
(`set_current_actor` / `get_current_actor`).
"""

from __future__ import annotations

import logging
from typing import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from usecase.audit_log import (
    reset_current_trigger,
    set_current_trigger,
)

logger = logging.getLogger("Phantom MCP.trigger")

HEADER_NAME = "X-Phantom-Trigger"

# X-Phantom-Approval-Bypass is NOT handled here. Skipping the approval gate is a
# privilege, so api/mcp_auth.py honours it only after authenticating the caller
# as the agent (MCP_TOKEN).

# Cap the trigger string so a malformed/oversized header can't bloat
# the audit table. Real triggers are short — "job:nightly-coverage"
# is 22 chars; the cap is 5x that to leave headroom.
MAX_TRIGGER_LEN = 128


class TriggerContextMiddleware(BaseHTTPMiddleware):
    """Read X-Phantom-Trigger from the request, set the contextvar for the
    request lifetime, reset on exit. Pairs with audit_log's record().
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        raw = request.headers.get(HEADER_NAME)
        token = None
        if raw:
            trigger = raw.strip()[:MAX_TRIGGER_LEN] or None
            if trigger:
                token = set_current_trigger(trigger)

        try:
            return await call_next(request)
        finally:
            if token is not None:
                reset_current_trigger(token)


def install(app) -> None:  # noqa: ANN001 — Starlette/FastAPI app
    """Install the middleware on the app.

    Call AFTER the request_log middleware so the trigger is already
    in scope when request_log records its access line — useful when
    the structured access log grows a `trigger=` field later.
    """
    app.add_middleware(TriggerContextMiddleware)
    logger.info("TriggerContextMiddleware installed (header=%s)", HEADER_NAME)
