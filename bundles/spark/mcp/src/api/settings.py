"""Settings HTTP endpoints — runtime overrides over the manifest's
`settings.defaults` for keys listed in `settings.overridable`.

The agent UI's admin panel uses these to let operators tweak runtime
behavior without rebuilding the bundle (model name, default scenario,
human-approval gates, etc.). Every set/clear is recorded to the audit
log via the `settings_changed` event already declared in the manifest.

Endpoints (all `Authorization: Bearer <MCP_TOKEN>`):

  GET /api/v1/settings        → describe-store snapshot:
        {
          "defaults":    {key: value, ...}   # manifest-bake (read-only)
          "overridable": ["key", ...]        # what the operator MAY set
          "effective":   {key: value, ...}   # merged: defaults ∪ overrides
          "overrides":   [
            {"key", "value", "default_value", "updated_at", "updated_by"},
            ...
          ]
        }

  PUT /api/v1/settings        → set or clear overrides in bulk
        body: {"updates": {key: value, ...},  # set/replace
               "clear":   ["key", ...],        # remove from overrides
               "actor":    "operator-id"}      # optional; recorded in audit

        response: { "applied": [...], "cleared": [...], "rejected": [...] }
        rejected = keys not in `overridable` (PermissionError); other
        errors raise the request as a whole.

# Why one PUT for both set and clear

The agent UI's settings panel is form-based: the operator opens it,
mutates several fields including some they want reset to default, and
clicks Save. A single bulk endpoint lets the form submit one HTTP
call and get a single coherent audit batch. Splitting into separate
DELETE/PATCH/POST surfaces would force the UI to interleave calls
and complicate error recovery.
"""

from __future__ import annotations

import logging
from typing import Any

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from api.auth import require_bearer
from usecase.settings_store import SqliteSettingsStore

logger = logging.getLogger("Phantom MCP")


def register_settings_routes(mcp: FastMCP, settings: SqliteSettingsStore) -> None:
    """Register /api/v1/settings on the FastMCP server."""

    @mcp.custom_route("/api/v1/settings", methods=["GET"], include_in_schema=False)
    async def get_settings(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        return JSONResponse(settings.describe())

    @mcp.custom_route("/api/v1/settings", methods=["PUT"], include_in_schema=False)
    async def put_settings(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        try:
            body: dict[str, Any] = await request.json()
        except Exception:
            return JSONResponse(
                {"error": "Request body must be JSON."}, status_code=400
            )
        if not isinstance(body, dict):
            return JSONResponse(
                {"error": "Request body must be a JSON object."}, status_code=400
            )

        actor = str(body.get("actor") or "operator")
        updates = body.get("updates") or {}
        clears = body.get("clear") or []
        if not isinstance(updates, dict):
            return JSONResponse(
                {"error": "`updates` must be a JSON object."}, status_code=400
            )
        if not isinstance(clears, list):
            return JSONResponse(
                {"error": "`clear` must be a JSON array of keys."}, status_code=400
            )

        applied: list[dict[str, Any]] = []
        cleared: list[str] = []
        rejected: list[dict[str, str]] = []

        # Two passes — first everything that will succeed, then the
        # report. This way a partial-fail surfaces all rejections
        # rather than stopping at the first.
        for key, value in updates.items():
            try:
                row = settings.set(key=str(key), value=value, actor=actor)
                applied.append(row.to_dict())
            except (PermissionError, ValueError) as exc:
                rejected.append({"key": key, "reason": str(exc)})
            except Exception as exc:
                rejected.append({"key": key, "reason": f"set failed: {exc}"})

        for key in clears:
            try:
                if settings.clear(key=str(key), actor=actor):
                    cleared.append(str(key))
            except PermissionError as exc:
                rejected.append({"key": str(key), "reason": str(exc)})
            except Exception as exc:
                rejected.append({"key": str(key), "reason": f"clear failed: {exc}"})

        return JSONResponse(
            {
                "applied": applied,
                "cleared": cleared,
                "rejected": rejected,
                "effective": settings.effective(),
            },
            status_code=200 if not rejected else 207,
        )
