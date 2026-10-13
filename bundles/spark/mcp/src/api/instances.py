"""Instance CRUD HTTP endpoints.

The Next.js agent's /connectors page + admin tools call these to create
connector instances (the Spark platform materializes the ones declared by
`manifest.yaml:setup.bindsInstances[]` itself).
Tools advertised by the MCP gate on the existence of instances (see
`usecase/connector_loader.py:iter_registrations`).

Endpoints (all require `Authorization: Bearer <MCP_TOKEN>`):

  GET    /api/v1/instances                 → list all instances
  GET    /api/v1/instances?connector_id=X  → list instances for a connector
  POST   /api/v1/instances                 → create one instance
  GET    /api/v1/instances/{instance_id}   → fetch one
  DELETE /api/v1/instances/{instance_id}   → delete one

NOTE: tools are not re-advertised live after CRUD — the MCP needs a
process restart to re-run iter_registrations and pick up new
instances. The CRUD response includes `requires_mcp_restart: true` so
clients (the agent) can show the right UX. The simplest way to apply a
change is `docker compose restart phantom-mcp` after a successful CRUD.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from typing import Any

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from api.auth import require_bearer, require_loopback_for_secrets
from usecase.audit_log import audit_log, reset_current_actor, set_current_actor
from usecase.connector_probes import PROBE_IMPLEMENTED, probe as run_probe
from usecase.connector_state import get_connector_state_store
from usecase.instance_store import Instance, InstanceStore
from usecase.secret_store import ForeignSecretRefError

logger = logging.getLogger("Phantom MCP")


# ─── restart on save ─────────────────────────────────────────────────────────
#
# A per-instance connector container reads its instance row and secrets once,
# when it starts (phantom-connector-runtime/runtime/entrypoint.py:_load_instance).
# Saving an instance therefore has no effect on the running container until it
# is restarted, so PATCH asks phantom-updater to restart it. Same URL and
# bearer token as the start and stop calls below (PHANTOM_UPDATER_URL, MCP_TOKEN).

# How long PATCH waits for the restart before answering. A restart is stop,
# image pull (best effort) and start, which can take longer than an operator
# should wait on Save; the restart keeps running and the response says so. It
# stays under the agent proxy's 15 s limit (mcp/agent/lib/mcp-proxy.ts), or the
# save would look failed although it succeeded.
RESTART_WAIT_S = 10.0
# The updater call itself is bounded too, so a hung updater cannot pile up tasks.
RESTART_CALL_TIMEOUT_S = 120.0

_restart_tasks: set["asyncio.Task[Any]"] = set()


async def _updater_restart(
    connector_id: str, container_instance_name: str, instance_id: str,
    image_ref: str | None = None,
) -> dict[str, Any]:
    """Ask phantom-updater to restart one instance's container (stop, then start).

    Returns {"ok": True, "status": "restarted"} or {"ok": False, "status": "failed",
    "error": <short reason>}. Never raises: the instance row is already saved.
    `container_instance_name` is the name segment of the container that is
    running (see _container_instance_name), already safe for a URL path.
    """
    import httpx

    updater_url = os.environ.get("PHANTOM_UPDATER_URL", "http://phantom-updater:8090").rstrip("/")
    url = f"{updater_url}/api/v1/connectors/{connector_id}/instances/{container_instance_name}/restart"
    token = os.environ.get("MCP_TOKEN", "")
    body: dict[str, Any] = {"instance_id": instance_id}
    if image_ref:
        body["image_ref"] = image_ref
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(RESTART_CALL_TIMEOUT_S)) as client:
            resp = await client.post(
                url, json=body, headers={"Authorization": f"Bearer {token}"} if token else {},
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("could not call phantom-updater restart for %s/%s: %s",
                       connector_id, container_instance_name, exc)
        reason = "timed out" if isinstance(exc, httpx.TimeoutException) else "could not be reached"
        return {"ok": False, "status": "failed", "error": f"phantom-updater {reason}"}
    if resp.status_code >= 300:
        detail = ""
        try:
            raw = resp.json().get("detail")
            detail = raw if isinstance(raw, str) else ""
        except Exception:  # noqa: BLE001
            detail = ""
        logger.warning("phantom-updater restart returned %d for %s/%s (body=%.300s)",
                       resp.status_code, connector_id, container_instance_name, resp.text)
        error = f"phantom-updater answered HTTP {resp.status_code}"
        if detail:
            error += f": {detail[:200]}"
        return {"ok": False, "status": "failed", "error": error}
    return {"ok": True, "status": "restarted"}


def _container_instance_name(inst: Instance, fallback_slug: str) -> str:
    """The name segment of the instance's running container.

    The container is named phantom-connector-<connector>-<name at creation> and
    its container_url carries that name. A rename does not rename the container,
    so the live name is read from container_url; an instance without one falls
    back to the slug of its current name.
    """
    url = inst.container_url or ""
    prefix = f"http://phantom-connector-{inst.connector_id}-"
    if url.startswith(prefix) and url.endswith(":9000"):
        name = url[len(prefix):-len(":9000")]
        if re.fullmatch(r"[a-zA-Z0-9_-]+", name):
            return name
    return fallback_slug


def _audit_restart(connector_id: str, instance_id: str, result: dict[str, Any]) -> None:
    """Write the final outcome of one restart as an `instance_restart` audit row."""
    a = audit_log()
    if a is None:
        return
    metadata: dict[str, Any] = {
        "instance_id": instance_id,
        "connector_id": connector_id,
        "outcome": result.get("status"),
    }
    if result.get("error"):
        metadata["error"] = str(result["error"])[:300]
    a.record(
        action="instance_restart",
        target=f"instance:{instance_id}",
        status="success" if result.get("ok") else "failure",
        actor="user:operator",
        metadata=metadata,
    )


async def _restart_and_wait(
    connector_id: str, container_instance_name: str, instance_id: str,
    image_ref: str | None,
) -> dict[str, Any]:
    """Run the restart and wait up to RESTART_WAIT_S for its outcome.

    When it is still running at the deadline the task keeps going and the answer
    is {"ok": True, "status": "in_progress"}: the save has succeeded and the
    connector is on its way up. Either way the FINAL outcome is audited once
    (as the task finishes), so a restart that fails after the response was sent
    is visible in observability, not only in the MCP log.
    """
    task = asyncio.ensure_future(
        _updater_restart(connector_id, container_instance_name, instance_id, image_ref)
    )
    _restart_tasks.add(task)

    def _finished(t: "asyncio.Task[Any]") -> None:
        _restart_tasks.discard(t)
        if t.cancelled():
            result: dict[str, Any] = {"ok": False, "status": "failed", "error": "restart was cancelled"}
        elif t.exception() is not None:
            result = {"ok": False, "status": "failed", "error": f"{type(t.exception()).__name__}"}
        else:
            result = t.result()
        if not result.get("ok"):
            logger.warning("restart of instance %s (%s) failed: %s",
                           instance_id, connector_id, result.get("error"))
        _audit_restart(connector_id, instance_id, result)

    task.add_done_callback(_finished)
    done, _ = await asyncio.wait({task}, timeout=RESTART_WAIT_S)
    if task in done:
        return task.result()
    return {"ok": True, "status": "in_progress"}


def _secrets_changed(secrets_in: Any) -> bool:
    """True when a PATCH `secrets` object carries at least one real value ("***" means keep)."""
    return isinstance(secrets_in, dict) and any(v != "***" for v in secrets_in.values())


def _instance_to_dict(
    inst: Instance,
    *,
    redact_secrets: bool = True,
    secret_store: Any | None = None,
) -> dict[str, Any]:
    """Serialize for HTTP response. Secrets are redacted by default.

    `enabled` is per-instance (instances.enabled column),
    independent of connector_state. `state` is still sourced from
    connector_state — that captures the *connection health* of the
    upstream (connected/failed/needs-auth/pending), which is a
    different axis from "is this the operator's chosen instance".
    Both must be true for tools to actually work in chat.

    When ``redact_secrets=False`` AND ``secret_store`` is
    provided, the secrets dict is returned as cleartext via
    ``inst.resolved_secrets(secret_store)`` — used by the backup
    feature so the resulting zip is restore-complete on a different
    deployment with a different PHANTOM_SECRET_KEK. Without
    ``secret_store``, the raw secret_refs (paths, not values) are
    returned.
    """
    cs_store = get_connector_state_store()
    state = "pending"
    last_error: str | None = None
    if cs_store is not None:
        cs = cs_store.get(inst.connector_id)
        if cs is not None:
            state = cs.state
            last_error = cs.last_error
    if redact_secrets:
        secrets_out: dict[str, Any] = {k: "***" for k in inst.secrets}
    elif secret_store is not None:
        secrets_out = inst.resolved_secrets(secret_store)
    else:
        secrets_out = inst.secrets
    return {
        "id": inst.id,
        "connector_id": inst.connector_id,
        "name": inst.name,
        "config": inst.config,
        "secrets": secrets_out,
        "created_at": inst.created_at,
        "enabled": inst.enabled,
        "state": state,
        # The last probe/tool failure for the connector (None when it has
        # not failed). Lets /connectors say why a connection is failing.
        "last_error": last_error,
        # container_url exists on the Instance dataclass (set by
        # phantom-updater's _agent_set_container_url callback for
        # style:container connectors). The instances_list +
        # instances_get MCP tools in self_mod_tools.py expose it too.
        # None is the expected value for in-process style:module
        # connectors.
        "container_url": inst.container_url,
        # Per-instance disabled-tools list. Drives the
        # /connectors instance Tools tab. Empty = all tools enabled.
        "disabled_tools": list(inst.disabled_tools),
    }


def register_instance_routes(mcp: FastMCP, store: InstanceStore) -> None:
    """Register /api/v1/instances/* routes on the FastMCP server."""

    @mcp.custom_route("/api/v1/instances", methods=["GET"], include_in_schema=False)
    async def list_instances(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        connector_id = request.query_params.get("connector_id")
        # The backup feature reads cleartext secrets from the
        # InstanceStore via this flag (same ?include_secrets=true pattern
        # as the ProviderStore). Default is redacted: callers get the
        # masked "***" sentinel.
        #
        # Bearer auth alone is not the gate: the agent-side backup route
        # delegates auth to middleware, which admits API keys, so a
        # read-scoped key could otherwise pull every stored credential.
        # A guarantee asserted in a comment across a network hop is an
        # assumption; the loopback check below makes it a control.
        if (resp := require_loopback_for_secrets(request)) is not None:
            return resp
        include_secrets = (
            request.query_params.get("include_secrets", "").lower() == "true"
        )
        if connector_id:
            instances = store.list_for(connector_id)
        else:
            instances = store.list_all()
        return JSONResponse(
            {
                "instances": [
                    _instance_to_dict(
                        i,
                        redact_secrets=not include_secrets,
                        secret_store=(
                            store._secret_store if include_secrets else None
                        ),
                    )
                    for i in instances
                ]
            }
        )

    # ─── connector container lifecycle helpers ───────────────────────────
    #
    # When a connector's connector.yaml has runtimeMapping.style: container,
    # the agent's instance create/delete handlers also call phantom-updater
    # to start/stop the per-instance container. Without these calls, the
    # connector_loader's container branch finds container-style
    # instances with no container_url set and tool calls error out at the
    # proxy with "container_url not set."
    #
    # phantom-updater is at PHANTOM_UPDATER_URL (default
    # http://phantom-updater:8090) and authenticated by the same MCP_TOKEN
    # the agent uses for /api/v1 — both services inherit it from the host
    # .env at startup.

    def _load_connector_spec(connector_id: str) -> dict[str, Any] | None:
        """Read connector.yaml from disk for the given id.

        Also scans /app/data/user_connectors/<id>/ for
        user-uploaded connectors. Returns the parsed YAML (or None
        when the file is missing/unparseable). Callers tolerate
        None as "unknown connector" (the install gate above
        prevents instance creation from unknown ids anyway).
        """
        from pathlib import Path
        import yaml

        bundle_root = Path(os.environ.get("BUNDLE_ROOT", "/app/bundle"))
        candidates = [
            bundle_root / "connectors" / connector_id / "connector.yaml",
            Path(os.environ.get("DATA_ROOT", "/app/data"))
            / "user_connectors"
            / connector_id
            / "connector.yaml",
        ]
        for cy in candidates:
            if cy.is_file():
                try:
                    doc = yaml.safe_load(cy.read_text(encoding="utf-8")) or {}
                    if isinstance(doc, dict):
                        return doc
                except Exception:  # noqa: BLE001
                    continue
        return None

    def _connector_runtime_style(connector_id: str) -> str:
        """Read runtimeMapping.style from a connector's connector.yaml.

        Defaults to 'container' when the YAML is missing or the field
        is unset; container is the only runtime style, so callers that
        hit the default still produce a useful behavior (start a
        container).
        """
        doc = _load_connector_spec(connector_id) or {}
        return ((doc.get("runtimeMapping") or {}).get("style") or "container")

    def _connector_image_ref(connector_id: str) -> str | None:
        """Read the optional `image` field from a connector.yaml.

        Bundle connectors leave this empty (phantom-updater
        derives ghcr.io/<owner>/phantom-connector-<id>-oss:<version>).
        User-uploaded connectors MUST declare an `image` ref (enforced
        at upload time by api/marketplace.py). Returns None when no
        explicit image is declared.
        """
        doc = _load_connector_spec(connector_id) or {}
        image = doc.get("image")
        if isinstance(image, str) and image.strip():
            return image.strip()
        return None

    def _slug_instance_name(name: str) -> str:
        """Slug an instance name for safe use in URL paths + docker
        container names.

        phantom-updater validates path segments against
        `^[a-zA-Z0-9_-]+$` (updater/src/main.py:_validate_path_segments)
        and uses the segment verbatim in `phantom-connector-<id>-<name>`
        docker container names. Display names with spaces, slashes, or
        accented characters break BOTH the URL routing AND the docker-
        name constraint.

        Passing `instance_name` raw to the updater would break for an
        instance named "Cortex XDR" (with a space, which the UI form
        accepts): the URL `/instances/Cortex%20XDR/start` is rejected by
        the updater with HTTP 400 "invalid path segment", so the row
        would exist but no container would spawn.

        This slug:
        - Replaces any non-allowed char with `_`
        - Collapses consecutive underscores
        - Strips leading/trailing underscores
        - Falls back to `i<first-8-chars-of-instance-id>` if the slug
          would be empty (defense against a name made entirely of
          excluded chars)

        The display name in instances.db is unchanged — operators
        still see "Cortex XDR" in the UI. Only the docker container
        name uses the slug.
        """
        import re

        slugged = re.sub(r"[^a-zA-Z0-9_-]+", "_", name)
        slugged = re.sub(r"_+", "_", slugged).strip("_-")
        return slugged or "instance"

    async def _updater_start(
        connector_id: str, instance_name: str, instance_id: str,
    ) -> dict[str, Any] | None:
        """Call phantom-updater to start a connector container. Returns
        the response body on success; None on failure (logged, not
        re-raised — the instance row is created either way; operators
        can retry the start via UI/API).

        Passes an optional `image_ref` body field for
        user-uploaded connectors. Phantom-updater uses the explicit
        image when present (skipping its own derivation), or falls
        back to its derivation for bundle connectors.

        The instance_name is slugged before being passed to the updater,
        because display names with spaces/slashes/etc. fail the
        updater's path-segment validation. The slug is purely a
        wire-format concern — instances.db still stores the original
        display name.
        """
        import httpx

        instance_slug = _slug_instance_name(instance_name)
        updater_url = os.environ.get(
            "PHANTOM_UPDATER_URL", "http://phantom-updater:8090"
        ).rstrip("/")
        url = (
            f"{updater_url}/api/v1/connectors/{connector_id}"
            f"/instances/{instance_slug}/start"
        )
        token = os.environ.get("MCP_TOKEN", "")
        body: dict[str, Any] = {"instance_id": instance_id}
        image_ref = _connector_image_ref(connector_id)
        if image_ref is not None:
            body["image_ref"] = image_ref
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
                resp = await client.post(
                    url,
                    json=body,
                    headers={"Authorization": f"Bearer {token}"} if token else {},
                )
            if resp.status_code >= 300:
                logger.warning(
                    "phantom-updater start returned %d for %s/%s "
                    "(body=%.300s)",
                    resp.status_code, connector_id, instance_name, resp.text,
                )
                return None
            return resp.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "could not call phantom-updater start for %s/%s: %s",
                connector_id, instance_name, exc,
            )
            return None

    async def _updater_stop(
        connector_id: str, instance_name: str,
    ) -> str:
        """Call phantom-updater to stop a connector container. Returns
        "stopped", "not_running" (idempotent: nothing was running), or
        "failed" (the updater refused or could not be reached; the
        container may still be running). Synchronous so the row delete
        waits for the container to be gone.

        The instance_name is slugged for the same reason
        _updater_start does — _validate_path_segments rejects spaces
        and other display-name characters.
        """
        import httpx

        instance_slug = _slug_instance_name(instance_name)
        updater_url = os.environ.get(
            "PHANTOM_UPDATER_URL", "http://phantom-updater:8090"
        ).rstrip("/")
        url = (
            f"{updater_url}/api/v1/connectors/{connector_id}"
            f"/instances/{instance_slug}/stop"
        )
        token = os.environ.get("MCP_TOKEN", "")
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
                resp = await client.post(
                    url,
                    headers={"Authorization": f"Bearer {token}"} if token else {},
                )
            if resp.status_code >= 300:
                logger.warning(
                    "phantom-updater stop returned %d for %s/%s",
                    resp.status_code, connector_id, instance_name,
                )
                return "failed"
            try:
                status = resp.json().get("status")
            except Exception:  # noqa: BLE001
                status = None
            return "not_running" if status == "not_running" else "stopped"
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "could not call phantom-updater stop for %s/%s: %s",
                connector_id, instance_name, exc,
            )
            return "failed"

    @mcp.custom_route("/api/v1/instances", methods=["POST"], include_in_schema=False)
    async def create_instance(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        # Tag the actor for audit attribution. Anyone hitting
        # an admin endpoint with a valid MCP_TOKEN is a human operator,
        # so the cascading audit events from store.create (instance_created
        # + secret_write) all attribute to "user:operator".
        actor_token = set_current_actor("user:operator")
        try:
            try:
                body = await request.json()
            except Exception as exc:
                return JSONResponse({"error": f"invalid JSON body: {exc}"}, status_code=400)
            if not isinstance(body, dict):
                return JSONResponse({"error": "body must be a JSON object"}, status_code=400)

            connector_id = body.get("connector_id")
            name = body.get("name")
            config_in = body.get("config") or {}
            secrets_in = body.get("secrets") or {}
            # Optional list of tool names to disable at create time.
            # Pairs with the toggle UX on the existing-instance row (PATCH path).
            # Empty/missing → all tools enabled.
            disabled_tools_in = body.get("disabled_tools") or []

            if not isinstance(connector_id, str) or not connector_id:
                return JSONResponse({"error": "connector_id is required (string)"}, status_code=400)
            if not isinstance(name, str) or not name:
                return JSONResponse({"error": "name is required (string)"}, status_code=400)
            if not isinstance(config_in, dict) or not isinstance(secrets_in, dict):
                return JSONResponse(
                    {"error": "config and secrets must be JSON objects"}, status_code=400
                )
            if not isinstance(disabled_tools_in, list) or not all(
                isinstance(t, str) for t in disabled_tools_in
            ):
                return JSONResponse(
                    {"error": "disabled_tools must be a list of strings"},
                    status_code=400,
                )

            # Install gate — instance creation requires the connector to
            # be marketplace-installed first; the marketplace is the
            # canonical entry point. Startup auto-installs every connector
            # that already has instances, so existing connectors never
            # hit this 409.
            from usecase.marketplace_store import get_marketplace_store
            _mp = get_marketplace_store()
            if _mp is not None and not _mp.is_installed(connector_id):
                return JSONResponse(
                    {
                        "error": (
                            f"connector {connector_id!r} is not installed. "
                            f"Install it from /connectors first (or POST "
                            f"/api/v1/marketplace/{connector_id}/install)."
                        ),
                        "code": "connector_not_installed",
                        "connector_id": connector_id,
                    },
                    status_code=409,
                )

            try:
                instance = store.create(
                    connector_id,
                    name,
                    config_in,
                    secrets_in,
                    disabled_tools=disabled_tools_in,
                )
            except ForeignSecretRefError as exc:
                return JSONResponse({"error": str(exc)}, status_code=400)
            except ValueError as exc:
                return JSONResponse({"error": str(exc)}, status_code=409)

            logger.info(
                "Created instance via API: connector_id=%s name=%s id=%s",
                connector_id, name, instance.id,
            )

            # If this connector has style: container,
            # also start the per-instance container via phantom-updater.
            # Returns the updater response (with container_url) on
            # success; None on failure — we still return 201 because
            # the row was created. Operators can retry the start via
            # POST /api/v1/connectors/<id>/instances/<name>/start.
            updater_response: dict[str, Any] | None = None
            style = _connector_runtime_style(connector_id)
            if style == "container":
                updater_response = await _updater_start(
                    connector_id, name, instance.id,
                )

            return JSONResponse(
                {
                    "instance": _instance_to_dict(instance),
                    "requires_mcp_restart": True,
                    # Echo container-mode start outcome when applicable.
                    # UI can surface "container starting…" / "container
                    # start failed — see logs" based on this.
                    "runtime_style": style,
                    "container_start": updater_response,
                },
                status_code=201,
            )
        finally:
            reset_current_actor(actor_token)

    @mcp.custom_route(
        "/api/v1/instances/{instance_id}",
        methods=["GET"],
        include_in_schema=False,
    )
    async def get_instance(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        instance_id = request.path_params["instance_id"]
        instance = store.get(instance_id)
        if instance is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        # Symmetric with /api/v1/instances (the list endpoint), which
        # honors `?include_secrets=true`. Same threat model and same
        # caller contract as the list endpoint, so the same loopback
        # gate applies.
        if (resp := require_loopback_for_secrets(request)) is not None:
            return resp
        include_secrets = (
            request.query_params.get("include_secrets", "").lower() == "true"
        )
        return JSONResponse(
            {
                "instance": _instance_to_dict(
                    instance,
                    redact_secrets=not include_secrets,
                    secret_store=(
                        store._secret_store if include_secrets else None
                    ),
                )
            }
        )

    @mcp.custom_route(
        "/api/v1/instances/{instance_id}",
        methods=["DELETE"],
        include_in_schema=False,
    )
    async def delete_instance(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        actor_token = set_current_actor("user:operator")
        try:
            instance_id = request.path_params["instance_id"]
            # For style: container connectors, stop
            # the container BEFORE deleting the row. If we delete first
            # and the container is still running, the agent's loader
            # would have a dangling proxy callable + the container
            # itself would be orphaned.
            existing = store.get(instance_id)
            container_stop: str | None = None
            if existing is not None:
                style = _connector_runtime_style(existing.connector_id)
                if style == "container":
                    container_stop = await _updater_stop(
                        existing.connector_id, existing.name
                    )
            deleted = store.delete(instance_id)
            if not deleted:
                return JSONResponse({"error": "not found"}, status_code=404)
            logger.info("Deleted instance via API: id=%s", instance_id)
            if container_stop == "failed":
                # The operator's intent (delete the instance) wins, but a
                # container that may still be running must not go unreported.
                logger.warning(
                    "Deleted instance %s but its container could not be stopped; "
                    "it may still be running (phantom-connector-%s-%s)",
                    instance_id, existing.connector_id, existing.name,
                )
            return JSONResponse(
                {
                    "deleted": True,
                    "id": instance_id,
                    "requires_mcp_restart": True,
                    # "stopped" | "not_running" | "failed" | null (the connector
                    # has no container, so there was nothing to stop).
                    "container_stop": container_stop,
                }
            )
        finally:
            reset_current_actor(actor_token)

    @mcp.custom_route(
        "/api/v1/instances/{instance_id}",
        methods=["PATCH"],
        include_in_schema=False,
    )
    async def patch_instance(request: Request) -> JSONResponse:
        """Partial update for an instance.

        Honored body fields:
          * enabled: bool         — enables or pauses the instance. A
                                    disabled instance's tools are not
                                    offered to the agent (the tool
                                    registry is reloaded on change).
          * name: str             — rename
          * config: dict          — replace the config blob
          * secrets: dict         — rotate one or more secret slots
                                    Per-slot "***" sentinel = leave
                                    that slot unchanged (so resubmitting
                                    the redacted form doesn't clobber
                                    stored secrets).
        Unrecognized keys are ignored.
        """
        if (resp := require_bearer(request)) is not None:
            return resp
        actor_token = set_current_actor("user:operator")
        try:
            instance_id = request.path_params["instance_id"]
            instance = store.get(instance_id)
            if instance is None:
                return JSONResponse({"error": "not found"}, status_code=404)
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

            # Collect every field we'll forward to store.update — enabled
            # joins name/config/secrets there so the one-active-per-
            # connector check happens atomically with the row write.
            update_kwargs: dict[str, Any] = {}
            if "enabled" in body:
                if not isinstance(body["enabled"], bool):
                    return JSONResponse(
                        {"error": "enabled must be a boolean"}, status_code=400
                    )
                update_kwargs["enabled"] = body["enabled"]
            if "name" in body:
                if not isinstance(body["name"], str) or not body["name"].strip():
                    return JSONResponse(
                        {"error": "name must be a non-empty string"},
                        status_code=400,
                    )
                update_kwargs["name"] = body["name"].strip()
            if "config" in body:
                if not isinstance(body["config"], dict):
                    return JSONResponse(
                        {"error": "config must be a JSON object"},
                        status_code=400,
                    )
                update_kwargs["config"] = body["config"]
            if "secrets" in body:
                if not isinstance(body["secrets"], dict):
                    return JSONResponse(
                        {"error": "secrets must be a JSON object"},
                        status_code=400,
                    )
                update_kwargs["secrets"] = body["secrets"]

            # disabled_tools is updated via a dedicated
            # store method (not the generic update) because:
            #   1. It's per-instance metadata that doesn't touch
            #      connector_state, the one-active-per-connector rule,
            #      or secret rotation — keeping the path separate avoids
            #      accidental coupling.
            #   2. The audit event shape is tool-toggle-specific (records
            #      which tools were added/removed), distinct from the
            #      generic instance_update event.
            disabled_tools_change: list[str] | None = None
            if "disabled_tools" in body:
                if not isinstance(body["disabled_tools"], list):
                    return JSONResponse(
                        {"error": "disabled_tools must be a JSON array of tool name strings"},
                        status_code=400,
                    )
                # All entries must be strings (cleaning happens in the store).
                for t in body["disabled_tools"]:
                    if not isinstance(t, str):
                        return JSONResponse(
                            {"error": "disabled_tools entries must be strings"},
                            status_code=400,
                        )
                disabled_tools_change = body["disabled_tools"]

            # What the container loaded when it started, for the restart decision below.
            config_before = dict(instance.config)
            was_enabled = instance.enabled

            if update_kwargs:
                try:
                    instance = store.update(instance_id, **update_kwargs)
                except ForeignSecretRefError as exc:
                    return JSONResponse({"error": str(exc)}, status_code=400)
                except ValueError as exc:
                    msg = str(exc)
                    # Surface "active-instance-conflict" as 409 so the UI
                    # can render a specific message instead of a generic
                    # 400. Substring match on the store's exception text;
                    # the message shape is shared with the create path.
                    is_conflict = "already has an active instance" in msg
                    return JSONResponse(
                        {"error": msg},
                        status_code=409 if is_conflict else 400,
                    )
                if instance is None:
                    return JSONResponse(
                        {"error": "not found"}, status_code=404
                    )

            if "enabled" in update_kwargs:
                # Enabling or disabling the instance changes which connectors
                # the agent is offered tools for; re-run the registration so
                # the catalogue follows without a restart.
                try:
                    from usecase.connector_loader import reload_tools_now  # noqa: PLC0415
                    reload_tools_now()
                except Exception as exc:  # noqa: BLE001 - the row IS updated
                    logger.warning(
                        "instance %s: enabled=%s stored but tool reload failed: %s. "
                        "The tool catalogue follows after an agent restart.",
                        instance_id, update_kwargs["enabled"], exc,
                    )

            if disabled_tools_change is not None:
                old_disabled = set(instance.disabled_tools)
                new_disabled = set(disabled_tools_change)
                added = sorted(new_disabled - old_disabled)
                removed = sorted(old_disabled - new_disabled)
                store.update_disabled_tools(instance_id, disabled_tools_change)
                instance = store.get(instance_id)
                if added or removed:
                    a = audit_log()
                    if a is not None:
                        a.record(
                            action="instance_tool_toggle",
                            target=f"instance:{instance_id}",
                            status="success",
                            metadata={
                                "instance_id": instance_id,
                                "connector_id": instance.connector_id,
                                "instance_name": instance.name,
                                "disabled_added": added,
                                "disabled_removed": removed,
                                "disabled_count_after": len(new_disabled),
                            },
                        )

            payload: dict[str, Any] = {"instance": _instance_to_dict(instance)}

            # The container loads config and secrets once, at start, so a saved
            # change reaches it only through a restart. Restart when the config
            # or a secret really changed, or when a disabled instance is enabled
            # (its container kept the settings it had when it was disabled). Not
            # for a tools-only or rename-only PATCH, a no-op save, or while the
            # instance is disabled (nothing offers its tools to the agent, and
            # enabling restarts it).
            config_changed = "config" in update_kwargs and instance.config != config_before
            needs_restart = (
                instance.enabled
                and (
                    config_changed
                    or _secrets_changed(update_kwargs.get("secrets"))
                    or (not was_enabled and update_kwargs.get("enabled") is True)
                )
                and _connector_runtime_style(instance.connector_id) == "container"
            )
            if needs_restart:
                payload["restart"] = await _restart_and_wait(
                    instance.connector_id,
                    _container_instance_name(instance, _slug_instance_name(instance.name)),
                    instance.id,
                    _connector_image_ref(instance.connector_id),
                )

            return JSONResponse(payload)
        finally:
            reset_current_actor(actor_token)

    @mcp.custom_route(
        "/api/v1/instances/{instance_id}/container_url",
        methods=["PUT"],
        include_in_schema=False,
    )
    async def set_instance_container_url(request: Request) -> JSONResponse:
        """Set or clear the per-instance container_url for
        connectors with `runtimeMapping.style: container` in their
        connector.yaml. Called by phantom-updater after each
        start/stop/restart of a connector container.

        Body:
          * container_url: str | null — the URL where the connector
                                        container's MCP listens
                                        (e.g. http://phantom-connector-
                                        web-acme:9000). null clears
                                        the routing entry (used by
                                        the stop endpoint).

        Returns 404 if the instance doesn't exist; 200 with
        {updated: true, instance_id, container_url} on success.

        Auth: same MCP_TOKEN bearer the rest of /api/v1 uses.
        Phantom-updater holds this token via env-var inheritance from
        the same .env file.
        """
        if (resp := require_bearer(request)) is not None:
            return resp
        actor_token = set_current_actor("system:phantom-updater")
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
            url = body.get("container_url")
            if url is not None and (
                not isinstance(url, str) or not url.strip()
            ):
                return JSONResponse(
                    {"error": "container_url must be a non-empty string or null"},
                    status_code=400,
                )
            ok = store.set_container_url(instance_id, url)
            if not ok:
                return JSONResponse(
                    {"error": f"instance {instance_id!r} not found"},
                    status_code=404,
                )
            logger.info(
                "instance %s: container_url %s",
                instance_id, "cleared" if url is None else f"= {url}",
            )
            # Trigger an in-place tool-registry reload so the proxy
            # closures pick up the new container_url. Without this,
            # the cached Instance objects (loaded at startup with
            # container_url=None) keep returning None from
            # merged_config(), and tool calls fail with "container_url
            # not set" until the agent restarts. See connector_loader's
            # _build_container_proxy — it reads container_url from
            # get_config() on each tool call but the underlying Instance
            # is the one captured by the closure.
            reloaded: tuple[int, int] | None = None
            try:
                from usecase.connector_loader import reload_tools_now  # noqa: PLC0415
                reloaded = reload_tools_now()
            except Exception as exc:  # noqa: BLE001
                # Best-effort — log and keep going. The DB row IS
                # updated; the operator can recover with a restart.
                logger.warning(
                    "instance %s: container_url stored but tool reload "
                    "failed: %s. Connector tool calls will fail with "
                    "stale container_url until agent restart.",
                    instance_id, exc,
                )
            return JSONResponse({
                "updated": True,
                "instance_id": instance_id,
                "container_url": url,
                "tools_reloaded": reloaded is not None,
                "tool_counts": {
                    "namespaced": reloaded[0] if reloaded else None,
                    "legacy": reloaded[1] if reloaded else None,
                },
            })
        finally:
            reset_current_actor(actor_token)

    @mcp.custom_route(
        "/api/v1/instances/{instance_id}/test",
        methods=["POST"],
        include_in_schema=False,
    )
    async def test_instance(request: Request) -> JSONResponse:
        """Run a real health probe for the instance's connector and
        update connector_state accordingly.

        Body (all optional):
          * config:  dict — override the persisted instance.config for
                            this probe. Lets the operator dry-run new
                            values from the edit dialog without saving.
          * secrets: dict — override the persisted secret slots. Per-
                            slot "***" sentinel = use the persisted
                            value (operator didn't change that slot).
          * dry_run: bool — when true (default if config/secrets given),
                            skip writing to connector_state. Lets the
                            operator try-before-save without polluting
                            connection-history. Default true if any
                            override is present, false otherwise.

        Every bundle connector has a read-only probe
        (usecase/connector_probes.py: it never sends an event; the
        sender connectors prove reachability only). It first checks the
        instance's connector container (`GET <container_url>/health`),
        then the connector's upstream. A connector without a probe (an
        operator-uploaded one) returns the current state unchanged with
        `probe_implemented: false` and a `message` saying it has no
        built-in test, so the UI can say so instead of staying silent.

        The probe reads instance.config + resolved secrets, so changing
        instance config changes the probe outcome.

        Response (probe run): {instance, probe_implemented: true, ok,
        error, is_auth_error, message, dry_run, connector_state}.
        `message` is what a pass proved (and, for senders, did not).
        """
        if (resp := require_bearer(request)) is not None:
            return resp
        actor_token = set_current_actor("user:operator")
        try:
            instance_id = request.path_params["instance_id"]
            instance = store.get(instance_id)
            if instance is None:
                return JSONResponse({"error": "not found"}, status_code=404)

            # Optional body — operator may dry-run with form values.
            config_override: dict[str, Any] | None = None
            secrets_override: dict[str, Any] | None = None
            dry_run_explicit: bool | None = None
            if request.headers.get("content-length", "0") not in ("", "0"):
                try:
                    body = await request.json()
                except Exception:
                    body = {}
                if isinstance(body, dict):
                    if isinstance(body.get("config"), dict):
                        config_override = body["config"]
                    if isinstance(body.get("secrets"), dict):
                        secrets_override = body["secrets"]
                    if isinstance(body.get("dry_run"), bool):
                        dry_run_explicit = body["dry_run"]

            has_override = (
                config_override is not None or secrets_override is not None
            )
            # Default: dry_run on when overrides present (form-test
            # before-save case), off when probing the persisted state
            # (post-save or card-level test).
            dry_run = (
                dry_run_explicit
                if dry_run_explicit is not None
                else has_override
            )

            cs_store = get_connector_state_store()
            cid = instance.connector_id

            if cid not in PROBE_IMPLEMENTED:
                # No built-in probe (an operator-uploaded connector): return
                # the current state with a flag and a plain message so the UI
                # never claims the test "passed" and never stays silent.
                current = cs_store.get(cid) if cs_store else None
                return JSONResponse(
                    {
                        "instance": _instance_to_dict(instance),
                        "probe_implemented": False,
                        "message": "This connector has no built-in test.",
                        "connector_state": (
                            current.to_dict() if current else None
                        ),
                    }
                )

            # Resolve effective config/secrets for the probe.
            effective_config: dict[str, Any] = (
                dict(config_override)
                if config_override is not None
                else dict(instance.config)
            )
            persisted_secrets = instance.resolved_secrets(store.secret_store)
            if secrets_override is None:
                effective_secrets: dict[str, Any] = persisted_secrets
            else:
                # Override mode — replace per-slot, with "***" sentinel
                # meaning "use persisted value" (operator didn't change
                # that slot in the form).
                effective_secrets = {}
                for slot, value in secrets_override.items():
                    if value == "***":
                        effective_secrets[slot] = persisted_secrets.get(slot, "")
                    else:
                        effective_secrets[slot] = value

            result = await run_probe(
                cid,
                config=effective_config,
                secrets=effective_secrets,
                container_url=instance.container_url,
                check_container=True,
            )
            ok, err, is_auth = result.ok, result.error, result.is_auth_error

            # Only write to connector_state when probing the persisted
            # config — a dry-run shouldn't pollute the connection
            # history with results that don't reflect the running stack.
            if cs_store is not None and not dry_run:
                if ok:
                    cs_store.record_success(cid)
                else:
                    cs_store.record_failure(
                        cid, error=err or "probe failed", is_auth_error=is_auth
                    )

            current = cs_store.get(cid) if cs_store else None
            return JSONResponse(
                {
                    "instance": _instance_to_dict(instance),
                    "probe_implemented": True,
                    "ok": ok,
                    "error": err,
                    "is_auth_error": is_auth,
                    "message": result.message,
                    "dry_run": dry_run,
                    "connector_state": current.to_dict() if current else None,
                }
            )
        finally:
            reset_current_actor(actor_token)
