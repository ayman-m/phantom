"""Marketplace API — canonical install-state surface.

An MCP-side REST surface backed by `marketplace_store.py`.
The Next.js routes under `app/api/agent/marketplace/*` are thin
proxies to this layer (same pattern as auth: agent UI calls
Next.js → Next.js proxies to MCP → MCP owns the canonical state).

Endpoints (all require `Authorization: Bearer <MCP_TOKEN>`):

  GET    /api/v1/marketplace                       → catalog + install state
  GET    /api/v1/marketplace/{connector_id}        → single connector detail
  POST   /api/v1/marketplace/{connector_id}/install   → mark installed
  POST   /api/v1/marketplace/{connector_id}/uninstall → unmark (409 if instances)
  DELETE /api/v1/marketplace/{connector_id}        → delete user connector entirely
                                                     (403 for bundle connectors)

Catalog source (read at every list call — cheap; just YAML on disk):

  Bundle connectors: manifest.yaml:toolConnectors[] + each entry's
    connector.yaml (image-baked under bundles/spark/connectors/<id>/)
  User connectors:   /app/data/user_connectors/<id>/connector.yaml
    (a missing directory is treated as empty)

Install/uninstall mutations DO NOT modify the catalog — they ONLY
flip the install marker in marketplace.db. Removing the install
marker does NOT remove the connector from the marketplace — it just
makes it "available, not installed". Bundle connectors STAY listed forever (image-baked);
user connectors stay until explicitly DELETEd.

Authority boundary:

  * Install state mutation: anyone holding MCP_TOKEN (Next.js layer
    + the agent's own chat handler via the `marketplace_install` MCP
    tool). Per the credential guardrail, install state is CATALOG
    metadata, not a credential — agent tools CAN read/write it
    ("catalog boundary ≠ credential boundary").
  * Instance state: same audit-event attribution policy as
    api/instances.py — `user:operator` for human-driven mutations,
    `agent` when the chat agent invokes the analogous tool.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from api.auth import require_bearer
from usecase.audit_log import (
    record_event,
    reset_current_actor,
    set_current_actor,
)
from usecase.connector_schema import (
    ConnectorSpecError,
    validate_connector_spec,
)
from usecase.instance_store import InstanceStore
from usecase.marketplace_store import (
    MarketplaceStore,
    MarketplaceInstall,
    ORIGIN_BUNDLE,
    ORIGIN_USER,
    resolved_data_root,
)

logger = logging.getLogger("Phantom MCP")


# ─────────────────────────────────────────────────────────────────
# Catalog scanning helpers
# ─────────────────────────────────────────────────────────────────

def _bundle_root() -> Path:
    """Path to the spark bundle on disk inside the agent container.

    Mirrors connector_loader._bundle_root() — kept duplicated rather
    than imported to avoid a circular dep between the marketplace
    API and the loader's heavy init path.
    """
    explicit = os.environ.get("BUNDLE_ROOT")
    if explicit:
        return Path(explicit)
    # Inside the agent image, the COPY in mcp/agent/Dockerfile places
    # the bundle at /app/bundle (see docker-compose.yml's read-only
    # mount of bundles/spark too). Both paths work.
    for cand in (Path("/app/bundle"), Path("/app/bundle/spark")):
        if (cand / "manifest.yaml").is_file():
            return cand
    # Final fallback for tests run from the repo root.
    return Path(__file__).resolve().parents[3]


def _user_connectors_root() -> Path:
    """Per-volume directory holding user-uploaded connector.yaml files.

    The upload path writes here; an empty/missing dir means 'no user
    connectors yet'.
    """
    return resolved_data_root() / "user_connectors"


def _load_yaml(path: Path) -> dict[str, Any]:
    """Best-effort YAML load. Logs + returns {} on error so a single
    bad file doesn't blow up the whole catalog response."""
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:
        logger.error("marketplace: pyyaml not importable; cannot read %s", path)
        return {}
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, Exception) as err:  # noqa: BLE001
        logger.warning("marketplace: failed to load %s: %s", path, err)
        return {}


