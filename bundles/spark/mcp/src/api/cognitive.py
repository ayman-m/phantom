"""Cognitive HTTP endpoints (sessions + memory + context).

Three logical resources, one module to keep wiring tidy:

  Sessions:
    GET    /api/v1/sessions
    POST   /api/v1/sessions                    body: {user, title, meta}
    GET    /api/v1/sessions/{id}
    DELETE /api/v1/sessions/{id}
    POST   /api/v1/sessions/{id}/end
    GET    /api/v1/sessions/{id}/messages
    POST   /api/v1/sessions/{id}/messages      body: {role, content, ...}

  Memories:
    GET    /api/v1/memories
    POST   /api/v1/memories                    body: {key, value, scope, ttl_seconds, meta}
                                                — meta.source is always overwritten
                                                server-side to "operator"; a REST
                                                write is definitionally operator-
                                                sourced (the agent writes through
                                                the memory_store MCP tool instead,
                                                which stamps "agent")
    POST   /api/v1/memories/search             body: {query, limit, scope, mode}
                                                — mode is an audit-only
                                                discriminator: "passive" for
                                                the memory-inject hook's
                                                automatic per-turn search,
                                                omitted/"active" for anything
                                                else (memory_search tool call,
                                                a direct API caller)
    GET    /api/v1/memories/by-key/{key}?scope=…
    DELETE /api/v1/memories/by-key/{key}?scope=…

  Context:
    POST   /api/v1/context                     body: {query, session_id}

All endpoints require `Authorization: Bearer <MCP_TOKEN>`. The actor
contextvar gets tagged "user:operator" for write paths so audit rows
attribute correctly (same pattern as the other admin endpoints).

# Why one module instead of three

These three resources share auth, share serialization shape, and the
agent UI typically mounts them in the same admin panel. Keeping them
in one file avoids a `register_*_routes` import explosion in main.py.
The internal sections below stay clearly delimited.
"""

from __future__ import annotations

import logging
from typing import Any

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from api.auth import require_bearer
from usecase.audit_log import reset_current_actor, set_current_actor
from usecase.context_assembler import ContextAssembler
from usecase.memory_store import SqliteMemoryStore
from usecase.session_store import SqliteSessionStore

logger = logging.getLogger("Phantom MCP")


def _int(query: Any, key: str, default: int) -> int:
    raw = query.get(key)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _resolve_scope_filter(
    scope: str | None, scope_prefix: str | None
) -> tuple[str | None, str | None]:
    """Map a caller's raw scope/scope_prefix into the pair
    memory_store.list_all/search expect.

    scope is a hierarchical string ("session:<uuid>"); an EXACT match
    on the bare aggregate "session" can never match any real row, which
    is why the memory page's session tab always showed zero rows. If
    the caller sent an explicit scope_prefix, honor it. Otherwise, if
    scope is exactly the bare aggregate "session", rewrite it into a
    prefix match transparently — existing callers passing a real leaf
    scope ("agent", "session:abc123") are unaffected.
    """
    scope = scope or None
    scope_prefix = scope_prefix or None
    if scope_prefix is not None:
        return None, scope_prefix
    if scope == "session":
        return None, "session:"
    return scope, None


def _bool(query: Any, key: str, default: bool = False) -> bool:
    raw = (query.get(key) or "").lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    return default


