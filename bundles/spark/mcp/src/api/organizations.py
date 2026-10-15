"""Organization HTTP endpoints: the sample company every generator draws from.

  GET    /api/v1/organizations                    -> {organizations: [meta], active_id}
  POST   /api/v1/organizations                    -> add one; body {document | text, format?, activate?, replace?}
  GET    /api/v1/organizations/active             -> the active organization with its document
  POST   /api/v1/organizations/validate           -> {valid, errors, warnings} for {document | text, format?}
  GET    /api/v1/organizations/{id}               -> one organization with its document
  PUT    /api/v1/organizations/{id}               -> replace the document; body {document, note?}
  DELETE /api/v1/organizations/{id}               -> operator organizations only, never the active one
  POST   /api/v1/organizations/{id}/activate      -> make it the one every generator uses
  POST   /api/v1/organizations/{id}/fork          -> editable copy; body {new_id?, new_name?}
  POST   /api/v1/organizations/{id}/changes       -> structured edit; body {changes, note?}
  GET    /api/v1/organizations/{id}/export        -> {format, text}; ?format=yaml|json
  GET    /api/v1/organizations/{id}/section       -> compact rows; ?name=&filter=&limit=&offset=&detail=&max_bytes=
  GET    /api/v1/organizations/{id}/cortex-setup  -> the ranges and suffixes to enter in Cortex
  GET    /api/v1/organizations/{id}/history       -> prior versions;   POST .../restore {seq}

All endpoints need `Authorization: Bearer <MCP_TOKEN>`. These are the operator-direct surface (the UI page); the agent
reaches the same store through the `organization_*` tools. An organization holds no credentials.
"""

from __future__ import annotations

import logging
from typing import Any

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from api.auth import require_bearer
from usecase import organization_model as om
from usecase.organization_store import OrganizationStoreError, SqliteOrganizationStore

logger = logging.getLogger("Phantom MCP")

_STATUS = {"not_found": 404, "exists": 409, "active": 409, "bundled_read_only": 409, "id_mismatch": 400}


def _fail(exc: Exception) -> JSONResponse:
    if isinstance(exc, OrganizationStoreError):
        return JSONResponse({"error": str(exc), "code": exc.code}, status_code=_STATUS.get(exc.code, 400))
    if isinstance(exc, om.OrganizationError):
        return JSONResponse({"error": str(exc), "errors": exc.errors, "code": "invalid"}, status_code=400)
    raise exc


