"""SqliteTelemetryStore — opt-in usage counters per
manifest.telemetry.events[].

Privacy-by-default: with manifest.telemetry.default == "off", the
store starts disabled. record() is a no-op until an operator opts
in via the API surface. When enabled, only events declared in the
manifest are recorded — `record("totally-made-up")` is rejected
even with telemetry on.

Anonymous + aggregate by design: payload values are bag-of-counters
the bundle author defined (no PII baked into events). This is
local-only today; a future flush_to_remote() can ship aggregates to
a vendor endpoint if the operator additionally opts in to that.

# Schema

    telemetry_events(
      id            INTEGER PRIMARY KEY AUTOINCREMENT,
      event_name    TEXT NOT NULL,        -- one of manifest.telemetry.events
      count         INTEGER NOT NULL DEFAULT 1,
      recorded_at   TEXT NOT NULL,        -- ISO8601 UTC
      payload_json  TEXT NOT NULL DEFAULT '{}'
    );
    CREATE INDEX idx_telemetry_event_date ON telemetry_events(event_name, recorded_at);

    telemetry_state(
      key       TEXT PRIMARY KEY,    -- "enabled"
      value     TEXT NOT NULL
    );
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

logger = logging.getLogger("Phantom MCP")

DEFAULT_DATA_ROOT = Path("/app/data")


@dataclass(frozen=True)
class TelemetryStatus:
    enabled: bool
    declared_events: list[str]
    total_recorded: int
    counts_by_event: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "declared_events": self.declared_events,
            "total_recorded": self.total_recorded,
            "counts_by_event": self.counts_by_event,
        }


class SqliteTelemetryStore:
    def __init__(
        self,
        declared_events: Iterable[str] = (),
        default_enabled: bool = False,
        data_root: Path | None = None,
        audit_log: Any | None = None,
    ) -> None:
        self._declared = frozenset(declared_events)
        self._data_root = (data_root or self._resolve_data_root()).resolve()
        self._data_root.mkdir(parents=True, exist_ok=True)
        self._db_path = self._data_root / "telemetry.db"
        self._lock = threading.Lock()
        self._audit = audit_log
        self._init_schema(default_enabled=default_enabled)

    @staticmethod
    def _resolve_data_root() -> Path:
        env = os.getenv("DATA_ROOT")
        return Path(env) if env else DEFAULT_DATA_ROOT

    def _init_schema(self, default_enabled: bool) -> None:
        with self._lock, sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS telemetry_events (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_name    TEXT NOT NULL,
                    count         INTEGER NOT NULL DEFAULT 1,
                    recorded_at   TEXT NOT NULL,
                    payload_json  TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_telemetry_event_date "
                "ON telemetry_events(event_name, recorded_at)"
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS telemetry_state (
                    key   TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            # Seed the enabled state ONCE — never overwrite an existing row.
            cur = conn.execute(
                "SELECT value FROM telemetry_state WHERE key = 'enabled'"
            )
            if cur.fetchone() is None:
                conn.execute(
                    "INSERT INTO telemetry_state (key, value) VALUES ('enabled', ?)",
                    ("1" if default_enabled else "0",),
                )

    # ─────────────────────────────────────────────────────────────
    # Opt-in toggle
    # ─────────────────────────────────────────────────────────────

    def is_enabled(self) -> bool:
        with self._lock, sqlite3.connect(self._db_path) as conn:
            row = conn.execute(
                "SELECT value FROM telemetry_state WHERE key = 'enabled'"
            ).fetchone()
        return bool(row and row[0] == "1")

    def set_enabled(self, enabled: bool, actor: str | None = None) -> bool:
        prev = self.is_enabled()
        with self._lock, sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO telemetry_state (key, value) VALUES ('enabled', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                ("1" if enabled else "0",),
            )
        if prev != enabled:
            self._audit_event(
                "telemetry_toggled", actor=actor, target="telemetry:state",
                metadata={"enabled": enabled, "previous": prev},
            )
        return prev != enabled

    # ─────────────────────────────────────────────────────────────
    # Record + read
    # ─────────────────────────────────────────────────────────────

    def record(
        self,
        event_name: str,
        count: int = 1,
        payload: dict[str, Any] | None = None,
    ) -> bool:
        """Record an event. Returns True if persisted, False if skipped
        (telemetry off, or event not declared)."""
        if not self.is_enabled():
            return False
        if event_name not in self._declared:
            logger.debug(
                "Telemetry record() ignored for undeclared event '%s'. "
                "Declared events: %s",
                event_name, sorted(self._declared),
            )
            return False
        ts = self._utc_now()
        with self._lock, sqlite3.connect(self._db_path) as conn:
            conn.execute(
                "INSERT INTO telemetry_events (event_name, count, recorded_at, payload_json) "
                "VALUES (?, ?, ?, ?)",
                (event_name, int(count), ts, json.dumps(payload or {})),
            )
        return True

    def status(self) -> TelemetryStatus:
        enabled = self.is_enabled()
        declared = sorted(self._declared)
        total = 0
        counts_by_event: dict[str, int] = {}
        with self._lock, sqlite3.connect(self._db_path) as conn:
            rows = conn.execute(
                "SELECT event_name, SUM(count) AS total FROM telemetry_events "
                "GROUP BY event_name"
            ).fetchall()
        for r in rows:
            counts_by_event[r[0]] = int(r[1] or 0)
            total += int(r[1] or 0)
        return TelemetryStatus(
            enabled=enabled,
            declared_events=declared,
            total_recorded=total,
            counts_by_event=counts_by_event,
        )

    def daily_counts(
        self,
        event_name: str | None = None,
        days: int = 30,
    ) -> list[dict[str, Any]]:
        """Return per-day counts for charts. Bucket key is YYYY-MM-DD."""
        clauses: list[str] = []
        args: list[Any] = []
        if event_name:
            clauses.append("event_name = ?")
            args.append(event_name)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        with self._lock, sqlite3.connect(self._db_path) as conn:
            rows = conn.execute(
                f"""
                SELECT substr(recorded_at, 1, 10) AS day,
                       event_name,
                       SUM(count) AS total
                FROM telemetry_events
                {where}
                GROUP BY day, event_name
                ORDER BY day DESC
                LIMIT ?
                """,
                args + [int(days) * 50],
            ).fetchall()
        return [{"day": r[0], "event_name": r[1], "total": int(r[2])} for r in rows]

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
            logger.warning("Telemetry audit record failed for %s: %s", action, exc)

    @staticmethod
    def _utc_now() -> str:
        from usecase._time_utils import utc_now_micros
        return utc_now_micros()


# ─────────────────────────────────────────────────────────────────
# Module-level singleton accessor
# ─────────────────────────────────────────────────────────────────

_telemetry: SqliteTelemetryStore | None = None


def set_telemetry_store(store: SqliteTelemetryStore | None) -> None:
    global _telemetry
    _telemetry = store


def telemetry_store() -> SqliteTelemetryStore | None:
    return _telemetry
