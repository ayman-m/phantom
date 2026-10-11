"""Phantom UI auth HTTP surface — sessions + change + reset.

Five routes, all requiring the standard MCP_TOKEN bearer (so the
Next.js side authenticates as the agent before relaying operator
input):

  POST /api/v1/ui/auth/login           body: {username, password, user_agent?}
                                       → 200 {session_token, expires_at_ms,
                                              credentials_changed, username}
                                       → 401 {error: "invalid credentials"}

  POST /api/v1/ui/auth/logout          body: {session_token}
                                       → 200 {ok: true}   (idempotent)

  POST /api/v1/ui/auth/session         body: {session_token}
                                       → 200 {valid, username,
                                              expires_at_ms,
                                              credentials_changed}
                                       (always 200; valid=false means
                                        unknown/revoked/expired token)

  POST /api/v1/ui/auth/change_password body: {session_token,
                                              current_password,
                                              new_password}
                                       → 200 {ok: true, sessions_revoked}
                                       → 401 {error: "invalid session"}
                                       → 403 {error: "current_password
                                              is incorrect"}
                                       → 400 {error: "<validation>"}

  POST /api/v1/ui/auth/admin_reset     body: {new_password}
                                       → 200 {ok: true, sessions_revoked}
                                       → 400 {error: "<validation>"}

# Trust boundary recap

The MCP_TOKEN bearer authenticates that the CALLER is the agent
process (either the Next.js side proxying operator input, or the
reset-admin CLI running inside the agent container). The token comes
from /proc/1/environ inside the phantom_agent container.

`/login` requires username + password — those are the operator's
credentials, NOT a bearer. `/change_password` requires a valid
session token AND the current password. `/admin_reset` only requires
the MCP_TOKEN bearer — that's the CLI-trust path; anyone who can
`docker exec` into phantom_agent can read the token from
/proc/1/environ, so the CLI doesn't need an additional secret.

# Audit events

  login_success                  actor=user:<username>
  login_failed                   actor=user:<username>  (no PII in body)
  password_changed_ui            actor=user:<username>
  password_changed_cli           actor=cli:<hostname>
  sessions_revoked               (count in metadata)

The Next.js side may emit further audit events (e.g. login_failed
with the source_ip in metadata) — those live in
mcp/agent/app/api/auth/login/route.ts. This module owns the
server-side post-verification events.

# What this module DOES NOT do

  - Rate limiting. The Next.js side owns the per-IP sliding window
    (see mcp/agent/app/api/auth/login/route.ts). The MCP side has no
    direct view of source IPs and would just re-implement the same
    counter behind a token.
  - Cookie handling. The MCP returns the raw session_token in JSON;
    the Next.js side wraps it in a Set-Cookie response with the
    correct attributes (HttpOnly, Secure, SameSite=Strict).
  - Default-password seeding. Boot-time idempotent seeding is the
    entrypoint's responsibility (calls auth_store.seed_admin_defaults_if_empty
    via a Python one-liner before starting the MCP HTTP server).

There are no /verify or /password endpoints and no backward-compat
fallback.
"""

from __future__ import annotations

import logging
import socket
from typing import Any

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from api.auth import require_bearer
from usecase.api_keys import api_key_store
from usecase.audit_log import (
    record_event,
    reset_current_actor,
    set_current_actor,
)
from usecase.auth_store import auth_store
from usecase.ui_auth import UiAuthError


logger = logging.getLogger("Phantom MCP")


def _hostname() -> str:
    """Best-effort container hostname for CLI audit attribution."""
    try:
        return socket.gethostname()
    except OSError:
        return "unknown"


def _record(action: str, *, actor: str, status: str, **metadata: Any) -> None:
    """Audit log helper. Sets the per-thread actor contextvar so the
    event is attributed correctly, then resets — matches the pattern
    used by self_mod_tools and the rest of the codebase."""
    token = set_current_actor(actor)
    try:
        record_event(
            action=action,
            target=metadata.pop("target", f"user:{actor.split(':', 1)[-1]}"),
            status=status,
            metadata=metadata or None,
        )
    finally:
        reset_current_actor(token)


async def _parse_json_dict(request: Request) -> dict[str, Any] | JSONResponse:
    """Shared body-parser. Returns a JSONResponse on error so the
    caller can short-circuit."""
    try:
        body = await request.json()
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            {"error": f"invalid JSON body: {exc}"}, status_code=400,
        )
    if not isinstance(body, dict):
        return JSONResponse(
            {"error": "body must be a JSON object"}, status_code=400,
        )
    return body


def _required_string(
    body: dict[str, Any], key: str, max_len: int = 256
) -> tuple[str | None, JSONResponse | None]:
    raw = body.get(key)
    if not isinstance(raw, str) or not raw:
        return None, JSONResponse(
            {"error": f"{key} (non-empty string) is required"}, status_code=400,
        )
    if len(raw) > max_len:
        return None, JSONResponse(
            {"error": f"{key} exceeds {max_len} characters"}, status_code=400,
        )
    return raw, None


