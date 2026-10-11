"""Media upload HTTP endpoints.

  POST   /api/v1/media               → multipart upload
        form fields:
          file       (required, the upload itself)
          actor      (optional, operator id)
        response 201: {item: {...metadata...}, extracted: bool}

  GET    /api/v1/media               → paginated list of metadata
        ?limit=100&offset=0
        response: {items: [{...metadata...}], count}

  GET    /api/v1/media/{id}          → metadata + extracted text
        response: {...metadata..., extracted: "<text>" | null}

  GET    /api/v1/media/{id}/raw      → original bytes
        response: file body, content_type echoed in headers

  DELETE /api/v1/media/{id}          → remove (file + metadata)

The agent UI's chat composer can attach files via POST; the agent's
LLM context can then reference {extracted} for text-extracted uploads
without re-fetching the binary every turn.
"""

from __future__ import annotations

import logging

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse

from api.auth import require_bearer
from usecase.media_store import MediaTooLargeError, SqliteMediaStore

logger = logging.getLogger("Phantom MCP")


def register_media_routes(mcp: FastMCP, store: SqliteMediaStore) -> None:
    @mcp.custom_route("/api/v1/media", methods=["POST"], include_in_schema=False)
    async def upload(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        try:
            form = await request.form()
        except Exception as exc:
            return JSONResponse(
                {"error": f"could not parse multipart form: {exc}"}, status_code=400
            )
        upload_field = form.get("file")
        if upload_field is None or not hasattr(upload_field, "read"):
            return JSONResponse(
                {"error": "form field `file` is required"}, status_code=400
            )
        actor = form.get("actor")
        filename = getattr(upload_field, "filename", None) or "upload"
        content_type = getattr(upload_field, "content_type", None)
        try:
            content = await upload_field.read()
        except Exception as exc:
            return JSONResponse(
                {"error": f"failed to read upload: {exc}"}, status_code=400
            )
        try:
            item = store.upload(
                filename=str(filename),
                content=content,
                content_type=content_type,
                actor=str(actor) if actor else None,
            )
        except MediaTooLargeError as exc:
            return JSONResponse({"error": str(exc)}, status_code=413)
        except (TypeError, ValueError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return JSONResponse(
            {
                "item": item.to_dict(),
                "extracted": item.extracted is not None,
            },
            status_code=201,
        )

    @mcp.custom_route("/api/v1/media", methods=["GET"], include_in_schema=False)
    async def list_media(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        q = request.query_params
        try:
            limit = int(q.get("limit") or "100")
            offset = int(q.get("offset") or "0")
        except ValueError:
            limit, offset = 100, 0
        items = store.list(limit=limit, offset=offset)
        return JSONResponse(
            {"items": [i.to_dict() for i in items], "count": len(items)}
        )

    @mcp.custom_route(
        "/api/v1/media/{media_id}", methods=["GET"], include_in_schema=False
    )
    async def get_one(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        media_id = request.path_params.get("media_id", "")
        item = store.get(media_id)
        if not item:
            return JSONResponse({"error": "not found"}, status_code=404)
        return JSONResponse(item.to_dict(include_extracted=True))

    @mcp.custom_route(
        "/api/v1/media/{media_id}/raw",
        methods=["GET"],
        include_in_schema=False,
    )
    async def download_raw(request: Request):
        if (resp := require_bearer(request)) is not None:
            return resp
        media_id = request.path_params.get("media_id", "")
        item = store.get(media_id)
        path = store.path(media_id)
        if not item or path is None or not path.exists():
            return JSONResponse({"error": "not found"}, status_code=404)
        return FileResponse(
            path,
            media_type=item.content_type or "application/octet-stream",
            filename=item.filename,
        )

    @mcp.custom_route(
        "/api/v1/media/{media_id}",
        methods=["DELETE"],
        include_in_schema=False,
    )
    async def delete_one(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        media_id = request.path_params.get("media_id", "")
        actor = request.query_params.get("actor")
        ok = store.delete(media_id, actor=actor)
        return JSONResponse(
            {"deleted": ok, "id": media_id},
            status_code=200 if ok else 404,
        )
