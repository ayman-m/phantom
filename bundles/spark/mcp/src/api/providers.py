"""Provider CRUD HTTP endpoints — parallel to api/instances.py.

Model providers have the same
configuration lifecycle as tool connectors. This module exposes
the same endpoints, just against `/api/v1/providers` and
the `ProviderStore`. There is no model-catalog route: the agent's model
registry owns the catalog.

  GET    /api/v1/providers                  → list all provider instances
  GET    /api/v1/providers?provider_id=X    → list instances for a provider
  POST   /api/v1/providers                  → create one instance
  GET    /api/v1/providers/{instance_id}    → fetch one
  PUT    /api/v1/providers/{instance_id}    → partial update
  DELETE /api/v1/providers/{instance_id}    → delete one

The `provider_id` of an instance is one of `MODEL_PROVIDER_IDS`. The agent reads
a provider's credentials from the store on every model call, so none of these
writes needs a restart (`requires_mcp_restart` is always false).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from api.auth import require_bearer, require_loopback_for_secrets
from usecase.audit_log import reset_current_actor, set_current_actor
from usecase.provider_store import (
    ForeignSecretRefError,
    ProviderInstance,
    ProviderStore,
    is_own_secret_ref,
)

logger = logging.getLogger("Phantom MCP")

# The model providers the agent has an adapter for. Anything else would be an
# instance nothing reads, so it is refused rather than stored.
MODEL_PROVIDER_IDS = ("vertex", "anthropic", "openai")


def _unknown_provider_response(provider_id: str) -> JSONResponse:
    return JSONResponse(
        {
            "error": (
                f"unknown provider_id {provider_id!r}; "
                f"expected one of {', '.join(MODEL_PROVIDER_IDS)}"
            )
        },
        status_code=400,
    )


def _instance_to_dict(
    inst: ProviderInstance,
    *,
    redact_secrets: bool = True,
    secret_store: Any | None = None,
) -> dict[str, Any]:
    """Serialize a ProviderInstance for an HTTP response.

    redact_secrets=True (default): every secret slot is returned as
        the literal "***" sentinel. Used by the list endpoint and the
        non-cleartext detail endpoint — the wire never carries the
        actual secret value.

    redact_secrets=False, secret_store=None: returns the raw
        secret_refs dict (SecretStore paths or inline values). NOT
        what callers asking for cleartext want — paths look like
        absolute filesystem paths and consumers typically interpret
        them that way.

    redact_secrets=False, secret_store=<store>: resolves each
        secret_refs path against the SecretStore and returns the
        cleartext values. This is the path the agent's chat-handler
        Vertex resolver hits via ?include_secrets=true.

    On the include_secrets path `secrets` must carry resolved values, not
    secret_refs: returning the SecretStore path string (e.g.
    /agents/phantom/providers/<id>/serviceAccountJson) would make the chat
    handler's file-path-vs-JSON detector treat it as a file path → ENOENT
    on every chat dispatch.
    """
    if redact_secrets:
        secrets_out: dict[str, Any] = {k: "***" for k in inst.secret_refs}
    elif secret_store is not None:
        secrets_out = {}
        for slot, ref_or_value in inst.secret_refs.items():
            if isinstance(ref_or_value, str) and ref_or_value.startswith("/"):
                if not is_own_secret_ref(inst.id, slot, ref_or_value):
                    # Never follow a reference into another owner's secret,
                    # even from a row stored before writes were checked.
                    logger.warning(
                        "ProviderInstance %s/%s: slot %s holds a reference outside "
                        "its own secret path; not resolving it.",
                        inst.provider_id, inst.name, slot,
                    )
                    secrets_out[slot] = ""
                    continue
                try:
                    secrets_out[slot] = secret_store.read(ref_or_value)
                except Exception as exc:
                    logger.warning(
                        "ProviderInstance %s/%s: include_secrets resolve "
                        "failed for slot %s at %s (%s)",
                        inst.provider_id, inst.name, slot, ref_or_value, exc,
                    )
                    secrets_out[slot] = ""
            else:
                # Inline value (legacy or non-SecretStore-backed) — pass through.
                secrets_out[slot] = ref_or_value
    else:
        secrets_out = dict(inst.secret_refs)
    return {
        "id": inst.id,
        "provider_id": inst.provider_id,
        "name": inst.name,
        "config": inst.config,
        "secrets": secrets_out,
        "created_at": inst.created_at,
    }


def _refresh_embedder(provider_id: str, reason: str) -> str | None:
    """Re-decide the memory/KB embedder after a Vertex provider changed.

    The embedder is chosen from the provider store; without this call a Vertex
    provider saved after boot would leave memory + knowledge on the stub until
    the container restarted. Returns the embedder mode, or None when the
    provider is not Vertex (or the runtime is not wired, e.g. in unit tests).
    """
    if provider_id != "vertex":
        return None
    from usecase.embedder_runtime import embedder_runtime

    rt = embedder_runtime()
    if rt is None:
        return None
    try:
        return rt.refresh(reason)
    except Exception:  # noqa: BLE001
        # The provider write already succeeded; a refresh failure must not turn
        # it into a 500. The runtime logs and keeps the live embedder.
        logger.exception("embedder refresh after %s failed", reason)
        return None


def register_provider_routes(mcp: FastMCP, store: ProviderStore) -> None:
    """Register /api/v1/providers/* routes."""

    @mcp.custom_route("/api/v1/providers", methods=["GET"], include_in_schema=False)
    async def list_provider_instances(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        provider_id = request.query_params.get("provider_id")
        if provider_id:
            instances = store.list_for(provider_id)
        else:
            instances = store.list_all()
        return JSONResponse(
            {"instances": [_instance_to_dict(i) for i in instances]}
        )

    @mcp.custom_route("/api/v1/providers", methods=["POST"], include_in_schema=False)
    async def create_provider_instance(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        actor_token = set_current_actor("user:operator")
        try:
            try:
                body = await request.json()
            except Exception as exc:
                return JSONResponse({"error": f"invalid JSON body: {exc}"}, status_code=400)
            if not isinstance(body, dict):
                return JSONResponse({"error": "body must be a JSON object"}, status_code=400)

            provider_id = body.get("provider_id")
            name = body.get("name")
            config_in = body.get("config") or {}
            secrets_in = body.get("secrets") or {}

            if not isinstance(provider_id, str) or not provider_id:
                return JSONResponse({"error": "provider_id is required (string)"}, status_code=400)
            if provider_id not in MODEL_PROVIDER_IDS:
                return _unknown_provider_response(provider_id)
            if not isinstance(name, str) or not name:
                return JSONResponse({"error": "name is required (string)"}, status_code=400)
            if not isinstance(config_in, dict) or not isinstance(secrets_in, dict):
                return JSONResponse(
                    {"error": "config and secrets must be JSON objects"}, status_code=400
                )

            try:
                instance = store.create(provider_id, name, config_in, secrets_in)
            except ForeignSecretRefError as exc:
                return JSONResponse({"error": str(exc)}, status_code=400)
            except ValueError as exc:
                return JSONResponse({"error": str(exc)}, status_code=409)

            logger.info(
                "Created provider instance via API: provider_id=%s name=%s id=%s",
                provider_id, name, instance.id,
            )
            # Off the event loop: the refresh probes the new embedder with a real
            # network call (see EmbedderRuntime._probe).
            embedder_mode = await asyncio.to_thread(
                _refresh_embedder, provider_id, "vertex provider created"
            )
            return JSONResponse(
                {
                    "instance": _instance_to_dict(instance),
                    # A provider is live as soon as it is saved: the embedder is
                    # rebuilt above (Vertex) and chat reads the store per call.
                    "requires_mcp_restart": False,
                    **({"embedder_mode": embedder_mode} if embedder_mode else {}),
                },
                status_code=201,
            )
        finally:
            reset_current_actor(actor_token)

    @mcp.custom_route(
        "/api/v1/providers/{instance_id}",
        methods=["GET"],
        include_in_schema=False,
    )
    async def get_provider_instance(request: Request) -> JSONResponse:
        """Return one provider instance.

        Query param `include_secrets=true` returns secrets in cleartext.
        Bearer-auth gated, so only callers with MCP_TOKEN reach this
        path; in practice that's the agent's own server-side code
        (chat handler, runtime-config resolution). Without the param,
        secrets are returned redacted as "***" — same shape the list
        endpoint uses.

        The include_secrets opt-in lets the agent's runtime-config
        populate GOOGLE_APPLICATION_CREDENTIALS directly from the
        ProviderStore on each chat dispatch (see
        /help/architecture#setup-wiring).
        """
        if (resp := require_bearer(request)) is not None:
            return resp
        instance_id = request.path_params["instance_id"]
        if (resp := require_loopback_for_secrets(request)) is not None:
            return resp
        include_secrets = (
            request.query_params.get("include_secrets", "").lower() == "true"
        )
        instance = store.get(instance_id)
        if instance is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        return JSONResponse(
            {
                "instance": _instance_to_dict(
                    instance,
                    redact_secrets=not include_secrets,
                    # When the caller asked for cleartext, resolve secret_refs
                    # to actual values via the SecretStore. Without this the
                    # caller would receive the SecretStore PATHS (which look
                    # like /agents/phantom/providers/<id>/<slot>) and code
                    # paths like the chat handler's parseCredentialsInput
                    # would treat them as file paths → ENOENT.
                    secret_store=store._secret_store if include_secrets else None,
                ),
            }
        )

    @mcp.custom_route(
        "/api/v1/providers/{instance_id}",
        methods=["PUT"],
        include_in_schema=False,
    )
    async def update_provider_instance(request: Request) -> JSONResponse:
        """Partial update of an existing provider instance.

        Body:
          { "name"?: str, "config"?: object, "secrets"?: object }

        Lets the agent's /providers page write directly to the
        ProviderStore. Mirrors the PATCH semantics on /api/v1/instances/{id}: any
        omitted field leaves the stored value alone, and a secret
        slot with value "***" is treated as the redaction sentinel
        meaning "keep the stored secret as-is."
        """
        if (resp := require_bearer(request)) is not None:
            return resp
        actor_token = set_current_actor("user:operator")
        try:
            instance_id = request.path_params["instance_id"]
            try:
                body = await request.json()
            except Exception as exc:
                return JSONResponse(
                    {"error": f"invalid JSON body: {exc}"}, status_code=400
                )
            if not isinstance(body, dict):
                return JSONResponse(
                    {"error": "body must be a JSON object"}, status_code=400
                )

            name = body.get("name")
            config_in = body.get("config")
            secrets_in = body.get("secrets")
            if name is not None and not isinstance(name, str):
                return JSONResponse({"error": "name must be a string"}, status_code=400)
            if config_in is not None and not isinstance(config_in, dict):
                return JSONResponse({"error": "config must be a JSON object"}, status_code=400)
            if secrets_in is not None and not isinstance(secrets_in, dict):
                return JSONResponse({"error": "secrets must be a JSON object"}, status_code=400)
            if "provider_id" in body:
                return JSONResponse(
                    {"error": "provider_id cannot be changed; delete and recreate the instance"},
                    status_code=400,
                )
            current = store.get(instance_id)
            if current is not None and current.provider_id not in MODEL_PROVIDER_IDS:
                return _unknown_provider_response(current.provider_id)

            try:
                updated = store.update(
                    instance_id,
                    name=name,
                    config=config_in,
                    secrets=secrets_in,
                )
            except ForeignSecretRefError as exc:
                return JSONResponse({"error": str(exc)}, status_code=400)
            if updated is None:
                return JSONResponse({"error": "not found"}, status_code=404)

            logger.info(
                "Updated provider instance via API: id=%s provider_id=%s",
                updated.id, updated.provider_id,
            )
            embedder_mode = await asyncio.to_thread(
                _refresh_embedder, updated.provider_id, "vertex provider updated",
            )
            return JSONResponse(
                {
                    "instance": _instance_to_dict(updated),
                    **({"embedder_mode": embedder_mode} if embedder_mode else {}),
                }
            )
        finally:
            reset_current_actor(actor_token)

    @mcp.custom_route(
        "/api/v1/providers/{instance_id}",
        methods=["DELETE"],
        include_in_schema=False,
    )
    async def delete_provider_instance(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        actor_token = set_current_actor("user:operator")
        try:
            instance_id = request.path_params["instance_id"]
            existing = store.get(instance_id)
            deleted = store.delete(instance_id)
            if not deleted:
                return JSONResponse({"error": "not found"}, status_code=404)
            logger.info("Deleted provider instance via API: id=%s", instance_id)
            embedder_mode = None
            if existing is not None:
                embedder_mode = await asyncio.to_thread(
                    _refresh_embedder, existing.provider_id, "vertex provider deleted",
                )
            return JSONResponse(
                {
                    "deleted": True,
                    "id": instance_id,
                    "requires_mcp_restart": False,
                    **({"embedder_mode": embedder_mode} if embedder_mode else {}),
                }
            )
        finally:
            reset_current_actor(actor_token)