def _connector_summary(
    connector_id: str,
    connector_yaml_path: Path,
    origin: str,
) -> dict[str, Any]:
    """Project a connector.yaml into the catalogue response shape.

    Kept thin — the full manifest is available via
    `GET /api/v1/connectors/{id}` (the existing detail surface in
    `api/connectors.py`). The marketplace tab on /connectors only
    needs name + version + tool count + tags.

    The projection includes `display_name` and `logo` so the
    UI doesn't need a separate detail fetch to render marketplace
    cards with proper names + logos.
    """
    spec = _load_yaml(connector_yaml_path)
    tools = (spec.get("spec") or {}).get("tools") or []
    # Logo is sometimes a multi-KB base64 string (worst case ~260 KB);
    # passing it through the list endpoint is fine for the ~10-20
    # connectors any deployment will have, and saves a per-card detail
    # fetch on the marketplace page render.
    raw_logo = spec.get("logo")
    logo = raw_logo if isinstance(raw_logo, str) and raw_logo.startswith("data:image/") else None
    return {
        "id": connector_id,
        "version": spec.get("version", "0.0.0"),
        "display_name": spec.get("displayName") or connector_id.replace("-", " ").title(),
        "description": spec.get("description") or spec.get("displayName") or "",
        "tools_count": len(tools),
        "tags": spec.get("tags") or [],
        "logo": logo,
        # `origin` is informational on the catalogue side — the
        # authoritative origin for install bookkeeping comes from
        # marketplace.db (set at install time). They agree by
        # construction but only the DB row gates DELETE.
        "origin": origin,
    }


def _scan_catalogue() -> dict[str, dict[str, Any]]:
    """Build the catalogue from disk. Bundle + user, indexed by id.

    Bundle entries: read from manifest.yaml:toolConnectors[].
    User entries:   each /app/data/user_connectors/<id>/connector.yaml.

    User-uploaded connectors that share an id with a bundle connector
    are REJECTED at upload time, so this function never
    has to disambiguate.
    """
    catalogue: dict[str, dict[str, Any]] = {}

    # Bundle catalogue
    root = _bundle_root()
    manifest = _load_yaml(root / "manifest.yaml")
    for entry in manifest.get("toolConnectors") or []:
        cid = entry.get("id")
        rel = entry.get("path")
        if not isinstance(cid, str) or not isinstance(rel, str):
            continue
        yaml_path = (root / rel).resolve() / "connector.yaml"
        if not yaml_path.is_file():
            logger.warning(
                "marketplace: bundle connector %s declared in manifest but "
                "%s does not exist; skipping from catalogue",
                cid,
                yaml_path,
            )
            continue
        catalogue[cid] = _connector_summary(cid, yaml_path, ORIGIN_BUNDLE)

    # User catalogue
    user_root = _user_connectors_root()
    if user_root.is_dir():
        for child in sorted(user_root.iterdir()):
            if not child.is_dir():
                continue
            yaml_path = child / "connector.yaml"
            if not yaml_path.is_file():
                continue
            spec = _load_yaml(yaml_path)
            cid = spec.get("id")
            if not isinstance(cid, str):
                continue
            if cid in catalogue:
                logger.warning(
                    "marketplace: user connector at %s declares id=%s which "
                    "collides with a bundle connector; preferring bundle "
                    "(upload would have rejected this)",
                    child,
                    cid,
                )
                continue
            catalogue[cid] = _connector_summary(cid, yaml_path, ORIGIN_USER)

    return catalogue


def _instances_count(store: InstanceStore, connector_id: str) -> int:
    """How many instances exist for this connector_id. Used to gate
    uninstall (and DELETE)."""
    try:
        return len(store.list_for(connector_id))
    except Exception:  # noqa: BLE001
        # If list_for misbehaves for any reason, be conservative and
        # report >0 so the uninstall path errs on the side of refusal.
        # Logged so the operator can see what happened.
        logger.exception(
            "marketplace: list_for(%s) failed; assuming instances present",
            connector_id,
        )
        return 1


def _install_to_dict(row: MarketplaceInstall | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "connector_id": row.connector_id,
        "installed_at": row.installed_at,
        "origin": row.origin,
        "version": row.version,
    }


# ─────────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────────

