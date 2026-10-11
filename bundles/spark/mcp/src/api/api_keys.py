"""API key HTTP endpoints — operator-minted credentials for external
integrations. See usecase/api_keys.py for the storage contract.

Endpoints (admin-only — the api-key minting/revoking surface itself
must be guarded by MCP_TOKEN, otherwise an operator with `*` could
mint additional keys for themselves):

  GET    /api/v1/api_keys             → list active + revoked keys
  POST   /api/v1/api_keys             → mint a new key
        body: {"label": "siem-poller", "scopes": ["audit:read"], "actor": "operator"}
        response: {"key": "<full plaintext>",   ← shown ONCE; not recoverable
                   "record": {... metadata ...}}
  DELETE /api/v1/api_keys/{id}        → revoke

Auth: requires MCP_TOKEN. We deliberately do NOT accept API keys on
this surface; an attacker with one scoped API key shouldn't be able to
mint themselves a wider one.
"""

from __future__ import annotations

import logging
from typing import Any

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from api.auth import require_bearer
from usecase.api_keys import SqliteApiKeyStore

logger = logging.getLogger("Phantom MCP")


def _is_mcp_token_principal(request: Request) -> bool:
    """Block API-key principals from this admin surface — they could
    only mint EQUAL-OR-LESSER keys but the audit + revocation paths
    are sensitive enough to keep behind the bundle-internal token."""
    return getattr(request.state, "auth_principal", "") == "mcp_token"


def register_api_key_routes(mcp: FastMCP, store: SqliteApiKeyStore) -> None:
    """Register /api/v1/api_keys[/{id}] on the FastMCP server."""

    @mcp.custom_route("/api/v1/api_keys", methods=["GET"], include_in_schema=False)
    async def list_api_keys(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        if not _is_mcp_token_principal(request):
            return JSONResponse(
                {"error": "API key minting/listing requires MCP_TOKEN"},
                status_code=403,
            )
        keys = [k.to_dict() for k in store.list()]
        return JSONResponse({"keys": keys, "count": len(keys)})

    @mcp.custom_route("/api/v1/api_keys", methods=["POST"], include_in_schema=False)
    async def create_api_key(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        if not _is_mcp_token_principal(request):
            return JSONResponse(
                {"error": "API key minting requires MCP_TOKEN"},
                status_code=403,
            )
        try:
            body: dict[str, Any] = await request.json()
        except Exception:
            return JSONResponse({"error": "Request body must be JSON."}, status_code=400)
        label = body.get("label")
        scopes = body.get("scopes")
        actor = body.get("actor")
        if not isinstance(label, str) or not label.strip():
            return JSONResponse({"error": "`label` is required"}, status_code=400)
        if scopes is not None and not isinstance(scopes, list):
            return JSONResponse({"error": "`scopes` must be an array of strings"}, status_code=400)
        try:
            created = store.create(label=label.strip(), scopes=scopes, actor=actor)
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return JSONResponse(
            {
                "key": created.plaintext,         # SHOWN ONCE — not recoverable
                "record": created.record.to_dict(),
                "warning": (
                    "Save this key value now. It is not recoverable from "
                    "the server after this response."
                ),
            },
            status_code=201,
        )

    @mcp.custom_route(
        "/api/v1/api_keys/{key_id}", methods=["DELETE"], include_in_schema=False
    )
    async def revoke_api_key(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        if not _is_mcp_token_principal(request):
            return JSONResponse(
                {"error": "API key revocation requires MCP_TOKEN"},
                status_code=403,
            )
        key_id = request.path_params.get("key_id", "")
        if not key_id:
            return JSONResponse({"error": "key_id required"}, status_code=400)
        actor = request.query_params.get("actor")
        revoked = store.revoke(key_id, actor=actor)
        if not revoked:
            return JSONResponse(
                {"revoked": False, "reason": "key not found or already revoked"},
                status_code=404,
            )
        return JSONResponse({"revoked": True, "id": key_id})
