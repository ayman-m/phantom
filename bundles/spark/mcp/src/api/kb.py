"""Knowledge-base HTTP endpoints.

The Next.js agent's "knowledge browser" view calls these to render the
bundle's loaded KBs. All endpoints are READ-ONLY at the API surface,
matching the manifest's `kbWrites: []` declaration. Operators who
want to add docs do it the right way: edit the bundle, redeploy, the
loader picks up the new files at boot.

Endpoints (all require `Authorization: Bearer <MCP_TOKEN>`):

  GET  /api/v1/kbs                            list all KBs (with counts)
  GET  /api/v1/kbs/{name}/docs                list docs in one KB
  GET  /api/v1/kbs/{name}/docs/{doc_id}       fetch one doc (audited)
  POST /api/v1/kbs/{name}/search              KB-scoped semantic search
  POST /api/v1/kbs/search                     cross-KB search (no scope)
"""

from __future__ import annotations

import logging

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from api.auth import require_bearer
from usecase.kb_store import SqliteKnowledgeBase

logger = logging.getLogger("Phantom MCP")


def register_kb_routes(mcp: FastMCP, kb: SqliteKnowledgeBase) -> None:
    """Register /api/v1/kbs/* routes."""

    def _kb_exists_or_404(name: str) -> JSONResponse | None:
        """Return a 404 JSONResponse if `name` isn't a loaded KB, else None.

        Why this matters: an empty list from `GET /kbs/ghost/docs` or
        `count: 0` from `POST /kbs/ghost/search` would make a silent typo
        look like "no results", and operators couldn't distinguish "this
        KB has no entries matching" from "this KB doesn't exist". A typo
        therefore gets a 404 with the full list of valid names so the
        operator (or agent) can self-correct.
        """
        if name in kb.kb_summary():
            return None
        valid = sorted(kb.kb_summary().keys())
        return JSONResponse(
            {
                "error": f"unknown knowledge base {name!r}",
                "valid_kbs": valid,
            },
            status_code=404,
        )

    @mcp.custom_route("/api/v1/kbs", methods=["GET"], include_in_schema=False)
    async def list_kbs(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        summary = kb.kb_summary()
        return JSONResponse(
            {
                "kbs": [
                    {"name": name, **stats}
                    for name, stats in sorted(summary.items())
                ],
                "count": len(summary),
            }
        )

    @mcp.custom_route(
        "/api/v1/kbs/{name}/docs", methods=["GET"], include_in_schema=False
    )
    async def list_kb_docs(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        name = request.path_params["name"]
        if (resp := _kb_exists_or_404(name)) is not None:
            return resp
        q = request.query_params
        try:
            limit = int(q.get("limit") or 100)
            offset = int(q.get("offset") or 0)
        except ValueError:
            limit, offset = 100, 0
        category = q.get("category") or None
        docs = kb.list_docs(
            name,
            category=category,
            limit=limit,
            offset=offset,
        )
        # Expose total_count + has_more so callers can paginate
        # correctly; `count` alone is the slice size and would hide the
        # true total.
        total = kb.count_docs(name, category=category)
        return JSONResponse(
            {
                # Default to NOT including content here — the list view
                # is for browsing, not bulk retrieval. Operators fetch
                # full content via /docs/{doc_id}.
                "documents": [d.to_dict(include_content=False) for d in docs],
                "count": len(docs),
                "total_count": total,
                "offset": offset,
                "limit": limit,
                "has_more": (offset + len(docs)) < total,
            }
        )

    @mcp.custom_route(
        "/api/v1/kbs/{name}/docs/{doc_id}",
        methods=["GET"],
        include_in_schema=False,
    )
    async def get_kb_doc(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        name = request.path_params["name"]
        if (resp := _kb_exists_or_404(name)) is not None:
            return resp
        doc_id = request.path_params["doc_id"]
        doc = kb.get_doc(name, doc_id)
        if doc is None:
            return JSONResponse(
                {"error": f"doc {doc_id!r} not found in kb {name!r}"},
                status_code=404,
            )
        return JSONResponse({"document": doc.to_dict()})

    @mcp.custom_route(
        "/api/v1/kbs/{name}/search",
        methods=["POST"],
        include_in_schema=False,
    )
    async def search_one_kb(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        name = request.path_params["name"]
        if (resp := _kb_exists_or_404(name)) is not None:
            return resp
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
        query = body.get("query")
        if not isinstance(query, str) or not query.strip():
            return JSONResponse(
                {"error": "'query' is required (non-empty string)"},
                status_code=400,
            )
        hits = kb.search(
            query,
            kb_name=name,
            category=body.get("category") or None,
            limit=int(body.get("limit") or 5),
            min_score=float(body.get("min_score") or 0.0),
        )
        return JSONResponse(
            {
                "results": [doc.to_dict(score=score) for doc, score in hits],
                "count": len(hits),
            }
        )

    @mcp.custom_route(
        "/api/v1/kbs/search", methods=["POST"], include_in_schema=False
    )
    async def search_all_kbs(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
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
        query = body.get("query")
        if not isinstance(query, str) or not query.strip():
            return JSONResponse(
                {"error": "'query' is required (non-empty string)"},
                status_code=400,
            )
        hits = kb.search(
            query,
            kb_name=body.get("kb_name") or None,
            category=body.get("category") or None,
            limit=int(body.get("limit") or 5),
            min_score=float(body.get("min_score") or 0.0),
        )
        return JSONResponse(
            {
                "results": [doc.to_dict(score=score) for doc, score in hits],
                "count": len(hits),
            }
        )
