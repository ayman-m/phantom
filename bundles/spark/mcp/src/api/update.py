"""Update HTTP endpoints — current version + manifest update config.

Implements the operator-visible surface of the spec's `update`
capability declared in manifest.update.{channel, registryUrl,
autoUpdate}. The bundle ships with `autoUpdate: false`, so the
substantive feature here is making that posture inspectable —
operators can see what channel they're tracking, what registry
the agent would update from if enabled, and the current
deployed version's identity.

Endpoints (Authorization: Bearer MCP_TOKEN or active API key):

  GET /api/v1/update/info       → {
        "current": {
          "image": "phantom-agent:local",
          "commit": "<git sha at build time, or null>",
          "branch": "<git branch at build time, or null>",
          "build_time": "<utc iso8601 from runtime-metadata.json>"
        },
        "manifest": {
          "channel": "stable",
          "registryUrl": "ghcr.io/<owner>/agents/...",
          "autoUpdate": false
        },
        "auto_update_enabled": false,
        "guidance": "manual update: docker compose pull + restart"
      }

# Why this exists, and what it isn't

Auto-update for a self-hosted SOC simulation agent is operationally
risky — the operator's deploy cadence is theirs to control. The
manifest's `autoUpdate: false` reflects that posture. This endpoint
honestly exposes the situation rather than implementing auto-update
machinery that would sit dormant.

If a future deploy flips `autoUpdate: true` (via manifest edit +
rebuild), the framework expected here is:
  1. A scheduled job (manifest.jobs[]) that calls a registry-
     polling helper to check for newer tags on the channel.
  2. When a newer version is found, publish a notification with
     topic="update-available" so operators see it in the agent UI.
  3. Optionally, an admin endpoint to TRIGGER the upgrade
     (docker compose pull + recreate) when an operator approves.

Today (1)–(3) are documented as future work; this endpoint just
exposes the inputs.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from api.auth import require_bearer

logger = logging.getLogger("Phantom MCP")

DEFAULT_BUNDLE_ROOT = "/app/bundle"
DEFAULT_RUNTIME_METADATA = "/app/runtime-metadata.json"


def _read_runtime_metadata() -> dict[str, Any]:
    """Read /app/runtime-metadata.json if present (baked in at image
    build time by scripts/export_agent_bundle.sh). Returns {} on any
    failure — operator just sees "build_time": null in the response."""
    candidates = [
        Path(os.getenv("RUNTIME_METADATA_PATH") or DEFAULT_RUNTIME_METADATA),
        Path("/app") / "runtime-metadata.json",
        Path(os.getenv("BUNDLE_ROOT") or DEFAULT_BUNDLE_ROOT) / "runtime-metadata.json",
    ]
    for p in candidates:
        if p.is_file():
            try:
                return json.loads(p.read_text("utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                logger.debug("update info: failed to read %s: %s", p, exc)
                return {}
    return {}


def _read_manifest_update_block(bundle_root: Path) -> dict[str, Any]:
    """Read the `update` block from manifest.yaml. Returns {} on any
    parse failure so the endpoint stays operational even with a
    malformed manifest."""
    try:
        import yaml
        manifest_path = bundle_root / "manifest.yaml"
        if not manifest_path.is_file():
            return {}
        data = yaml.safe_load(manifest_path.read_text("utf-8")) or {}
        block = data.get("update") or {}
        if isinstance(block, dict):
            return block
        return {}
    except Exception as exc:  # pragma: no cover
        logger.debug("update info: failed to parse manifest: %s", exc)
        return {}


def register_update_routes(mcp: FastMCP) -> None:
    @mcp.custom_route(
        "/api/v1/update/info", methods=["GET"], include_in_schema=False
    )
    async def update_info(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp

        bundle_root = Path(os.getenv("BUNDLE_ROOT") or DEFAULT_BUNDLE_ROOT)
        meta = _read_runtime_metadata()
        manifest_update = _read_manifest_update_block(bundle_root)

        auto = bool(manifest_update.get("autoUpdate", False))
        guidance = (
            "auto-update enabled — scheduled poller checks the registry; "
            "operator approves upgrade via /api/v1/admin/upgrade (future)."
            if auto
            else "manual update: `docker compose pull && docker compose up -d "
                 "--force-recreate` after the operator confirms a new image is ready."
        )

        return JSONResponse(
            {
                "current": {
                    "image": os.getenv("PHANTOM_AGENT_IMAGE", "phantom-agent:local"),
                    "commit": meta.get("source_commit") or None,
                    "branch": meta.get("source_branch") or None,
                    "bundle_name": meta.get("bundle_name") or None,
                    "bundle_mode": meta.get("bundle_mode") or None,
                    "build_time": meta.get("created_at") or None,
                },
                "manifest": {
                    "channel": manifest_update.get("channel"),
                    "registryUrl": manifest_update.get("registryUrl"),
                    "autoUpdate": auto,
                },
                "auto_update_enabled": auto,
                "guidance": guidance,
            }
        )
