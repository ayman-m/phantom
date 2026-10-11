"""Connector state machine.

Tracks the lifecycle of every configured tool connector so operators
can see at a glance which integrations are healthy vs. need
attention. Replaces the implicit "tool errored => maybe auth issue"
guesswork with explicit per-connector state.

Adapted from SnowAgent's MCP connection states
(snow-agent-complete/snow-agent/07-mcp/services/mcp/) — same five
states (`connected | failed | needs-auth | pending | disabled`).

# State semantics

  - `connected` — the connector responded successfully to its last
    health probe / tool call. Operator: green dot, no action needed.
  - `pending` — never been probed, or being initialized after a
    config change. Operator: amber dot, give it a moment.
  - `failed` — last call returned a non-auth error (e.g. CALDERA
    server unreachable, XSIAM 5xx). Operator: red dot, check the
    upstream service.
  - `needs-auth` — last call returned 401/403. Operator: orange
    dot, click "Reauth" to re-run the OAuth / token-refresh flow.
  - `disabled` — operator explicitly turned the connector off via
    the /connectors UI. Operator: grey dot, won't be probed.

# Transitions

      pending  → connected   (first successful call)
              → failed       (transport error)
              → needs-auth   (401/403)
              → disabled     (operator action)

      connected → failed     (transport error)
                → needs-auth (401/403)
                → disabled

      failed    → connected  (recovery)
                → needs-auth
                → disabled

      needs-auth → connected (reauth + first success)
                 → disabled

      disabled  → pending    (operator re-enables)

The state is NOT terminal in any case; transitions cycle as the
connector's external service comes and goes.

# Why a separate store (vs. tagging instances or extending
# instance_store)

Instances carry CONFIGURATION (URLs, references to secrets).
Connector state tracks RUNTIME health which changes minute-to-
minute. Mixing them would mean every health update writes to
the instance row, churning that DB. A dedicated state table
keeps the configuration writes append-rare and the health
writes append-frequent without crossing.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger("Phantom MCP")

DEFAULT_DATA_ROOT = Path("/app/data")

VALID_STATE = {"connected", "failed", "needs-auth", "pending", "disabled"}


@dataclass
class ConnectorState:
    """One connector's runtime state.

    Field semantics:
      connector_id          stable id from manifest.toolConnectors[].id
      state                 one of VALID_STATE
      last_transition_at    most recent state-change timestamp
      last_probed_at        most recent probe (regardless of outcome).
                            distinct from last_transition_at because a
                            probe that just confirms current state
                            doesn't transition.
      last_error            truncated error message; only set when
                            state is `failed` or `needs-auth`.
      consecutive_failures  count of consecutive failures in this
                            state. resets to 0 on success. useful for
                            backoff and alerting.
    """

    connector_id: str
    state: str
    last_transition_at: str
    last_probed_at: str | None
    last_error: str | None
    consecutive_failures: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "connector_id": self.connector_id,
            "state": self.state,
            "last_transition_at": self.last_transition_at,
            "last_probed_at": self.last_probed_at,
            "last_error": self.last_error,
            "consecutive_failures": self.consecutive_failures,
        }


class SqliteConnectorStateStore:
    """One row per connector. Reads are point-in-time consistent;
    writes are lock-serialized. Tiny table (~10 rows in typical
    deploys), so we don't bother with FTS or aggressive indexes."""

    def __init__(self, data_root: Path | None = None) -> None:
        root = data_root or self._resolve_data_root()
        root.mkdir(parents=True, exist_ok=True)
        self._db_path = root / "connector_state.db"
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
        return c

    def _init_schema(self) -> None:
        with self._lock, self._conn() as c:
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS connector_state (
                    connector_id           TEXT PRIMARY KEY,
                    state                  TEXT NOT NULL,
                    last_transition_at     TEXT NOT NULL,
                    last_probed_at         TEXT,
                    last_error             TEXT,
                    consecutive_failures   INTEGER NOT NULL DEFAULT 0
                )
                """
            )

    @staticmethod
    def _now() -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    # ─── Public API ─────────────────────────────────────────────

    def list(self) -> list[ConnectorState]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT connector_id, state, last_transition_at, "
                "last_probed_at, last_error, consecutive_failures "
                "FROM connector_state ORDER BY connector_id ASC"
            ).fetchall()
        return [self._row_to_state(r) for r in rows]

    def get(self, connector_id: str) -> ConnectorState | None:
        with self._conn() as c:
            row = c.execute(
                "SELECT connector_id, state, last_transition_at, "
                "last_probed_at, last_error, consecutive_failures "
                "FROM connector_state WHERE connector_id = ?",
                (connector_id,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_state(row)

    def upsert_pending(self, connector_id: str) -> ConnectorState:
        """Initialize a row in `pending`. Idempotent: if a row
        already exists, leaves it unchanged."""
        existing = self.get(connector_id)
        if existing is not None:
            return existing
        now = self._now()
        with self._lock, self._conn() as c:
            c.execute(
                "INSERT OR IGNORE INTO connector_state "
                "(connector_id, state, last_transition_at, "
                " consecutive_failures) "
                "VALUES (?, 'pending', ?, 0)",
                (connector_id, now),
            )
        return self.get(connector_id)  # type: ignore[return-value]

    def record_success(self, connector_id: str) -> ConnectorState:
        """Mark connector as connected. Resets consecutive_failures.
        If the previous state was already connected, only
        last_probed_at is updated (no transition row churn)."""
        existing = self.get(connector_id)
        now = self._now()
        if existing is None:
            # Auto-init on first success.
            with self._lock, self._conn() as c:
                c.execute(
                    "INSERT INTO connector_state "
                    "(connector_id, state, last_transition_at, "
                    " last_probed_at, consecutive_failures) "
                    "VALUES (?, 'connected', ?, ?, 0)",
                    (connector_id, now, now),
                )
            return self.get(connector_id)  # type: ignore[return-value]
        if existing.state == "connected":
            # Just update last_probed_at — same state.
            with self._lock, self._conn() as c:
                c.execute(
                    "UPDATE connector_state SET last_probed_at = ?, "
                    "consecutive_failures = 0 WHERE connector_id = ?",
                    (now, connector_id),
                )
        else:
            # Transition.
            with self._lock, self._conn() as c:
                c.execute(
                    "UPDATE connector_state SET state = 'connected', "
                    "last_transition_at = ?, last_probed_at = ?, "
                    "last_error = NULL, consecutive_failures = 0 "
                    "WHERE connector_id = ?",
                    (now, now, connector_id),
                )
        return self.get(connector_id)  # type: ignore[return-value]

    def record_failure(
        self,
        connector_id: str,
        *,
        error: str,
        is_auth_error: bool = False,
    ) -> ConnectorState:
        """Mark a failure. Use is_auth_error=True for 401/403 (transitions
        to needs-auth); other errors transition to failed."""
        new_state = "needs-auth" if is_auth_error else "failed"
        existing = self.get(connector_id)
        now = self._now()
        truncated = (error or "")[:500]
        if existing is None:
            with self._lock, self._conn() as c:
                c.execute(
                    "INSERT INTO connector_state "
                    "(connector_id, state, last_transition_at, "
                    " last_probed_at, last_error, consecutive_failures) "
                    "VALUES (?, ?, ?, ?, ?, 1)",
                    (connector_id, new_state, now, now, truncated),
                )
            return self.get(connector_id)  # type: ignore[return-value]
        if existing.state == new_state:
            # Same failure mode — just bump counter.
            with self._lock, self._conn() as c:
                c.execute(
                    "UPDATE connector_state SET last_probed_at = ?, "
                    "last_error = ?, "
                    "consecutive_failures = consecutive_failures + 1 "
                    "WHERE connector_id = ?",
                    (now, truncated, connector_id),
                )
        else:
            with self._lock, self._conn() as c:
                c.execute(
                    "UPDATE connector_state SET state = ?, "
                    "last_transition_at = ?, last_probed_at = ?, "
                    "last_error = ?, consecutive_failures = 1 "
                    "WHERE connector_id = ?",
                    (new_state, now, now, truncated, connector_id),
                )
        return self.get(connector_id)  # type: ignore[return-value]

    def set_disabled(
        self, connector_id: str, *, disabled: bool
    ) -> ConnectorState | None:
        """Operator action: enable or disable the connector. When
        re-enabling, we transition to pending (the next call will
        probe and resolve to connected/failed/needs-auth)."""
        existing = self.get(connector_id)
        if existing is None:
            if disabled:
                # Initialize as disabled directly.
                self.upsert_pending(connector_id)
                return self.set_disabled(connector_id, disabled=True)
            return None
        target = "disabled" if disabled else "pending"
        if existing.state == target:
            return existing
        now = self._now()
        with self._lock, self._conn() as c:
            c.execute(
                "UPDATE connector_state SET state = ?, "
                "last_transition_at = ?, last_error = NULL, "
                "consecutive_failures = 0 WHERE connector_id = ?",
                (target, now, connector_id),
            )
        return self.get(connector_id)

    @staticmethod
    def _row_to_state(row: tuple[Any, ...]) -> ConnectorState:
        (
            connector_id, state, last_transition_at,
            last_probed_at, last_error, consecutive_failures,
        ) = row
        return ConnectorState(
            connector_id=connector_id,
            state=state,
            last_transition_at=last_transition_at,
            last_probed_at=last_probed_at,
            last_error=last_error,
            consecutive_failures=int(consecutive_failures or 0),
        )


_global_store: SqliteConnectorStateStore | None = None


def set_connector_state_store(store: SqliteConnectorStateStore) -> None:
    global _global_store
    _global_store = store


def get_connector_state_store() -> SqliteConnectorStateStore | None:
    return _global_store
