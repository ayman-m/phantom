"""Authentication for the MCP JSON-RPC tool endpoint (`MCP_PATH`).

Every REST route on this server calls `require_bearer()`. The JSON-RPC transport
that FastMCP mounts at `MCP_PATH` is not one of them, and nothing else guarded
it, so anyone who could reach the published port 8080 could list and call all of
the agent's tools with no credential at all. This middleware is that guard.

Accepted, on every method and sub-path of the endpoint:

  * `Authorization: Bearer <MCP_TOKEN>`: the agent's own token, unrestricted.
  * `Authorization: Bearer phantom_ak_...` for an active API key that holds
    `tools:call` (or `*`), the documented scope for JSON-RPC tool dispatch.

Anything else gets 401 (no or unknown credential) or 403 (a valid key without the
scope), before FastMCP sees the request.

The approval-bypass header is decided here too. `X-Phantom-Approval-Bypass` skips
the human approval gate for the request, so it may only come from the principal
that owns the approval policy: the agent, authenticated with MCP_TOKEN. A key
holder asking for bypass is ignored. (It used to be honoured from any caller,
because the endpoint was open.)

Pure ASGI rather than BaseHTTPMiddleware: the transport streams (SSE), and
buffering middleware is not appropriate in front of it.
"""

from __future__ import annotations

import hmac
import json
import logging
from typing import Any

from config.config import config
from usecase.api_keys import api_key_store
from usecase.audit_log import reset_current_approval_bypass, set_current_approval_bypass

logger = logging.getLogger("Phantom MCP.mcp_auth")

TOOLS_SCOPE = "tools:call"
BYPASS_HEADER = b"x-phantom-approval-bypass"
_BYPASS_TRUTHY = frozenset({"1", "true", "yes", "on"})


def authorize_transport(authorization: str | None) -> tuple[str | None, int, str]:
    """Decide one request. Returns (principal, status, message).

    `principal` is "mcp_token" or "api_key:<id>" on success (status 200); on
    failure it is None with the HTTP status to answer with.
    """
    expected = config.mcp_token
    if not expected:
        return None, 503, "MCP_TOKEN is not configured on this server"
    if not authorization or not authorization.lower().startswith("bearer "):
        return None, 401, "missing or malformed Authorization header"
    token = authorization[len("bearer "):].strip()
    if hmac.compare_digest(token, expected):
        return "mcp_token", 200, ""
    if token.startswith("phantom_ak_"):
        store = api_key_store()
        row = store.verify(token) if store is not None else None
        if row is not None:
            if "*" in row.scopes or TOOLS_SCOPE in row.scopes:
                return f"api_key:{row.id}", 200, ""
            return None, 403, f"this API key lacks the {TOOLS_SCOPE} scope"
    return None, 401, "invalid bearer token"


class McpTransportAuthMiddleware:
    def __init__(self, app: Any, path: str) -> None:
        self.app = app
        self.path = "/" + path.strip("/")

    def _guards(self, request_path: str) -> bool:
        p = request_path.rstrip("/") or "/"
        return p == self.path or p.startswith(self.path + "/")

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http" or not self._guards(scope["path"]):
            await self.app(scope, receive, send)
            return

        headers = {k.lower(): v for k, v in scope.get("headers", [])}
        raw = headers.get(b"authorization")
        principal, status, message = authorize_transport(raw.decode("latin-1") if raw else None)
        if principal is None:
            body = json.dumps({"error": message}).encode()
            await send({
                "type": "http.response.start",
                "status": status,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                    (b"www-authenticate", b"Bearer"),
                ],
            })
            await send({"type": "http.response.body", "body": body})
            logger.warning("rejected unauthenticated MCP transport request (%s %s): %s",
                           scope.get("method"), scope["path"], message)
            return

        scope.setdefault("state", {})["mcp_principal"] = principal
        bypass_token = None
        wants_bypass = headers.get(BYPASS_HEADER, b"").decode("latin-1").strip().lower() in _BYPASS_TRUTHY
        if wants_bypass:
            if principal == "mcp_token":
                bypass_token = set_current_approval_bypass(True)
                logger.info("approval bypass active for this request")
            else:
                logger.warning("ignored X-Phantom-Approval-Bypass from %s", principal)
        try:
            await self.app(scope, receive, send)
        finally:
            if bypass_token is not None:
                reset_current_approval_bypass(bypass_token)


def install(app: Any, path: str) -> Any:
    """Wrap the Starlette app so the transport path is authenticated.

    Returns the app to serve. Call it BEFORE the other middleware installs, so
    that request logging (added later, therefore outermost) records rejections.
    """
    app.add_middleware(McpTransportAuthMiddleware, path=path)
    logger.info("McpTransportAuthMiddleware installed (path=%s)", path)
    return app
