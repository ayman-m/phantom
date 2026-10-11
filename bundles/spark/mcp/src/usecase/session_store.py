"""SqliteSessionStore — bundle-local implementation of the spec's
`sessions` capability (spec.md §6.10 row "sessions").

Per spec §6.10, `sessions` has two backend impls:

  - **Standalone**: `SqliteSessionStore` — local sqlite at
                    `<data_root>/sessions.db`.
  - **Platform**:   `PostgresSessionStore` — shared per-tenant
                    Postgres table the platform's UI multiplexes over.

This module is the standalone variant. It models a session as an
ordered conversation: a header row in `sessions(...)` plus an append-
only stream of `messages(...)` keyed by session_id. The retention
policy is enforced at boot via `prune_older_than(days)`.

# Why two tables, not one JSON-blob field

Two tables let the API answer "give me the last 50 messages of session
X" without deserializing the full conversation, which can be large.
The agent's UI typically renders in pages of 20-50 messages; a JSON
blob would force loading the entire history just to show the latest
page. Per-message rows also let `audit_log` reference a specific
message_id when something noteworthy happens mid-conversation.

# Schema

    sessions(
      id           TEXT PRIMARY KEY,    -- uuid4
      user         TEXT NOT NULL,        -- "operator" today; multi-user later
      started_at   TEXT NOT NULL,        -- ISO8601 UTC
      ended_at     TEXT,                 -- nullable; set on explicit close
      title        TEXT,                 -- optional human label
      meta_json    TEXT NOT NULL          -- arbitrary key/value (model used,
                                          -- skill invoked, etc.)
    );
    messages(
      id           TEXT PRIMARY KEY,    -- uuid4
      session_id   TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
      ts           TEXT NOT NULL,        -- ISO8601 UTC, microsecond precision
      role         TEXT NOT NULL,        -- user|assistant|tool|system
      content      TEXT NOT NULL,        -- raw text or JSON-stringified payload
      tool_call_id TEXT,                 -- nullable; for role=tool
      meta_json    TEXT NOT NULL          -- arbitrary; e.g. token counts
    );
    CREATE INDEX idx_messages_session_id ON messages(session_id, ts);
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger("Phantom MCP")

DEFAULT_DATA_ROOT = Path("/app/data")

# Allowed values for `messages.role`. We keep an allowlist so a bad
# caller can't muddy the conversation with arbitrary roles the agent
# wouldn't know how to render.
_ROLES = {"user", "assistant", "tool", "system"}


@dataclass(frozen=True)
class Session:
    id: str
    user: str
    started_at: str
    ended_at: str | None
    title: str | None
    meta: dict[str, Any]
    message_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "user": self.user,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "title": self.title,
            "meta": self.meta,
            "message_count": self.message_count,
        }


@dataclass(frozen=True)
class Message:
    id: str
    session_id: str
    ts: str
    role: str
    content: str
    tool_call_id: str | None
    meta: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "ts": self.ts,
            "role": self.role,
            "content": self.content,
            "tool_call_id": self.tool_call_id,
            "meta": self.meta,
        }


class SqliteSessionStore:
    """Sqlite-backed session + message store at ``<data_root>/sessions.db``.

    Thread-safe via a single lock plus per-call connections (matches the
    pattern set by InstanceStore + ApprovalsBus). Lock discipline:
    methods that need to call `self.get_*` after a write release the
    lock first, so the read takes its own lock without deadlocking
    (see `approvals_bus.py:resolve` for the same pattern).
    """

    def __init__(
        self,
        data_root: Path | None = None,
        retention_days: int | None = None,
    ) -> None:
        self._data_root = (data_root or self._resolve_data_root()).resolve()
        self._data_root.mkdir(parents=True, exist_ok=True)
        self._db_path = self._data_root / "sessions.db"
        self._lock = threading.Lock()
        self._retention_days = retention_days
        self._init_schema()
        if retention_days:
            n = self.prune_older_than(retention_days)
            if n:
                logger.info(
                    "SessionStore: pruned %d session(s) older than %d days at boot",
                    n, retention_days,
                )
        logger.info("SqliteSessionStore at %s", self._db_path)

    @staticmethod
    def _resolve_data_root() -> Path:
        raw = os.getenv("DATA_ROOT", str(DEFAULT_DATA_ROOT))
        return Path(raw)

    @property
    def db_path(self) -> Path:
        return self._db_path

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self._db_path, isolation_level=None, check_same_thread=False)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys = ON")
        return c

    def _init_schema(self) -> None:
        with self._lock, self._conn() as c:
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id           TEXT PRIMARY KEY,
                    user         TEXT NOT NULL,
                    started_at   TEXT NOT NULL,
                    ended_at     TEXT,
                    title        TEXT,
                    meta_json    TEXT NOT NULL
                )
                """
            )
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id           TEXT PRIMARY KEY,
                    session_id   TEXT NOT NULL,
                    ts           TEXT NOT NULL,
                    role         TEXT NOT NULL,
                    content      TEXT NOT NULL,
                    tool_call_id TEXT,
                    meta_json    TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions(id)
                        ON DELETE CASCADE
                )
                """
            )
            c.execute(
                "CREATE INDEX IF NOT EXISTS idx_messages_session_ts "
                "ON messages(session_id, ts)"
            )
            c.execute(
                "CREATE INDEX IF NOT EXISTS idx_sessions_user_started "
                "ON sessions(user, started_at)"
            )
            # Expression-based index on the scheduled_by
            # JSON pointer that the chat sidebar's `exclude_scheduled`
            # filter (list_sessions) uses. Without this, the WHERE
            # clause forces a SCAN on the sessions table — fine at low
            # row counts, painful at high ones (daily growth is dominated
            # by scheduled jobs). The expression index
            # lets the optimizer use a range scan that touches only
            # rows where `scheduled_by IS NULL`. SQLite supports
            # expression indexes since 3.9.
            c.execute(
                "CREATE INDEX IF NOT EXISTS idx_sessions_scheduled_by "
                "ON sessions(json_extract(meta_json, '$.scheduled_by'))"
            )
            # Session forking columns. parent_id
            # points at the session this one was forked from;
            # fork_point_message_id names the message we branched at.
            # Both nullable + additive — non-fork sessions stay NULL.
            cols = {r["name"] for r in c.execute("PRAGMA table_info(sessions)").fetchall()}
            if "parent_id" not in cols:
                c.execute("ALTER TABLE sessions ADD COLUMN parent_id TEXT")
            if "fork_point_message_id" not in cols:
                c.execute(
                    "ALTER TABLE sessions ADD COLUMN fork_point_message_id TEXT"
                )

    @staticmethod
    def _now_iso(usec: bool = True) -> str:
        if usec:
            return time.strftime("%Y-%m-%dT%H:%M:%S.", time.gmtime()) + (
                f"{int((time.time() % 1) * 1_000_000):06d}Z"
            )
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    # ─── Session lifecycle ─────────────────────────────────────

    def create_session(
        self,
        *,
        user: str = "operator",
        title: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> Session:
        sid = str(uuid.uuid4())
        started = self._now_iso(usec=False)
        meta_dict = dict(meta or {})
        with self._lock, self._conn() as c:
            c.execute(
                "INSERT INTO sessions (id, user, started_at, title, meta_json) "
                "VALUES (?, ?, ?, ?, ?)",
                (sid, user, started, title, json.dumps(meta_dict)),
            )
        logger.info("SessionStore.create_session id=%s user=%s", sid, user)
        from usecase.audit_log import ACTION_SESSION_CREATED, record_event
        record_event(
            ACTION_SESSION_CREATED,
            target=f"session:{sid}",
            status="success",
            metadata={"session_id": sid, "user": user, "title": title},
        )
        return Session(
            id=sid, user=user, started_at=started, ended_at=None,
            title=title, meta=meta_dict, message_count=0,
        )

    def fork_session(
        self,
        *,
        from_session_id: str,
        from_message_id: str | None = None,
        title: str | None = None,
        user: str | None = None,
    ) -> "Session | None":
        """Fork a new session from an existing
        one's message history. Copies messages up-to-and-including
        `from_message_id` (or all messages when None — "fork the full
        conversation"). The new session stores parent_id + fork_point
        so the tree relationship is recoverable.

        Memory scope boundary: the new session's session-scoped memory
        starts empty — we do NOT copy `session:<parent_id>`-scoped
        memories into `session:<new_id>`. The whole point of forking
        is hypothetical exploration; bleeding parent state defeats
        that intent.

        Returns the new Session or None when from_session_id doesn't
        exist (or from_message_id doesn't belong to it).
        """
        parent = self.get_session(from_session_id)
        if parent is None:
            return None

        new_sid = str(uuid.uuid4())
        started = self._now_iso(usec=False)
        new_user = user or parent.user
        new_title = title or (
            f"{parent.title} (fork)" if parent.title else None
        )

        with self._lock, self._conn() as c:
            # Validate from_message_id when supplied — must belong to
            # the parent. Returns None on mismatch to surface the bug
            # rather than silently fork the wrong slice.
            if from_message_id is not None:
                row = c.execute(
                    "SELECT id FROM messages WHERE id = ? AND session_id = ?",
                    (from_message_id, from_session_id),
                ).fetchone()
                if row is None:
                    return None

            # Insert the new session record. Copy parent's meta but
            # tag with the fork relationship.
            meta = dict(parent.meta or {})
            meta["forked_from"] = from_session_id
            if from_message_id:
                meta["fork_point_message_id"] = from_message_id
            c.execute(
                "INSERT INTO sessions (id, user, started_at, title, meta_json, "
                "parent_id, fork_point_message_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    new_sid, new_user, started, new_title,
                    json.dumps(meta),
                    from_session_id, from_message_id,
                ),
            )

            # Copy messages up-to-and-including the fork point. When
            # from_message_id is None, copy all messages (full
            # conversation fork). Otherwise we use the fork message's
            # ts as the cutoff (≤) since messages are timestamp-
            # ordered within a session.
            if from_message_id is not None:
                fork_ts = c.execute(
                    "SELECT ts FROM messages WHERE id = ?",
                    (from_message_id,),
                ).fetchone()["ts"]
                source_rows = c.execute(
                    "SELECT id, ts, role, content, tool_call_id, meta_json "
                    "FROM messages WHERE session_id = ? AND ts <= ? "
                    "ORDER BY ts ASC",
                    (from_session_id, fork_ts),
                ).fetchall()
            else:
                source_rows = c.execute(
                    "SELECT id, ts, role, content, tool_call_id, meta_json "
                    "FROM messages WHERE session_id = ? "
                    "ORDER BY ts ASC",
                    (from_session_id,),
                ).fetchall()

            # Each copied message gets a fresh id but preserves the
            # original ts so the fork's history reads chronologically
            # the same way the parent's did.
            for r in source_rows:
                new_msg_id = str(uuid.uuid4())
                c.execute(
                    "INSERT INTO messages (id, session_id, ts, role, "
                    "content, tool_call_id, meta_json) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        new_msg_id, new_sid, r["ts"], r["role"],
                        r["content"], r["tool_call_id"], r["meta_json"],
                    ),
                )

        from usecase.audit_log import record_event
        record_event(
            "session_forked",
            target=f"session:{new_sid}",
            status="success",
            metadata={
                "session_id": new_sid,
                "parent_id": from_session_id,
                "fork_point_message_id": from_message_id,
                "messages_copied": len(source_rows),
            },
        )

        result = self.get_session(new_sid)
        if result is None:
            raise RuntimeError(f"fork_session: row {new_sid} vanished after insert")
        return result

    def end_session(self, session_id: str) -> bool:
        ended = self._now_iso(usec=False)
        with self._lock, self._conn() as c:
            cur = c.execute(
                "UPDATE sessions SET ended_at = ? "
                "WHERE id = ? AND ended_at IS NULL",
                (ended, session_id),
            )
        if cur.rowcount > 0:
            logger.info("SessionStore.end_session id=%s", session_id)
            from usecase.audit_log import ACTION_SESSION_ENDED, record_event
            record_event(
                ACTION_SESSION_ENDED,
                target=f"session:{session_id}",
                status="success",
                metadata={"session_id": session_id},
            )
            return True
        return False

    def delete_session(self, session_id: str) -> bool:
        with self._lock, self._conn() as c:
            cur = c.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        if cur.rowcount > 0:
            logger.info("SessionStore.delete_session id=%s", session_id)
            from usecase.audit_log import ACTION_SESSION_DELETED, record_event
            record_event(
                ACTION_SESSION_DELETED,
                target=f"session:{session_id}",
                status="success",
                metadata={"session_id": session_id},
            )
            return True
        return False

    # ─── Message append ────────────────────────────────────────

    def append_message(
        self,
        session_id: str,
        *,
        role: str,
        content: str,
        tool_call_id: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> Message:
        if role not in _ROLES:
            raise ValueError(
                f"role must be one of {sorted(_ROLES)} (got {role!r})"
            )
        if not isinstance(content, str):
            raise ValueError("content must be a string")
        mid = str(uuid.uuid4())
        ts = self._now_iso(usec=True)
        meta_dict = dict(meta or {})
        with self._lock, self._conn() as c:
            row = c.execute(
                "SELECT 1 FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
            if row is None:
                raise ValueError(f"session {session_id!r} does not exist")
            c.execute(
                "INSERT INTO messages "
                "(id, session_id, ts, role, content, tool_call_id, meta_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (mid, session_id, ts, role, content, tool_call_id,
                 json.dumps(meta_dict)),
            )
        # Audit per message — the granularity SOC needs to reconstruct
        # an agent's reasoning chain. role+content_chars (not full
        # content) keeps the audit row small.
        from usecase.audit_log import ACTION_MESSAGE_APPENDED, record_event
        record_event(
            ACTION_MESSAGE_APPENDED,
            target=f"message:{mid}",
            status="success",
            metadata={
                "session_id": session_id,
                "message_id": mid,
                "role": role,
                "content_chars": len(content),
                "tool_call_id": tool_call_id,
            },
        )
        return Message(
            id=mid, session_id=session_id, ts=ts, role=role,
            content=content, tool_call_id=tool_call_id, meta=meta_dict,
        )

    # ─── Update API ────────────────────────────────────────────

    def update_session(
        self,
        session_id: str,
        *,
        title: str | None = None,
        meta: dict[str, Any] | None = None,
        merge_meta: bool = True,
    ) -> Session | None:
        """Patch a session's mutable metadata. Returns the updated row
        or None if the session doesn't exist.

        - `title=None` leaves the title unchanged; pass an empty string
          to clear it explicitly.
        - `meta` is merged over the existing meta when `merge_meta`
          is True (default); replaces it entirely when False.
        """
        with self._lock, self._conn() as c:
            row = c.execute(
                "SELECT * FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
            if row is None:
                return None
            existing_meta: dict[str, Any] = json.loads(row["meta_json"] or "{}")
            new_meta = (
                {**existing_meta, **meta} if (meta is not None and merge_meta)
                else (meta if meta is not None else existing_meta)
            )
            new_title = row["title"] if title is None else title
            c.execute(
                "UPDATE sessions SET title = ?, meta_json = ? WHERE id = ?",
                (new_title or None, json.dumps(new_meta), session_id),
            )
        return self.get_session(session_id)

    # ─── Read API ──────────────────────────────────────────────

    def get_session(self, session_id: str) -> Session | None:
        with self._lock, self._conn() as c:
            row = c.execute(
                "SELECT s.*, "
                "  (SELECT COUNT(*) FROM messages m WHERE m.session_id = s.id) AS n "
                "FROM sessions s WHERE s.id = ?",
                (session_id,),
            ).fetchone()
        return self._row_to_session(row) if row else None

    def list_sessions(
        self,
        *,
        user: str | None = None,
        limit: int | None = None,
        offset: int = 0,
        active_only: bool = False,
        exclude_scheduled: bool = False,
    ) -> list[Session]:
        """List sessions with optional filters.

        `exclude_scheduled=True` filters out sessions that
        carry `meta.scheduled_by=<job-name>` — i.e. sessions started
        by the recurring-job dispatcher rather than by an operator
        chatting in the UI. The chat sidebar uses this filter so
        operator-driven conversations don't drown under hundreds of
        scheduled-job sessions on busy installs (without server-side
        filtering, a default-size window can be 100% scheduled and
        the sidebar shows empty after a client-side filter drops
        them all).

        The filter is implemented via SQLite's json_extract on the
        `meta_json` column. SQLite ships JSON1 by default in every
        distribution Python's stdlib sqlite3 module bundles (since
        SQLite 3.38 / Python 3.10), so no feature flag or
        compile-time check is needed.
        """
        clauses, params = [], []
        if user:
            clauses.append("user = ?")
            params.append(user)
        if active_only:
            clauses.append("ended_at IS NULL")
        if exclude_scheduled:
            # `meta_json` is NOT NULL by schema, but defensive against
            # historic rows where it might be the literal string "{}":
            # `json_extract` on a missing key returns NULL, which is
            # what we want.
            clauses.append("json_extract(meta_json, '$.scheduled_by') IS NULL")
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        # No default cap. `limit=None` (the default) returns
        # everything. SQLite's LIMIT -1 means unlimited. Pagination via
        # explicit `limit=N`.
        eff_limit = -1 if (limit is None or limit <= 0) else int(limit)
        params.extend([eff_limit, max(0, offset)])
        with self._lock, self._conn() as c:
            rows = c.execute(
                "SELECT s.*, "
                "  (SELECT COUNT(*) FROM messages m WHERE m.session_id = s.id) AS n "
                f"FROM sessions s {where} "
                "ORDER BY s.started_at DESC LIMIT ? OFFSET ?",
                params,
            ).fetchall()
        return [self._row_to_session(r) for r in rows]

    def get_history(
        self,
        session_id: str,
        *,
        limit: int | None = None,
        offset: int = 0,
        ascending: bool = True,
    ) -> list[Message]:
        """Return all messages in a session by default.

        Limits are an explicit pagination opt-in, NOT a default
        ceiling. Chat transcripts must load completely so the operator
        sees every bubble; the only legitimate context-window
        constraint is `lib/compaction.ts` (it summarizes old turns into
        a checkpoint row but doesn't drop them from storage).

        A default cap would mismatch the export endpoint
        (`limit=10_000`) and the telemetry rehydrate (`?limit=500`)
        and silently truncate any session crossing the threshold.

        Pass `limit=N` (N > 0) for explicit pagination; omit or pass
        None for no limit. SQLite's `LIMIT -1` means unlimited.
        """
        order = "ASC" if ascending else "DESC"
        eff_limit = -1 if (limit is None or limit <= 0) else int(limit)
        with self._lock, self._conn() as c:
            rows = c.execute(
                f"SELECT * FROM messages WHERE session_id = ? "
                f"ORDER BY ts {order} LIMIT ? OFFSET ?",
                (session_id, eff_limit, max(0, offset)),
            ).fetchall()
        return [self._row_to_message(r) for r in rows]

    def get_recent_messages(
        self, session_id: str, limit: int = 20
    ) -> list[Message]:
        """Return the last N messages in chronological (ascending) order.

        Used by ContextAssembler to seed the LLM prompt with the most
        recent slice of the conversation.
        """
        # Fetch in DESC, reverse — saves a SQL ORDER BY twist.
        with self._lock, self._conn() as c:
            rows = c.execute(
                "SELECT * FROM messages WHERE session_id = ? "
                "ORDER BY ts DESC LIMIT ?",
                (session_id, max(1, min(limit, 1000))),
            ).fetchall()
        msgs = [self._row_to_message(r) for r in rows]
        return list(reversed(msgs))

    # ─── Retention reaper ──────────────────────────────────────

    def prune_older_than(self, days: int) -> int:
        """Delete sessions (and CASCADE their messages) older than `days`.

        Sessions are aged by their `started_at`. Active (ended_at IS
        NULL) sessions are spared regardless of age — operators may
        leave a session open for weeks; we only prune dead history.
        """
        if days <= 0:
            return 0
        cutoff_epoch = time.time() - days * 86400
        cutoff_iso = time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime(cutoff_epoch)
        )
        with self._lock, self._conn() as c:
            cur = c.execute(
                "DELETE FROM sessions "
                "WHERE started_at < ? AND ended_at IS NOT NULL",
                (cutoff_iso,),
            )
        return cur.rowcount

    # ─── Row mappers ───────────────────────────────────────────

    @staticmethod
    def _row_to_session(row: sqlite3.Row) -> Session:
        # `n` is present on join queries; default to 0 otherwise.
        try:
            count = int(row["n"])
        except (KeyError, IndexError):
            count = 0
        return Session(
            id=row["id"],
            user=row["user"],
            started_at=row["started_at"],
            ended_at=row["ended_at"],
            title=row["title"],
            meta=json.loads(row["meta_json"]),
            message_count=count,
        )

    @staticmethod
    def _row_to_message(row: sqlite3.Row) -> Message:
        return Message(
            id=row["id"],
            session_id=row["session_id"],
            ts=row["ts"],
            role=row["role"],
            content=row["content"],
            tool_call_id=row["tool_call_id"],
            meta=json.loads(row["meta_json"]),
        )


# ─────────────────────────────────────────────────────────────────
# Module-level singleton accessor — wired by main.py
# ─────────────────────────────────────────────────────────────────

_session_store: SqliteSessionStore | None = None


def set_session_store(store: SqliteSessionStore | None) -> None:
    """Wire the process-wide session store. Called once from main.py."""
    global _session_store
    _session_store = store


def session_store() -> SqliteSessionStore | None:
    """Return the active store (or None when not yet wired).

    Built-in cognitive tools (sessions_list, sessions_history, and
    soon the context assembler) prefer this over taking an explicit
    dependency since they're registered before `main.py` finishes
    wiring.
    """
    return _session_store
