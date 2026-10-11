"""Log destinations REST endpoints.

Operator-facing CRUD over `LogDestinationStore`. Each row carries
a `type_id` that points at a manifest in `destination_types_loader`;
the type's handler module implements the actual probe + send.

Surface (all require `Authorization: Bearer <MCP_TOKEN>`):

  GET    /api/v1/destination-types                  → all loaded manifests
  GET    /api/v1/destination-types/{type_id}        → single manifest
  GET    /api/v1/log-destinations                   → list (?type_id=, ?enabled_only=)
  GET    /api/v1/log-destinations/{id}              → single (?include_secrets= loopback-gated)
  POST   /api/v1/log-destinations                   → create
  PATCH  /api/v1/log-destinations/{id}              → update (partial)
  DELETE /api/v1/log-destinations/{id}              → delete
  POST   /api/v1/log-destinations/{id}/probe        → run handler.probe()
  POST   /api/v1/log-destinations/{id}/set-default  → mark as default-of-type

Agent MCP tools registered separately in main.py (read-only):
  log_destinations_list, log_destinations_get
"""

from __future__ import annotations

import logging
from typing import Any

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from api.auth import require_bearer
from usecase.audit_log import audit_log, reset_current_actor, set_current_actor
from usecase.destination_handler_registry import (
    dispatch_probe,
)
from usecase.destination_types_loader import (
    get_destination_types_loader,
)
from usecase.log_destinations_store import (
    LogDestination,
    LogDestinationStore,
)

logger = logging.getLogger("Phantom MCP")


def _dest_to_dict(
    dest: LogDestination,
    *,
    include_secrets: bool = False,
    store: LogDestinationStore | None = None,
) -> dict[str, Any]:
    """Serialize a destination for HTTP response.

    `include_secrets=False` (default) returns secrets as the redacted
    "***" sentinel.

    `include_secrets=True` resolves the actual values from SecretStore.
    Caller MUST verify this is safe — the route guards this behind a
    loopback-only check that callers from inside the same container
    (xlog) can satisfy.
    """
    payload = dest.to_dict(include_secrets=False)
    if include_secrets and store is not None:
        merged = store.merged_config(dest.id) or {}
        # Only fill secret-slot keys; non-secret config stays as-is
        resolved_secrets: dict[str, Any] = {}
        for slot in dest.secret_refs.keys():
            resolved_secrets[slot] = merged.get(slot)
        payload["secrets"] = resolved_secrets
    return payload


# Config fields that determine WHERE a probe sends. Changing any of these
# retargets the request, which is what makes carrying a stored secret through
# a dry-run override dangerous. Derived from what the shipped handlers read as
# their destination: splunk_hec / webhook / xsiam_http use `url`; syslog uses
# `host` + `port`.
_TARGET_FIELDS = ("url", "host", "port", "endpoint", "server")


def _is_loopback(request: Request) -> bool:
    """Determine whether the request originated from inside the same
    container (loopback). Used to gate `?include_secrets=true`.

    Starlette's Request.client populates with the peer address. Inside
    the agent container, xlog calls back via 127.0.0.1; agent UI calls
    via the proxy to the same loopback. Both qualify. Anything else
    (which shouldn't happen — the MCP only binds loopback) fails.
    """
    if request.client is None:
        return False
    host = request.client.host
    return host in ("127.0.0.1", "::1", "localhost")


