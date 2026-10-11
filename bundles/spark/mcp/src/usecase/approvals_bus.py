"""InProcessApprovalsBus — bundle-local implementation of the spec's
`approvals` capability (spec.md §6.10 row "approvals").

Per spec §6.10 there are two approvals backends:

  - **Standalone**: `InProcessApprovalsBus` — a single-process queue
                    backed by a sqlite table for durability. Pending
                    approvals get an `asyncio.Event` (or
                    `threading.Event` for sync tools) keyed by id,
                    and `/api/v1/approvals/{id}/resolve` sets it.
  - **Platform**:   `KafkaApprovalsBus` — pending requests publish to
                    a Kafka topic the platform's UI consumes; resolution
                    flows back via another topic.

This module is the standalone variant. The interface is intentionally
minimal:

  request(tool, actor, args, namespaced, legacy)  → str (approval_id)
  await wait_async(approval_id, timeout=...)      → (status, reason)
  wait_sync(approval_id, timeout=...)             → (status, reason)
  resolve(approval_id, resolver, decision, reason) → bool
  list_pending()                                   → list[Approval]
  list_recent(limit)                               → list[Approval]
  get(approval_id)                                 → Approval | None

# Schema (`<data_root>/approvals.db`)

    approvals(
      id          TEXT PRIMARY KEY,    -- uuid4
      created_at  TEXT NOT NULL,        -- ISO8601 UTC, microsecond
      resolved_at TEXT,                 -- nullable; set on resolve
      tool        TEXT NOT NULL,        -- bare tool name from manifest
      namespaced  TEXT NOT NULL,        -- "<connector>.<tool>"
      actor       TEXT,                 -- "agent" (the requester)
      resolver    TEXT,                 -- "user:operator" (set on resolve)
      status      TEXT NOT NULL,        -- pending|approved|denied|timeout
      args_json   TEXT NOT NULL,        -- JSON of args being approved
      reason      TEXT                  -- optional human note
    );
    CREATE INDEX idx_approvals_status   ON approvals(status);
    CREATE INDEX idx_approvals_tool     ON approvals(tool);
    CREATE INDEX idx_approvals_created  ON approvals(created_at);

# Crash semantics

The in-memory `_waiters` dict goes away on process restart. If a tool
call was blocked on `wait_async` when the MCP died, the agent's MCP
request also dies — the next invocation starts fresh. Pending rows in
the sqlite table get reaped on next boot via `_reap_orphaned_pending()`
which marks anything still pending older than the boot time as
"timeout" with status_reason="orphaned". That keeps the UI from
showing zombie approvals.

# Block-until-resolved is intentional

The agent's MCP tool call blocks until the human resolves. From the
agent's perspective this looks like a slow tool call — no special
state machine needed. The configured timeout (default 5 minutes) is
the upper bound. A
"pending_approval" prompt the agent shows the operator, but the
mechanic itself is: wrapper waits, human clicks, wrapper proceeds.
"""

from __future__ import annotations

import asyncio
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

from usecase.audit_log import AUDIT_SENSITIVE_KEY_SUBSTRINGS

logger = logging.getLogger("Phantom MCP")

# Origin discrimination for approvals.
#
# Approvals are tagged with the surface that requested them so the
# right resolver UI lights up. Format conventions match the existing
# X-Phantom-Trigger contextvar (audit_log._current_trigger):
#
#   "chat:<session_id>"   chat thread that initiated the request →
#                         inline approval card in that chat session
#   "job:<job_name>"      scheduler-fired tool call →
#                         /approvals page (no live chat to host card)
#   "api"                 REST/MCP direct call from outside →
#                         /approvals page
#   "operator"            UI-initiated mutation →
#                         /approvals page
#   None / unset          legacy / unknown → falls through to "unknown"
#                         at insert time, /approvals page
#
# The bus reads from `audit_log.get_current_trigger()` rather than
# duplicating a parallel contextvar — same plumbing already routes
# X-Phantom-Trigger from chat/scheduler/REST handlers down through
# every awaited code path via Python contextvars.

