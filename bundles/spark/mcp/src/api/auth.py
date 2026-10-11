"""Bearer-token auth for the MCP admin/setup HTTP endpoints.

Two acceptable bearer shapes:

  1. **MCP_TOKEN** (bundle-internal): the Next.js agent's setup screen
     and internal tools send `Authorization: Bearer <MCP_TOKEN>`. This
     is the unrestricted admin path — same trust as the embedded MCP
     itself. Generated at container start (or pinned in `.env`).

  2. **API key** (`phantom_ak_<id>_<secret>`): operator-minted long-
     lived keys for external integrations. Looked up in the
     SqliteApiKeyStore; verified by hash; scoped per-row. Active keys
     are accepted on routes that match their scope list.

`require_bearer()` accepts either shape and returns:
  * None on success
  * JSONResponse(401/403/503) on failure

`require_scope(scope)` adds an additional check — used by routes that
want to gate on a specific scope (e.g. `audit:read` on the audit-list
endpoint). Pass-through for MCP_TOKEN (admin); enforced for API keys.
"""

from __future__ import annotations

import hmac

from starlette.requests import Request
from starlette.responses import JSONResponse

from config.config import config
from usecase.api_keys import api_key_store


def _extract_token(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        return None
    return header[len("bearer "):].strip()


def require_bearer(request: Request) -> JSONResponse | None:
    """Accept MCP_TOKEN OR an active API key.

    Side effect for API keys: the row's last_used_at is updated and the
    resolved scopes are stashed on `request.state.api_key_scopes`. Routes
    that care can then call `require_scope()` to enforce.
    """
    expected = config.mcp_token
    if not expected:
        return JSONResponse(
            {"error": "MCP_TOKEN is not configured on this server"},
            status_code=503,
        )
    token = _extract_token(request)
    if token is None:
        return JSONResponse(
            {"error": "missing or malformed Authorization header"},
            status_code=401,
        )

    # Path 1: MCP_TOKEN (admin). Constant-time compare so an attacker
    # can't infer prefix matches via timing.
    if hmac.compare_digest(token, expected):
        request.state.auth_principal = "mcp_token"
        request.state.api_key_scopes = ["*"]
        return None

    # Path 2: API key. Only consult the store when the token has the
    # API-key prefix — saves a sqlite hit on every malformed bearer.
    if token.startswith("phantom_ak_"):
        store = api_key_store()
        if store is not None:
            row = store.verify(token)
            if row is not None:
                request.state.auth_principal = f"api_key:{row.id}"
                request.state.api_key_scopes = row.scopes
                return None

    return JSONResponse(
        {"error": "invalid bearer token"},
        status_code=403,
    )


def require_scope(request: Request, scope: str) -> JSONResponse | None:
    """Per-route scope gate. Call AFTER `require_bearer()`.

    Wildcard `*` in the principal's scope list grants any scope. Used
    by routes that want stricter granularity than "valid token == full
    access". MCP_TOKEN principals always carry `*`.
    """
    scopes: list[str] = getattr(request.state, "api_key_scopes", []) or []
    if "*" in scopes or scope in scopes:
        return None
    return JSONResponse(
        {"error": f"token lacks required scope: {scope}"},
        status_code=403,
    )


def require_loopback_for_secrets(request: Request) -> JSONResponse | None:
    """Gate `?include_secrets=true` on caller location, not bearer alone.

    Returns a 403 response when the caller asked for plaintext secrets from
    off-box, or None when the request may proceed.

    WHY THIS IS SHARED
    ------------------
    `include_secrets` flips redaction off and returns resolved plaintext
    credentials. Three endpoints honour it — instances, providers and
    log_destinations — and all of them check caller location in addition
    to bearer auth, including the two MOST sensitive (connector secrets,
    provider credentials).

    A guarantee that the agent's /api/agent/backup route "verifies the
    operator's session cookie before proxying here" lives on the other
    side of a network hop, so on its own it is an assumption, not a
    control: if backup delegated auth to middleware that admits API keys,
    any read-scoped key could retrieve every stored credential as a zip.
    This makes it a control on the MCP side.

    WHAT THIS IS AND IS NOT
    -----------------------
    Loopback is a weak signal on its own: the agent proxy reaches the MCP
    over localhost, so anything it forwards inherits "local" status — the
    confused-deputy hole that leaked destination tokens. That hole is closed
    at the proxy, which now strips the parameter outright.

    So this is defence in depth, not the primary control. It stops a
    NEW proxy route from silently re-opening the same hole, and it costs the
    legitimate callers nothing: backup, vertex-credentials and
    anthropic-credentials all run inside the agent container and reach the
    MCP over localhost.
    """
    if request.query_params.get("include_secrets", "").lower() != "true":
        return None
    client = request.client
    host = client.host if client is not None else None
    if host in ("127.0.0.1", "::1", "localhost"):
        return None
    return JSONResponse(
        {
            "error": "include_secrets requires a loopback caller",
            "detail": (
                "Plaintext credentials are only served to in-container "
                "callers. Use the redacted response, which lists every "
                "secret slot with a '***' placeholder."
            ),
        },
        status_code=403,
    )