def register_log_destination_routes(
    mcp: FastMCP,
    store: LogDestinationStore,
) -> None:
    """Register all log-destination REST endpoints on the FastMCP app."""

    # ─── GET /api/v1/destination-types ─────────────────────────────

    @mcp.custom_route(
        "/api/v1/destination-types",
        methods=["GET"],
        include_in_schema=False,
    )
    async def list_destination_types(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        loader = get_destination_types_loader()
        types = [m.to_dict() for m in loader.list_all().values()]
        types.sort(key=lambda t: t["name"])
        return JSONResponse({"types": types})

    @mcp.custom_route(
        "/api/v1/destination-types/{type_id}",
        methods=["GET"],
        include_in_schema=False,
    )
    async def get_destination_type(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        type_id = request.path_params["type_id"]
        manifest = get_destination_types_loader().get(type_id)
        if manifest is None:
            return JSONResponse(
                {"error": f"unknown destination type {type_id!r}"},
                status_code=404,
            )
        return JSONResponse({"type": manifest.to_dict()})

    # ─── GET /api/v1/log-destinations ──────────────────────────────

    @mcp.custom_route(
        "/api/v1/log-destinations",
        methods=["GET"],
        include_in_schema=False,
    )
    async def list_destinations(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        type_id = request.query_params.get("type_id") or None
        enabled_only = (
            request.query_params.get("enabled_only", "").lower() == "true"
        )
        rows = store.list_all(type_id=type_id, enabled_only=enabled_only)
        return JSONResponse({
            "destinations": [_dest_to_dict(d) for d in rows],
        })

    @mcp.custom_route(
        "/api/v1/log-destinations/{dest_id}",
        methods=["GET"],
        include_in_schema=False,
    )
    async def get_destination(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        dest_id = request.path_params["dest_id"]
        dest = store.get(dest_id)
        if dest is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        include_secrets = (
            request.query_params.get("include_secrets", "").lower() == "true"
        )
        if include_secrets and not _is_loopback(request):
            # Reject non-loopback callers asking for plaintext.
            return JSONResponse(
                {"error": "include_secrets requires loopback caller"},
                status_code=403,
            )
        return JSONResponse({
            "destination": _dest_to_dict(
                dest, include_secrets=include_secrets, store=store,
            ),
        })

    # ─── POST /api/v1/log-destinations ─────────────────────────────

    @mcp.custom_route(
        "/api/v1/log-destinations",
        methods=["POST"],
        include_in_schema=False,
    )
    async def create_destination(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        actor_token = set_current_actor("user:operator")
        try:
            try:
                body = await request.json()
            except Exception as exc:
                return JSONResponse(
                    {"error": f"invalid JSON body: {exc}"},
                    status_code=400,
                )
            if not isinstance(body, dict):
                return JSONResponse(
                    {"error": "body must be a JSON object"},
                    status_code=400,
                )

            name = body.get("name")
            type_id = body.get("type_id")
            config_in = body.get("config") or {}
            secrets_in = body.get("secrets") or {}
            description = body.get("description")
            enabled = bool(body.get("enabled", True))
            is_default = bool(body.get("is_default", False))

            if not isinstance(name, str) or not name:
                return JSONResponse(
                    {"error": "name is required (string)"},
                    status_code=400,
                )
            if not isinstance(type_id, str) or not type_id:
                return JSONResponse(
                    {"error": "type_id is required (string)"},
                    status_code=400,
                )
            if not isinstance(config_in, dict) or not isinstance(secrets_in, dict):
                return JSONResponse(
                    {"error": "config and secrets must be JSON objects"},
                    status_code=400,
                )

            try:
                dest = store.create(
                    name=name,
                    type_id=type_id,
                    config=config_in,
                    secrets=secrets_in,
                    description=description,
                    enabled=enabled,
                    is_default=is_default,
                )
            except ValueError as exc:
                msg = str(exc)
                code = 409 if "already exists" in msg else 400
                return JSONResponse({"error": msg}, status_code=code)

            try:
                audit_log().record(
                    action="log_destination_create",
                    target=f"log_destination:{dest.id}",
                    status="success",
                    metadata={
                        "name": dest.name,
                        "type_id": dest.type_id,
                        "is_default": dest.is_default,
                    },
                )
            except Exception as e:  # noqa: BLE001
                logger.warning("audit record failed: %s", e)

            return JSONResponse(
                {"destination": _dest_to_dict(dest)},
                status_code=201,
            )
        finally:
            reset_current_actor(actor_token)

    # ─── PATCH /api/v1/log-destinations/{id} ───────────────────────

    @mcp.custom_route(
        "/api/v1/log-destinations/{dest_id}",
        methods=["PATCH"],
        include_in_schema=False,
    )
    async def update_destination(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        actor_token = set_current_actor("user:operator")
        try:
            dest_id = request.path_params["dest_id"]
            try:
                body = await request.json()
            except Exception as exc:
                return JSONResponse(
                    {"error": f"invalid JSON body: {exc}"},
                    status_code=400,
                )
            if not isinstance(body, dict):
                return JSONResponse(
                    {"error": "body must be a JSON object"},
                    status_code=400,
                )

            kwargs: dict[str, Any] = {}
            if "name" in body:
                if not isinstance(body["name"], str):
                    return JSONResponse(
                        {"error": "name must be a string"},
                        status_code=400,
                    )
                kwargs["name"] = body["name"]
            if "config" in body:
                if not isinstance(body["config"], dict):
                    return JSONResponse(
                        {"error": "config must be a JSON object"},
                        status_code=400,
                    )
                kwargs["config"] = body["config"]
            if "secrets" in body:
                if not isinstance(body["secrets"], dict):
                    return JSONResponse(
                        {"error": "secrets must be a JSON object"},
                        status_code=400,
                    )
                kwargs["secrets"] = body["secrets"]
            if "enabled" in body:
                if not isinstance(body["enabled"], bool):
                    return JSONResponse(
                        {"error": "enabled must be a boolean"},
                        status_code=400,
                    )
                kwargs["enabled"] = body["enabled"]
            if "is_default" in body:
                if not isinstance(body["is_default"], bool):
                    return JSONResponse(
                        {"error": "is_default must be a boolean"},
                        status_code=400,
                    )
                kwargs["is_default"] = body["is_default"]
            if "description" in body:
                kwargs["description"] = (
                    None if body["description"] is None
                    else str(body["description"])
                )

            try:
                updated = store.update(dest_id, **kwargs)
            except ValueError as exc:
                return JSONResponse(
                    {"error": str(exc)}, status_code=409,
                )
            if updated is None:
                return JSONResponse(
                    {"error": "not found"}, status_code=404,
                )
            try:
                audit_log().record(
                    action="log_destination_update",
                    target=f"log_destination:{dest_id}",
                    status="success",
                    metadata={"fields": sorted(kwargs.keys())},
                )
            except Exception as e:  # noqa: BLE001
                logger.warning("audit record failed: %s", e)
            return JSONResponse({"destination": _dest_to_dict(updated)})
        finally:
            reset_current_actor(actor_token)

    # ─── DELETE /api/v1/log-destinations/{id} ──────────────────────

    @mcp.custom_route(
        "/api/v1/log-destinations/{dest_id}",
        methods=["DELETE"],
        include_in_schema=False,
    )
    async def delete_destination(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        actor_token = set_current_actor("user:operator")
        try:
            dest_id = request.path_params["dest_id"]
            removed = store.delete(dest_id)
            if not removed:
                return JSONResponse(
                    {"error": "not found"}, status_code=404,
                )
            try:
                audit_log().record(
                    action="log_destination_delete",
                    target=f"log_destination:{dest_id}",
                    status="success",
                )
            except Exception as e:  # noqa: BLE001
                logger.warning("audit record failed: %s", e)
            return JSONResponse({"ok": True})
        finally:
            reset_current_actor(actor_token)

    # ─── POST /api/v1/log-destinations/{id}/probe ──────────────────

    @mcp.custom_route(
        "/api/v1/log-destinations/{dest_id}/probe",
        methods=["POST"],
        include_in_schema=False,
    )
    async def probe_destination(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        actor_token = set_current_actor("user:operator")
        try:
            dest_id = request.path_params["dest_id"]
            dest = store.get(dest_id)
            if dest is None:
                return JSONResponse(
                    {"error": "not found"}, status_code=404,
                )

            # Optional dry-run override body: {config?, secrets?}
            # Lets the UI test before saving.
            try:
                body = await request.json()
            except Exception:
                body = {}
            dry_run = bool(body) if isinstance(body, dict) else False

            if dry_run and isinstance(body, dict):
                # Build merged_config from the overrides
                override_cfg = body.get("config") or {}
                override_secrets = body.get("secrets") or {}
                base = store.merged_config(dest_id) or {}

                # A config override that RETARGETS the probe must not carry the
                # stored secret with it.
                #
                # The legitimate use of a dry-run override is "test this config
                # before I save it". The attack is the same request with only
                # `url` replaced: the stored token survives in `base`, the
                # destination becomes an attacker's host, and dispatch_probe
                # posts `Authorization: <real token>` straight to them —
                # credential exfiltration with an agent:write call and no
                # secret ever being read back.
                #
                # So when the caller changes a target-identifying field, every
                # secret slot must be supplied explicitly in this request. The
                # "***" preserve-sentinel is refused here for the same reason:
                # its whole purpose is to carry a stored secret forward, which
                # is precisely what must not happen to a new target.
                retargeted = any(
                    k in override_cfg and str(override_cfg.get(k)) != str(base.get(k))
                    for k in _TARGET_FIELDS
                )
                if retargeted:
                    for slot in dest.secret_refs.keys():
                        base.pop(slot, None)
                    for slot, value in override_secrets.items():
                        if value == "***":
                            return JSONResponse(
                                {
                                    "error": (
                                        "cannot preserve a stored secret while "
                                        "changing the destination target; supply "
                                        f"{slot!r} explicitly"
                                    )
                                },
                                status_code=400,
                            )
                        base[slot] = value
                else:
                    # "***" sentinel preserves existing secret
                    for slot, value in override_secrets.items():
                        if value == "***":
                            continue
                        base[slot] = value
                merged = {**base, **override_cfg}
            else:
                merged = store.merged_config(dest_id) or {}

            try:
                result = await dispatch_probe(dest.type_id, merged)
            except KeyError as e:
                return JSONResponse(
                    {"error": str(e)}, status_code=400,
                )

            if not dry_run:
                store.record_probe(
                    dest_id,
                    ok=bool(result.get("ok")),
                    error=result.get("error"),
                    latency_ms=int(result.get("latency_ms") or 0),
                )
            try:
                audit_log().record(
                    action="log_destination_probe",
                    target=f"log_destination:{dest_id}",
                    status="success" if result.get("ok") else "failure",
                    metadata={
                        "type_id": dest.type_id,
                        "dry_run": dry_run,
                        "latency_ms": result.get("latency_ms"),
                    },
                )
            except Exception as e:  # noqa: BLE001
                logger.warning("audit record failed: %s", e)

            return JSONResponse({
                "ok": result.get("ok"),
                "error": result.get("error"),
                "latency_ms": result.get("latency_ms"),
                "dry_run": dry_run,
            })
        finally:
            reset_current_actor(actor_token)

    # ─── POST /api/v1/log-destinations/{id}/set-default ────────────

    @mcp.custom_route(
        "/api/v1/log-destinations/{dest_id}/set-default",
        methods=["POST"],
        include_in_schema=False,
    )
    async def set_default(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        actor_token = set_current_actor("user:operator")
        try:
            dest_id = request.path_params["dest_id"]
            updated = store.set_default(dest_id)
            if updated is None:
                return JSONResponse(
                    {"error": "not found"}, status_code=404,
                )
            try:
                audit_log().record(
                    action="log_destination_set_default",
                    target=f"log_destination:{dest_id}",
                    status="success",
                    metadata={"type_id": updated.type_id},
                )
            except Exception as e:  # noqa: BLE001
                logger.warning("audit record failed: %s", e)
            return JSONResponse({"destination": _dest_to_dict(updated)})
        finally:
            reset_current_actor(actor_token)

    logger.info(
        "Registered log_destination routes (CRUD + probe + set-default)"
    )
