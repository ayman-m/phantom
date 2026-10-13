"""Bearer-token auth for the MCP admin HTTP endpoints.

Two acceptable bearer shapes:

  1. **MCP_TOKEN** (bundle-internal): the Next.js agent's /api/agent/*
     proxies and internal tools send `Authorization: Bearer <MCP_TOKEN>`. This
     is the unrestricted admin path — same trust as the embedded MCP
     itself. Generated at container start (or pinned in `.env`).

  2. **API key** (`phantom_ak_<id>_<secret>`): operator-minted long-
     lived keys for external integrations. Looked up in the
     SqliteApiKeyStore; verified by hash; scoped per-row.

An API key is NOT a general credential on this port. It is accepted only
on the routes listed in `API_KEY_ROUTE_SCOPES`, each of which names the one
scope it needs (`*` satisfies any of them). Every other route is MCP_TOKEN
only. That matters because port 8080 is published on the host: a key minted
for a SIEM poller (`audit:read`) must not be able to create jobs or read
instances. The agent API on port 3000 maps keys to `agent:read` /
`agent:write` itself and reaches this port with MCP_TOKEN.

`require_bearer()` accepts either shape and returns:
  * None on success
  * JSONResponse(401/403/503) on failure
"""

from __future__ import annotations

import hmac
import re

from starlette.requests import Request
from starlette.responses import JSONResponse

from config.config import config
from usecase.api_keys import api_key_store


def _extract_token(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        return None
    return header[len("bearer "):].strip()


# The REST routes an API key may use, and the scope each requires. Keep in sync
# with the scope table in /help/user#api-keys and the catalog on /api-keys.
# `tools:call` (the JSON-RPC tool endpoint) is enforced in api/mcp_auth.py.
API_KEY_ROUTE_SCOPES: tuple[tuple[frozenset[str], "re.Pattern[str]", str], ...] = (
    (frozenset({"GET"}), re.compile(r"^/api/v1/audit(/.*)?$"), "audit:read"),
    (frozenset({"GET"}), re.compile(r"^/api/v1/settings$"), "settings:read"),
    (frozenset({"PUT"}), re.compile(r"^/api/v1/settings$"), "settings:write"),
    (frozenset({"POST"}), re.compile(r"^/api/v1/approvals/[^/]+/resolve$"), "approvals:resolve"),
)


def api_key_allows(scopes: list[str], method: str, path: str) -> bool:
    """May a key holding `scopes` call `method path` on this port?"""
    for methods, pattern, needed in API_KEY_ROUTE_SCOPES:
        if method.upper() in methods and pattern.match(path):
            return "*" in scopes or needed in scopes
    return False


def require_bearer(request: Request) -> JSONResponse | None:
    """Accept MCP_TOKEN, or an active API key on the routes it is scoped for.

    Side effect for API keys: the row's last_used_at is updated and the
    resolved scopes are stashed on `request.state.api_key_scopes`.
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
                if not api_key_allows(row.scopes, request.method, request.url.path):
                    return JSONResponse(
                        {"error": "this API key's scopes do not allow this route"},
                        status_code=403,
                    )
                request.state.auth_principal = f"api_key:{row.id}"
                request.state.api_key_scopes = row.scopes
                return None

    return JSONResponse(
        {"error": "invalid bearer token"},
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
    providers/credentials all run inside the agent container and reach the
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