DEFAULT_DATA_ROOT = Path("/app/data")
DEFAULT_TIMEOUT_SECONDS = 300  # 5 minutes

# Status values
STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_DENIED = "denied"
STATUS_TIMEOUT = "timeout"

# Decision values accepted by resolve(). "approve"/"approved" both work
# for ergonomics — the UI may send either.
_APPROVE_ALIASES = {"approve", "approved", "yes", "ok"}
_DENY_ALIASES = {"deny", "denied", "reject", "rejected", "no"}


@dataclass(frozen=True)
class Approval:
    """One approval row, materialized."""

    id: str
    created_at: str
    resolved_at: str | None
    tool: str
    namespaced: str
    actor: str | None
    resolver: str | None
    status: str
    args: dict[str, Any]
    reason: str | None
    # Risk tier for the agent self-modification feature.
    # Values: "read" | "soft" | "destructive" | "credential". Drives UI
    # rendering (color, confirmation ceremony) and audit filtering.
    # Rows without this column read as "soft" (the most common tier in
    # the manifest `humanRequired[]` defaults).
    risk_tier: str = "soft"
    # Surface where this approval was requested. Drives
    # which UI lights up to resolve it. Format:
    #   chat:<session_id>   → inline approval card in that chat
    #   job:<job_name>      → /approvals page (no live chat to host card)
    #   api                 → /approvals page (REST/MCP direct)
    #   operator            → /approvals page (UI-initiated mutation)
    #   unknown             → /approvals page (legacy rows, fallback)
    # Same row appears in /approvals regardless of origin — chat-origin
    # rows are visible there for audit, just default-filtered out of
    # the "Pending" tab so operators don't double-resolve from two
    # surfaces.
    origin: str = "unknown"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "created_at": self.created_at,
            "resolved_at": self.resolved_at,
            "tool": self.tool,
            "namespaced": self.namespaced,
            "actor": self.actor,
            "resolver": self.resolver,
            "status": self.status,
            "args": self.args,
            "reason": self.reason,
            "risk_tier": self.risk_tier,
            "origin": self.origin,
        }


class ApprovalDeniedError(RuntimeError):
    """Raised when the approval was denied by the resolver."""


class ApprovalTimeoutError(TimeoutError):
    """Raised when the approval window elapsed with no decision."""


class ApprovalSelfResolveError(PermissionError):
    """Raised when the resolver matches the original requester (actor).

    Defense-in-depth: an agent that issued a self-modification request
    MUST NOT be able to also approve it. Without this check, an agent
    could call `personality_update` (gated), see the pending row in
    `approvals_list_pending`, then call `approvals_resolve` to approve
    its own request — turning a "human-in-the-loop" gate into a no-op.

    The check is at the bus level (not just the tool layer) so the
    invariant holds regardless of which write path created the
    request: REST endpoint, MCP tool, future cron-driven self-mod,
    etc. See docs/agent-self-modification.md.
    """