async def _json(request: Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except Exception as exc:  # noqa: BLE001
        raise om.OrganizationError(f"invalid JSON body: {exc}") from exc
    if not isinstance(body, dict):
        raise om.OrganizationError("body must be a JSON object")
    return body


def _document(body: dict[str, Any]) -> dict[str, Any]:
    """The organization a request carries: an object under `document`, or YAML/JSON text under `text`."""
    if isinstance(body.get("document"), dict):
        return body["document"]
    if isinstance(body.get("text"), str):
        return om.parse_document(body["text"], body.get("format"))
    raise om.OrganizationError("body needs a `document` object or a `text` string")


def register_organization_routes(mcp: FastMCP, store: SqliteOrganizationStore) -> None:
    base = "/api/v1/organizations"

    def route(path: str, methods: list[str]):
        return mcp.custom_route(path, methods=methods, include_in_schema=False)

    @route(base, ["GET"])
    async def list_organizations(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        recs = store.list()
        active = next((r.id for r in recs if r.active), None)
        return JSONResponse({"organizations": [r.meta() for r in recs], "active_id": active, "count": len(recs)})

    @route(base, ["POST"])
    async def add_organization(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        try:
            body = await _json(request)
            actor = str(body.get("actor") or "user:operator")
            if isinstance(body.get("text"), str):
                rec = store.import_text(body["text"], body.get("format"), actor=actor,
                                        activate=bool(body.get("activate")), replace=bool(body.get("replace")))
            else:
                rec = store.create(_document(body), actor=actor, activate=bool(body.get("activate")))
        except (om.OrganizationError, OrganizationStoreError) as exc:
            return _fail(exc)
        return JSONResponse(rec.to_dict(), status_code=201)

    @route(f"{base}/active", ["GET"])
    async def active_organization(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        rec = store.get_active()
        if rec is None:
            return JSONResponse({"error": "no active organization", "code": "not_found"}, status_code=404)
        return JSONResponse(rec.to_dict())

    @route(f"{base}/validate", ["POST"])
    async def validate_organization(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        try:
            doc = _document(await _json(request))
        except om.OrganizationError as exc:
            return JSONResponse({"valid": False, "errors": exc.errors, "warnings": []})
        return JSONResponse(om.check(doc))

    @route(f"{base}/{{org_id}}", ["GET"])
    async def get_organization(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        rec = store.get(request.path_params["org_id"])
        if rec is None:
            return JSONResponse({"error": "not found", "code": "not_found"}, status_code=404)
        return JSONResponse(rec.to_dict())

    @route(f"{base}/{{org_id}}", ["PUT"])
    async def put_organization(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        try:
            body = await _json(request)
            rec = store.put(request.path_params["org_id"], _document(body),
                            actor=str(body.get("actor") or "user:operator"), note=body.get("note"))
        except (om.OrganizationError, OrganizationStoreError) as exc:
            return _fail(exc)
        return JSONResponse(rec.to_dict())

    @route(f"{base}/{{org_id}}", ["DELETE"])
    async def delete_organization(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        try:
            store.delete(request.path_params["org_id"], actor="user:operator")
        except OrganizationStoreError as exc:
            return _fail(exc)
        return JSONResponse({"deleted": request.path_params["org_id"]})

    @route(f"{base}/{{org_id}}/activate", ["POST"])
    async def activate_organization(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        try:
            rec = store.activate(request.path_params["org_id"], actor="user:operator")
        except OrganizationStoreError as exc:
            return _fail(exc)
        return JSONResponse(rec.to_dict())

    @route(f"{base}/{{org_id}}/fork", ["POST"])
    async def fork_organization(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        try:
            try:
                body = await _json(request)
            except om.OrganizationError:
                body = {}
            rec = store.fork(request.path_params["org_id"], new_id=body.get("new_id"), new_name=body.get("new_name"),
                             actor="user:operator")
        except (om.OrganizationError, OrganizationStoreError) as exc:
            return _fail(exc)
        return JSONResponse(rec.to_dict(), status_code=201)

    @route(f"{base}/{{org_id}}/changes", ["POST"])
    async def change_organization(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        try:
            body = await _json(request)
            rec, notes, forked_from = store.apply_changes(
                request.path_params["org_id"], body.get("changes") or {}, actor=str(body.get("actor") or "user:operator"),
                note=body.get("note"))
        except (om.OrganizationError, OrganizationStoreError) as exc:
            return _fail(exc)
        return JSONResponse({**rec.to_dict(), "notes": notes, "forked_from": forked_from})

    @route(f"{base}/{{org_id}}/export", ["GET"])
    async def export_organization(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        fmt = "json" if request.query_params.get("format") == "json" else "yaml"
        try:
            text = store.export_text(request.path_params["org_id"], fmt)
        except OrganizationStoreError as exc:
            return _fail(exc)
        return JSONResponse({"format": fmt, "text": text})

    @route(f"{base}/{{org_id}}/section", ["GET"])
    async def organization_section(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        rec = store.get(request.path_params["org_id"])
        if rec is None:
            return JSONResponse({"error": "not found", "code": "not_found"}, status_code=404)
        q = request.query_params

        def num(key: str, default: int) -> int:
            try:
                return int(q.get(key) or default)
            except ValueError:
                return default

        # The UI has no tool-result cap, so it may ask for a larger page than the agent's default 12 KB.
        max_bytes = max(2_000, min(num("max_bytes", om.DEFAULT_MAX_BYTES), 2_000_000))
        try:
            return JSONResponse(om.section(rec.document, q.get("name"), q.get("filter"), num("limit", 50),
                                           num("offset", 0), q.get("detail") in ("1", "true"), max_bytes))
        except om.OrganizationError as exc:
            return _fail(exc)

    @route(f"{base}/{{org_id}}/cortex-setup", ["GET"])
    async def organization_cortex_setup(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        rec = store.get(request.path_params["org_id"])
        if rec is None:
            return JSONResponse({"error": "not found", "code": "not_found"}, status_code=404)
        return JSONResponse(om.cortex_setup(rec.document))

    @route(f"{base}/{{org_id}}/history", ["GET"])
    async def organization_history(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        try:
            limit = int(request.query_params.get("limit") or 10)
        except ValueError:
            limit = 10
        rows = store.history(request.path_params["org_id"], limit=limit)
        return JSONResponse({"versions": rows, "count": len(rows)})

    @route(f"{base}/{{org_id}}/restore", ["POST"])
    async def restore_organization(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        try:
            body = await _json(request)
            rec = store.restore(request.path_params["org_id"], int(body.get("seq")), actor="user:operator")
        except (om.OrganizationError, OrganizationStoreError) as exc:
            return _fail(exc)
        except (TypeError, ValueError):
            return JSONResponse({"error": "body needs an integer `seq`"}, status_code=400)
        return JSONResponse(rec.to_dict())