def register_cognitive_routes(
    mcp: FastMCP,
    sessions: SqliteSessionStore,
    memories: SqliteMemoryStore,
    assembler: ContextAssembler,
) -> None:
    """Register all cognitive routes."""

    # ─── Sessions ───────────────────────────────────────────────

    @mcp.custom_route("/api/v1/sessions", methods=["GET"], include_in_schema=False)
    async def list_sessions(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        q = request.query_params
        rows = sessions.list_sessions(
            user=q.get("user") or None,
            limit=_int(q, "limit", 50),
            offset=_int(q, "offset", 0),
            active_only=_bool(q, "active_only", False),
            # When truthy, drops sessions that have
            # `meta.scheduled_by` set (i.e. job-driven sessions
            # spawned by the recurring-job dispatcher). The chat
            # sidebar uses this so operator-driven conversations
            # aren't buried under scheduled-job churn. See
            # SqliteSessionStore.list_sessions for the SQL detail.
            exclude_scheduled=_bool(q, "exclude_scheduled", False),
        )
        return JSONResponse(
            {"sessions": [s.to_dict() for s in rows], "count": len(rows)}
        )

    @mcp.custom_route("/api/v1/sessions", methods=["POST"], include_in_schema=False)
    async def create_session(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        actor_token = set_current_actor("user:operator")
        try:
            try:
                body = await request.json()
            except Exception as exc:
                return JSONResponse(
                    {"error": f"invalid JSON body: {exc}"}, status_code=400
                )
            if not isinstance(body, dict):
                body = {}
            user = body.get("user") or "operator"
            title = body.get("title")
            meta = body.get("meta") or {}
            if not isinstance(meta, dict):
                return JSONResponse(
                    {"error": "meta must be a JSON object"}, status_code=400
                )
            sess = sessions.create_session(user=user, title=title, meta=meta)
            return JSONResponse({"session": sess.to_dict()}, status_code=201)
        finally:
            reset_current_actor(actor_token)

    @mcp.custom_route(
        "/api/v1/sessions/{session_id}",
        methods=["GET"],
        include_in_schema=False,
    )
    async def get_session(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        sess = sessions.get_session(request.path_params["session_id"])
        if sess is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        return JSONResponse({"session": sess.to_dict()})

    @mcp.custom_route(
        "/api/v1/sessions/{session_id}",
        methods=["DELETE"],
        include_in_schema=False,
    )
    async def delete_session(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        actor_token = set_current_actor("user:operator")
        try:
            sid = request.path_params["session_id"]
            ok = sessions.delete_session(sid)
            if not ok:
                return JSONResponse({"error": "not found"}, status_code=404)
            return JSONResponse({"deleted": True, "id": sid})
        finally:
            reset_current_actor(actor_token)

    @mcp.custom_route(
        "/api/v1/sessions/{session_id}",
        methods=["PATCH"],
        include_in_schema=False,
    )
    async def patch_session(request: Request) -> JSONResponse:
        """Rename a session or merge custom metadata.

        Body shape (all fields optional):
          {"title": "string",          # set/clear title
           "metadata": {"k": "v"},     # merged over existing meta
           "replace_metadata": false}  # if true, replaces instead of merging
        """
        if (resp := require_bearer(request)) is not None:
            return resp
        actor_token = set_current_actor("user:operator")
        try:
            sid = request.path_params["session_id"]
            try:
                body = await request.json()
            except Exception:
                return JSONResponse(
                    {"error": "request body must be JSON"}, status_code=400
                )
            if not isinstance(body, dict):
                return JSONResponse(
                    {"error": "request body must be an object"}, status_code=400
                )
            updated = sessions.update_session(
                sid,
                title=body.get("title"),
                meta=body.get("metadata"),
                merge_meta=not bool(body.get("replace_metadata", False)),
            )
            if updated is None:
                return JSONResponse({"error": "not found"}, status_code=404)
            return JSONResponse({"session": updated.to_dict()})
        finally:
            reset_current_actor(actor_token)

    @mcp.custom_route(
        "/api/v1/sessions/{session_id}/fork",
        methods=["POST"],
        include_in_schema=False,
    )
    async def fork_session(request: Request) -> JSONResponse:
        """Fork a new session from an existing
        session's message history.

        Body (all optional):
          {
            "from_message_id": "msg-uuid",  # cut-off; omit for full history
            "title":           "string",     # optional override (default
                                             # parent's title + ' (fork)')
            "user":            "string"      # optional override (default
                                             # parent's user)
          }
        """
        if (resp := require_bearer(request)) is not None:
            return resp
        actor_token = set_current_actor("user:operator")
        try:
            parent_id = request.path_params["session_id"]
            try:
                body = await request.json()
            except Exception:
                body = {}
            if not isinstance(body, dict):
                body = {}
            new_sess = sessions.fork_session(
                from_session_id=parent_id,
                from_message_id=body.get("from_message_id"),
                title=body.get("title"),
                user=body.get("user"),
            )
            if new_sess is None:
                return JSONResponse(
                    {"error": "parent session not found or fork_point invalid"},
                    status_code=404,
                )
            return JSONResponse(
                {"session": new_sess.to_dict()}, status_code=201,
            )
        finally:
            reset_current_actor(actor_token)

    @mcp.custom_route(
        "/api/v1/sessions/{session_id}/export",
        methods=["GET"],
        include_in_schema=False,
    )
    async def export_session(request: Request):
        """Download a session transcript as YAML, JSON, Markdown, or
        a derived wire-event trace.

        Query params:
          format = yaml | json | markdown | events   (default: markdown)

        The `events` format exists because the live telemetry panel shows
        wire events (meta, model, cache_hit, tool_call, tool_result,
        turn_cost, done) while the markdown/json/yaml exports only
        contain persisted message turns. It derives a flat event-list timeline
        from the messages + their meta blobs — same data the panel's
        rehydrate path reconstructs after a session reload — and ships
        it as JSON. No streaming-only events (text_delta, etc.) because
        those aren't persisted; for those, capture from the live SSE
        stream during execution. The events format gives operators a
        forensic record of the run that they can post-process or
        archive separately from the human-readable transcript.
        """
        from starlette.responses import PlainTextResponse

        if (resp := require_bearer(request)) is not None:
            return resp
        sid = request.path_params["session_id"]
        sess = sessions.get_session(sid)
        if sess is None:
            return JSONResponse({"error": "not found"}, status_code=404)

        fmt = (request.query_params.get("format") or "markdown").lower()
        if fmt not in ("yaml", "json", "markdown", "md", "events"):
            return JSONResponse(
                {"error": "format must be yaml | json | markdown | events"},
                status_code=400,
            )

        # Pass limit=None for "load every message in this session".
        # Compaction is the only legitimate context-window manager;
        # export always sees the full transcript.
        msgs = sessions.get_history(sid, limit=None, ascending=True)
        title = sess.title or sid

        if fmt == "events":
            # Derive a wire-event-shaped timeline from messages + meta.
            # Each persisted message produces 1+ events:
            #   - User message     → 1 event: type=user_message
            #   - Assistant text   → 1 event: type=assistant_text + meta
            #     (run_id, model, cache info, finish_reason if present)
            #   - Tool message     → 2 events: tool_call (from meta.tool
            #     + meta.args) and tool_result (the message content)
            # Ordered by ts ascending. Each event has {ts, type, ...}.
            #
            # Merge in audit_log rows for chat_* actions targeting this
            # session. The chat route persists cache_hit, turn_cost,
            # compaction_*, context_warning, plan_proposed and
            # model_preference_changed events to audit_log via the
            # safeAudit helper, so the session-events export is the
            # single source of truth for them.
            #
            # text_delta is intentionally NOT audited (hundreds per
            # turn — would balloon storage); the live panel remains
            # the only place to see per-token deltas.
            import json as _json
            from usecase.audit_log import audit_log as _audit_log_singleton
            events: list[dict] = []
            for m in msgs:
                meta = m.meta if isinstance(m.meta, dict) else {}
                role = m.role
                ts = m.ts
                if role == "user":
                    events.append({
                        "ts": ts,
                        "type": "user_message",
                        "content": m.content or "",
                        "meta": meta,
                    })
                elif role == "tool":
                    # Decompose into tool_call (the invocation) +
                    # tool_result (the response). meta typically has
                    # `tool` and `args`; the message content is the
                    # tool's response payload.
                    tool_name = meta.get("tool") or "unknown"
                    args = meta.get("args") or {}
                    events.append({
                        "ts": ts,
                        "type": "tool_call",
                        "tool": tool_name,
                        "args": args,
                    })
                    events.append({
                        "ts": ts,
                        "type": "tool_result",
                        "tool": tool_name,
                        "result": m.content or "",
                        "status": meta.get("status", "success"),
                        "duration_ms": meta.get("duration_ms"),
                        "error": meta.get("error"),
                    })
                else:
                    # assistant or other — emit as text-bearing event
                    events.append({
                        "ts": ts,
                        "type": f"{role}_text",
                        "content": m.content or "",
                        "meta": meta,
                    })

            # Merge in chat_* audit-log events for this
            # session. Map action name → friendly wire-event type so the
            # operator sees "cache_hit" not "chat_cache_hit" in the
            # export. Each row's metadata is passed through directly so
            # the operator can post-process (e.g. sum cost_usd across
            # all chat_turn_cost rows for a per-session bill).
            audit_singleton = _audit_log_singleton()
            audit_events_count = 0
            if audit_singleton is not None:
                # chat_* audit rows are tagged with target=session:<sid>.
                rows = audit_singleton.query(
                    target=f"session:{sid}",
                    limit=None,
                )
                # Friendly type names matching what the live-telemetry
                # panel renders (see debug-panel.tsx::eventTypeClass).
                ACTION_TO_TYPE = {
                    "chat_turn_cost": "turn_cost",
                    "chat_cache_hit": "cache_hit",
                    "chat_compaction_start": "compaction_start",
                    "chat_compaction_end": "compaction_end",
                    "chat_compaction_failed": "compaction_failed",
                    "chat_context_warning": "context_warning",
                    "chat_plan_proposed": "plan_proposed",
                    "chat_plan_failed": "plan_failed",
                    "chat_subagent_started": "subagent_started",
                    "chat_subagent_completed": "subagent_completed",
                }
                for row in rows:
                    action = row.get("action") or ""
                    if action not in ACTION_TO_TYPE:
                        continue
                    events.append({
                        "ts": row.get("ts"),
                        "type": ACTION_TO_TYPE[action],
                        "status": row.get("status"),
                        "duration_ms": row.get("duration_ms"),
                        "metadata": row.get("metadata") or {},
                        "source": "audit_log",
                    })
                    audit_events_count += 1

            # Re-sort the merged list by ts so message-derived + audit-
            # derived events interleave correctly in the timeline. The
            # original message-derived list was already in order; the
            # audit query returns DESC. Sort handles both inputs.
            events.sort(key=lambda e: (e.get("ts") or ""))

            payload = {
                "session": sess.to_dict(),
                "events": events,
                "event_count": len(events),
                "messages_derived_count": len(events) - audit_events_count,
                "audit_derived_count": audit_events_count,
                "schema_version": 2,
                "exported_at": __import__("datetime").datetime.utcnow().isoformat() + "Z",
                "note": (
                    "Unified events export (schema_version 2). "
                    "Includes both persisted messages (user_message, "
                    "tool_call, tool_result, assistant_text) AND chat_* "
                    "audit-log events (cache_hit, turn_cost, "
                    "compaction_*, context_warning, plan_proposed, "
                    "subagent_*). The only events NOT included are "
                    "per-token text_delta (intentionally — would inflate "
                    "every turn's row count by 100x). For per-token "
                    "stream forensics, use the live-telemetry panel's "
                    "export button during the run."
                ),
            }
            return PlainTextResponse(
                _json.dumps(payload, indent=2),
                media_type="application/json",
            )

        if fmt == "json":
            import json as _json
            payload = {
                "session": sess.to_dict(),
                "messages": [m.to_dict() for m in msgs],
            }
            return PlainTextResponse(
                _json.dumps(payload, indent=2),
                media_type="application/json",
            )
        if fmt == "yaml":
            try:
                import yaml  # type: ignore
                payload = {
                    "session": sess.to_dict(),
                    "messages": [m.to_dict() for m in msgs],
                }
                return PlainTextResponse(
                    yaml.safe_dump(payload, sort_keys=False),
                    media_type="text/yaml",
                )
            except ImportError:
                return JSONResponse(
                    {"error": "PyYAML not installed; use format=json or format=markdown"},
                    status_code=501,
                )

        # Markdown (default).
        lines: list[str] = [
            f"# {title}",
            "",
            f"- Session ID: `{sess.id}`",
            f"- Started: {sess.started_at}",
            f"- Ended: {sess.ended_at or '—'}",
            f"- Messages: {sess.message_count}",
            "",
            "---",
            "",
        ]
        for m in msgs:
            who = m.role.capitalize()
            lines.append(f"## {who} — {m.ts}")
            lines.append("")
            lines.append(m.content or "")
            lines.append("")
            if m.meta and isinstance(m.meta, dict) and m.meta:
                lines.append("```json")
                import json as _json
                lines.append(_json.dumps(m.meta, indent=2))
                lines.append("```")
                lines.append("")
        return PlainTextResponse(
            "\n".join(lines), media_type="text/markdown"
        )

    @mcp.custom_route(
        "/api/v1/sessions/{session_id}/end",
        methods=["POST"],
        include_in_schema=False,
    )
    async def end_session(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        actor_token = set_current_actor("user:operator")
        try:
            sid = request.path_params["session_id"]
            ok = sessions.end_session(sid)
            if not ok:
                return JSONResponse(
                    {"error": "session not found or already ended"},
                    status_code=409,
                )
            return JSONResponse({"ended": True, "id": sid})
        finally:
            reset_current_actor(actor_token)

    @mcp.custom_route(
        "/api/v1/sessions/{session_id}/messages",
        methods=["GET"],
        include_in_schema=False,
    )
    async def get_session_messages(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        sid = request.path_params["session_id"]
        if sessions.get_session(sid) is None:
            return JSONResponse({"error": "session not found"}, status_code=404)
        q = request.query_params
        # When `limit` is omitted, fetch every message. Pagination is
        # opt-in (?limit=N); compaction handles context-window
        # constraints, not this endpoint.
        limit_raw = q.get("limit")
        try:
            limit_arg = int(limit_raw) if limit_raw not in (None, "") else None
        except ValueError:
            limit_arg = None
        msgs = sessions.get_history(
            sid,
            limit=limit_arg,
            offset=_int(q, "offset", 0),
            ascending=_bool(q, "ascending", True),
        )
        return JSONResponse(
            {"session_id": sid, "messages": [m.to_dict() for m in msgs],
             "count": len(msgs)}
        )

    @mcp.custom_route(
        "/api/v1/sessions/{session_id}/messages",
        methods=["POST"],
        include_in_schema=False,
    )
    async def append_message(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        actor_token = set_current_actor("user:operator")
        try:
            sid = request.path_params["session_id"]
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
            role = body.get("role")
            content = body.get("content")
            if not isinstance(role, str) or not isinstance(content, str):
                return JSONResponse(
                    {"error": "'role' and 'content' are required strings"},
                    status_code=400,
                )
            try:
                msg = sessions.append_message(
                    sid,
                    role=role,
                    content=content,
                    tool_call_id=body.get("tool_call_id"),
                    meta=body.get("meta") or {},
                )
            except ValueError as exc:
                return JSONResponse({"error": str(exc)}, status_code=400)

            return JSONResponse({"message": msg.to_dict()}, status_code=201)
        finally:
            reset_current_actor(actor_token)

    # ─── Memories ───────────────────────────────────────────────

    @mcp.custom_route("/api/v1/memories", methods=["GET"], include_in_schema=False)
    async def list_memories(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        q = request.query_params
        scope, scope_prefix = _resolve_scope_filter(
            q.get("scope"), q.get("scope_prefix")
        )
        limit = _int(q, "limit", 100)
        offset = _int(q, "offset", 0)
        rows = memories.list_all(
            scope=scope,
            scope_prefix=scope_prefix,
            limit=limit,
            offset=offset,
        )
        # Was a silent read path — DELETE already audited, list/point-
        # read did not, so "did someone enumerate the memory store?"
        # was unanswerable. Enumeration is worth a record even on a
        # zero-result page (that's still "someone looked").
        from usecase.audit_log import ACTION_MEMORY_LISTED, record_event
        record_event(
            ACTION_MEMORY_LISTED,
            target="memory:_list_",
            status="success",
            metadata={
                "scope": scope,
                "scope_prefix": scope_prefix,
                "limit": limit,
                "offset": offset,
                "count": len(rows),
            },
        )
        return JSONResponse(
            {"memories": [m.to_dict() for m in rows], "count": len(rows)}
        )

    @mcp.custom_route("/api/v1/memories", methods=["POST"], include_in_schema=False)
    async def store_memory(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        actor_token = set_current_actor("user:operator")
        try:
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
            # meta.source is stamped here, server-side, and NOT taken
            # from the caller's body — a REST write only ever comes
            # from the operator (via the UI or a direct API call), and
            # letting the caller set its own source would let a script
            # forge "operator" provenance on what's actually automated
            # agent output. Any other caller-supplied meta keys pass
            # through unchanged.
            meta = dict(body.get("meta") or {})
            meta["source"] = "operator"
            try:
                m = memories.store(
                    key=body.get("key", ""),
                    value=body.get("value", ""),
                    scope=body.get("scope") or "agent",
                    ttl_seconds=body.get("ttl_seconds"),
                    meta=meta,
                )
            except ValueError as exc:
                return JSONResponse({"error": str(exc)}, status_code=400)
            return JSONResponse({"memory": m.to_dict()}, status_code=201)
        finally:
            reset_current_actor(actor_token)

    @mcp.custom_route(
        "/api/v1/memories/search", methods=["POST"], include_in_schema=False
    )
    async def search_memories(request: Request) -> JSONResponse:
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
                {"error": "'query' is required (non-empty string)"}, status_code=400
            )
        scope, scope_prefix = _resolve_scope_filter(
            body.get("scope"), body.get("scope_prefix")
        )
        hits = memories.search(
            query,
            limit=int(body.get("limit") or 5),
            scope=scope,
            scope_prefix=scope_prefix,
            min_score=float(body.get("min_score") or 0.0),
            mode=body.get("mode") or None,
        )
        return JSONResponse(
            {
                "results": [m.to_dict(score=score) for m, score in hits],
                "count": len(hits),
            }
        )

    @mcp.custom_route(
        "/api/v1/memories/by-key/{key}",
        methods=["GET"],
        include_in_schema=False,
    )
    async def get_memory(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        key = request.path_params["key"]
        scope = request.query_params.get("scope") or "agent"
        m = memories.get(key=key, scope=scope)
        from usecase.audit_log import ACTION_MEMORY_READ, record_event
        record_event(
            ACTION_MEMORY_READ,
            target=f"memory:{key}",
            status="success" if m is not None else "not_found",
            metadata={"key": key, "scope": scope},
        )
        if m is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        return JSONResponse({"memory": m.to_dict()})

    @mcp.custom_route(
        "/api/v1/memories/by-key/{key}",
        methods=["DELETE"],
        include_in_schema=False,
    )
    async def delete_memory(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        actor_token = set_current_actor("user:operator")
        try:
            key = request.path_params["key"]
            scope = request.query_params.get("scope") or "agent"
            ok = memories.delete(key=key, scope=scope)
            if not ok:
                return JSONResponse({"error": "not found"}, status_code=404)
            return JSONResponse({"deleted": True, "key": key, "scope": scope})
        finally:
            reset_current_actor(actor_token)

    # ─── Context ────────────────────────────────────────────────

    @mcp.custom_route("/api/v1/context", methods=["POST"], include_in_schema=False)
    async def assemble_context(request: Request) -> JSONResponse:
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
        result = assembler.assemble(
            query=query, session_id=body.get("session_id"),
        )
        return JSONResponse({"context": result.to_dict()})
