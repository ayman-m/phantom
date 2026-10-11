"""SqliteEventLog — runtime structured-event store for the spec's
observability.events capability.

Distinct from the audit log:

  * Audit is a FORENSIC trail. Append-only, never deleted,
    every state change recorded. Optimized for "show me everything
    that happened on this resource between dates X and Y".

  * Events (this module) are RUNTIME TELEMETRY. Granular operational
    signals like `rt.simulation.started` or `rt.validation.completed`.
    Optimized for live dashboards + per-event-name aggregation. Can
    be retained shorter than audit (default 7d).

Both can be enabled side by side; they answer different questions
and a single state change typically produces both. A simulation
start writes `simulation_created` to audit (forensic) AND
`rt.simulation.started` to events (runtime telemetry).

# Schema

    runtime_events(
      id            TEXT PRIMARY KEY,    -- uuid4
      event_name    TEXT NOT NULL,        -- one of manifest.observability.events
      ts            TEXT NOT NULL,        -- ISO8601 UTC, microseconds
      actor         TEXT,                 -- principal id (mcp_token / api_key:<id>)
      payload_json  TEXT NOT NULL DEFAULT '{}'
    );
    CREATE INDEX idx_runtime_events_name_ts ON runtime_events(event_name, ts);
    CREATE INDEX idx_runtime_events_ts      ON runtime_events(ts);

# Side effects on record()

  1. sqlite append (this module)
  2. structured log line (`docker logs phantom_agent` picks it up)
  3. metrics counter `phantom_mcp_runtime_events_total{event_name}` ++

The metric is auto-registered on first record() per event name —
operators don't need to pre-declare each event in the registry.
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
from typing import Any, Iterable

logger = logging.getLogger("Phantom MCP.events")

DEFAULT_DATA_ROOT = Path("/app/data")


@dataclass(frozen=True)
class RuntimeEvent:
    id: str
    event_name: str
    ts: str
    actor: str | None
    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "event_name": self.event_name,
            "ts": self.ts,
            "actor": self.actor,
            "payload": self.payload,
        }


class SqliteEventLog:
    def __init__(
        self,
        declared_events: Iterable[str] = (),
        data_root: Path | None = None,
        retention_days: int | None = 7,
    ) -> None:
        self._declared = frozenset(declared_events)
        self._data_root = (data_root or self._resolve_data_root()).resolve()
        self._data_root.mkdir(parents=True, exist_ok=True)
        self._db_path = self._data_root / "events.db"
        self._lock = threading.Lock()
        self._retention_days = retention_days
        self._init_schema()
        self._reap_old()

    @staticmethod
    def _resolve_data_root() -> Path:
        env = os.getenv("DATA_ROOT")
        return Path(env) if env else DEFAULT_DATA_ROOT

    def _init_schema(self) -> None:
        with self._lock, sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS runtime_events (
                    id            TEXT PRIMARY KEY,
                    event_name    TEXT NOT NULL,
                    ts            TEXT NOT NULL,
                    actor         TEXT,
                    payload_json  TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_runtime_events_name_ts "
                "ON runtime_events(event_name, ts)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_runtime_events_ts "
                "ON runtime_events(ts)"
            )

    def _reap_old(self) -> int:
        """Drop events older than retention_days. Best-effort; failure
        logs a warning but doesn't break boot."""
        if self._retention_days is None:
            return 0
        cutoff = self._utc_minus_days(self._retention_days)
        try:
            with self._lock, sqlite3.connect(self._db_path) as conn:
                cur = conn.execute(
                    "DELETE FROM runtime_events WHERE ts < ?", (cutoff,)
                )
                n = cur.rowcount
        except Exception as exc:  # pragma: no cover
            logger.warning("event log retention sweep failed: %s", exc)
            return 0
        if n > 0:
            logger.info("event log: reaped %d row(s) older than %s", n, cutoff)
        return n

    # ─────────────────────────────────────────────────────────────
    # Record + query
    # ─────────────────────────────────────────────────────────────

    def record(
        self,
        event_name: str,
        payload: dict[str, Any] | None = None,
        actor: str | None = None,
    ) -> str | None:
        """Append one runtime event. Returns the row id, or None when
        skipped (event not declared in manifest).

        Best-effort: NEVER raises into caller. Audit log + structured
        log line are emitted as side effects; metric counter is bumped.
        """
        if event_name not in self._declared:
            logger.debug(
                "event log: refusing undeclared event %r — declared: %s",
                event_name, sorted(self._declared),
            )
            return None
        row_id = str(uuid.uuid4())
        ts = self._utc_now()
        body = payload or {}
        try:
            with self._lock, sqlite3.connect(self._db_path) as conn:
                conn.execute(
                    "INSERT INTO runtime_events "
                    "(id, event_name, ts, actor, payload_json) VALUES (?, ?, ?, ?, ?)",
                    (row_id, event_name, ts, actor, json.dumps(body)),
                )
        except Exception as exc:  # pragma: no cover
            logger.warning("event log: failed to record %s: %s", event_name, exc)
            return None

        # Side effect 1: structured log line for log-shipper integration.
        logger.info(
            "[event] name=%s actor=%s payload=%s",
            event_name, actor or "anon", json.dumps(body, separators=(",", ":")),
        )

        # Side effect 2: metrics counter — auto-registered per event name.
        try:
            from usecase.metrics_registry import metrics_registry
            reg = metrics_registry()
            if reg is not None:
                c = reg.counter(
                    "phantom_mcp_runtime_events_total",
                    "Total runtime events recorded by event name.",
                )
                c.inc(event_name=event_name)
        except Exception as exc:  # pragma: no cover
            logger.debug("event log metric inc failed: %s", exc)

        return row_id

    def query(
        self,
        event_name: str | None = None,
        actor: str | None = None,
        since: str | None = None,
        until: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[RuntimeEvent]:
        """Query runtime events.

        No default limit: a default cap would silently truncate
        /observability/events on installs with many retained events. The retention
        reaper bounds the on-disk window separately; this method's
        job is to return everything in that window unless the caller
        explicitly asks for pagination.

        Pass `limit=N` (N > 0) for opt-in pagination; omit or pass
        None for no limit. SQLite LIMIT -1 means unlimited.
        """
        clauses: list[str] = []
        args: list[Any] = []
        if event_name:
            clauses.append("event_name = ?")
            args.append(event_name)
        if actor:
            clauses.append("actor = ?")
            args.append(actor)
        if since:
            clauses.append("ts >= ?")
            args.append(since)
        if until:
            clauses.append("ts <= ?")
            args.append(until)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        eff_limit = -1 if (limit is None or int(limit) <= 0) else int(limit)
        with self._lock, sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                f"""
                SELECT id, event_name, ts, actor, payload_json
                FROM runtime_events
                {where}
                ORDER BY ts DESC
                LIMIT ? OFFSET ?
                """,
                args + [eff_limit, int(offset)],
            ).fetchall()
        return [
            RuntimeEvent(
                id=r["id"],
                event_name=r["event_name"],
                ts=r["ts"],
                actor=r["actor"],
                payload=json.loads(r["payload_json"]),
            )
            for r in rows
        ]

    def summary(self) -> dict[str, int]:
        """Counts-by-event-name across the entire retention window."""
        with self._lock, sqlite3.connect(self._db_path) as conn:
            rows = conn.execute(
                "SELECT event_name, COUNT(*) AS c FROM runtime_events GROUP BY event_name"
            ).fetchall()
        return {r[0]: int(r[1]) for r in rows}

    @property
    def declared_events(self) -> list[str]:
        return sorted(self._declared)

    # ─────────────────────────────────────────────────────────────
    # Internals
    # ─────────────────────────────────────────────────────────────

    @staticmethod
    def _utc_now() -> str:
        from usecase._time_utils import utc_now_micros
        return utc_now_micros()

    @staticmethod
    def _utc_minus_days(days: int) -> str:
        import time
        cutoff = time.time() - (days * 86400)
        return time.strftime("%Y-%m-%dT%H:%M:%S.", time.gmtime(cutoff)) + (
            f"{int((cutoff % 1) * 1_000_000):06d}Z"
        )


# ─────────────────────────────────────────────────────────────────
# Module-level singleton
# ─────────────────────────────────────────────────────────────────

_event_log: SqliteEventLog | None = None


def set_event_log(log: SqliteEventLog | None) -> None:
    global _event_log
    _event_log = log


def event_log() -> SqliteEventLog | None:
    return _event_log