def register_ui_auth_routes(mcp: FastMCP) -> None:
    """Register /api/v1/ui/auth/* routes on the FastMCP server.

    The /verify and /password endpoints are not registered and return
    404."""

    # ─── POST /api/v1/ui/auth/login ────────────────────────

    @mcp.custom_route(
        "/api/v1/ui/auth/login",
        methods=["POST"],
        include_in_schema=False,
    )
    async def login(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        body_or_err = await _parse_json_dict(request)
        if isinstance(body_or_err, JSONResponse):
            return body_or_err
        body = body_or_err

        username, err = _required_string(body, "username", max_len=64)
        if err is not None:
            return err
        password, err = _required_string(body, "password", max_len=512)
        if err is not None:
            return err
        user_agent_raw = body.get("user_agent")
        user_agent = user_agent_raw if isinstance(user_agent_raw, str) else None

        store = auth_store()
        if not store.verify_password(username, password):
            _record(
                "login_failed",
                actor=f"user:{username}",
                status="failure",
                target=f"user:{username}",
            )
            # Generic message — no info leak about whether the username
            # exists. Single-user system today, so the question doesn't
            # arise, but defense-in-depth for the multi-user future.
            return JSONResponse(
                {"error": "invalid credentials"}, status_code=401,
            )

        raw_token = store.create_session(username, user_agent=user_agent)
        validation = store.validate_session(raw_token)
        if validation is None:
            # Should be unreachable: we JUST minted the token. If this
            # fails, the store is broken — return 500.
            logger.error(
                "login: minted session for %r but immediate validate "
                "returned None — store inconsistency",
                username,
            )
            return JSONResponse(
                {"error": "session minting failed"}, status_code=500,
            )

        _record(
            "login_success",
            actor=f"user:{username}",
            status="success",
            target=f"user:{username}",
            credentials_changed=validation["credentials_changed"],
        )
        return JSONResponse(
            {
                "session_token": raw_token,
                "expires_at_ms": validation["expires_at_ms"],
                "credentials_changed": validation["credentials_changed"],
                "username": username,
            }
        )

    # ─── POST /api/v1/ui/auth/logout ───────────────────────

    @mcp.custom_route(
        "/api/v1/ui/auth/logout",
        methods=["POST"],
        include_in_schema=False,
    )
    async def logout(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        body_or_err = await _parse_json_dict(request)
        if isinstance(body_or_err, JSONResponse):
            return body_or_err
        body = body_or_err

        token = body.get("session_token")
        if not isinstance(token, str) or not token:
            # Idempotent — no token = nothing to revoke = ok.
            return JSONResponse({"ok": True})

        store = auth_store()
        revoked = store.revoke_session(token)
        if revoked:
            # We don't know the username without re-looking; the
            # session row holds it but we just revoked. The audit row
            # gets actor="user:unknown" — acceptable since logout is
            # low-risk and the operator initiated it.
            _record(
                "logout",
                actor="user:unknown",
                status="success",
                target="session:revoked",
            )
        return JSONResponse({"ok": True})

    # ─── POST /api/v1/ui/auth/session ──────────────────────

    @mcp.custom_route(
        "/api/v1/ui/auth/session",
        methods=["POST"],
        include_in_schema=False,
    )
    async def session_validate(request: Request) -> JSONResponse:
        """Validate a session token. Returns 200 with {valid: false}
        for unknown/revoked/expired tokens (not 401) so the caller
        can distinguish "session check failed" from "MCP unreachable"
        cleanly — the latter would produce a 5xx; the former always
        produces a 200 with structured data."""
        if (resp := require_bearer(request)) is not None:
            return resp
        body_or_err = await _parse_json_dict(request)
        if isinstance(body_or_err, JSONResponse):
            return body_or_err
        body = body_or_err

        token = body.get("session_token")
        if not isinstance(token, str) or not token:
            return JSONResponse(
                {
                    "valid": False,
                    "username": None,
                    "expires_at_ms": None,
                    "credentials_changed": None,
                }
            )

        store = auth_store()
        validation = store.validate_session(token)
        if validation is None:
            return JSONResponse(
                {
                    "valid": False,
                    "username": None,
                    "expires_at_ms": None,
                    "credentials_changed": None,
                }
            )

        return JSONResponse(
            {
                "valid": True,
                "username": validation["username"],
                "expires_at_ms": validation["expires_at_ms"],
                "credentials_changed": validation["credentials_changed"],
            }
        )

    # ─── POST /api/v1/ui/auth/verify_key ───────────────────
    @mcp.custom_route(
        "/api/v1/ui/auth/verify_key",
        methods=["POST"],
        include_in_schema=False,
    )
    async def verify_key(request: Request) -> JSONResponse:
        """Validate an API key (``phantom_ak_*``) for the Next.js agent
        middleware. MCP_TOKEN-gated internal loopback. Returns 200 with
        ``{valid: false}`` for unknown/revoked keys (not 401) — same
        contract as ``/session`` so the caller distinguishes "key
        invalid" from "MCP unreachable" (which would surface as 5xx)."""
        if (resp := require_bearer(request)) is not None:
            return resp
        body_or_err = await _parse_json_dict(request)
        if isinstance(body_or_err, JSONResponse):
            return body_or_err

        api_key = body_or_err.get("api_key")
        if not isinstance(api_key, str) or not api_key:
            return JSONResponse({"valid": False, "reason": "missing_api_key"})

        store = api_key_store()
        if store is None:
            return JSONResponse({"valid": False, "reason": "store_unavailable"})

        row = store.verify(api_key)
        if row is None:
            return JSONResponse({"valid": False, "reason": "unknown_or_revoked"})

        return JSONResponse(
            {
                "valid": True,
                "scopes": row.scopes,
                "key_id": row.id,
                "label": row.label,
            }
        )

    # ─── POST /api/v1/ui/auth/change_password ──────────────

    @mcp.custom_route(
        "/api/v1/ui/auth/change_password",
        methods=["POST"],
        include_in_schema=False,
    )
    async def change_password(request: Request) -> JSONResponse:
        """Operator-driven password change from /profile. Requires:
        (1) a valid session token, AND (2) the current password.

        Verifying the current password is the second factor. The
        session token alone is insufficient because a stolen cookie
        would otherwise let an attacker lock out the operator."""
        if (resp := require_bearer(request)) is not None:
            return resp
        body_or_err = await _parse_json_dict(request)
        if isinstance(body_or_err, JSONResponse):
            return body_or_err
        body = body_or_err

        token, err = _required_string(body, "session_token", max_len=128)
        if err is not None:
            return err
        current_password, err = _required_string(
            body, "current_password", max_len=512,
        )
        if err is not None:
            return err
        new_password, err = _required_string(
            body, "new_password", max_len=512,
        )
        if err is not None:
            return err

        store = auth_store()
        validation = store.validate_session(token)
        if validation is None:
            return JSONResponse(
                {"error": "invalid session"}, status_code=401,
            )
        username = validation["username"]

        if not store.verify_password(username, current_password):
            _record(
                "password_change_rejected",
                actor=f"user:{username}",
                status="failure",
                target=f"user:{username}",
                reason="current_password_incorrect",
            )
            return JSONResponse(
                {"error": "current_password is incorrect"},
                status_code=403,
            )

        if new_password == current_password:
            return JSONResponse(
                {"error": "new_password must differ from current_password"},
                status_code=400,
            )

        try:
            store.set_password(username, new_password, mark_changed=True)
        except UiAuthError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

        # Revoke ALL sessions for this user — including the one that
        # just authorized this change. The operator must log in again
        # with the new password on the next request.
        revoked = store.revoke_all_sessions(username)

        _record(
            "password_changed_ui",
            actor=f"user:{username}",
            status="success",
            target=f"user:{username}",
            sessions_revoked=revoked,
        )
        return JSONResponse({"ok": True, "sessions_revoked": revoked})

    # ─── POST /api/v1/ui/auth/admin_reset ──────────────────

    @mcp.custom_route(
        "/api/v1/ui/auth/admin_reset",
        methods=["POST"],
        include_in_schema=False,
    )
    async def admin_reset(request: Request) -> JSONResponse:
        """CLI-driven password reset. Only the MCP_TOKEN bearer is
        required (no session, no current password). The trust boundary
        is `docker exec` into the agent container — anyone who can do
        that can read MCP_TOKEN from /proc/1/environ.

        Used by mcp/agent/cli/reset-admin.mjs (the host-side reset CLI)
        for the forgot-password case."""
        if (resp := require_bearer(request)) is not None:
            return resp
        body_or_err = await _parse_json_dict(request)
        if isinstance(body_or_err, JSONResponse):
            return body_or_err
        body = body_or_err

        new_password, err = _required_string(
            body, "new_password", max_len=512,
        )
        if err is not None:
            return err

        # Defense-in-depth: don't let the CLI reset the password to
        # something blatantly weak. The 8-char minimum lives inside
        # UiAuthStore.set_password but checking here lets us return a
        # specific error vs. a generic UiAuthError.
        if len(new_password.strip()) < 8:
            return JSONResponse(
                {"error": "new_password must be at least 8 characters"},
                status_code=400,
            )

        store = auth_store()
        # The username is hardwired — single-user. A multi-user
        # deployment would derive it from a CLI flag.
        from usecase.auth_store import auth_store as _auth_store_factory  # noqa: F401

        username = "admin"
        try:
            store.set_password(username, new_password, mark_changed=True)
        except UiAuthError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

        revoked = store.revoke_all_sessions(username)
        _record(
            "password_changed_cli",
            actor=f"cli:{_hostname()}",
            status="success",
            target=f"user:{username}",
            sessions_revoked=revoked,
        )
        return JSONResponse({"ok": True, "sessions_revoked": revoked})
