"""SqliteAuditLog — bundle-local implementation of the spec's `audit`
capability (spec.md §6.10 row 14).

Per spec §6.10, `audit` has two backend impls:

  - **Standalone**: `SqliteAuditLog` writes append-only rows to a local
                    sqlite DB under `<data_root>/audit.db`.
  - **Platform**:   `OpenSearchAuditLog` writes to the platform's
                    central audit index, queryable via Kibana etc.

This module is the standalone variant. The interface is intentionally
minimal — `record(action, target, ...)` and a few `query_*()` helpers
for the /api/v1/audit endpoint. The platform variant can be a thin
adapter over the same interface.

# Schema

    audit_events(
      id            TEXT PRIMARY KEY,    -- uuid4
      ts            TEXT NOT NULL,        -- ISO8601 UTC, microsecond precision
      actor         TEXT,                 -- "system", "user:<name>",
                                          -- "agent", or "anonymous"
      action        TEXT NOT NULL,        -- one of manifest.audit.events
                                          -- (plus the SOC-tool-specific
                                          -- secret_*, instance_*, provider_*
                                          -- events introduced here)
      target        TEXT,                 -- the thing acted on:
                                          --   "connector:caldera"
                                          --   "tool:xsiam.execute_xql_query"
                                          --   "secret:/agents/phantom/..."
                                          --   "instance:<uuid>"
      status        TEXT,                 -- "success" | "failure" | "skipped"
      duration_ms   INTEGER,              -- nullable; populated for tool_call
      metadata_json TEXT NOT NULL          -- JSON blob with action-specific
                                          -- detail (NEVER secret VALUES,
                                          -- only paths/identifiers)
    );
    CREATE INDEX idx_audit_ts     ON audit_events(ts);
    CREATE INDEX idx_audit_actor  ON audit_events(actor);
    CREATE INDEX idx_audit_action ON audit_events(action);
    CREATE INDEX idx_audit_target ON audit_events(target);

# Append-only contract

There is intentionally NO `update` or `delete` API. SOC audit trails
must be tamper-evident; the bundle's UI exposes read-only views. Row
deletion would require operating on the sqlite file directly with
elevated privileges.

# What gets recorded

Per `manifest.yaml:audit.events`:

    tool_call                       — every connector tool invocation
    simulation_created              — xlog.create_*_worker
    scenario_started                — xlog.create_scenario_worker_*
    caldera_operation_created       — caldera.start_operation
    detection_validation_recorded   — xsiam.execute_xql_query (with intent)
    coverage_report_generated       — xlog.generate_coverage_report
    settings_changed                — POST /api/v1/settings
    instance_created                — InstanceStore.create

Plus the secret-store + provider-store + delete events that aren't
in the manifest's audit.events list but the spec's §6.10 row 14
requires every state-changing action to leave a trace:

    secret_read     — SecretStore.read
    secret_write    — SecretStore.write
    secret_deleted  — SecretStore.delete + delete_under
    instance_deleted — InstanceStore.delete
    provider_created — ProviderStore.create
    provider_deleted — ProviderStore.delete

# Actor inference

The current contextvar (set by future auth middleware) supplies the
actor when known. For now the actor is inferred:

  - Any direct admin endpoint hit comes through `require_bearer`, so
    the actor is "user:operator" (the human who knows the MCP token).
  - Tool calls during MCP dispatch are "agent".
  - Migration / boot reads are "system".

Approvals can write distinct actors for
human-approved actions vs autonomous ones; this module's `record(...)`
API takes `actor` as an arg so that's a no-op extension.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
import uuid
from contextvars import ContextVar
from pathlib import Path
from typing import Any

logger = logging.getLogger("Phantom MCP")

DEFAULT_DATA_ROOT = Path("/app/data")

# Shared key-name heuristic for "does this metadata key hint at a secret
# value". Single source of truth shared by
# SqliteAuditLog._sanitize and ApprovalsBus._sanitize_args (one concept,
# one home).
# Widened from the original 7-substring set to catch credential/session/
# cookie/private-key-shaped keys the original set missed.
AUDIT_SENSITIVE_KEY_SUBSTRINGS = (
    "token", "password", "secret", "bearer", "apikey", "api_key", "auth",
    "credential", "passwd", "pwd", "session", "cookie", "private",
    "passphrase", "private_key", "client_secret", "refresh", "access_key",
    "secret_key", "signature", "otp", "pin",
)

# Contextvar for actor attribution. The admin HTTP layer sets this to
# "user:operator" for the duration of a request; the connector-loader
# wrapper sets it to "agent" for the duration of a tool call. Anything
# outside those scopes (boot, migrations, the secret store touched
# directly) falls through to "system".
_current_actor: ContextVar[str | None] = ContextVar("_current_actor", default=None)


def get_current_actor() -> str:
    """Return the active actor, defaulting to 'system'."""
    return _current_actor.get() or "system"


def set_current_actor(actor: str | None) -> Any:
    """Set the actor for the current async/thread context. Returns a token
    for `reset_current_actor` (paired with try/finally)."""
    return _current_actor.set(actor)


def reset_current_actor(token: Any) -> None:
    _current_actor.reset(token)


# Contextvar for trigger attribution. Set by the api/trigger_context
# middleware whenever an inbound HTTP request carries the
# `X-Phantom-Trigger` header. Audit rows pick it up through
# `record()` so operators can filter the audit feed by trigger
# (e.g. `trigger=job:nightly-coverage` to find all activity driven
# by a scheduled job vs interactive operator chats).
#
# The header value is namespaced with a colon-prefixed type tag:
#   "job:<name>"           — fired by the scheduler (chat or tool_call action)
#   "operator:<id>"        — interactive operator turn (future, not set today)
#   "schedule:<id>"        — driven by an external cron (Cloud Scheduler, etc.)
# Anything else flows through unchanged so the schema is forward-
# compatible.
_current_trigger: ContextVar[str | None] = ContextVar(
    "_current_trigger", default=None,
)


def get_current_trigger() -> str | None:
    """Return the active trigger if set; None otherwise (untriggered)."""
    return _current_trigger.get()


def set_current_trigger(trigger: str | None) -> Any:
    """Set the trigger for the current async/thread context. Returns a
    token for `reset_current_trigger` (paired with try/finally)."""
    return _current_trigger.set(trigger)


def reset_current_trigger(token: Any) -> None:
    _current_trigger.reset(token)


# Approval-bypass contextvar. Set by the trigger_context
# middleware when the inbound HTTP request carries
# `X-Phantom-Approval-Bypass: 1`. Read by `_approval_gate.gate_and_execute`
# — when active, gated tools execute immediately with an auto-approval
# audit row instead of blocking on operator confirmation.
#
# Why a separate contextvar instead of overloading `_current_trigger`:
# the trigger value identifies the SOURCE of activity (chat session,
# job, REST), and the bypass flag is an orthogonal POLICY decision
# the operator made for that source. Coupling them ("trigger=job:xyz
# implies bypass") would force every scheduler-driven job to lose
# approval, which is the opposite of what we want — bypass is opt-in,
# per chat session via the chat dropdown or per job via the job
# definition's bypass_approvals toggle. Keeping the two contextvars
# separate keeps the two decisions independent.
#
# The bypass header is intentionally simple: presence + truthy value
# (`1`, `true`, `yes`) means "bypass on for this request". Anything
# else means "bypass off". The middleware does the parsing.
_current_approval_bypass: ContextVar[bool] = ContextVar(
    "_current_approval_bypass", default=False,
)


def get_current_approval_bypass() -> bool:
    """Return True if the current request has approval bypass enabled."""
    return _current_approval_bypass.get()


def set_current_approval_bypass(bypass: bool) -> Any:
    """Set the approval-bypass flag for the current async/thread context.
    Returns a token for `reset_current_approval_bypass` (paired with
    try/finally)."""
    return _current_approval_bypass.set(bool(bypass))


def reset_current_approval_bypass(token: Any) -> None:
    _current_approval_bypass.reset(token)


# ─────────────────────────────────────────────────────────────────
# Action taxonomy — keep in sync with manifest.yaml:audit.events
# ─────────────────────────────────────────────────────────────────

# Manifest-declared events (the bundle author opted in to these).
ACTION_TOOL_CALL = "tool_call"
ACTION_SIMULATION_CREATED = "simulation_created"
ACTION_SCENARIO_STARTED = "scenario_started"
ACTION_CALDERA_OPERATION_CREATED = "caldera_operation_created"
ACTION_DETECTION_VALIDATION_RECORDED = "detection_validation_recorded"
ACTION_COVERAGE_REPORT_GENERATED = "coverage_report_generated"
ACTION_SETTINGS_CHANGED = "settings_changed"
ACTION_INSTANCE_CREATED = "instance_created"

# Spec §6.10-mandated state-change events (always logged regardless of
# manifest opt-in, so an operator-leaked secret can always be traced).
ACTION_INSTANCE_DELETED = "instance_deleted"
ACTION_PROVIDER_CREATED = "provider_created"
ACTION_PROVIDER_DELETED = "provider_deleted"
ACTION_SECRET_READ = "secret_read"
ACTION_SECRET_WRITE = "secret_write"
ACTION_SECRET_DELETED = "secret_deleted"

# Approvals capability (spec §6.10 row "approvals").
ACTION_APPROVAL_REQUESTED = "approval_requested"
ACTION_APPROVAL_RESOLVED = "approval_resolved"

# Sessions + memory + context (spec §6.10 rows for these).
ACTION_SESSION_CREATED = "session_created"
ACTION_SESSION_ENDED = "session_ended"
ACTION_SESSION_DELETED = "session_deleted"
ACTION_MESSAGE_APPENDED = "message_appended"
ACTION_MEMORY_STORED = "memory_stored"
ACTION_MEMORY_SEARCHED = "memory_searched"
ACTION_MEMORY_DELETED = "memory_deleted"
# Closes a read/write audit asymmetry: DELETE already recorded an
# event, but list/point-read did not, so "did someone enumerate the
# memory store?" and "who read this key?" were both unanswerable.
ACTION_MEMORY_LISTED = "memory_listed"
ACTION_MEMORY_READ = "memory_read"
ACTION_CONTEXT_ASSEMBLED = "context_assembled"

# Jobs scheduler (spec §6.10 row "scheduling").
ACTION_JOB_REGISTERED = "job_registered"
ACTION_JOB_FIRED = "job_fired"
ACTION_JOB_COMPLETED = "job_completed"
ACTION_JOB_FAILED = "job_failed"
ACTION_JOB_SKIPPED = "job_skipped"
ACTION_JOB_ENABLED = "job_enabled"
ACTION_JOB_DISABLED = "job_disabled"
# Runtime job CRUD (POST/PATCH/DELETE /api/v1/jobs)
ACTION_JOB_REMOVED = "job_removed"
ACTION_JOB_UPDATED = "job_updated"

# Knowledge base (spec §6.10 row "knowledge").
ACTION_KB_LOADED = "kb_loaded"
ACTION_KB_DOC_INDEXED = "kb_doc_indexed"
ACTION_KB_DOC_REMOVED = "kb_doc_removed"
ACTION_KB_SEARCHED = "kb_searched"
ACTION_KB_DOC_READ = "kb_doc_read"

# Agent self-modification.
# personality_changed: every put() to SqlitePersonalityStore.
# agent_self_mod_*: bookend events for chat-driven self-mod tool calls.
# A successful Tier-2/3/4 write emits both: an "_requested" when the
# tool is invoked, and an "_executed" once approvals resolves and the
# underlying operation completes. Operators can audit "what did the
# agent change about itself?" by filtering action ∈ {agent_self_mod_*}.
ACTION_PERSONALITY_CHANGED = "personality_changed"
# organization_changed: every create / put / activate / delete / restore on SqliteOrganizationStore.
ACTION_ORGANIZATION_CHANGED = "organization_changed"
ACTION_AGENT_SELF_MOD_REQUESTED = "agent_self_mod_requested"
ACTION_AGENT_SELF_MOD_EXECUTED = "agent_self_mod_executed"

# Closed-loop coverage engine.
# detections_synced: every detections_sync call (per-XSIAM-page upsert).
# coverage_snapshot_taken: every coverage_snapshot_take.
# coverage_drift_detected: when a snapshot diff crosses the operator's
#   drift threshold (e.g. a rule that fired regularly went silent).
# coverage_gap_observed: when coverage_gaps surfaces a technique with
#   no detections or no recent fires that the operator hasn't seen.
ACTION_DETECTIONS_SYNCED = "detections_synced"
ACTION_COVERAGE_SNAPSHOT_TAKEN = "coverage_snapshot_taken"
ACTION_COVERAGE_DRIFT_DETECTED = "coverage_drift_detected"
ACTION_COVERAGE_GAP_OBSERVED = "coverage_gap_observed"


class SqliteAuditLog:
    """Append-only audit trail at ``<data_root>/audit.db``.

    Designed for high write volume on the tool-call hot path. The schema
    is denormalized intentionally — every row is self-contained, so
    queries don't need joins. The metadata column is JSON for
    flexibility; the indexed columns (action, target, actor, ts) cover
    the common query shapes.
    """

    def __init__(self, data_root: Path | None = None) -> None:
        self._data_root = (data_root or self._resolve_data_root()).resolve()
        self._data_root.mkdir(parents=True, exist_ok=True)
        self._db_path = self._data_root / "audit.db"
        self._lock = threading.Lock()
        self._init_schema()
        logger.info("SqliteAuditLog at %s", self._db_path)

    @staticmethod
    def _resolve_data_root() -> Path:
        raw = os.getenv("DATA_ROOT", str(DEFAULT_DATA_ROOT))
        return Path(raw)

    @property
    def db_path(self) -> Path:
        return self._db_path

    def _conn(self) -> sqlite3.Connection:
        # `check_same_thread=False` is safe here because every call
        # opens its own connection and the lock serializes writes.
        c = sqlite3.connect(self._db_path, isolation_level=None, check_same_thread=False)
        c.row_factory = sqlite3.Row
        return c

    def _init_schema(self) -> None:
        with self._lock, self._conn() as c:
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_events (
                    id            TEXT PRIMARY KEY,
                    ts            TEXT NOT NULL,
                    actor         TEXT,
                    action        TEXT NOT NULL,
                    target        TEXT,
                    status        TEXT,
                    duration_ms   INTEGER,
                    metadata_json TEXT NOT NULL,
                    trigger       TEXT
                )
                """
            )
            # Migration for existing audit.db's that pre-date the
            # `trigger` column. PRAGMA introspection + ADD COLUMN
            # is the same pattern used by job_scheduler.py for the
            # `source` column. Idempotent — re-running is a no-op.
            cols = {
                r["name"]
                for r in c.execute("PRAGMA table_info(audit_events)").fetchall()
            }
            if "trigger" not in cols:
                c.execute("ALTER TABLE audit_events ADD COLUMN trigger TEXT")
            c.execute("CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_events(ts)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_audit_actor ON audit_events(actor)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_events(action)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_audit_target ON audit_events(target)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_audit_trigger ON audit_events(trigger)")

    # ─── Recording ────────────────────────────────────────────

    def record(
        self,
        action: str,
        *,
        target: str | None = None,
        status: str | None = None,
        actor: str | None = None,
        duration_ms: int | None = None,
        metadata: dict[str, Any] | None = None,
        trigger: str | None = None,
    ) -> str:
        """Append one audit event. Returns the row id.

        Best-effort: NEVER raises into the caller. A failed audit write
        logs a warning but doesn't block the underlying operation —
        otherwise a corrupt sqlite file would brick the entire MCP.

        `trigger` defaults to whatever's in the trigger contextvar
        (set by the trigger_context middleware from the inbound
        X-Phantom-Trigger header). Direct callers can override by
        passing the keyword explicitly — useful for record-after-the-
        fact paths (boot reconciliation etc.) that aren't inside an
        HTTP request.
        """
        row_id = str(uuid.uuid4())
        ts = time.strftime("%Y-%m-%dT%H:%M:%S.", time.gmtime()) + (
            f"{int((time.time() % 1) * 1_000_000):06d}Z"
        )
        actor_val = actor or get_current_actor()
        trigger_val = trigger if trigger is not None else get_current_trigger()
        meta_json = json.dumps(self._sanitize(metadata or {}))
        try:
            with self._lock, self._conn() as c:
                c.execute(
                    "INSERT INTO audit_events "
                    "(id, ts, actor, action, target, status, duration_ms, "
                    "metadata_json, trigger) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        row_id, ts, actor_val, action, target, status,
                        duration_ms, meta_json, trigger_val,
                    ),
                )
        except Exception as exc:
            # Don't let an audit write break the request path.
            logger.warning(
                "SqliteAuditLog: failed to record action=%s target=%s: %s",
                action, target, exc,
            )

        # No surface bus to publish to: the agent UI is a plain Next.js
        # app that pulls /api/agent/audit on demand.

        return row_id

    @staticmethod
    def _sanitize(meta: dict[str, Any]) -> dict[str, Any]:
        """Best-effort scrub of values that look like raw secrets.

        Defense-in-depth: callers SHOULD never pass secret VALUES into
        metadata, but if a bug ever does, we redact heuristically. The
        rule:

          - Only string values are candidates for redaction (ints,
            lists, dicts can't carry literal credentials in a way the
            sanitizer would catch — and redacting `secret_slot_count: 3`
            to `"***"` made output useless without adding any safety).
          - A string value is redacted iff its key matches a hint name
            (`token`, `password`, `key`, `secret`, `bearer`, etc.).
          - Strings that look like SecretStore PATHS (`/agents/...`)
            pass through — they're references, not values.
        """
        scrubbed: dict[str, Any] = {}
        for k, v in meta.items():
            if not isinstance(v, str):
                # Numeric / collection values can't carry literal secret
                # material in a way our heuristic would catch.
                scrubbed[k] = v
                continue
            if isinstance(k, str) and any(s in k.lower() for s in AUDIT_SENSITIVE_KEY_SUBSTRINGS):
                if v.startswith("/agents/"):
                    # SecretStore path — fine to keep verbatim.
                    scrubbed[k] = v
                else:
                    scrubbed[k] = "***"
            else:
                scrubbed[k] = v
        return scrubbed

    # ─── Querying ─────────────────────────────────────────────

    def query(
        self,
        *,
        action: str | None = None,
        actor: str | None = None,
        target: str | None = None,
        target_prefix: str | None = None,
        since: str | None = None,
        until: str | None = None,
        trigger: str | None = None,
        trigger_prefix: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Read audit events with simple filters.

        No default limit and no hard cap: a default cap would silently
        truncate /observability/events on installs with many retained
        audit rows. Pagination is opt-in
        (pass `limit=N`); omit for unlimited.

        `target_prefix` does a `LIKE 'X%'` match — useful for "all events
        on instances of connector X" via `target_prefix="instance:"`.

        `trigger` does an exact match (e.g. "job:nightly-coverage");
        `trigger_prefix` does a LIKE prefix match (e.g. "job:" to find
        all scheduler-driven activity regardless of which job).
        """
        clauses: list[str] = []
        params: list[Any] = []
        if action:
            clauses.append("action = ?")
            params.append(action)
        if actor:
            clauses.append("actor = ?")
            params.append(actor)
        if target:
            clauses.append("target = ?")
            params.append(target)
        if target_prefix:
            clauses.append("target LIKE ?")
            params.append(target_prefix + "%")
        if since:
            clauses.append("ts >= ?")
            params.append(since)
        if until:
            clauses.append("ts <= ?")
            params.append(until)
        if trigger:
            clauses.append("trigger = ?")
            params.append(trigger)
        if trigger_prefix:
            clauses.append("trigger LIKE ?")
            params.append(trigger_prefix + "%")

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        query = (
            "SELECT id, ts, actor, action, target, status, duration_ms, "
            "metadata_json, trigger "
            f"FROM audit_events {where} "
            "ORDER BY ts DESC LIMIT ? OFFSET ?"
        )
        eff_limit = -1 if (limit is None or int(limit) <= 0) else int(limit)
        params.extend([eff_limit, max(0, offset)])

        with self._lock, self._conn() as c:
            rows = c.execute(query, params).fetchall()

        return [self._row_to_dict(r) for r in rows]

    def count(
        self,
        *,
        action: str | None = None,
        actor: str | None = None,
        target: str | None = None,
        target_prefix: str | None = None,
        since: str | None = None,
        until: str | None = None,
        trigger: str | None = None,
        trigger_prefix: str | None = None,
    ) -> int:
        """Count rows matching the filter set.

        Mirrors `query()`'s filter signature so callers can reuse the
        same kwargs for total-count + paginated-rows. Used by the
        /api/v1/audit list route to surface a `total` field for the
        UI's pagination controls.
        """
        clauses: list[str] = []
        params: list[Any] = []
        if action:
            clauses.append("action = ?")
            params.append(action)
        if actor:
            clauses.append("actor = ?")
            params.append(actor)
        if target:
            clauses.append("target = ?")
            params.append(target)
        if target_prefix:
            clauses.append("target LIKE ?")
            params.append(f"{target_prefix}%")
        if since:
            clauses.append("ts >= ?")
            params.append(since)
        if until:
            clauses.append("ts <= ?")
            params.append(until)
        if trigger:
            clauses.append("trigger = ?")
            params.append(trigger)
        if trigger_prefix:
            clauses.append("trigger LIKE ?")
            params.append(f"{trigger_prefix}%")
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        with self._lock, self._conn() as c:
            row = c.execute(
                f"SELECT COUNT(*) FROM audit_events {where}", params
            ).fetchone()
        return int(row[0]) if row else 0

    def summary(self) -> dict[str, Any]:
        """Aggregate counts by action — for the admin dashboard."""
        with self._lock, self._conn() as c:
            rows = c.execute(
                "SELECT action, COUNT(*) AS n FROM audit_events GROUP BY action"
            ).fetchall()
            total = c.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]
            latest = c.execute(
                "SELECT ts FROM audit_events ORDER BY ts DESC LIMIT 1"
            ).fetchone()
        return {
            "total": int(total),
            "latest_ts": latest[0] if latest else None,
            "by_action": {r["action"]: int(r["n"]) for r in rows},
        }

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        # Use sqlite3.Row.keys() to tolerate older DBs that haven't
        # picked up the trigger-column migration yet (the schema migrate
        # at boot adds it, but in-flight reads on a never-restarted
        # process could see a row from before the column existed).
        keys = row.keys() if hasattr(row, "keys") else []
        return {
            "id": row["id"],
            "ts": row["ts"],
            "actor": row["actor"],
            "action": row["action"],
            "target": row["target"],
            "status": row["status"],
            "duration_ms": row["duration_ms"],
            "metadata": json.loads(row["metadata_json"]),
            "trigger": row["trigger"] if "trigger" in keys else None,
        }


# ─────────────────────────────────────────────────────────────────
# Module-level singleton accessor — set by main.py at boot
# ─────────────────────────────────────────────────────────────────

_audit: SqliteAuditLog | None = None


def set_audit_log(log: SqliteAuditLog | None) -> None:
    """Wire the process-wide audit sink. Called once from main.py."""
    global _audit
    _audit = log


def audit_log() -> SqliteAuditLog | None:
    """Return the active audit sink (or None when not yet wired).

    Modules in hot paths (SecretStore, the tool wrapper) prefer this
    over taking an explicit dependency, since they're constructed
    before main.py finishes wiring. A None return means "no-op";
    callers MUST tolerate that.
    """
    return _audit


def record_event(
    action: str,
    *,
    target: str | None = None,
    status: str | None = None,
    actor: str | None = None,
    duration_ms: int | None = None,
    metadata: dict[str, Any] | None = None,
    trigger: str | None = None,
) -> None:
    """Convenience: record on the singleton if wired, else no-op.

    Used by the SecretStore + tool wrapper which can't reasonably take
    the audit log as a constructor parameter (they're wired before main
    completes). When `trigger` is None (the common case), `record()`
    pulls from the trigger contextvar set by the trigger_context
    middleware.
    """
    log = _audit
    if log is None:
        return
    log.record(
        action,
        target=target,
        status=status,
        actor=actor,
        duration_ms=duration_ms,
        metadata=metadata,
        trigger=trigger,
    )
