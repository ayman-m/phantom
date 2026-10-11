"""SqliteTaskStore — durable task registry for long-running work.

Adapted from SnowAgent's task system
(`snow-agent-complete/snow-agent/09-agents-tasks/`) — Phantom needs
the same shape (status / progress / output / abort) for our
long-running scenario workers.

Why this exists:

  - Phantom's xlog scenario workers live in `xlog/app/schema.py:48`
    as `workers = {}` — a module-level dict. Restart the container,
    lose every active worker. Per-replica state. No abort
    controllers exposed in the chat (operator has to GraphQL
    deleteWorker manually). No progress visibility.
  - Auto-compaction summarizers, Vertex cache creators and
    hook subprocess invocations are all
    candidates for "background work the operator should be able
    to see and cancel."
  - Spark connector tools (XSIAM XQL queries, CALDERA operations)
    can run for minutes. Today they block a chat turn. With a
    task surface, the agent can spawn one as a task, return
    immediately with a task id, and the operator polls /tasks for
    progress.

# Schema

    tasks (
      id              TEXT PRIMARY KEY,    -- uuid
      kind            TEXT NOT NULL,       -- 'scenario_worker' |
                                           -- 'compaction' |
                                           -- 'caldera_op' | etc.
      status          TEXT NOT NULL,       -- 'pending' | 'running' |
                                           -- 'succeeded' | 'failed' |
                                           -- 'aborted'
      title           TEXT NOT NULL,       -- operator-friendly label
      parent_session_id  TEXT,             -- chat session that
                                           -- spawned this task (NULL
                                           -- for cron / system-spawned)
      progress        REAL NOT NULL DEFAULT 0,  -- 0.0 .. 1.0
      progress_label  TEXT,                -- "step 3 of 10:
                                           --  generating IOCs"
      output          TEXT,                -- final result (success
                                           -- payload OR error msg)
      cancel_token    TEXT,                -- opaque token; an aborted
                                           -- task records this and the
                                           -- worker checks it to bail
      meta_json       TEXT NOT NULL DEFAULT '{}',  -- arbitrary kind-
                                                   -- specific data
      created_at      TEXT NOT NULL,
      updated_at      TEXT NOT NULL,
      completed_at    TEXT
    );
    CREATE INDEX idx_tasks_status            ON tasks(status);
    CREATE INDEX idx_tasks_kind              ON tasks(kind);
    CREATE INDEX idx_tasks_parent_session    ON tasks(parent_session_id);
    CREATE INDEX idx_tasks_created_at        ON tasks(created_at);

# Why a column for cancel_token (vs a separate cancel signaling
# mechanism)

The simplest abort path for an in-process worker is "the worker
periodically checks `if store.is_aborted(task_id): break`." That
needs persistent state per task, indexed for fast lookup. Adding
a `cancel_token` column we set on abort gives us the persistent
state. Workers poll `get(id).status == 'aborted'` directly; the
token column is for any future use case where the worker needs to
know WHO requested the abort (audit attribution).

# Lifecycle

    pending  →  running  →  succeeded
                          \\→  failed
                          \\→  aborted (operator pressed Stop)

Pending → running transition is set by the worker when it picks
up the task. Some short-lived tasks skip pending and start in
running. Running → succeeded/failed/aborted is terminal — no
further updates accepted.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger("Phantom MCP")

DEFAULT_DATA_ROOT = Path("/app/data")

VALID_STATUS = {"pending", "running", "succeeded", "failed", "aborted"}
TERMINAL_STATUS = {"succeeded", "failed", "aborted"}


@dataclass
class Task:
    id: str
    kind: str
    status: str
    title: str
    parent_session_id: str | None
    progress: float
    progress_label: str | None
    output: str | None
    cancel_token: str | None
    meta: dict[str, Any]
    created_at: str
    updated_at: str
    completed_at: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "status": self.status,
            "title": self.title,
            "parent_session_id": self.parent_session_id,
            "progress": self.progress,
            "progress_label": self.progress_label,
            "output": self.output,
            "meta": self.meta,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "completed_at": self.completed_at,
        }


class SqliteTaskStore:
    """Persistent task registry. Writes are lock-serialized; reads
    are concurrency-safe via WAL."""

    def __init__(self, data_root: Path | None = None) -> None:
        root = data_root or self._resolve_data_root()
        root.mkdir(parents=True, exist_ok=True)
        self._db_path = root / "tasks.db"
        self._lock = threading.Lock()
        self._init_schema()

    @staticmethod
    def _resolve_data_root() -> Path:
        from os import environ

        return Path(environ.get("PHANTOM_DATA_ROOT", str(DEFAULT_DATA_ROOT)))

    @property
    def db_path(self) -> Path:
        return self._db_path

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self._db_path, isolation_level=None)
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA foreign_keys=ON")
        return c

    def _init_schema(self) -> None:
        with self._lock, self._conn() as c:
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    id                TEXT PRIMARY KEY,
                    kind              TEXT NOT NULL,
                    status            TEXT NOT NULL,
                    title             TEXT NOT NULL,
                    parent_session_id TEXT,
                    progress          REAL NOT NULL DEFAULT 0,
                    progress_label    TEXT,
                    output            TEXT,
                    cancel_token      TEXT,
                    meta_json         TEXT NOT NULL DEFAULT '{}',
                    created_at        TEXT NOT NULL,
                    updated_at        TEXT NOT NULL,
                    completed_at      TEXT
                )
                """
            )
            for index_sql in (
                "CREATE INDEX IF NOT EXISTS idx_tasks_status "
                "ON tasks(status)",
                "CREATE INDEX IF NOT EXISTS idx_tasks_kind "
                "ON tasks(kind)",
                "CREATE INDEX IF NOT EXISTS idx_tasks_parent_session "
                "ON tasks(parent_session_id)",
                "CREATE INDEX IF NOT EXISTS idx_tasks_created_at "
                "ON tasks(created_at)",
            ):
                c.execute(index_sql)

    @staticmethod
    def _now() -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    # ─── Public API ─────────────────────────────────────────────

    def create(
        self,
        *,
        kind: str,
        title: str,
        parent_session_id: str | None = None,
        meta: dict[str, Any] | None = None,
        initial_status: str = "pending",
        task_id: str | None = None,
    ) -> Task:
        """Insert a new task in `pending` state by default.
        Returns the persisted Task. Caller-provided `task_id` is
        accepted (idempotent re-create) but a fresh uuid is minted
        when absent."""
        if initial_status not in ("pending", "running"):
            raise ValueError(
                f"initial_status must be 'pending' or 'running'; "
                f"got {initial_status!r}"
            )
        tid = task_id or str(uuid.uuid4())
        now = self._now()
        meta_json = json.dumps(meta or {})
        with self._lock, self._conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO tasks "
                "(id, kind, status, title, parent_session_id, "
                " progress, progress_label, output, cancel_token, "
                " meta_json, created_at, updated_at, completed_at) "
                "VALUES (?, ?, ?, ?, ?, 0, NULL, NULL, NULL, ?, ?, ?, NULL)",
                (
                    tid, kind, initial_status, title,
                    parent_session_id, meta_json, now, now,
                ),
            )
        return self.get(tid)  # type: ignore[return-value]

    def get(self, task_id: str) -> Task | None:
        with self._conn() as c:
            row = c.execute(
                "SELECT id, kind, status, title, parent_session_id, "
                "progress, progress_label, output, cancel_token, "
                "meta_json, created_at, updated_at, completed_at "
                "FROM tasks WHERE id = ?",
                (task_id,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_task(row)

    def list(
        self,
        *,
        status: str | None = None,
        kind: str | None = None,
        parent_session_id: str | None = None,
        active_only: bool = False,
        limit: int = 200,
        offset: int = 0,
    ) -> list[Task]:
        sql = (
            "SELECT id, kind, status, title, parent_session_id, "
            "progress, progress_label, output, cancel_token, "
            "meta_json, created_at, updated_at, completed_at FROM tasks"
        )
        clauses: list[str] = []
        params: list[Any] = []
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        if kind is not None:
            clauses.append("kind = ?")
            params.append(kind)
        if parent_session_id is not None:
            clauses.append("parent_session_id = ?")
            params.append(parent_session_id)
        if active_only:
            clauses.append("status IN ('pending', 'running')")
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        with self._conn() as c:
            rows = c.execute(sql, params).fetchall()
        return [self._row_to_task(r) for r in rows]

    def update_progress(
        self,
        task_id: str,
        *,
        progress: float | None = None,
        progress_label: str | None = None,
        meta_patch: dict[str, Any] | None = None,
    ) -> Task | None:
        """Update progress and optional metadata. Status unchanged.
        Useful for streaming progress without changing lifecycle.
        Rejects updates on terminal-status tasks."""
        existing = self.get(task_id)
        if existing is None:
            return None
        if existing.status in TERMINAL_STATUS:
            return existing  # silent no-op
        new_progress = (
            existing.progress if progress is None
            else max(0.0, min(1.0, progress))
        )
        new_label = (
            progress_label if progress_label is not None
            else existing.progress_label
        )
        new_meta = existing.meta
        if meta_patch:
            new_meta = {**existing.meta, **meta_patch}
        now = self._now()
        with self._lock, self._conn() as c:
            c.execute(
                "UPDATE tasks SET progress = ?, progress_label = ?, "
                "meta_json = ?, updated_at = ? WHERE id = ?",
                (
                    new_progress, new_label,
                    json.dumps(new_meta), now, task_id,
                ),
            )
        return self.get(task_id)

    def transition(
        self,
        task_id: str,
        *,
        new_status: str,
        output: str | None = None,
        cancel_token: str | None = None,
    ) -> Task | None:
        """Change lifecycle status. Validates transitions:
            pending  → running, aborted
            running  → succeeded, failed, aborted
            terminal → no transitions
        Sets completed_at on terminal transitions."""
        if new_status not in VALID_STATUS:
            raise ValueError(
                f"new_status must be one of {VALID_STATUS}; "
                f"got {new_status!r}"
            )
        existing = self.get(task_id)
        if existing is None:
            return None
        cur = existing.status
        if cur in TERMINAL_STATUS:
            return existing
        if cur == "pending" and new_status not in (
            "running", "aborted", "failed"
        ):
            raise ValueError(
                f"invalid transition pending → {new_status}"
            )
        if cur == "running" and new_status not in (
            "succeeded", "failed", "aborted"
        ):
            raise ValueError(
                f"invalid transition running → {new_status}"
            )
        now = self._now()
        completed = now if new_status in TERMINAL_STATUS else None
        # Final progress on succeeded → 1.0; on failed/aborted leave
        # at last reported value (helps the UI show "we got 60%
        # through before the abort").
        new_progress = (
            1.0 if new_status == "succeeded" else existing.progress
        )
        with self._lock, self._conn() as c:
            c.execute(
                "UPDATE tasks SET status = ?, output = ?, "
                "cancel_token = COALESCE(?, cancel_token), "
                "progress = ?, updated_at = ?, completed_at = ? "
                "WHERE id = ?",
                (
                    new_status, output, cancel_token,
                    new_progress, now, completed, task_id,
                ),
            )
        return self.get(task_id)

    def abort(
        self,
        task_id: str,
        *,
        cancel_token: str | None = None,
        reason: str | None = None,
    ) -> Task | None:
        """Mark a task aborted. The worker thread is expected to
        poll status periodically and bail when it sees `aborted`.
        Idempotent on terminal-status tasks (returns existing)."""
        existing = self.get(task_id)
        if existing is None:
            return None
        if existing.status in TERMINAL_STATUS:
            return existing
        return self.transition(
            task_id,
            new_status="aborted",
            output=reason,
            cancel_token=cancel_token,
        )

    def is_aborted(self, task_id: str) -> bool:
        """Cheap check used by worker bodies to know "should I
        stop?" between progress steps. No allocation; index lookup
        on (id, status)."""
        with self._conn() as c:
            row = c.execute(
                "SELECT status FROM tasks WHERE id = ?", (task_id,),
            ).fetchone()
        if row is None:
            return False
        return row[0] == "aborted"

    @staticmethod
    def _row_to_task(row: tuple[Any, ...]) -> Task:
        (
            id_, kind, status, title, parent_session_id,
            progress, progress_label, output, cancel_token,
            meta_json, created_at, updated_at, completed_at,
        ) = row
        try:
            meta = json.loads(meta_json) if meta_json else {}
        except json.JSONDecodeError:
            meta = {}
        return Task(
            id=id_,
            kind=kind,
            status=status,
            title=title,
            parent_session_id=parent_session_id,
            progress=float(progress or 0),
            progress_label=progress_label,
            output=output,
            cancel_token=cancel_token,
            meta=meta,
            created_at=created_at,
            updated_at=updated_at,
            completed_at=completed_at,
        )


_global_store: SqliteTaskStore | None = None


def set_task_store(store: SqliteTaskStore) -> None:
    """Stash the singleton so other modules (xlog adapter, hook
    runner) can read/write tasks without dependency injection."""
    global _global_store
    _global_store = store


def get_task_store() -> SqliteTaskStore | None:
    return _global_store