def register_marketplace_routes(
    mcp: FastMCP,
    marketplace_store: MarketplaceStore,
    instance_store: InstanceStore,
) -> None:
    """Wire the marketplace HTTP surface onto the given FastMCP."""

    @mcp.custom_route(
        "/api/v1/marketplace", methods=["GET"], include_in_schema=False,
    )
    async def list_marketplace(request: Request) -> JSONResponse:
        """Catalogue + install state for every connector.

        Response shape:
          {
            "connectors": [
              {
                "id": "caldera",
                "version": "1.0.0",
                "description": "...",
                "tools_count": 18,
                "tags": [...],
                "origin": "bundle",         (from catalogue)
                "installed": true,
                "install": {                 (null when not installed)
                  "installed_at": "...",
                  "origin": "bundle",        (from DB — authoritative)
                  "version": "bundled"
                },
                "instances_count": 1
              },
              ...
            ]
          }
        """
        if (resp := require_bearer(request)) is not None:
            return resp

        catalogue = _scan_catalogue()
        installs_by_id = {r.connector_id: r for r in marketplace_store.list_installed()}

        connectors: list[dict[str, Any]] = []
        for cid, summary in sorted(catalogue.items()):
            install_row = installs_by_id.get(cid)
            connectors.append(
                {
                    **summary,
                    "installed": install_row is not None,
                    "install": _install_to_dict(install_row),
                    "instances_count": _instances_count(instance_store, cid),
                }
            )

        # Sanity-include any install rows that don't correspond to a
        # known connector on disk. Shouldn't happen in steady state
        # but surfaces orphaned rows (e.g. user_connectors dir deleted
        # without going through DELETE /api/v1/marketplace/<id>) for
        # operator triage rather than hiding them.
        known_ids = set(catalogue.keys())
        orphans = [r for r in installs_by_id.values() if r.connector_id not in known_ids]
        for r in orphans:
            logger.warning(
                "marketplace: install row %s has no catalogue entry "
                "(orphaned)",
                r.connector_id,
            )

        return JSONResponse(
            {
                "connectors": connectors,
                "orphan_installs": [_install_to_dict(r) for r in orphans],
            }
        )

    @mcp.custom_route(
        "/api/v1/marketplace/{connector_id}",
        methods=["GET"],
        include_in_schema=False,
    )
    async def get_marketplace(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        connector_id = request.path_params["connector_id"]

        catalogue = _scan_catalogue()
        summary = catalogue.get(connector_id)
        if summary is None:
            return JSONResponse(
                {"error": f"connector {connector_id!r} not found in catalogue"},
                status_code=404,
            )
        install_row = marketplace_store.get(connector_id)
        return JSONResponse(
            {
                **summary,
                "installed": install_row is not None,
                "install": _install_to_dict(install_row),
                "instances_count": _instances_count(instance_store, connector_id),
            }
        )

    @mcp.custom_route(
        "/api/v1/marketplace/{connector_id}/download",
        methods=["GET"],
        include_in_schema=False,
    )
    async def download_connector_yaml(request: Request):
        """Stream a connector's full connector.yaml back to the caller.

        Operator-facing download for both bundle + user
        connectors. Same path resolution as `_scan_catalogue` so
        whatever the catalog says is on disk is what comes back.

        Headers: Content-Type: application/yaml + Content-Disposition
        attachment with the suggested filename `<connector_id>.yaml`.
        Browsers honor the attachment header and prompt save-as.

        The logo field — if present in the YAML — round-
        trips embedded in the file. No separate asset to serve.

        Audit: writes a `connector_downloaded` event so the operator
        can grep /observability/events for who pulled which connector
        and when.
        """
        from starlette.responses import PlainTextResponse
        if (resp := require_bearer(request)) is not None:
            return resp
        connector_id = request.path_params["connector_id"]

        # Locate the source YAML using the same logic as _scan_catalogue.
        # Bundle: bundles/spark/connectors/<id>/connector.yaml (resolved
        # via manifest.yaml). User: /app/data/user_connectors/<id>/connector.yaml.
        bundle_path = None
        try:
            root = _bundle_root()
            manifest = _load_yaml(root / "manifest.yaml")
            for entry in manifest.get("toolConnectors") or []:
                cid = entry.get("id")
                rel = entry.get("path")
                if cid == connector_id and isinstance(rel, str):
                    candidate = (root / rel).resolve() / "connector.yaml"
                    if candidate.is_file():
                        bundle_path = candidate
                        break
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "marketplace download: bundle resolution failed for %s: %s",
                connector_id, exc,
            )

        user_path = _user_connectors_root() / connector_id / "connector.yaml"
        source_path: Path | None = None
        origin: str
        if bundle_path is not None and bundle_path.is_file():
            source_path = bundle_path
            origin = ORIGIN_BUNDLE
        elif user_path.is_file():
            source_path = user_path
            origin = ORIGIN_USER
        else:
            return JSONResponse(
                {"error": f"connector {connector_id!r} not found"},
                status_code=404,
            )

        try:
            raw_text = source_path.read_text(encoding="utf-8")
        except OSError as exc:
            return JSONResponse(
                {"error": f"could not read {source_path}: {exc}"},
                status_code=500,
            )

        actor_token = set_current_actor("user:operator")
        try:
            record_event(
                action="connector_downloaded",
                target=f"connector:{connector_id}",
                status="success",
                metadata={
                    "origin": origin,
                    "bytes": len(raw_text),
                    "source_path": str(source_path),
                },
            )
        finally:
            reset_current_actor(actor_token)

        # Browser-side save-as ergonomics. application/yaml is the IANA
        # media type (RFC 9512 — text/x.yaml works too but yaml.org
        # registered application/yaml in 2024). Filename derives from
        # id rather than the on-disk name so URLs stay stable across
        # any future internal renames.
        return PlainTextResponse(
            content=raw_text,
            media_type="application/yaml",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="{connector_id}.yaml"'
                ),
                "Cache-Control": "no-store",
            },
        )

    @mcp.custom_route(
        "/api/v1/marketplace/{connector_id}/install",
        methods=["POST"],
        include_in_schema=False,
    )
    async def install_connector(request: Request) -> JSONResponse:
        """Mark connector as installed. Idempotent.

        Origin is derived from the catalogue (bundle vs user-uploaded)
        and pinned at first install. Subsequent installs return the
        existing row unchanged.
        """
        if (resp := require_bearer(request)) is not None:
            return resp
        connector_id = request.path_params["connector_id"]

        catalogue = _scan_catalogue()
        summary = catalogue.get(connector_id)
        if summary is None:
            return JSONResponse(
                {"error": f"connector {connector_id!r} not found in catalogue"},
                status_code=404,
            )
        origin = summary["origin"]

        actor_token = set_current_actor("user:operator")
        try:
            row = marketplace_store.install(
                connector_id,
                origin=origin,
                version=summary.get("version", "0.0.0"),
            )
            record_event(
                action="marketplace_install",
                target=f"connector:{connector_id}",
                status="success",
                metadata={"origin": origin, "version": row.version},
            )
            return JSONResponse(
                {"ok": True, "install": _install_to_dict(row)},
                status_code=200,
            )
        finally:
            reset_current_actor(actor_token)

    @mcp.custom_route(
        "/api/v1/marketplace/{connector_id}/uninstall",
        methods=["POST"],
        include_in_schema=False,
    )
    async def uninstall_connector(request: Request) -> JSONResponse:
        """Remove the install marker. 409 if instances exist for this
        connector — operator must delete instances first.

        Does NOT remove the connector from the catalogue. Bundle
        connectors stay listed (image-baked); user connectors stay
        until DELETE /api/v1/marketplace/{id}.
        """
        if (resp := require_bearer(request)) is not None:
            return resp
        connector_id = request.path_params["connector_id"]

        if not marketplace_store.is_installed(connector_id):
            return JSONResponse(
                {"error": f"connector {connector_id!r} is not installed"},
                status_code=404,
            )

        n_instances = _instances_count(instance_store, connector_id)
        if n_instances > 0:
            return JSONResponse(
                {
                    "error": (
                        f"connector {connector_id!r} has {n_instances} "
                        f"instance(s); delete instances before uninstalling"
                    ),
                    "instances_count": n_instances,
                },
                status_code=409,
            )

        actor_token = set_current_actor("user:operator")
        try:
            removed = marketplace_store.uninstall(connector_id)
            record_event(
                action="marketplace_uninstall",
                target=f"connector:{connector_id}",
                status="success" if removed else "noop",
                metadata={},
            )
            return JSONResponse({"ok": True, "removed": removed})
        finally:
            reset_current_actor(actor_token)

    # ── Upload (user connectors) ──────────────────────────────────

    @mcp.custom_route(
        "/api/v1/marketplace/upload",
        methods=["POST"],
        include_in_schema=False,
    )
    async def upload_connector(request: Request) -> JSONResponse:
        """Accept a connector.yaml file for a USER connector.

        Body: multipart/form-data with one field 'connector_yaml'
        carrying the file. Optional fields 'description', 'tags'
        (comma-separated) supply marketplace-card metadata when the
        YAML itself doesn't.

        Validation pipeline (fail-fast on first error):
          1. Body has a connector_yaml field with file content.
          2. Content parses as YAML.
          3. Spec validates against connector.schema.json. All required fields, container-only style,
             schema-valid configSchema, etc.
          4. spec.id does not collide with a bundle connector id.
          5. spec.id does not collide with an EXISTING user connector
             id (use DELETE first to replace).
          6. spec has an 'image' field (required for user connectors
             since phantom-updater can't derive an image ref from a
             connector_id it doesn't know about).

        On success:
          - Writes the YAML to /app/data/user_connectors/<id>/connector.yaml
          - Emits a `connector_uploaded` audit event
          - Returns 201 with the parsed spec summary

        Origin tracking: the marketplace_installs row gets origin='user'
        when the operator subsequently clicks Install. The on-disk
        location (user_connectors/<id>/) is the source-of-truth for
        origin determination during catalogue scans.
        """
        if (resp := require_bearer(request)) is not None:
            return resp

        try:
            form = await request.form()
        except Exception as exc:  # noqa: BLE001
            return JSONResponse(
                {"error": f"could not parse multipart body: {exc}"},
                status_code=400,
            )

        upload = form.get("connector_yaml")
        if upload is None:
            return JSONResponse(
                {
                    "error": (
                        "field 'connector_yaml' is required (multipart "
                        "file upload of the connector.yaml content)"
                    )
                },
                status_code=400,
            )

        # Read content. Both UploadFile (with .read()) and str (plain
        # form field) are tolerated — UploadFile is what curl -F sends
        # when the field is a @file; plain string covers the `-F
        # name=<text>` shorthand.
        try:
            if hasattr(upload, "read"):
                raw_bytes = await upload.read()
                if isinstance(raw_bytes, bytes):
                    raw_text = raw_bytes.decode("utf-8")
                else:
                    raw_text = str(raw_bytes)
            else:
                raw_text = str(upload)
        except Exception as exc:  # noqa: BLE001
            return JSONResponse(
                {"error": f"could not read uploaded file: {exc}"},
                status_code=400,
            )

        if not raw_text.strip():
            return JSONResponse(
                {"error": "uploaded connector_yaml is empty"},
                status_code=400,
            )

        try:
            import yaml  # type: ignore[import-untyped]
        except ImportError:
            return JSONResponse(
                {"error": "server missing pyyaml dep — cannot parse uploads"},
                status_code=500,
            )

        try:
            spec = yaml.safe_load(raw_text)
        except yaml.YAMLError as err:
            return JSONResponse(
                {"error": f"uploaded YAML failed to parse: {err}"},
                status_code=400,
            )
        if not isinstance(spec, dict):
            return JSONResponse(
                {"error": "uploaded YAML must be a top-level object"},
                status_code=400,
            )

        # Schema validation. Same validator + same schema the bundle
        # connectors validate against.
        try:
            validate_connector_spec(spec, source_path="<uploaded>")
        except ConnectorSpecError as err:
            return JSONResponse(
                {"error": str(err)},
                status_code=400,
            )

        cid = spec.get("id")
        if not isinstance(cid, str):
            return JSONResponse(
                {"error": "uploaded YAML missing valid id field"},
                status_code=400,
            )

        # Collision checks — bundle ids are reserved; existing user
        # ids must be deleted first.
        catalogue = _scan_catalogue()
        existing = catalogue.get(cid)
        if existing is not None:
            existing_origin = existing.get("origin")
            if existing_origin == ORIGIN_BUNDLE:
                return JSONResponse(
                    {
                        "error": (
                            f"connector id {cid!r} is reserved by a bundle "
                            f"connector and cannot be overridden by upload"
                        ),
                        "code": "id_collides_with_bundle",
                    },
                    status_code=409,
                )
            return JSONResponse(
                {
                    "error": (
                        f"user connector {cid!r} already exists. DELETE "
                        f"/api/v1/marketplace/{cid} first, then re-upload."
                    ),
                    "code": "id_already_exists",
                },
                status_code=409,
            )

        # Image ref is required for user connectors — phantom-updater
        # has no way to derive an image from a connector_id it didn't
        # ship with. Schema marks `image` optional (bundle connectors
        # don't need it); we enforce required-for-user here.
        image_ref = spec.get("image")
        if not isinstance(image_ref, str) or not image_ref.strip():
            return JSONResponse(
                {
                    "error": (
                        "user connectors must declare an 'image' field "
                        "with the OCI image reference of the published "
                        "connector container (e.g. 'ghcr.io/your-org/"
                        "your-connector:v1.0')"
                    ),
                    "code": "image_ref_required",
                },
                status_code=400,
            )

        # Write to disk: /app/data/user_connectors/<id>/connector.yaml
        target_dir = _user_connectors_root() / cid
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            (target_dir / "connector.yaml").write_text(
                raw_text, encoding="utf-8",
            )
        except OSError as err:
            return JSONResponse(
                {"error": f"could not persist user connector: {err}"},
                status_code=500,
            )

        actor_token = set_current_actor("user:operator")
        try:
            record_event(
                action="connector_uploaded",
                target=f"connector:{cid}",
                status="success",
                metadata={
                    "origin": ORIGIN_USER,
                    "version": spec.get("version", "0.0.0"),
                    "image": image_ref,
                    "tools_count": len((spec.get("spec") or {}).get("tools") or []),
                },
            )
        finally:
            reset_current_actor(actor_token)

        return JSONResponse(
            {
                "ok": True,
                "connector": _connector_summary(
                    cid, target_dir / "connector.yaml", ORIGIN_USER,
                ),
                "next_step": (
                    f"POST /api/v1/marketplace/{cid}/install to make this "
                    f"connector available for instance creation."
                ),
            },
            status_code=201,
        )

    # ── Delete (user connectors only) ─────────────────────────────

    @mcp.custom_route(
        "/api/v1/marketplace/{connector_id}",
        methods=["DELETE"],
        include_in_schema=False,
    )
    async def delete_connector(request: Request) -> JSONResponse:
        """Remove a USER connector from the marketplace entirely.

        Bundle connectors are 403-rejected — they're image-baked and
        can't be removed at runtime. The uninstall path
        (POST /api/v1/marketplace/<id>/uninstall) is the right tool
        for bundle connectors that you want to hide.

        For user connectors, this:
          1. Verifies no instances exist (409 if any).
          2. Removes the marketplace_installs row (if installed).
          3. Deletes /app/data/user_connectors/<id>/ recursively.
          4. Emits a `connector_deleted` audit event.

        Idempotent on the install row (no-op if not installed). NOT
        idempotent on the on-disk directory — once deleted, the
        operator must re-upload.
        """
        if (resp := require_bearer(request)) is not None:
            return resp
        connector_id = request.path_params["connector_id"]

        catalogue = _scan_catalogue()
        summary = catalogue.get(connector_id)
        if summary is None:
            return JSONResponse(
                {"error": f"connector {connector_id!r} not found"},
                status_code=404,
            )
        if summary["origin"] != ORIGIN_USER:
            return JSONResponse(
                {
                    "error": (
                        f"connector {connector_id!r} is a bundle connector "
                        f"and cannot be deleted. Use uninstall instead if "
                        f"you want to hide it from instance creation."
                    ),
                    "code": "cannot_delete_bundle",
                    "origin": summary["origin"],
                },
                status_code=403,
            )

        # Refuse if instances exist
        n_instances = _instances_count(instance_store, connector_id)
        if n_instances > 0:
            return JSONResponse(
                {
                    "error": (
                        f"connector {connector_id!r} has {n_instances} "
                        f"instance(s); delete instances before deleting "
                        f"the connector itself."
                    ),
                    "code": "has_instances",
                    "instances_count": n_instances,
                },
                status_code=409,
            )

        actor_token = set_current_actor("user:operator")
        try:
            # Remove the install marker if present.
            marketplace_store.uninstall(connector_id)

            # Remove the on-disk YAML directory.
            target_dir = _user_connectors_root() / connector_id
            try:
                import shutil

                if target_dir.is_dir():
                    shutil.rmtree(target_dir)
            except OSError as err:
                logger.warning(
                    "marketplace: could not remove %s after deleting "
                    "install row: %s. Manual cleanup needed.",
                    target_dir,
                    err,
                )

            record_event(
                action="connector_deleted",
                target=f"connector:{connector_id}",
                status="success",
                metadata={"origin": ORIGIN_USER},
            )
        finally:
            reset_current_actor(actor_token)

        return JSONResponse({"ok": True, "deleted": connector_id})
