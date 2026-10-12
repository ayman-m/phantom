"""SqliteNotificationStore + NotificationDispatcher — bundle-local
implementation of the spec's `notifications` capability.

The bundle declares topics in manifest.notifications.topics[]:

    - { name: "setup-required",       severity: "warning",  target: "user:operator" }
    - { name: "simulation-complete",  severity: "info",     target: "user:operator" }
    - { name: "detection-miss",       severity: "warning",  target: "channel:soc" }
    - { name: "caldera-operation",    severity: "critical", target: "channel:purple-team" }

This module wires those declarations to runtime behavior:

  * `publish(topic, payload, ...)` looks up the topic in the manifest,
    stamps the severity + target, persists a row, and (optionally)
    fans out to an external channel webhook for `channel:*` targets.
    If the topic isn't declared in the manifest, publish() rejects —
    spec compliance: only declared topics are emittable.

  * The agent UI's notification surface calls
    `pending(target="user:operator")` to render badge counts +
    inbox; `ack(id)` to mark read.

# Why one store, not separate per-target tables

Topics share a 95% schema (id, severity, target, payload, timestamps).
A single table keeps the audit-friendly story simple: every dispatched
notification leaves a forensic trail regardless of target shape. Future
external-channel work (Slack, PagerDuty, SOAR webhooks) attaches via
the optional `dispatch_webhook` callback; the store stays the source
of truth.

# Schema

    notifications(
      id            TEXT PRIMARY KEY,    -- uuid4
      topic         TEXT NOT NULL,        -- manifest topic.name
      severity      TEXT NOT NULL,        -- "info" | "warning" | "critical"
      target        TEXT NOT NULL,        -- e.g. "user:operator", "channel:soc"
      payload_json  TEXT NOT NULL,        -- arbitrary application payload
      created_at    TEXT NOT NULL,        -- ISO8601 UTC
      read_at       TEXT,                 -- nullable; set on ack()
      dispatch_status TEXT NOT NULL,      -- "stored" | "dispatched" | "failed"
      dispatch_error  TEXT                -- nullable; failure detail
    );
    CREATE INDEX idx_notifications_target_unread
      ON notifications(target, created_at) WHERE read_at IS NULL;
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

logger = logging.getLogger("Phantom MCP")

DEFAULT_DATA_ROOT = Path("/app/data")

VALID_SEVERITIES = {"info", "warning", "critical"}


@dataclass(frozen=True)
class TopicSpec:
    """One row from manifest.notifications.topics."""

    name: str
    severity: str
    target: str

    @classmethod
    def from_manifest(cls, raw: dict[str, Any]) -> "TopicSpec":
        name = str(raw.get("name") or "").strip()
        severity = str(raw.get("severity") or "info").strip()
        target = str(raw.get("target") or "").strip()
        if not name:
            raise ValueError("manifest topic missing 'name'")
        if severity not in VALID_SEVERITIES:
            raise ValueError(
                f"manifest topic '{name}' has invalid severity '{severity}'; "
                f"expected one of {sorted(VALID_SEVERITIES)}"
            )
        if not target:
            raise ValueError(f"manifest topic '{name}' missing 'target'")
        return cls(name=name, severity=severity, target=target)


@dataclass(frozen=True)
class Notification:
    id: str
    topic: str
    severity: str
    target: str
    payload: dict[str, Any]
    created_at: str
    read_at: str | None
    dispatch_status: str
    dispatch_error: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "topic": self.topic,
            "severity": self.severity,
            "target": self.target,
            "payload": self.payload,
            "created_at": self.created_at,
            "read_at": self.read_at,
            "dispatch_status": self.dispatch_status,
            "dispatch_error": self.dispatch_error,
        }


# Optional channel-dispatch hook signature. Implementations can post
# to Slack, PagerDuty, etc. Failures are caught and recorded as
# dispatch_status=failed; the store row still persists.
DispatchHook = Callable[[Notification], None]


class SqliteNotificationStore:
    """Sqlite-backed notification store at ``<data_root>/notifications.db``."""

    def __init__(
        self,
        topics: Iterable[TopicSpec] = (),
        data_root: Path | None = None,
        audit_log: Any | None = None,
        dispatch_hook: DispatchHook | None = None,
    ) -> None:
        self._topics: dict[str, TopicSpec] = {t.name: t for t in topics}
        self._data_root = (data_root or self._resolve_data_root()).resolve()
        self._data_root.mkdir(parents=True, exist_ok=True)
        self._db_path = self._data_root / "notifications.db"
        self._lock = threading.Lock()
        self._audit = audit_log
        self._dispatch_hook = dispatch_hook
        self._init_schema()

    @staticmethod
    def _resolve_data_root() -> Path:
        env = os.getenv("DATA_ROOT")
        if env:
            return Path(env)
        return DEFAULT_DATA_ROOT

    def _init_schema(self) -> None:
        with self._lock, sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS notifications (
                    id              TEXT PRIMARY KEY,
                    topic           TEXT NOT NULL,
                    severity        TEXT NOT NULL,
                    target          TEXT NOT NULL,
                    payload_json    TEXT NOT NULL,
                    created_at      TEXT NOT NULL,
                    read_at         TEXT,
                    dispatch_status TEXT NOT NULL,
                    dispatch_error  TEXT
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_notifications_target_unread "
                "ON notifications(target, created_at) "
                "WHERE read_at IS NULL"
            )

    # ─────────────────────────────────────────────────────────────
    # Publish path
    # ─────────────────────────────────────────────────────────────

    def topics(self) -> list[TopicSpec]:
        return sorted(self._topics.values(), key=lambda t: t.name)

    def publish(
        self,
        topic: str,
        payload: dict[str, Any] | None = None,
        actor: str | None = None,
    ) -> Notification:
        """Emit one notification. Topic must be declared in the manifest."""
        spec = self._topics.get(topic)
        if spec is None:
            raise ValueError(
                f"topic '{topic}' is not declared in manifest.notifications.topics. "
                f"Known topics: {sorted(self._topics)}"
            )
        nid = str(uuid.uuid4())
        ts = self._utc_now()
        body = payload or {}
        notif = Notification(
            id=nid, topic=spec.name, severity=spec.severity,
            target=spec.target, payload=body, created_at=ts,
            read_at=None, dispatch_status="stored", dispatch_error=None,
        )

        # Try the optional channel-dispatch hook FIRST (for channel:*
        # targets). Failures get folded into the persisted row so the
        # operator can see what failed where.
        status = "stored"
        error: str | None = None
        if self._dispatch_hook is not None and spec.target.startswith("channel:"):
            try:
                self._dispatch_hook(notif)
                status = "dispatched"
            except Exception as exc:  # noqa: BLE001
                status = "failed"
                error = f"{type(exc).__name__}: {exc}"
                logger.warning(
                    "Notification dispatch failed for topic=%s target=%s: %s",
                    spec.name, spec.target, error,
                )

        with self._lock, sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO notifications (
                    id, topic, severity, target, payload_json, created_at,
                    read_at, dispatch_status, dispatch_error
                ) VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?)
                """,
                (nid, spec.name, spec.severity, spec.target,
                 json.dumps(body), ts, status, error),
            )
        # Audit hook (best-effort; never blocks publish).
        self._audit_event(
            "notification_published", actor=actor, target=f"notification:{nid}",
            metadata={
                "topic": spec.name, "severity": spec.severity,
                "channel_target": spec.target, "dispatch_status": status,
            },
        )
        return Notification(
            id=nid, topic=spec.name, severity=spec.severity,
            target=spec.target, payload=body, created_at=ts,
            read_at=None, dispatch_status=status, dispatch_error=error,
        )

    # ─────────────────────────────────────────────────────────────
    # Read paths
    # ─────────────────────────────────────────────────────────────

    @staticmethod
    def _where(
        target: str | None, unread_only: bool, since: str | None
    ) -> tuple[str, list[Any]]:
        clauses: list[str] = []
        args: list[Any] = []
        if target:
            clauses.append("target = ?")
            args.append(target)
        if unread_only:
            clauses.append("read_at IS NULL")
        if since:
            # created_at is an ISO-8601 UTC string, so a string compare is a
            # time compare as long as `since` is in the same format.
            clauses.append("created_at >= ?")
            args.append(since)
        return (("WHERE " + " AND ".join(clauses)) if clauses else ""), args

    def list(
        self,
        target: str | None = None,
        unread_only: bool = False,
        limit: int = 100,
        offset: int = 0,
        since: str | None = None,
    ) -> list[Notification]:
        """Newest first. `offset` pages through the same ordering; `since`
        keeps only rows created at or after that ISO-8601 UTC timestamp."""
        where, args = self._where(target, unread_only, since)
        args = [*args, int(limit), max(0, int(offset))]
        with self._lock, sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                f"""
                SELECT id, topic, severity, target, payload_json, created_at,
                       read_at, dispatch_status, dispatch_error
                FROM notifications
                {where}
                ORDER BY created_at DESC, id DESC
                LIMIT ? OFFSET ?
                """,
                args,
            ).fetchall()
        return [
            Notification(
                id=r["id"], topic=r["topic"], severity=r["severity"],
                target=r["target"], payload=json.loads(r["payload_json"]),
                created_at=r["created_at"], read_at=r["read_at"],
                dispatch_status=r["dispatch_status"],
                dispatch_error=r["dispatch_error"],
            )
            for r in rows
        ]

    def count(
        self,
        target: str | None = None,
        unread_only: bool = False,
        since: str | None = None,
    ) -> int:
        """How many rows `list` would return with no limit or offset."""
        where, args = self._where(target, unread_only, since)
        with self._lock, sqlite3.connect(self._db_path) as conn:
            row = conn.execute(
                f"SELECT COUNT(*) FROM notifications {where}", args
            ).fetchone()
        return int(row[0])

    def ack(self, notification_id: str) -> bool:
        ts = self._utc_now()
        with self._lock, sqlite3.connect(self._db_path) as conn:
            cur = conn.execute(
                "UPDATE notifications SET read_at = ? "
                "WHERE id = ? AND read_at IS NULL",
                (ts, notification_id),
            )
            return cur.rowcount > 0

    def ack_all(self, target: str | None = None) -> int:
        """Mark every unread row (optionally only one target's) read; returns how many changed."""
        ts = self._utc_now()
        sql = "UPDATE notifications SET read_at = ? WHERE read_at IS NULL"
        args: list[Any] = [ts]
        if target:
            sql += " AND target = ?"
            args.append(target)
        with self._lock, sqlite3.connect(self._db_path) as conn:
            return conn.execute(sql, args).rowcount

    def unread_count(self, target: str | None = None) -> int:
        clauses = ["read_at IS NULL"]
        args: list[Any] = []
        if target:
            clauses.append("target = ?")
            args.append(target)
        with self._lock, sqlite3.connect(self._db_path) as conn:
            row = conn.execute(
                f"SELECT COUNT(*) AS c FROM notifications WHERE {' AND '.join(clauses)}",
                args,
            ).fetchone()
        return int(row[0])

    # ─────────────────────────────────────────────────────────────
    # Internals
    # ─────────────────────────────────────────────────────────────

    def _audit_event(
        self,
        action: str,
        *,
        actor: str | None = None,
        target: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if self._audit is None:
            return
        try:
            record = getattr(self._audit, "record", None)
            if record is None:
                return
            record(action, target=target, actor=actor, metadata=metadata or {})
        except Exception as exc:  # pragma: no cover
            logger.warning("Notification audit record failed for %s: %s", action, exc)

    @staticmethod
    def _utc_now() -> str:
        from usecase._time_utils import utc_now_micros
        return utc_now_micros()


# ─────────────────────────────────────────────────────────────────
# Module-level singleton accessor
# ─────────────────────────────────────────────────────────────────

_notifications: SqliteNotificationStore | None = None


def set_notification_store(store: SqliteNotificationStore | None) -> None:
    global _notifications
    _notifications = store


def notification_store() -> SqliteNotificationStore | None:
    return _notifications
