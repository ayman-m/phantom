"""Operator workflow state — sqlite-backed canonical home.

Holds the operator's UI workflow state that's NOT a UI preference and
should follow them across devices + survive volume operations:

  * tested_journeys — which journey ids the operator has marked tested
    on /help/journeys. Not kept in localStorage: it would not survive
    volume wipes or sync across browsers, violating both the operator's
    mental model and the canonical-state discipline (Rule 1: one state
    surface = one storage home).

  * metrics_bookmarks — saved metric queries on /observability/metrics.
    Not kept in localStorage, for the same reasons.

# What this store does NOT hold

It's specifically for OPERATOR WORKFLOW STATE — facts the operator
wants to track that aren't bound to a single device. Things that DO
NOT belong here:

  * UI preferences (theme, sidebar collapsed, debug panel open). Those
    legitimately live in localStorage — device-local state for the
    chrome around the platform. See use-theme.ts + sidebar.tsx + the
    help-page sidebar toggles for the keep-in-localStorage examples.
  * Operator credentials. SecretStore handles those.
  * Connector / instance state. marketplace.db + instances.db.
  * Auth sessions. auth_sessions.db.
  * Agent self-modification state. Each subsystem owns its own store
    (memory_store, agent_definition_store, etc.).

This store is intentionally narrow: a key-value table where the value
is an opaque JSON blob the hook owns. Adding a new operator workflow
concern doesn't require a schema migration — just pick a new key.

# Schema

    operator_state(
      key         TEXT PRIMARY KEY,
      value_json  TEXT NOT NULL,     -- arbitrary JSON serialized by the caller
      updated_at  TEXT NOT NULL      -- ISO 8601 UTC
    );

`key` is a stable identifier the caller picks (e.g. 'tested_journeys').
Suggested naming: lowercase + snake_case, ASCII only. The store does
NOT enforce a particular shape on value_json — that's a hook-level
concern. Each hook documents what shape it stores.

# Multi-user readiness

Today phantom is single-user (one admin). The schema has
no `user_id` column because there's exactly one user. When multi-user
lands, add `user_id TEXT NOT NULL DEFAULT 'admin'` +
move PRIMARY KEY to `(user_id, key)`. All existing rows migrate
cleanly with the DEFAULT clause; the API layer changes from "get the
authenticated MCP_TOKEN owner" (currently always admin) to "filter
rows by the resolved user_id from the session token." Same migration
shape as `sessions` (one user today, multi-user-ready
schema).

# Concurrency

Same pattern as marketplace_store.py: module-level RLock guards every
SQLite operation; short-lived connections per call; WAL journal mode.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger("Phantom MCP")

DEFAULT_DATA_ROOT = Path("/app/data")


@dataclass(frozen=True)
class OperatorState:
    """One row from operator_state. Read-only DTO.

    `value` is the parsed JSON — callers get a Python object, not the
    raw string. The store handles serialization in put().
    """

    key: str
    value: Any
    updated_at: str  # ISO 8601 UTC


class OperatorStateStore:
    """SQLite-backed key-value store for operator workflow state."""

    def __init__(self, data_root: Path | None = None) -> None:
        self._data_root = Path(data_root) if data_root else DEFAULT_DATA_ROOT
        self._data_root.mkdir(parents=True, exist_ok=True)
        self._db_path = self._data_root / "operator_state.db"
        self._lock = threading.RLock()
        self._init_schema()

    # ── connection + schema ───────────────────────────────────────

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            self._db_path, check_same_thread=False, isolation_level=None
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_schema(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS operator_state (
                    key        TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    # ── public API ────────────────────────────────────────────────

    def get(self, key: str) -> OperatorState | None:
        """Return the row for `key`, or None when not set.

        Callers MUST tolerate None as "no state yet" — the hook
        treats it as "use the default empty state" rather than
        crashing. Same pattern auth uses for the first-login
        before credentials_changed exists.
        """
        if not isinstance(key, str) or not key:
            raise ValueError("key must be a non-empty string")
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT key, value_json, updated_at "
                "FROM operator_state WHERE key=?",
                (key,),
            ).fetchone()
        if not row:
            return None
        try:
            value = json.loads(row["value_json"])
        except (json.JSONDecodeError, TypeError) as err:
            # Defensive: a row that's somehow not valid JSON shouldn't
            # crash callers. Log + treat as missing.
            logger.warning(
                "operator_state[%r] has unparseable value_json (%s); "
                "treating as unset",
                key,
                err,
            )
            return None
        return OperatorState(
            key=row["key"],
            value=value,
            updated_at=row["updated_at"],
        )

    def put(self, key: str, value: Any) -> OperatorState:
        """Upsert the row for `key`. Returns the persisted row.

        `value` is serialized via json.dumps; anything json-serializable
        is accepted (lists, dicts, strings, numbers, None). The hook
        layer determines the shape; the store doesn't enforce.

        Idempotent at the row-shape level — calling put() with the
        same value twice produces the same final row (just with
        the updated_at refreshed). Callers that care about no-op
        detection should diff value before calling.
        """
        if not isinstance(key, str) or not key:
            raise ValueError("key must be a non-empty string")
        try:
            value_json = json.dumps(value, separators=(",", ":"))
        except (TypeError, ValueError) as err:
            raise ValueError(
                f"value for key {key!r} is not JSON-serializable: {err}"
            ) from err
        ts = _iso_now()
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO operator_state (key, value_json, updated_at) "
                "VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET "
                "  value_json = excluded.value_json, "
                "  updated_at = excluded.updated_at",
                (key, value_json, ts),
            )
        return OperatorState(key=key, value=value, updated_at=ts)

    def delete(self, key: str) -> bool:
        """Remove the row for `key`. Returns True if a row was deleted.

        Idempotent — re-calling on a missing key returns False, no
        error. Used by the hook's `reset()` operation.
        """
        if not isinstance(key, str) or not key:
            raise ValueError("key must be a non-empty string")
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM operator_state WHERE key=?",
                (key,),
            )
            return cur.rowcount > 0

    def list_all(self) -> list[OperatorState]:
        """All rows, ordered by updated_at DESC.

        Used by /api/agent/backup to include operator state in the
        backup zip. Not for hot-path UI rendering — keep that
        per-key via get().
        """
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT key, value_json, updated_at "
                "FROM operator_state "
                "ORDER BY updated_at DESC"
            ).fetchall()
        out: list[OperatorState] = []
        for row in rows:
            try:
                value = json.loads(row["value_json"])
            except (json.JSONDecodeError, TypeError):
                # Skip unparseable rows in the bulk list rather than
                # break the whole response.
                continue
            out.append(
                OperatorState(
                    key=row["key"], value=value, updated_at=row["updated_at"],
                )
            )
        return out


def _iso_now() -> str:
    """UTC ISO 8601 — same format the audit log + other stores use."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ─────────────────────────────────────────────────────────────────
# Module-level singleton accessor.
#
# Same convention used by audit_log, instance_store, provider_store,
# marketplace_store — route code reads via a getter rather than
# threading the store through every callsite. Set once at boot from
# main.py.
# ─────────────────────────────────────────────────────────────────

_singleton: OperatorStateStore | None = None


def set_operator_state_store(store: OperatorStateStore | None) -> None:
    """Wire the process-wide operator state store. Called once from main.py."""
    global _singleton
    _singleton = store


def get_operator_state_store() -> OperatorStateStore | None:
    """Return the active store (or None when not yet wired).

    Callers MUST tolerate None — early-boot code paths may run before
    main.py finishes wiring. Returning None == "no operator state
    available" so callers can fall back to a clean default.
    """
    return _singleton