class InProcessApprovalsBus:
    """Sqlite-backed standalone approvals bus.

    Thread-safe by way of a single lock around DB access + the in-memory
    waiter map. Async-aware: `wait_async` uses `asyncio.Event`, sync uses
    `threading.Event`. Both paths share the same DB row.
    """

    def __init__(
        self,
        data_root: Path | None = None,
        default_timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._data_root = (data_root or self._resolve_data_root()).resolve()
        self._data_root.mkdir(parents=True, exist_ok=True)
        self._db_path = self._data_root / "approvals.db"
        self._lock = threading.Lock()
        self._async_waiters: dict[str, asyncio.Event] = {}
        self._sync_waiters: dict[str, threading.Event] = {}
        self._async_loops: dict[str, asyncio.AbstractEventLoop] = {}
        self._default_timeout = default_timeout_seconds
        self._init_schema()
        self._reap_orphaned_pending()
        logger.info(
            "InProcessApprovalsBus at %s (default timeout %ds)",
            self._db_path, self._default_timeout,
        )

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
        return c

    def _init_schema(self) -> None:
        with self._lock, self._conn() as c:
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS approvals (
                    id          TEXT PRIMARY KEY,
                    created_at  TEXT NOT NULL,
                    resolved_at TEXT,
                    tool        TEXT NOT NULL,
                    namespaced  TEXT NOT NULL,
                    actor       TEXT,
                    resolver    TEXT,
                    status      TEXT NOT NULL,
                    args_json   TEXT NOT NULL,
                    reason      TEXT,
                    risk_tier   TEXT NOT NULL DEFAULT 'soft',
                    origin      TEXT NOT NULL DEFAULT 'unknown'
                )
                """
            )
            # Migration — older databases created the table without
            # `risk_tier`. PRAGMA is idempotent: running ALTER on a column
            # that already exists raises OperationalError; we swallow it.
            cols = {r[1] for r in c.execute("PRAGMA table_info(approvals)").fetchall()}
            if "risk_tier" not in cols:
                try:
                    c.execute(
                        "ALTER TABLE approvals ADD COLUMN risk_tier TEXT "
                        "NOT NULL DEFAULT 'soft'"
                    )
                    logger.info(
                        "ApprovalsBus: added risk_tier column to existing "
                        "approvals.db"
                    )
                except sqlite3.OperationalError as exc:
                    # Race: another process beat us. Fine.
                    logger.debug("risk_tier add skipped: %s", exc)
            # Migration — `origin` column. Discriminates the
            # surface where the approval was REQUESTED so the right
            # resolver UI can light up: chat-origin → inline approval
            # card in that chat session; job/api/operator → /approvals
            # page. Legacy rows get the default 'unknown' which the
            # /approvals UI renders as a generic 'background' origin.
            if "origin" not in cols:
                try:
                    c.execute(
                        "ALTER TABLE approvals ADD COLUMN origin TEXT "
                        "NOT NULL DEFAULT 'unknown'"
                    )
                    logger.info(
                        "ApprovalsBus: added origin column to existing "
                        "approvals.db"
                    )
                except sqlite3.OperationalError as exc:
                    logger.debug("origin add skipped: %s", exc)
            c.execute(
                "CREATE INDEX IF NOT EXISTS idx_approvals_status "
                "ON approvals(status)"
            )
            # Index on (status, origin) so the chat-side
            # subscriber and /approvals filter both have a fast path.
            c.execute(
                "CREATE INDEX IF NOT EXISTS idx_approvals_origin_status "
                "ON approvals(origin, status)"
            )
            c.execute(
                "CREATE INDEX IF NOT EXISTS idx_approvals_tool "
                "ON approvals(tool)"
            )
            c.execute(
                "CREATE INDEX IF NOT EXISTS idx_approvals_created "
                "ON approvals(created_at)"
            )

    def _reap_orphaned_pending(self) -> None:
        """Mark any pending rows from a prior process as 'timeout'.

        Pending state lives in memory (waiter Events). After a restart,
        the in-memory state is gone but the row is still in `pending`.
        Anything pending at boot is by definition orphaned — the
        original tool-call request is also dead. Mark them so the UI
        doesn't show zombies.
        """
        now = self._now_iso()
        with self._lock, self._conn() as c:
            cur = c.execute(
                "UPDATE approvals SET status = ?, resolved_at = ?, "
                "reason = COALESCE(reason, 'orphaned by MCP restart') "
                "WHERE status = ?",
                (STATUS_TIMEOUT, now, STATUS_PENDING),
            )
        if cur.rowcount:
            logger.info(
                "InProcessApprovalsBus: reaped %d orphaned pending row(s) at boot",
                cur.rowcount,
            )

    @staticmethod
    def _now_iso() -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%S.", time.gmtime()) + (
            f"{int((time.time() % 1) * 1_000_000):06d}Z"
        )

    # ─── Request lifecycle ─────────────────────────────────────

    def request(
        self,
        *,
        tool: str,
        namespaced: str,
        actor: str,
        args: dict[str, Any] | None = None,
        risk_tier: str = "soft",
        origin: str | None = None,
    ) -> str:
        """Insert a pending row, return the approval id.

        Args:
            tool: bare tool name (manifest.approvals.humanRequired[] match).
            namespaced: "<connector>.<tool>" form (or bare for built-ins).
            actor: who's asking (e.g. "agent" for chat-driven self-mod,
                   "operator" for UI-initiated). Recorded as the requester.
                   Used by resolve()'s self-resolve check.
            args: tool-input kwargs, sanitized for credential leakage.
            risk_tier: one of "read" | "soft" | "destructive" | "credential".
                   Drives UI rendering (color, confirmation ceremony) and
                   audit filtering. "read" is unusual for an approval row
                   (reads aren't gated) but supported for completeness.
                   "destructive" gets a red banner; "credential" requires
                   a "type CONFIRM" ceremony before the Approve button
                   activates.
            origin: surface that initiated the request. Format:
                   "chat:<session_id>" | "job:<job_name>" | "api" |
                   "operator" | "unknown" (default if not provided).
                   Drives where the resolver UI lights up: chat-origin
                   gets an inline approval card in the chat session;
                   everything else falls through to /approvals. If the
                   caller doesn't pass an explicit origin, we read the
                   `current_origin` contextvar (set by request handlers
                   at the entry point, see set_current_origin()).
        """
        if risk_tier not in ("read", "soft", "destructive", "credential"):
            raise ValueError(
                f"unknown risk_tier {risk_tier!r}; expected one of "
                f"read | soft | destructive | credential"
            )
        approval_id = str(uuid.uuid4())
        created = self._now_iso()
        # Resolve origin: explicit kwarg wins, else read from the
        # X-Phantom-Trigger contextvar (already set by chat/scheduler/
        # REST request handlers — see usecase.audit_log), else
        # "unknown" (the table default).
        from usecase.audit_log import get_current_trigger
        resolved_origin = origin or get_current_trigger() or "unknown"
        # Sanitize args before persisting — same heuristic as the audit
        # log: anything keyed by a credential-hint name gets `***`.
        # We never want the args row to leak a literal API key.
        sanitized = self._sanitize_args(args or {})
        with self._lock, self._conn() as c:
            c.execute(
                "INSERT INTO approvals "
                "(id, created_at, tool, namespaced, actor, status, "
                " args_json, risk_tier, origin) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (approval_id, created, tool, namespaced, actor,
                 STATUS_PENDING,
                 json.dumps(sanitized, default=self._json_safe_repr),
                 risk_tier, resolved_origin),
            )
        logger.info(
            "ApprovalsBus.request id=%s tool=%s namespaced=%s actor=%s "
            "risk_tier=%s origin=%s",
            approval_id, tool, namespaced, actor, risk_tier, resolved_origin,
        )
        # Fire-site — notify the agent's hook
        # dispatcher so operator-installed PermissionRequest hooks
        # fire. Fire-and-forget; failure here must NOT block the
        # approval creation that triggered it.
        from usecase.hook_dispatch_callback import fire_hook_event_async
        # Derive the source dimension from the origin string the
        # contextvar produced. job: → job-run, chat: → chat-tool-call.
        if resolved_origin.startswith("job:"):
            source = "job-run"
        elif resolved_origin.startswith("chat:"):
            source = "chat-tool-call"
        elif resolved_origin.startswith("skill:"):
            source = "skill-invocation"
        else:
            source = "chat-tool-call"
        fire_hook_event_async(
            "PermissionRequest",
            {
                "event": "PermissionRequest",
                "requestId": approval_id,
                "source": source,
                "actor": {
                    "sessionId": (
                        resolved_origin[len("chat:"):]
                        if resolved_origin.startswith("chat:")
                        else None
                    ),
                    "jobId": (
                        resolved_origin[len("job:"):]
                        if resolved_origin.startswith("job:")
                        else None
                    ),
                    "skillId": (
                        resolved_origin[len("skill:"):]
                        if resolved_origin.startswith("skill:")
                        else None
                    ),
                },
                "requestedAction": {
                    "toolName": tool,
                    "arguments": sanitized,
                },
                "riskTier": (
                    "destructive" if risk_tier == "destructive"
                    else "write" if risk_tier == "soft"
                    else "read"
                ),
                "createdAt": created,
            },
        )
        return approval_id

    @staticmethod
    def _sanitize_args(args: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for k, v in args.items():
            if not isinstance(v, str):
                out[k] = v
                continue
            if isinstance(k, str) and any(s in k.lower() for s in AUDIT_SENSITIVE_KEY_SUBSTRINGS):
                if v.startswith("/agents/"):
                    out[k] = v
                else:
                    out[k] = "***"
            else:
                out[k] = v
        return out

    @staticmethod
    def _json_safe_repr(o: Any) -> str:
        """json.dumps `default` callback for non-serializable values.

        The framework occasionally injects framework-internal objects
        (e.g. FastMCP `Context`) into tool kwargs, and they bubble up
        here when an approval row is recorded. Without this callback the
        JSON encoder would raise
        `TypeError: Object of type Context is not JSON serializable`
        and the entire approval request would fail — the operator
        would never see the request and the agent would get a 500.

        Coerce to a stable, redacted string ('<TypeName>') so:
          * the approval row always lands in the DB,
          * the audit trail isn't poisoned by an arbitrary repr() that
            might leak referenced secrets,
          * the operator sees something readable in the args column.

        Defined as a @staticmethod (not a module-level function)
        because a module-level function placed mid-file would silently
        end the class body and turn every subsequent method
        (wait_async, resolve, get, ...) into a dead nested function
        inside this helper. A staticmethod can't make that mistake —
        it IS part of the class.
        """
        return f"<{type(o).__name__}>"

    # ─── Waiters ───────────────────────────────────────────────

    async def wait_async(
        self, approval_id: str, timeout: int | None = None
    ) -> tuple[str, str | None]:
        """Block until resolution or timeout. Returns (status, reason).

        On timeout: marks the row as STATUS_TIMEOUT and returns it.
        Does NOT raise — the caller decides what to do with a non-
        approved status (typically: raise ApprovalDeniedError).
        """
        timeout_s = timeout if timeout is not None else self._default_timeout

        # Fast path: already resolved (operator clicked before we got here).
        existing = self.get(approval_id)
        if existing and existing.status != STATUS_PENDING:
            return existing.status, existing.reason

        event = asyncio.Event()
        loop = asyncio.get_running_loop()
        with self._lock:
            self._async_waiters[approval_id] = event
            self._async_loops[approval_id] = loop
        try:
            await asyncio.wait_for(event.wait(), timeout=timeout_s)
        except asyncio.TimeoutError:
            self._mark_timeout(approval_id)
            return STATUS_TIMEOUT, "timeout waiting for human approval"
        finally:
            with self._lock:
                self._async_waiters.pop(approval_id, None)
                self._async_loops.pop(approval_id, None)

        row = self.get(approval_id)
        if row is None:
            return STATUS_TIMEOUT, "approval row vanished"
        return row.status, row.reason

    def wait_sync(
        self, approval_id: str, timeout: int | None = None
    ) -> tuple[str, str | None]:
        """Same as wait_async but for synchronous tools."""
        timeout_s = timeout if timeout is not None else self._default_timeout

        existing = self.get(approval_id)
        if existing and existing.status != STATUS_PENDING:
            return existing.status, existing.reason

        event = threading.Event()
        with self._lock:
            self._sync_waiters[approval_id] = event
        try:
            if not event.wait(timeout=timeout_s):
                self._mark_timeout(approval_id)
                return STATUS_TIMEOUT, "timeout waiting for human approval"
        finally:
            with self._lock:
                self._sync_waiters.pop(approval_id, None)

        row = self.get(approval_id)
        if row is None:
            return STATUS_TIMEOUT, "approval row vanished"
        return row.status, row.reason

    # ─── Resolution ────────────────────────────────────────────

    def resolve(
        self,
        approval_id: str,
        *,
        resolver: str,
        decision: str,
        reason: str | None = None,
    ) -> Approval | None:
        """Approve or deny a pending request. Returns the updated row.

        Idempotent: resolving an already-resolved row is a no-op
        returning the existing row. Returns None if the row doesn't
        exist.

        Lock discipline: this method does NOT call `self.get()` while
        holding `self._lock` — `Lock` is not reentrant, so doing so
        would deadlock. Instead we read all needed columns inside the
        locked block and materialize the Approval after releasing.
        """
        decision_l = decision.lower().strip()
        if decision_l in _APPROVE_ALIASES:
            new_status = STATUS_APPROVED
        elif decision_l in _DENY_ALIASES:
            new_status = STATUS_DENIED
        else:
            raise ValueError(
                f"unknown decision {decision!r}; use approved/denied"
            )

        resolved_at = self._now_iso()
        async_event: asyncio.Event | None = None
        async_loop: asyncio.AbstractEventLoop | None = None
        sync_event: threading.Event | None = None
        with self._lock, self._conn() as c:
            existing = c.execute(
                "SELECT * FROM approvals WHERE id = ?", (approval_id,)
            ).fetchone()
            if existing is None:
                return None
            if existing["status"] != STATUS_PENDING:
                # Already resolved — return existing row, don't overwrite
                # AND don't touch waiters (they've already been notified).
                return self._row_to_approval(existing)

            # Defense-in-depth: actor cannot resolve their own request.
            # The chat-driven self-mod feature must not let an agent
            # both REQUEST a sensitive change and APPROVE it. Without
            # this check, the agent could call `personality_update`
            # (gated → creates pending row), then call `approvals_resolve`
            # to approve its own request — collapsing the human gate.
            #
            # We compare the existing row's `actor` to the incoming
            # `resolver`. Equality is exact (case-sensitive). Operators
            # supplying their actor as "user:operator" remain free to
            # resolve agent-initiated approvals. The agent supplies its
            # own actor as "agent" (or "agent:<session_id>" once inline
            # approvals are wired); either way, "agent" != "operator".
            if existing["actor"] and existing["actor"] == resolver:
                raise ApprovalSelfResolveError(
                    f"actor {resolver!r} cannot resolve their own approval "
                    f"request {approval_id!r}; a different resolver must "
                    f"approve this. (Defense-in-depth: see ApprovalSelfResolveError "
                    f"in approvals_bus.py.)"
                )

            c.execute(
                "UPDATE approvals SET status = ?, resolver = ?, "
                "resolved_at = ?, reason = ? WHERE id = ?",
                (new_status, resolver, resolved_at, reason, approval_id),
            )
            updated = c.execute(
                "SELECT * FROM approvals WHERE id = ?", (approval_id,)
            ).fetchone()

            # Capture waiter handles inside the lock to avoid races.
            async_event = self._async_waiters.get(approval_id)
            async_loop = self._async_loops.get(approval_id)
            sync_event = self._sync_waiters.get(approval_id)

        # Wake waiters OUTSIDE the lock so set() callbacks can't
        # contend with us if they try to clean up _async_waiters.
        if async_event is not None and async_loop is not None:
            try:
                async_loop.call_soon_threadsafe(async_event.set)
            except RuntimeError:
                # Loop already closed — waiter is dead anyway.
                pass
        if sync_event is not None:
            sync_event.set()

        logger.info(
            "ApprovalsBus.resolve id=%s decision=%s resolver=%s",
            approval_id, new_status, resolver,
        )
        return self._row_to_approval(updated) if updated else None

    def _mark_timeout(self, approval_id: str) -> None:
        with self._lock, self._conn() as c:
            c.execute(
                "UPDATE approvals SET status = ?, resolved_at = ?, "
                "reason = COALESCE(reason, 'timeout waiting for human approval') "
                "WHERE id = ? AND status = ?",
                (STATUS_TIMEOUT, self._now_iso(), approval_id, STATUS_PENDING),
            )

    # ─── Read API ──────────────────────────────────────────────

    def get(self, approval_id: str) -> Approval | None:
        with self._lock, self._conn() as c:
            row = c.execute(
                "SELECT * FROM approvals WHERE id = ?", (approval_id,)
            ).fetchone()
        return self._row_to_approval(row) if row else None

    def list_pending(self, *, limit: int | None = None) -> list[Approval]:
        """Pending rows, oldest first (FIFO order matches operator UX —
        the longest-waiting request goes first).

        Args:
            limit: optional cap. None returns all pending. Tier-1 self-
                mod tool `approvals_list_pending` passes a limit so the
                agent can avoid pulling thousands of rows in pathological
                cases.
        """
        clauses = "WHERE status = ? ORDER BY created_at ASC"
        params: list[Any] = [STATUS_PENDING]
        if limit is not None:
            clauses += " LIMIT ?"
            params.append(max(1, min(int(limit), 1000)))
        with self._lock, self._conn() as c:
            rows = c.execute(
                f"SELECT * FROM approvals {clauses}", params,
            ).fetchall()
        return [self._row_to_approval(r) for r in rows]

    def list_history(
        self, *, limit: int = 100, status: str | None = None
    ) -> list[Approval]:
        """Alias for list_recent() — used by the agent self-mod tool
        `approvals_list_history`. Existing callers of list_recent()
        keep working; the alias just gives the read-side a clearer
        name in the tool catalog (history > recent for forensic queries)."""
        return self.list_recent(limit=limit, status=status)

    def list_recent(
        self, *, limit: int = 100, status: str | None = None
    ) -> list[Approval]:
        clauses, params = [], []
        if status:
            clauses.append("status = ?")
            params.append(status)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(max(1, min(limit, 1000)))
        with self._lock, self._conn() as c:
            rows = c.execute(
                f"SELECT * FROM approvals {where} "
                "ORDER BY created_at DESC LIMIT ?",
                params,
            ).fetchall()
        return [self._row_to_approval(r) for r in rows]

    @staticmethod
    def _row_to_approval(row: sqlite3.Row) -> Approval:
        # Defensive on `risk_tier` — older deploys may have rows that
        # pre-date the column; the migration backfills with 'soft' but
        # schema reads through `row.keys()` may not surface it.
        try:
            risk_tier = row["risk_tier"] or "soft"
        except (IndexError, KeyError):
            risk_tier = "soft"
        # Same defensive read for `origin`.
        try:
            origin = row["origin"] or "unknown"
        except (IndexError, KeyError):
            origin = "unknown"
        return Approval(
            id=row["id"],
            created_at=row["created_at"],
            resolved_at=row["resolved_at"],
            tool=row["tool"],
            namespaced=row["namespaced"],
            actor=row["actor"],
            resolver=row["resolver"],
            status=row["status"],
            args=json.loads(row["args_json"]),
            reason=row["reason"],
            risk_tier=risk_tier,
            origin=origin,
        )


# ─────────────────────────────────────────────────────────────────
# Module-level singleton + tool-name matching helper
# ─────────────────────────────────────────────────────────────────

_bus: InProcessApprovalsBus | None = None


def set_approvals_bus(bus: InProcessApprovalsBus | None) -> None:
    """Wire the process-wide approvals bus. Called once from main.py."""
    global _bus
    _bus = bus


def approvals_bus() -> InProcessApprovalsBus | None:
    return _bus


def needs_human_approval(
    *,
    tool_name: str,
    namespaced: str,
    legacy_name: str | None,
    human_required: set[str],
    instance_trusted: bool = False,
) -> bool:
    """Return True iff any of the tool's identifiers is in `human_required`.

    The manifest's `approvals.humanRequired` may use bare names
    (`launch_caldera_operation`), namespaced (`caldera.launch_caldera_operation`),
    or legacy aliases (`caldera_launch_caldera_operation`). Match any.

    `instance_trusted` bypasses the gate entirely. Set
    `trusted: true` on an instance's config to mark it as a trusted
    lab connector — tool calls against that instance skip approval
    regardless of what's in the manifest. Use this for sandbox
    Caldera/XSIAM tenants where every operation is intentional and
    the human-in-the-loop overhead is friction, not safety.

    Production deployments should leave `trusted` unset (default
    False) so the manifest gate still fires.
    """
    if instance_trusted:
        return False
    if not human_required:
        return False
    candidates = {tool_name, namespaced}
    if legacy_name:
        candidates.add(legacy_name)
    return bool(candidates & human_required)
