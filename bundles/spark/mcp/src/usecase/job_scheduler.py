"""CroniterJobScheduler — bundle-local implementation of the spec's
`scheduling` capability (spec.md §6.10 row "scheduling").

Per spec §6.10, `scheduling` has two backend impls:

  - **Standalone**: `CroniterJobScheduler` — a single asyncio task
                    that walks `manifest.yaml:jobs[]` and fires each
                    job's action when its cron expression is due.
  - **Platform**:   `KubernetesCronJobScheduler` — the platform's
                    central cron controller materializes one Kubernetes
                    `CronJob` per declared job and routes its output
                    back through the agent runtime.

This module is the standalone variant. It composes cleanly with
the audit, approvals and cognitive layers: when a cron fires `xlog.generate_coverage_report`, the
dispatch goes through the SAME wrapped tool callable the agent uses,
so audit, approvals, and instance contextvar all apply uniformly.

# State split: manifest vs sqlite

  - `manifest.yaml:jobs[]` is the **source of truth for cron
    definitions**. Editing the manifest requires a redeploy/reboot;
    that's intentional — cron schedules are infra config, not runtime
    settings.
  - `<data_root>/jobs.db` holds **runtime mutable state**: per-job
    `enabled` flag (operators can pause without editing manifest) and
    the `last_fired_at`/`last_status`/`next_due_at` history. Plus a
    `job_runs` table keyed to each fire for "show me last N runs of
    job X" forensics.

When the manifest changes, on next boot the scheduler reconciles:
new jobs get inserted with enabled=1; jobs that disappeared from the
manifest are marked `removed=1` (kept for historical run records but
never fired again).

# Schema

    jobs(
      name           TEXT PRIMARY KEY,    -- from manifest jobs[].name
      cron           TEXT NOT NULL,
      timezone       TEXT NOT NULL,
      action_json    TEXT NOT NULL,        -- {type: "tool_call", name, args}
      enabled        INTEGER NOT NULL DEFAULT 1,
      removed        INTEGER NOT NULL DEFAULT 0,  -- "manifest no longer
                                                  --  declares this job"
      last_fired_at  TEXT,
      last_status    TEXT,                 -- success|failure|skipped
      last_error     TEXT,
      next_due_at    TEXT,
      registered_at  TEXT NOT NULL,
      description    TEXT NOT NULL DEFAULT ''  -- operator's note on the job
    );
    job_runs(
      id           TEXT PRIMARY KEY,
      job_name     TEXT NOT NULL,
      fired_at     TEXT NOT NULL,
      finished_at  TEXT,
      status       TEXT NOT NULL,         -- success|failure|skipped
      duration_ms  INTEGER,
      result_json  TEXT,
      error        TEXT,
      trigger      TEXT NOT NULL          -- "cron"|"manual"
    );
    CREATE INDEX idx_job_runs_name_fired ON job_runs(job_name, fired_at);
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

from usecase.credential_guardrail import assert_no_credential_tools

try:
    from croniter import croniter  # type: ignore[import-untyped]
except ImportError as exc:  # pragma: no cover — surfaced at boot
    croniter = None  # type: ignore[assignment]
    _IMPORT_ERROR = exc

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover — Python < 3.9
    ZoneInfo = None  # type: ignore[assignment]

logger = logging.getLogger("Phantom MCP")

DEFAULT_DATA_ROOT = Path("/app/data")

# Cap on how long the master loop sleeps between schedule checks. Even
# if the next-due time is hours away, we wake up periodically so
# operator-initiated enable/disable takes effect within ~30 seconds
# without needing an asyncio.Event signaling layer.
MAX_SLEEP_SECONDS = 30.0

# How long a single job's action is allowed to run before the
# scheduler logs a warning (it doesn't kill the job — that's a future
# refinement; the runqueue.max_concurrent in the manifest is the real
# guard). 600s is conservative for "long-running coverage report".
WARN_AFTER_SECONDS = 600

# After this many consecutive failures the scheduler auto-disables a
# non-run_once job so a chronically-failing job (for example one that
# 401s on /api/chat every minute) stops re-firing and flooding the audit
# log. The operator re-enables via PATCH once the cause is fixed. Distinct from the
# immediate "references unknown tool" disable, which fires on the first
# occurrence because that error never self-heals.
MAX_CONSECUTIVE_FAILURES = 10


class CompletedRunOnceError(ValueError):
    """Raised when something tries to arm a run-once job that already fired.

    A run-once job stores its Run-at time as `M H D Mo *` (no year). After it
    fires it is disabled; arming it from that stored cron would pick the same
    date next year and fire unattended. The only ways back are a new Run-at
    time (PATCH with a different `cron`) or Duplicate / a new job.
    """

# Where the embedded MCP can reach the agent's /api/chat endpoint when
# firing action_type="chat" jobs. In phantom-standalone deploys agent
# and MCP share the container, so localhost:3000 is correct. Operators
# in split-deploy modes (agent and MCP in different pods) can override
# via the PHANTOM_AGENT_INTERNAL_URL env var — same convention the
# agent's lib/api/client.ts uses for SSR calls.
DEFAULT_AGENT_INTERNAL_URL = "http://localhost:3000"

# Per-job timeout when firing a chat action. The model loop can take
# minutes to converge across multiple tool calls; 5 min is the same
# cap operators see in `gh run watch` for CI end-to-end tests, generous
# for any reasonable scheduled prompt without being unbounded.
CHAT_ACTION_TIMEOUT_S = 300


ToolDispatcher = Callable[[str, dict[str, Any]], Awaitable[Any]]


# Cheap shape probe for the resolve_ident path. We don't actually parse
# the string into a UUID — `uuid.UUID(s)` would raise on non-UUID input
# and we'd swallow the exception, which costs more than a regex on the
# happy path. The check is "looks like 8-4-4-4-12 hex with hyphens"; if
# it matches we try id-lookup first, otherwise we go straight to name.
import re as _re
# Upper bound on a job's description (a note, not a document).
MAX_DESCRIPTION_CHARS = 2000

_UUID_RE = _re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    _re.IGNORECASE,
)


def _looks_like_uuid(s: str) -> bool:
    return isinstance(s, str) and bool(_UUID_RE.match(s))


@dataclass(frozen=True)
class JobDefinition:
    """One job from manifest.yaml's jobs[] block."""

    name: str
    cron: str
    timezone: str
    action: dict[str, Any]   # {type: "tool_call", name: ..., args: {...}}

    @property
    def action_type(self) -> str:
        return str(self.action.get("type") or "")

    @property
    def action_name(self) -> str:
        return str(self.action.get("name") or "")

    @property
    def action_args(self) -> dict[str, Any]:
        a = self.action.get("args") or {}
        return a if isinstance(a, dict) else {}


def _completed_run_once_message(name: str) -> str:
    return (
        f"job {name!r} is a run-once job that already ran, so it cannot be "
        "resumed (its stored Run-at time has no year and would fire again "
        "next year). Set a new Run-at time with Edit, or Duplicate the job."
    )


# Keys a job's permission policy used to carry and no longer does.
_LEGACY_POLICY_KEYS = ("require_approval",)


def _without_legacy_policy_keys(policy: Any) -> Any:
    """A copy of `policy` without the keys a policy no longer carries, so a
    create or update never stores them. Anything that is not a dict passes
    through unchanged. Rows already stored with a legacy key are not
    migrated; the reader ignores the key."""
    if not isinstance(policy, dict):
        return policy
    return {k: v for k, v in policy.items() if k not in _LEGACY_POLICY_KEYS}


@dataclass(frozen=True)
class JobRow:
    """Materialized row from the jobs table — the runtime view."""

    name: str
    cron: str
    timezone: str
    action: dict[str, Any]
    enabled: bool
    removed: bool
    last_fired_at: str | None
    last_status: str | None
    last_error: str | None
    next_due_at: str | None
    registered_at: str
    # Opaque UUID. Assigned at insert (or backfilled at boot for rows
    # that pre-date the column). Stable across rename. The UI uses this
    # in URLs because it doesn't need path encoding and doesn't change
    # if operators rename a job. `name` remains the human-facing label.
    id: str = ""
    # `manifest` (declared in manifest.yaml:jobs[]) or `runtime` (created
    # via POST /api/v1/jobs at runtime). Manifest jobs are reconciled on
    # boot — their cron/timezone/action are reset from the manifest each
    # boot; runtime jobs survive boot untouched and can be edited via
    # PATCH/DELETE.
    source: str = "manifest"
    # When true, the scheduler disables the job after its first
    # successful (or failed) fire. Used by the /jobs/new form's
    # "Run Now" + "Run Once" frequencies — a one-shot fires the
    # action, then never again. Job stays in the table with its run
    # history visible; operator can re-enable to fire again.
    run_once: bool = False
    # Lifetime fire count. Populated by `_row_to_jobrow` via a
    # correlated subquery against `job_runs.job_name`. Surfaced here
    # so the agent UI's job list can show "Runs: N" without needing
    # to issue a separate /api/v1/jobs/{name}/runs request per row.
    # Defaults to 0 for in-memory construction (e.g. fresh inserts).
    run_count: int = 0
    # When true, _dispatch_chat sends
    # `X-Phantom-Approval-Bypass: 1` so the MCP-side gate auto-
    # approves any gated tools the agent calls during this job.
    # Operator opts in per-job via the job edit form's bypass slider.
    # Audit rows still record each tool call with auto_approved=true.
    bypass_approvals: bool = False
    # Per-job model override. When set,
    # _dispatch_chat threads this into the `body.model` field of the
    # /api/chat POST so the chat route's resolveModelName() picks it
    # over runtimeConfig.GEMINI_MODEL. None means "use the runtime
    # default" — the operator hasn't overridden. Stored verbatim;
    # we don't validate that the model id is currently available
    # (operator could revoke a provider after creating the job).
    model_id: str | None = None
    # Extended thinking mode. When true, the
    # dispatcher adds `thinking: true` to the request body so the
    # chat route configures the provider for extended-reasoning
    # behavior (e.g. Gemini's thinkingConfig). The effect depends on
    # the model — flash variants ignore it, pro variants honor it.
    thinking_enabled: bool = False
    # Per-job permission policy. Declarative
    # tool allowlist enforced by the chat-route's tool-dispatch loop:
    # before each tool fires, the loop evaluates the policy and may
    # short-circuit with a synthetic deny (the model sees the result
    # as a tool error, the chat thread surfaces the denial reason).
    # JSON blob shape:
    #   {
    #     "allowed_tools":  ["pattern", ...],   # whitelist (globs)
    #     "denied_tools":   ["pattern", ...]    # blacklist (globs)
    #   }
    # Approval cards are decided by the manifest's humanRequired list, not
    # by the policy. A legacy "require_approval" key (removed in v1.0.3) is
    # dropped when a job is created or updated; a stored row that still has
    # it is read and the key ignored.
    # Glob syntax: same as HookMatcher.toolGlob (`*`, `?`, comma-list).
    # Empty arrays = "no constraint on that dimension." Empty policy
    # object {} = no restrictions (equivalent to None). None means
    # "use the default policy at dispatch time" (the runtime default
    # is fully permissive — operator opts INTO restrictions).
    permission_policy: dict[str, Any] | None = None
    # Operator's free-text note about what the job is for (the /jobs/new
    # form's Description field). "" when none; rows stored before the column
    # existed read as "".
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "cron": self.cron,
            "timezone": self.timezone,
            "action": self.action,
            "enabled": self.enabled,
            "removed": self.removed,
            "last_fired_at": self.last_fired_at,
            "last_status": self.last_status,
            "last_error": self.last_error,
            "next_due_at": self.next_due_at,
            "registered_at": self.registered_at,
            "source": self.source,
            "run_once": self.run_once,
            "run_count": self.run_count,
            "bypass_approvals": self.bypass_approvals,
            "model_id": self.model_id,
            "thinking_enabled": self.thinking_enabled,
            "permission_policy": self.permission_policy,
            "description": self.description,
        }


@dataclass(frozen=True)
class JobRun:
    """One row from the job_runs table."""

    id: str
    job_name: str
    fired_at: str
    finished_at: str | None
    status: str
    duration_ms: int | None
    result_json: str | None
    error: str | None
    trigger: str

    def to_dict(self) -> dict[str, Any]:
        result: Any = None
        if self.result_json:
            try:
                result = json.loads(self.result_json)
            except json.JSONDecodeError:
                result = self.result_json
        return {
            "id": self.id,
            "job_name": self.job_name,
            "fired_at": self.fired_at,
            "finished_at": self.finished_at,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "result": result,
            "error": self.error,
            "trigger": self.trigger,
        }


class CroniterJobScheduler:
    """Sqlite-backed scheduler driven by manifest.yaml:jobs[].

    Lifecycle:
      1. Construct with the manifest's job definitions + a
         tool_dispatcher callable (so the scheduler can fire
         action.type=="tool_call" jobs through the same registry the
         MCP server uses).
      2. `register_jobs()` reconciles the definitions with the
         persisted state — inserts new rows, marks vanished jobs as
         removed, leaves the enabled flag alone for existing jobs.
      3. `start()` spawns the master asyncio task. `stop()` cancels it.
      4. The master loop wakes up at MAX_SLEEP_SECONDS or sooner,
         finds jobs whose next_due_at has passed, and fires them.
    """

    def __init__(
        self,
        *,
        definitions: list[JobDefinition],
        dispatcher: ToolDispatcher,
        data_root: Path | None = None,
    ) -> None:
        if croniter is None:
            raise RuntimeError(
                "croniter is required for CroniterJobScheduler "
                f"(import error: {_IMPORT_ERROR})"
            )
        self._defs = list(definitions)
        self._dispatcher = dispatcher
        self._data_root = (data_root or self._resolve_data_root()).resolve()
        self._data_root.mkdir(parents=True, exist_ok=True)
        self._db_path = self._data_root / "jobs.db"
        self._lock = threading.Lock()
        self._task: asyncio.Task | None = None
        self._stop_event: asyncio.Event | None = None
        # YAML load errors collected for the
        # /api/v1/jobs/yaml-issues endpoint. Initialized empty so
        # consumers can read it even before load_yaml_jobs() runs.
        self.yaml_load_issues: list[dict[str, Any]] = []
        self._init_schema()
        self.register_jobs()
        # Reconcile YAML-on-disk runtime jobs into SQLite. Per spark-
        # agents spec §7.1: <data_root>/jobs/*.yaml are operator-
        # editable runtime job definitions; SQLite is the runtime
        # state cache. Re-running this is idempotent (load_yaml_jobs
        # explains which side wins which field). Manifest jobs already
        # loaded above; YAML jobs come second and never overwrite a
        # manifest row (a name collision is reported as a load issue).
        loaded_yaml = self.load_yaml_jobs()
        # Bring every mirror file in line with SQLite (and the current banner),
        # so files written by an older build stop claiming a state the job
        # no longer has.
        self.converge_job_mirrors()
        logger.info(
            "CroniterJobScheduler at %s — %d job(s) from manifest + %d from YAML mirror",
            self._db_path, len(self._defs), loaded_yaml,
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
                CREATE TABLE IF NOT EXISTS jobs (
                    name           TEXT PRIMARY KEY,
                    cron           TEXT NOT NULL,
                    timezone       TEXT NOT NULL,
                    action_json    TEXT NOT NULL,
                    enabled        INTEGER NOT NULL DEFAULT 1,
                    removed        INTEGER NOT NULL DEFAULT 0,
                    last_fired_at  TEXT,
                    last_status    TEXT,
                    last_error     TEXT,
                    next_due_at    TEXT,
                    registered_at  TEXT NOT NULL,
                    source         TEXT NOT NULL DEFAULT 'manifest',
                    run_once       INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            # Migration: add `source`, `run_once`, and `id` columns to
            # existing tables that predate runtime job CRUD / one-shot
            # jobs / opaque-identifier URLs. SQLite's IF NOT EXISTS on
            # the ALTER doesn't exist, so probe pragma_table_info first.
            cols = {r["name"] for r in c.execute("PRAGMA table_info(jobs)").fetchall()}
            if "source" not in cols:
                c.execute(
                    "ALTER TABLE jobs ADD COLUMN source TEXT NOT NULL DEFAULT 'manifest'"
                )
            if "run_once" not in cols:
                c.execute(
                    "ALTER TABLE jobs ADD COLUMN run_once INTEGER NOT NULL DEFAULT 0"
                )
            # Per-job approval bypass. When true, the scheduler
            # sets `X-Phantom-Approval-Bypass: 1` on every chat dispatch
            # for this job, which causes the MCP-side gate to auto-
            # approve gated tools (recording an audit row) instead of
            # blocking on operator confirmation. Default 0 — operators
            # opt in per-job via the job edit form's slider.
            if "bypass_approvals" not in cols:
                c.execute(
                    "ALTER TABLE jobs ADD COLUMN bypass_approvals INTEGER NOT NULL DEFAULT 0"
                )
            # Per-job model override + extended-thinking toggle. Both
            # nullable/defaulted so rows created before the columns
            # existed get the "use runtime default / thinking off"
            # behavior.
            if "model_id" not in cols:
                c.execute("ALTER TABLE jobs ADD COLUMN model_id TEXT")
            if "thinking_enabled" not in cols:
                c.execute(
                    "ALTER TABLE jobs ADD COLUMN thinking_enabled INTEGER NOT NULL DEFAULT 0"
                )
            # Per-job permission policy as a JSON
            # blob. Same nullable additive pattern: NULL = "no policy"
            # (no restrictions enforced); non-NULL = the declarative
            # allowlist the chat-route's tool-dispatch loop checks
            # before firing each tool.
            if "permission_policy_json" not in cols:
                c.execute(
                    "ALTER TABLE jobs ADD COLUMN permission_policy_json TEXT"
                )
            # Operator's note on the job. NOT NULL DEFAULT '' so rows from
            # before the column existed read as empty with no backfill.
            if "description" not in cols:
                c.execute(
                    "ALTER TABLE jobs ADD COLUMN description TEXT NOT NULL DEFAULT ''"
                )
            if "id" not in cols:
                # `id` is an opaque UUID; UI uses it for stable URLs that
                # don't churn on operator-facing rename and don't need
                # path encoding. `name` stays the human-facing label and
                # the agent-tool-facing key (jobs_get/update/delete take
                # name; manifest reconciliation looks up by name).
                # SQLite can't add a NOT NULL column with no default to
                # a non-empty table, so we add it nullable, backfill
                # UUIDs, then enforce uniqueness via index. (We can't
                # ALTER … ADD CONSTRAINT either.)
                c.execute("ALTER TABLE jobs ADD COLUMN id TEXT")
                # Backfill: assign a UUID to each existing row.
                rows_to_backfill = c.execute(
                    "SELECT name FROM jobs WHERE id IS NULL OR id = ''"
                ).fetchall()
                for r in rows_to_backfill:
                    c.execute(
                        "UPDATE jobs SET id = ? WHERE name = ?",
                        (str(uuid.uuid4()), r["name"]),
                    )
                c.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_id ON jobs(id)"
                )

            # Collapse job action types to {prompt, tool_call}.
            # The two legacy extras get migrated in place:
            #   - chat → prompt   (rename — same dispatch behavior)
            #   - log  → tool_call(xlog.create_data_worker, <flat args>)
            #     (the log shortcut was already syntactic sugar over a
            #     data-worker tool_call; rewriting the action_json gives
            #     operators a single mental model and lets us delete the
            #     dispatch branch.)
            # Idempotent: rows that already have type=prompt or
            # type=tool_call are left alone. Runs every boot so re-imports
            # of an old manifest also get normalized.
            self._migrate_action_types(c)
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS job_runs (
                    id           TEXT PRIMARY KEY,
                    job_name     TEXT NOT NULL,
                    fired_at     TEXT NOT NULL,
                    finished_at  TEXT,
                    status       TEXT NOT NULL,
                    duration_ms  INTEGER,
                    result_json  TEXT,
                    error        TEXT,
                    trigger      TEXT NOT NULL
                )
                """
            )
            c.execute(
                "CREATE INDEX IF NOT EXISTS idx_job_runs_name_fired "
                "ON job_runs(job_name, fired_at)"
            )

    def _migrate_action_types(self, c: sqlite3.Connection) -> None:
        """Idempotent in-place migration of action.type values.

        Two transforms:
          - {type: "chat", message} → {type: "prompt", message}
          - {type: "log", <log_args>} → {type: "tool_call",
                                         name: "xlog.create_data_worker",
                                         args: <log_args>}
                                         where log_args is the action
                                         object minus the "type" key,
                                         and "format" is renamed to
                                         "type" because the underlying
                                         tool's own args use `type` for
                                         the log format (JSON / CEF /
                                         LEEF / SYSLOG / WINEVENT). args
                                         is passed flat — the tool takes
                                         its parameters directly, not
                                         wrapped in a "request" key.

        Why migrate vs. keep dispatching the legacy types: the operator
        wants only two job types — prompt + tool_call — to keep the
        mental model simple. Mid-flight legacy rows are converted on
        boot so they keep firing under the new dispatch path without
        the operator having to recreate them by hand.

        Idempotent: a second run of the same migration sees only
        prompt + tool_call rows and changes nothing.
        """
        rows = c.execute("SELECT name, action_json FROM jobs").fetchall()
        migrated = {"chat": 0, "log": 0}
        for row in rows:
            try:
                action = json.loads(row["action_json"])
            except (json.JSONDecodeError, TypeError):
                # Corrupt action_json — skip; the dispatcher will fail
                # this row at fire time with a clear error and the
                # operator can recreate it.
                continue
            if not isinstance(action, dict):
                continue
            t = action.get("type")
            if t == "chat":
                action["type"] = "prompt"
                c.execute(
                    "UPDATE jobs SET action_json = ? WHERE name = ?",
                    (json.dumps(action), row["name"]),
                )
                migrated["chat"] += 1
            elif t == "log":
                # Lift the log-shortcut keys into a tool_call request.
                # Field-name reverse mapping mirrors what the legacy
                # `log` dispatch branch did at fire time.
                log_args = {
                    k: v for k, v in action.items()
                    if k not in ("type", "name", "args")
                }
                if "format" in log_args and "type" not in log_args:
                    log_args["type"] = log_args.pop("format")
                new_action = {
                    "type": "tool_call",
                    "name": "xlog.create_data_worker",
                    "args": log_args,
                }
                c.execute(
                    "UPDATE jobs SET action_json = ? WHERE name = ?",
                    (json.dumps(new_action), row["name"]),
                )
                migrated["log"] += 1
        if migrated["chat"] or migrated["log"]:
            logger.info(
                "JobScheduler: migrated job action types — "
                "chat→prompt: %d, log→tool_call: %d",
                migrated["chat"], migrated["log"],
            )

    @staticmethod
    def _now_iso(epoch: float | None = None) -> str:
        t = epoch if epoch is not None else time.time()
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))

    @staticmethod
    def _now_iso_usec() -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%S.", time.gmtime()) + (
            f"{int((time.time() % 1) * 1_000_000):06d}Z"
        )

    def _resolve_tz(self, tz_name: str) -> Any:
        if not tz_name or tz_name == "UTC":
            return timezone.utc
        if ZoneInfo is None:
            return timezone.utc
        try:
            return ZoneInfo(tz_name)
        except Exception as exc:
            logger.warning(
                "Job tz %r unrecognized (%s) — falling back to UTC",
                tz_name, exc,
            )
            return timezone.utc

    def _next_due_epoch(self, j: JobRow, *, after: float | None = None) -> float:
        """Compute the next fire time as a UTC epoch."""
        base_epoch = after if after is not None else time.time()
        tz = self._resolve_tz(j.timezone)
        base_dt = datetime.fromtimestamp(base_epoch, tz=tz)
        it = croniter(j.cron, base_dt)
        nxt = it.get_next(datetime)
        # croniter returns tz-aware datetime → cast to UTC epoch.
        return nxt.timestamp()

    @staticmethod
    def _is_completed_run_once(j: JobRow) -> bool:
        """True for a run-once job that already fired and is now disabled."""
        return bool(j.run_once and j.last_fired_at and not j.enabled)

    def _scheduled_next_due(self, j: JobRow) -> str | None:
        """ISO next-fire time for `j`, or None when it has none.

        A job only has a next run while it is enabled and not removed.
        A paused (or never-enabled, or completed run-once) job is never
        picked up by the tick loop, so any stored value would go stale
        and the UI would show "next run 4h ago" for it. Resuming
        recomputes from now, which also stops a stale past value being
        replayed as an immediate catch-up fire. (Resuming a COMPLETED
        run-once job is refused before this is reached: see
        `set_enabled` / `update_job`.)
        """
        if not j.enabled or j.removed:
            return None
        return self._now_iso(self._next_due_epoch(j))

    # ─── Reconciliation with manifest ─────────────────────────

    def register_jobs(self) -> None:
        """Reconcile manifest definitions with persisted state.

        - New jobs get inserted (enabled=1).
        - Existing jobs have their cron/tz/action updated (manifest
          is the source of truth for those).
        - Jobs no longer in the manifest get `removed=1` so they
          stop firing but their run history stays queryable.
        - The enabled flag is preserved across reboots — operator
          intent survives a redeploy.
        """
        from usecase.audit_log import ACTION_JOB_REGISTERED, record_event

        now = self._now_iso()
        manifest_names = {d.name for d in self._defs}

        with self._lock, self._conn() as c:
            # Pull existing rows together with their `source` so we know
            # which to reconcile (manifest) and which to leave alone
            # (runtime). Runtime jobs persist across boots untouched.
            existing_rows = c.execute(
                "SELECT name, enabled, source FROM jobs"
            ).fetchall()
            existing = {
                r["name"]: {"enabled": bool(r["enabled"]), "source": r["source"] or "manifest"}
                for r in existing_rows
            }
            existing_manifest_names = {n for n, m in existing.items() if m["source"] == "manifest"}

            # Insert / update from manifest.
            for d in self._defs:
                # Compute next_due so the API can show it without
                # waiting for the master loop's first tick.
                tmp = JobRow(
                    name=d.name, cron=d.cron, timezone=d.timezone,
                    action=d.action, enabled=existing.get(d.name, {}).get("enabled", True),
                    removed=False,
                    last_fired_at=None, last_status=None, last_error=None,
                    next_due_at=None, registered_at=now,
                    source="manifest",
                )
                next_due_iso = self._scheduled_next_due(tmp)

                if d.name in existing:
                    # Reset source to manifest in case a prior run had
                    # the same name as a runtime job (defensive — names
                    # collide only if an operator was sloppy).
                    c.execute(
                        "UPDATE jobs SET cron = ?, timezone = ?, "
                        "action_json = ?, removed = 0, next_due_at = ?, "
                        "source = 'manifest' "
                        "WHERE name = ?",
                        (d.cron, d.timezone, json.dumps(d.action),
                         next_due_iso, d.name),
                    )
                else:
                    c.execute(
                        "INSERT INTO jobs "
                        "(name, id, cron, timezone, action_json, enabled, "
                        " removed, next_due_at, registered_at, source) "
                        "VALUES (?, ?, ?, ?, ?, 1, 0, ?, ?, 'manifest')",
                        (d.name, str(uuid.uuid4()), d.cron, d.timezone,
                         json.dumps(d.action), next_due_iso, now),
                    )

            # Mark MANIFEST jobs that vanished from the YAML as removed.
            # Runtime-created jobs survive — `removed` is operator intent
            # for those, not "manifest no longer declares this".
            removed = [
                n for n in existing_manifest_names if n not in manifest_names
            ]
            for n in removed:
                c.execute(
                    "UPDATE jobs SET removed = 1, next_due_at = NULL "
                    "WHERE name = ?", (n,),
                )

        for d in self._defs:
            record_event(
                ACTION_JOB_REGISTERED,
                target=f"job:{d.name}",
                status="success",
                metadata={
                    "job_name": d.name,
                    "cron": d.cron,
                    "timezone": d.timezone,
                    "action_type": d.action_type,
                    "action_name": d.action_name,
                },
            )
        if removed:
            logger.info(
                "JobScheduler: %d job(s) removed from manifest, marked inactive: %s",
                len(removed), removed,
            )

    # ─── Scheduler loop ────────────────────────────────────────

    async def start(self) -> None:
        """Spawn the master loop. Idempotent — re-calling is a no-op."""
        if self._task is not None and not self._task.done():
            return
        self._stop_event = asyncio.Event()
        self._task = asyncio.create_task(self._run_loop())
        logger.info(
            "CroniterJobScheduler started (max_sleep=%.0fs)", MAX_SLEEP_SECONDS
        )

    def stop(self) -> None:
        """Signal the master loop to exit at its next wake-up.

        Doesn't await — callers should `await scheduler.task` to join.
        """
        if self._stop_event is not None:
            self._stop_event.set()

    @property
    def task(self) -> asyncio.Task | None:
        return self._task

    async def _run_loop(self) -> None:
        """Master loop: wake periodically, fire due jobs."""
        assert self._stop_event is not None
        while not self._stop_event.is_set():
            try:
                await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("JobScheduler tick failed: %s", exc)
            # Sleep with cancellation-aware wait so stop() takes effect quickly.
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=MAX_SLEEP_SECONDS,
                )
            except asyncio.TimeoutError:
                pass
        logger.info("CroniterJobScheduler loop exited")

    async def _tick(self) -> None:
        """One pass: find jobs due now, fire them, update next_due."""
        now_epoch = time.time()
        due_jobs = self._read_due_jobs(now_epoch)
        if not due_jobs:
            return
        for row in due_jobs:
            await self._fire(row, trigger="cron")

    def _read_due_jobs(self, now_epoch: float) -> list[JobRow]:
        """Return all enabled, non-removed jobs whose next_due_at is past."""
        cutoff = self._now_iso(now_epoch)
        with self._lock, self._conn() as c:
            rows = c.execute(
                "SELECT * FROM jobs "
                "WHERE enabled = 1 AND removed = 0 "
                "  AND (next_due_at IS NOT NULL AND next_due_at <= ?)",
                (cutoff,),
            ).fetchall()
        return [self._row_to_jobrow(r) for r in rows]

    # ─── Fire one job ──────────────────────────────────────────

    async def _fire(self, row: JobRow, *, trigger: str = "cron") -> JobRun:
        """Execute one job's action. Records run + audit. Returns JobRun."""
        from usecase.audit_log import (
            ACTION_JOB_COMPLETED,
            ACTION_JOB_FAILED,
            ACTION_JOB_FIRED,
            ACTION_JOB_SKIPPED,
            record_event,
        )

        run_id = str(uuid.uuid4())
        fired_at = self._now_iso_usec()
        record_event(
            ACTION_JOB_FIRED,
            target=f"job:{row.name}",
            status="pending",
            metadata={
                "job_name": row.name,
                "trigger": trigger,
                "cron": row.cron,
                "action_type": str(row.action.get("type", "")),
                "action_name": str(row.action.get("name", "")),
            },
        )

        # Insert the run row up-front in pending state so the audit
        # endpoint can show "currently running" jobs.
        with self._lock, self._conn() as c:
            c.execute(
                "INSERT INTO job_runs "
                "(id, job_name, fired_at, status, trigger) "
                "VALUES (?, ?, ?, 'pending', ?)",
                (run_id, row.name, fired_at, trigger),
            )

        start_perf = time.perf_counter()
        status = "success"
        error: str | None = None
        result: Any = None

        action_type = str(row.action.get("type") or "")
        action_name = str(row.action.get("name") or "")
        action_args = row.action.get("args") or {}
        if not isinstance(action_args, dict):
            action_args = {}

        try:
            if action_type == "tool_call":
                if not action_name:
                    raise ValueError("action.name is required for tool_call")
                logger.info(
                    "JobScheduler firing %s → %s(%s) [trigger=%s]",
                    row.name, action_name,
                    ",".join(action_args.keys()) or "no args", trigger,
                )
                result = await self._dispatcher(action_name, action_args)
            elif action_type in ("prompt", "chat"):
                # Only two job action types exist — `prompt` and
                # `tool_call`. `chat` is accepted as an alias for
                # `prompt` (the boot migration normalizes existing rows;
                # this alias is here purely for in-flight requests
                # arriving during the migration window or from older
                # API clients).
                #
                # action: {type: "prompt", message: "...", skill?: "name"}.
                # Loops back through the agent's /api/chat endpoint so
                # the scheduled prompt runs through the SAME pipeline
                # an interactive operator chat goes through:
                #   - system prompt with personalityMd + live skills
                #     registry applied (the /api/chat handler always
                #     calls fetchPersonalityForPrompt() and
                #     fetchSkillsForPrompt() — confirmed parity with
                #     operator-driven chat)
                #   - memory + KB tools available (memory_search,
                #     memory_store, knowledge_search) for the agent
                #     to call on demand
                #   - tool dispatch + audit + session persistence
                # The scheduler doesn't call Gemini directly —
                # provider.chat() is NotImplementedError by design:
                # the model call lives in the agent layer.
                #
                # Optional `skill` field. When set,
                # the scheduler resolves the skill MD body once at
                # dispatch time and prepends it to the user message
                # in a <skill>…</skill> wrapper. This makes scheduled
                # runs deterministic: regardless of model drift, the
                # specific skill the operator chose runs. When unset
                # (the default), the agent's system prompt already
                # contains the skills registry metadata so the model
                # decides for itself which skill (if any) applies.
                message = str(row.action.get("message") or "").strip()
                if not message:
                    raise ValueError("action.message is required for prompt")
                skill_name = str(row.action.get("skill") or "").strip()
                if skill_name:
                    skill_body = self._load_skill_body(skill_name)
                    if skill_body is None:
                        logger.warning(
                            "JobScheduler %s: skill %r not found on disk, "
                            "falling back to plain prompt without binding",
                            row.name, skill_name,
                        )
                    else:
                        # Wrap so the agent sees the skill body as a
                        # distinct, attributable section rather than
                        # mixed into the operator's task. The model is
                        # already trained to respect <skill> blocks
                        # via the system-prompt instruction
                        # (renderSkillsBlock).
                        message = (
                            f"<skill name=\"{skill_name}\">\n"
                            f"{skill_body}\n"
                            f"</skill>\n\n"
                            f"{message}"
                        )
                        logger.info(
                            "JobScheduler %s: bound to skill %r (+%d chars)",
                            row.name, skill_name, len(skill_body),
                        )
                # Skill-side overrides.
                # When a job is bound to a skill (action.skill = X)
                # AND the skill's MD frontmatter declares model: /
                # thinking: / permissions: blocks, those serve as
                # fallback values for whichever job fields are unset.
                # Operator-explicit job-level overrides always win;
                # the skill-side fields fill in defaults so a skill
                # author can recommend "this skill works best on Pro
                # with thinking" and a job that doesn't override gets
                # that recommendation.
                effective_model_id = row.model_id
                effective_thinking = row.thinking_enabled
                effective_policy = row.permission_policy
                if skill_name:
                    fm = self._parse_skill_frontmatter(skill_name)
                    if not effective_model_id and isinstance(fm.get("model"), str):
                        effective_model_id = fm["model"].strip() or None
                    # row.thinking_enabled defaults to False; only
                    # adopt skill's True when job hasn't explicitly
                    # opted IN. (Skill author saying "thinking: false"
                    # can't override a job-side True — operator wins.)
                    if not effective_thinking and fm.get("thinking") is True:
                        effective_thinking = True
                    if effective_policy is None and isinstance(fm.get("permissions"), dict):
                        # Normalize to the same shape the chat-route
                        # validator expects.
                        effective_policy = fm["permissions"]
                logger.info(
                    "JobScheduler firing %s → prompt: %.80s [trigger=%s]",
                    row.name, message, trigger,
                )
                result = await self._dispatch_chat(
                    message, row.name,
                    bypass_approvals=row.bypass_approvals,
                    model_id=effective_model_id,
                    thinking_enabled=effective_thinking,
                    permission_policy=effective_policy,
                )
            else:
                # `log` is not an action type — exactly two exist,
                # prompt + tool_call. The
                # boot migration converts existing log rows to
                # tool_call(phantom_create_data_worker, …) shape, so
                # this branch should be unreachable in practice. Any
                # post-migration row with a foreign action_type was
                # either externally injected (bad client) or somehow
                # escaped the migration. Surface the failure clearly.
                status = "skipped"
                error = (
                    f"unsupported action type {action_type!r} — "
                    f"only 'prompt' and 'tool_call' are supported. "
                    f"If this job predates that rule it should have "
                    f"been auto-migrated at boot; recreate it via "
                    f"/jobs/new if it didn't."
                )
                logger.warning(
                    "JobScheduler skipping %s — %s", row.name, error,
                )
        except Exception as exc:
            status = "failure"
            error = f"{type(exc).__name__}: {exc}"
            logger.exception("JobScheduler %s failed: %s", row.name, exc)

        duration_ms = int((time.perf_counter() - start_perf) * 1000)
        finished_at = self._now_iso_usec()

        # Try to JSON-serialize the result; fall back to repr() so the
        # row stays well-formed even if a tool returns a non-JSON object.
        result_json: str | None
        if result is None:
            result_json = None
        else:
            try:
                result_json = json.dumps(result, default=str)
            except (TypeError, ValueError):
                result_json = json.dumps({"_repr": repr(result)})

        # Compute next_due AFTER the fire so a long-running job doesn't
        # double-fire. Base it on `now` rather than on the previous
        # next_due so a job that was overdue at boot doesn't fire
        # repeatedly to "catch up".
        next_due_epoch = self._next_due_epoch(row, after=time.time())
        next_due_iso = self._now_iso(next_due_epoch)

        # `run_once` jobs auto-disable after their first fire (success
        # OR failure — both count). The cron column stays as-is so the
        # operator can see what schedule was used; Resume is refused
        # for a fired run-once job (its cron has no year). We
        # also clear next_due_at so the disabled job doesn't show a
        # phantom "next run" in the UI. The READ side filters disabled
        # jobs from the tick loop already (see _read_due_jobs WHERE
        # enabled = 1) so this is the only mutation needed.
        new_enabled = 0 if row.run_once else (1 if row.enabled else 0)

        # Auto-disable jobs whose target tool isn't registered.
        # KeyError text from _build_dispatch is "job action references
        # unknown tool ..." — these failures will never recover without
        # operator intervention (the tool genuinely doesn't exist on
        # this MCP), so re-firing every cron tick is pure noise that
        # bloats the audit log + the session feed.
        # Example: a manifest job pointing at a tool that was never
        # shipped fires on every tick and adds a failed-job row each time.
        if (
            status == "failure"
            and error
            and "references unknown tool" in error
            and not row.run_once
        ):
            new_enabled = 0
            logger.warning(
                "JobScheduler auto-disabled %s — target tool not registered "
                "(error: %s). Re-enable via PATCH after the tool is shipped.",
                row.name, error,
            )
        # Also back off jobs that fail for ANY persistent
        # reason (not just unknown-tool). Count trailing consecutive
        # failures (this run is still 'pending' in job_runs, so add 1);
        # once it crosses the threshold, disable so the job stops flooding
        # the audit log. The operator re-enables via PATCH after the fix.
        elif status == "failure" and not row.run_once and new_enabled == 1:
            consecutive = self._trailing_failure_count(row.name, run_id) + 1
            if consecutive >= MAX_CONSECUTIVE_FAILURES:
                new_enabled = 0
                error = (error or "scheduled job failed") + (
                    f" [auto-disabled after {consecutive} consecutive "
                    f"failures — re-enable via PATCH once the cause is fixed]"
                )
                logger.warning(
                    "JobScheduler auto-disabled %s after %d consecutive "
                    "failures — re-enable via PATCH once the cause is fixed.",
                    row.name, consecutive,
                )

        new_next_due = None if row.run_once or new_enabled == 0 else next_due_iso

        with self._lock, self._conn() as c:
            c.execute(
                "UPDATE job_runs SET finished_at = ?, status = ?, "
                "duration_ms = ?, result_json = ?, error = ? "
                "WHERE id = ?",
                (finished_at, status, duration_ms, result_json, error, run_id),
            )
            c.execute(
                "UPDATE jobs SET last_fired_at = ?, last_status = ?, "
                "last_error = ?, next_due_at = ?, enabled = ? "
                "WHERE name = ?",
                (fired_at, status, error, new_next_due, new_enabled, row.name),
            )

        if row.run_once and new_enabled == 0:
            logger.info(
                "JobScheduler disabled run-once job %s after first fire "
                "(status=%s)", row.name, status,
            )
        if new_enabled != (1 if row.enabled else 0):
            # A fire that disables the job (run-once completion, unknown
            # tool, failure back-off) must reach the YAML mirror too, or
            # replaying the mirror into a fresh DB would arm it again.
            self._mirror_job_yaml(self.get_job(row.name))

        if duration_ms > WARN_AFTER_SECONDS * 1000:
            logger.warning(
                "JobScheduler %s ran for %dms — consider splitting work",
                row.name, duration_ms,
            )

        # Audit completion / failure / skipped.
        completion_action = (
            ACTION_JOB_COMPLETED if status == "success"
            else ACTION_JOB_SKIPPED if status == "skipped"
            else ACTION_JOB_FAILED
        )
        record_event(
            completion_action,
            target=f"job:{row.name}",
            status=status,
            duration_ms=duration_ms,
            metadata={
                "job_name": row.name,
                "run_id": run_id,
                "trigger": trigger,
                "action_name": action_name,
                # What was actually stored: None for a run-once job that
                # just finished, an auto-disabled job, or a manual run of
                # a paused job (none of them have a next run).
                "next_due_at": new_next_due,
                "error": error,
            },
        )

        # Surface every scheduled job run as a
        # notification so the operator gets feedback without having
        # to tail the jobs page. Skipped runs don't emit (they're
        # noise from cron-cap squelching). Failures get the
        # job-run-failed topic which the manifest declares as
        # severity=warning, so the bell badge updates.
        #
        # Best-effort: if the notification store isn't initialized
        # (some test paths), we silently skip rather than failing the
        # whole run. The audit row above is the canonical record.
        if status != "skipped":
            try:
                from .notifications import notification_store
                store = notification_store()
                if store is not None:
                    topic = (
                        "job-run-completed" if status == "success"
                        else "job-run-failed"
                    )
                    store.publish(
                        topic,
                        payload={
                            "job_name": row.name,
                            "run_id": run_id,
                            "trigger": trigger,
                            "action_name": action_name or action_type,
                            "duration_ms": duration_ms,
                            "next_due_at": new_next_due,
                            "error": error,
                            # Short summary the UI uses for the
                            # notification card without having to
                            # parse result_json. Truncate to keep
                            # the SQLite row small.
                            "summary": (
                                f"Job {row.name} succeeded in {duration_ms}ms"
                                if status == "success"
                                else f"Job {row.name} failed: {(error or 'unknown')[:200]}"
                            ),
                        },
                        actor=f"job_scheduler:{row.name}",
                    )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Failed to publish job-run notification for %s: %s",
                    row.name, exc,
                )

        return JobRun(
            id=run_id, job_name=row.name, fired_at=fired_at,
            finished_at=finished_at, status=status,
            duration_ms=duration_ms,
            result_json=result_json, error=error, trigger=trigger,
        )

    def _trailing_failure_count(self, job_name: str, exclude_run_id: str) -> int:
        """Count this job's most-recent consecutive 'failure' runs in
        job_runs, excluding the in-flight run (still 'pending' at this
        point). Used by the consecutive-failure back-off so a job that fails
        persistently (e.g. a 401 on /api/chat) auto-disables instead of
        re-firing every cron tick forever. Reads at most
        MAX_CONSECUTIVE_FAILURES rows via the (job_name, fired_at) index."""
        with self._conn() as c:
            rows = c.execute(
                "SELECT status FROM job_runs WHERE job_name = ? AND id != ? "
                "ORDER BY fired_at DESC LIMIT ?",
                (job_name, exclude_run_id, MAX_CONSECUTIVE_FAILURES),
            ).fetchall()
        n = 0
        for r in rows:
            if r["status"] == "failure":
                n += 1
            else:
                break
        return n

    async def _dispatch_chat(
        self, message: str, job_name: str,
        bypass_approvals: bool = False,
        model_id: str | None = None,
        thinking_enabled: bool = False,
        permission_policy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Fire a scheduled chat prompt through the agent's /api/chat
        endpoint. The agent middleware gates /api/chat
        (session cookie OR `phantom_ak_` API key); this server-side
        scheduler call carries neither, so it authenticates with the
        container's MCP_TOKEN as an internal-service bearer —
        the same loopback trust the /api/agent/internal/* routes use. The
        agent's route handlers still attach MCP_TOKEN themselves when they
        call the embedded MCP downstream.

        Streams the SSE response, accumulates `text_delta` and
        `tool_call`/`tool_result` frames into a structured result, and
        returns when the `done` event arrives. Errors propagate to the
        runner's catch block which records status=failure.

        The session_id is auto-created by the chat route when omitted —
        we let it pick a fresh one so each scheduled run is its own
        session, browseable in the chat sidebar like any other.

        When `model_id` is set, the request body
        includes `model: <id>` so the chat route's resolveModelName()
        picks it over runtimeConfig.GEMINI_MODEL. When `thinking_enabled`
        is True, the body also carries `thinking: true` — the chat
        route forwards that to the model provider's thinkingConfig (no-
        op on flash variants, honored on pro variants).

        When `bypass_approvals=True`, the request carries
        `X-Phantom-Approval-Bypass: 1` so the MCP-side gate auto-
        approves any humanRequired[] tools the agent calls during the
        job. Operators set this per-job via the job edit form. The
        chat route forwards the header onto every downstream MCP
        call (see PhantomMCPClient's extraHeaders) so the contextvar
        is set when gate_and_execute runs.
        """
        import os
        import httpx

        agent_url = os.environ.get(
            "PHANTOM_AGENT_INTERNAL_URL", DEFAULT_AGENT_INTERNAL_URL,
        ).rstrip("/")
        chat_endpoint = f"{agent_url}/api/chat"

        # The bearer that authenticates this loopback to the
        # middleware-gated /api/chat. Same MCP_TOKEN the agent uses to reach
        # the embedded MCP; read from the canonical pydantic-settings source.
        from usecase.agent_internal_auth import internal_chat_bearer  # noqa: PLC0415
        chat_bearer = internal_chat_bearer()

        text_parts: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        meta: dict[str, Any] = {}
        final_response = ""
        last_error: str | None = None

        # Build headers — bypass is conditional, the others are always
        # present. Unsetting bypass when False is intentional rather
        # than sending it explicitly false; the middleware reads
        # absence as the default of False, so omitting is cleaner.
        request_headers = {
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            # Tag the request so audit can identify scheduler-driven
            # turns vs. operator-driven.
            "X-Phantom-Trigger": f"job:{job_name}",
        }
        # Present MCP_TOKEN so the middleware gate on /api/chat accepts
        # this internal call. Without it every scheduled prompt job would
        # 401 with no_session_cookie.
        if chat_bearer:
            request_headers["Authorization"] = chat_bearer
        else:
            logger.warning(
                "JobScheduler %s: MCP_TOKEN unset — /api/chat call will 401 "
                "under the middleware gate", job_name,
            )
        if bypass_approvals:
            request_headers["X-Phantom-Approval-Bypass"] = "1"
            logger.info(
                "JobScheduler %s: dispatching with approval bypass ON",
                job_name,
            )

        # Assemble the body. The chat route
        # reads `body.model` via resolveModelName (single source of
        # model selection per the route's own discipline; see the
        # comment at chat/route.ts:2580+) and `body.thinking` for the
        # extended-thinking config.
        body: dict[str, Any] = {"message": message}
        if model_id:
            body["model"] = model_id
        if thinking_enabled:
            body["thinking"] = True
        # Per-job permission policy. Sent verbatim
        # as a JSON object; the chat-route evaluates it before each
        # tool call in the model loop. Empty/None means no policy.
        if permission_policy:
            body["permission_policy"] = permission_policy

        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(CHAT_ACTION_TIMEOUT_S),
            ) as client:
                async with client.stream(
                    "POST",
                    chat_endpoint,
                    json=body,
                    headers=request_headers,
                ) as resp:
                    if resp.status_code != 200:
                        body = (await resp.aread()).decode(errors="replace")
                        raise RuntimeError(
                            f"agent /api/chat returned {resp.status_code}: "
                            f"{body[:300]}"
                        )
                    event_type: str | None = None
                    async for raw_line in resp.aiter_lines():
                        line = raw_line.rstrip("\r")
                        if not line:
                            event_type = None
                            continue
                        if line.startswith("id: "):
                            continue
                        if line.startswith("event: "):
                            event_type = line[len("event: "):].strip()
                        elif line.startswith("data: "):
                            payload = line[len("data: "):]
                            try:
                                data = json.loads(payload)
                            except json.JSONDecodeError:
                                data = payload
                            if event_type == "meta" and isinstance(data, dict):
                                meta = data
                            elif (
                                event_type == "tool_call"
                                and isinstance(data, dict)
                            ):
                                tool_calls.append(
                                    {
                                        "name": data.get("name"),
                                        "args": data.get("arguments"),
                                    }
                                )
                            elif (
                                event_type == "tool_result"
                                and isinstance(data, dict)
                                and tool_calls
                                and tool_calls[-1].get("name")
                                == data.get("name")
                            ):
                                # Truncate the result so a 100KB JSON
                                # payload doesn't blow up the job_runs
                                # row. The full result is in the chat
                                # session transcript.
                                result_text = data.get("result", "")
                                tool_calls[-1]["result_status"] = data.get(
                                    "status"
                                )
                                tool_calls[-1]["result_preview"] = (
                                    result_text[:240]
                                    if isinstance(result_text, str)
                                    else str(result_text)[:240]
                                )
                            elif (
                                event_type == "text_delta"
                                and isinstance(data, dict)
                            ):
                                text_parts.append(data.get("text", ""))
                            elif event_type == "done" and isinstance(
                                data, dict
                            ):
                                final_response = data.get("response") or ""
                            elif event_type == "error":
                                last_error = (
                                    data
                                    if isinstance(data, str)
                                    else json.dumps(data)
                                )
        except httpx.TimeoutException as exc:
            raise RuntimeError(
                f"agent /api/chat timed out after {CHAT_ACTION_TIMEOUT_S}s"
            ) from exc

        if last_error and not final_response:
            # Stream emitted an `error` event without a `done` —
            # surface it as the run's failure.
            raise RuntimeError(f"chat error event: {last_error}")

        return {
            "session_id": meta.get("session_id"),
            "run_id": meta.get("run_id"),
            "response": final_response or "".join(text_parts),
            "tool_calls": tool_calls,
            "tool_call_count": len(tool_calls),
        }

    # ─── External APIs (used by /api/v1/jobs) ──────────────────

    def list_jobs(self, *, include_removed: bool = False) -> list[JobRow]:
        # Correlated subquery against job_runs gives us a per-job
        # lifetime fire count without a separate trip per row. The
        # idx_job_runs_name_fired index covers the `job_name = ?`
        # equality so this stays O(unique-jobs * log N).
        clause = "" if include_removed else "WHERE removed = 0"
        with self._lock, self._conn() as c:
            rows = c.execute(
                f"""
                SELECT j.*,
                       (SELECT COUNT(*) FROM job_runs jr
                        WHERE jr.job_name = j.name) AS run_count
                FROM jobs j {clause}
                ORDER BY j.name
                """
            ).fetchall()
        return [self._row_to_jobrow(r) for r in rows]

    def get_job(self, name: str) -> JobRow | None:
        with self._lock, self._conn() as c:
            row = c.execute(
                """
                SELECT j.*,
                       (SELECT COUNT(*) FROM job_runs jr
                        WHERE jr.job_name = j.name) AS run_count
                FROM jobs j WHERE j.name = ?
                """,
                (name,),
            ).fetchone()
        return self._row_to_jobrow(row) if row else None

    def get_job_by_id(self, job_id: str) -> JobRow | None:
        """Lookup by opaque UUID. Used by the API resolver to support
        URL paths like `/api/v1/jobs/{id}` alongside the legacy
        `/api/v1/jobs/{name}`. Internal callers (manifest reconciliation,
        agent self-mod tools) still use get_job(name)."""
        if not job_id:
            return None
        with self._lock, self._conn() as c:
            row = c.execute(
                """
                SELECT j.*,
                       (SELECT COUNT(*) FROM job_runs jr
                        WHERE jr.job_name = j.name) AS run_count
                FROM jobs j WHERE j.id = ?
                """,
                (job_id,),
            ).fetchone()
        return self._row_to_jobrow(row) if row else None

    def resolve_ident(self, ident: str) -> JobRow | None:
        """Accept either an opaque UUID or a name; return the row or
        None. UUIDs are first-tried because the UI prefers them now;
        names are the path used by the manifest, agent self-mod tools
        and any caller holding a name-based link. On collision (a job named like a UUID), id wins —
        practically impossible since add_job mints UUIDs at insert and
        the manifest uses readable names."""
        if not ident:
            return None
        # Hyphenated 36-char strings shaped like UUIDs go to id lookup
        # first; everything else (and id-shaped strings that don't
        # match any row) falls through to name.
        if _looks_like_uuid(ident):
            row = self.get_job_by_id(ident)
            if row is not None:
                return row
        return self.get_job(ident)

    def list_runs(
        self, name: str, *, limit: int = 20
    ) -> list[JobRun]:
        with self._lock, self._conn() as c:
            rows = c.execute(
                "SELECT * FROM job_runs WHERE job_name = ? "
                "ORDER BY fired_at DESC LIMIT ?",
                (name, max(1, min(limit, 200))),
            ).fetchall()
        return [self._row_to_jobrun(r) for r in rows]

    def set_enabled(self, name: str, enabled: bool) -> JobRow | None:
        """Pause (`enabled=False`) or resume (`enabled=True`) a job.

        Raises CompletedRunOnceError when asked to resume a run-once job
        that already fired: its stored cron has no year, so resuming would
        arm it for the same date next year. Give it a new Run-at time
        (`update_job(cron=...)`) or duplicate it instead.
        """
        from usecase.audit_log import (
            ACTION_JOB_DISABLED,
            ACTION_JOB_ENABLED,
            record_event,
        )

        with self._lock, self._conn() as c:
            row = c.execute(
                "SELECT * FROM jobs WHERE name = ?", (name,)
            ).fetchone()
            if row is None:
                return None
            # Pausing clears next_due_at; resuming recomputes it from
            # now. Without this a paused job kept a frozen next_due_at
            # that slid into the past, and resuming it fired a catch-up
            # run on the next tick.
            current = self._row_to_jobrow(row)
            if enabled and not current.enabled and self._is_completed_run_once(current):
                raise CompletedRunOnceError(_completed_run_once_message(name))
            next_due_iso = self._scheduled_next_due(
                replace(current, enabled=enabled)
            )
            c.execute(
                "UPDATE jobs SET enabled = ?, next_due_at = ? WHERE name = ?",
                (1 if enabled else 0, next_due_iso, name),
            )
            updated = c.execute(
                "SELECT * FROM jobs WHERE name = ?", (name,)
            ).fetchone()
        record_event(
            ACTION_JOB_ENABLED if enabled else ACTION_JOB_DISABLED,
            target=f"job:{name}",
            status="success",
            metadata={"job_name": name},
        )
        out = self._row_to_jobrow(updated) if updated else None
        if out is not None:
            self._mirror_job_yaml(out)
        return out

    async def trigger_now(self, name: str) -> JobRun | None:
        """Fire a job immediately, out of band. Used by /jobs/{name}/run."""
        row = self.get_job(name)
        if row is None or row.removed:
            return None
        return await self._fire(row, trigger="manual")

    # ─── Runtime CRUD (used by POST/PATCH/DELETE /api/v1/jobs) ──
    #
    # Runtime jobs are persisted with source='runtime' and survive
    # boots untouched (manifest reconciliation skips them). The
    # cron string is validated by attempting to parse with croniter
    # before the row is written; an invalid expression raises
    # ValueError so the route handler can return 400.

    @staticmethod
    def _validate_description(description: Any) -> str:
        """A description is plain text up to MAX_DESCRIPTION_CHARS; None is empty."""
        if description is None:
            return ""
        if not isinstance(description, str):
            raise ValueError("description must be a string")
        text = description.strip()
        if len(text) > MAX_DESCRIPTION_CHARS:
            raise ValueError(
                f"description is {len(text)} characters; the limit is {MAX_DESCRIPTION_CHARS}"
            )
        return text

    @staticmethod
    def _validate_cron(cron: str, tz: Any) -> None:
        try:
            croniter(cron, datetime.now(tz=tz))
        except Exception as exc:  # noqa: BLE001 - croniter raises generic Exception
            raise ValueError(f"invalid cron expression: {cron!r} ({exc})") from exc

    @staticmethod
    def _validate_action(action: dict[str, Any]) -> None:
        if not isinstance(action, dict):
            raise ValueError("action must be an object")
        action_type = action.get("type")
        # Only `prompt` and `tool_call` are valid action types.
        # `chat` is accepted as a legacy alias for `prompt` (the same
        # alias the dispatcher honors at fire time, for back-compat with
        # API clients that haven't been updated yet).
        if action_type not in ("tool_call", "prompt", "chat"):
            raise ValueError(
                f"action.type must be one of tool_call|prompt, got "
                f"{action_type!r}"
            )
        if action_type == "tool_call":
            if not isinstance(action.get("name"), str) or not action["name"]:
                raise ValueError("tool_call action requires a non-empty `name`")
            # Refuse at creation, not only at fire time, so the agent gets an
            # immediate error instead of a job that fails every run.
            assert_no_credential_tools([action["name"]], where="job action")
            args = action.get("args", {})
            if args is not None and not isinstance(args, dict):
                raise ValueError("tool_call action `args` must be an object")
        else:
            # prompt (or chat alias)
            if not isinstance(action.get("message"), str) or not action["message"].strip():
                raise ValueError("prompt action requires a non-empty `message`")
            # Optional `skill` field on prompt
            # actions. When present, must be a non-empty string —
            # the scheduler resolves it to a skill MD body at
            # dispatch time. We validate the shape but NOT that the
            # skill exists on disk — skills can be created/deleted
            # after a job is added, and we'd rather log a "skill not
            # found" warning at fire time than reject a job that
            # might come back into validity later.
            skill = action.get("skill")
            if skill is not None and (not isinstance(skill, str) or not skill.strip()):
                raise ValueError(
                    "prompt action `skill` must be a non-empty string when set"
                )

    def _load_skill_body(self, skill_name: str) -> str | None:
        """Resolve a skill name to its MD body, or None if not found.

        The scheduler doesn't import skills_crud (that would entangle
        two usecase modules). Instead it walks the skills directory
        directly using the same SKILLS_DIR resolution logic. This is
        cheap (a couple of stat() calls) and runs once per scheduled
        prompt fire — well below any latency budget.

        We try `<category>/<skill_name>.md` for each known category
        first (the common case — skill_name is the canonical id from
        the registry, no extension). If that misses we fall back to
        a glob across categories in case the operator passed a path-
        like value. Returns None if nothing matched; the dispatcher
        logs a warning and continues with the unbound prompt rather
        than failing the job entirely.
        """
        from pathlib import Path
        skills_dir = Path(os.getenv("SKILLS_DIR", "/app/skills"))
        if not skills_dir.exists():
            # Try the canonical fallback used by skills_crud
            from .builtin_components.skills_crud import SKILLS_DIR as crud_dir
            skills_dir = crud_dir
        if not skills_dir.exists():
            return None
        # Normalize: strip leading "category/" if operator passed a
        # rooted path, strip trailing ".md".
        clean = skill_name.strip()
        if clean.endswith(".md"):
            clean = clean[: -len(".md")]
        # Direct hit by category
        for category in ("foundation", "scenarios", "validation", "workflows"):
            candidate = skills_dir / category / f"{clean}.md"
            if candidate.is_file():
                try:
                    return candidate.read_text(encoding="utf-8")
                except OSError:
                    return None
        # Fallback: glob in case the name was already category-qualified
        # (e.g. "scenarios/ransomware_double_extortion") or a different
        # naming pattern.
        if "/" in clean:
            candidate = skills_dir / f"{clean}.md"
            if candidate.is_file():
                try:
                    return candidate.read_text(encoding="utf-8")
                except OSError:
                    return None
        return None

    def _parse_skill_frontmatter(self, skill_name: str) -> dict[str, Any]:
        """Skill-side overrides.

        Parse YAML frontmatter from a skill's MD file. Returns the
        parsed dict (empty when missing / unparseable). Used by the
        dispatch path to derive per-skill model_id / thinking_enabled
        / permission_policy as a fallback when the job itself doesn't
        set them — operator-explicit job overrides always win.

        Frontmatter shape:

            ---
            displayName: My Skill
            category: scenarios
            model: gemini-2.5-flash
            thinking: true
            permissions:
              allowed_tools: ["xlog_*"]
              denied_tools: ["*_delete"]
            ---
            (markdown body...)

        Returns {} on any parse failure — fallback gracefully to "no
        skill-side override" rather than crashing the dispatch.
        """
        body = self._load_skill_body(skill_name)
        if not body:
            return {}
        stripped = body.lstrip()
        # YAML frontmatter is delimited by lines containing only "---"
        # at the top of the file. Detect, extract, parse.
        if not stripped.startswith("---"):
            return {}
        # Find the closing delimiter. The first "---" is consumed
        # already by `startswith`; look for the next from after it.
        after_first = stripped[3:]
        end_marker = after_first.find("\n---")
        if end_marker < 0:
            return {}
        yaml_block = after_first[:end_marker]
        try:
            import yaml
            parsed = yaml.safe_load(yaml_block)
        except Exception:  # noqa: BLE001
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def add_job(
        self,
        *,
        name: str,
        cron: str,
        timezone_name: str = "UTC",
        action: dict[str, Any],
        enabled: bool = True,
        run_once: bool = False,
        bypass_approvals: bool = False,
        model_id: str | None = None,
        thinking_enabled: bool = False,
        permission_policy: dict[str, Any] | None = None,
        description: str | None = None,
    ) -> JobRow:
        """Create a runtime job. Raises ValueError on validation failure
        or if a job with the same name already exists.

        When `run_once=True`, the scheduler disables the job after its
        first fire (success or failure) so it never repeats. Used by
        the /jobs/new form's "Run Now" + "Run Once" frequencies — both
        produce a single-fire job that stays in the table with its
        run history visible. A fired run-once job is NOT re-armed by Resume
        (see `CompletedRunOnceError`); it needs a new Run-at time or a
        duplicate.

        When `bypass_approvals=True`, every chat dispatch
        for this job carries `X-Phantom-Approval-Bypass: 1` so the
        MCP-side gate auto-approves any tools listed in
        manifest.approvals.humanRequired[]. Audit rows still record
        each tool call with `auto_approved=true` so post-hoc review
        sees what fired without operator confirmation.
        """
        from usecase.audit_log import ACTION_JOB_REGISTERED, record_event

        if not name or not isinstance(name, str):
            raise ValueError("name is required")
        self._validate_action(action)
        tz = self._resolve_tz(timezone_name)
        self._validate_cron(cron, tz)
        description_text = self._validate_description(description)
        permission_policy = _without_legacy_policy_keys(permission_policy) or None

        now = self._now_iso()
        # Compute next_due for immediate visibility.
        tmp = JobRow(
            name=name, cron=cron, timezone=timezone_name, action=action,
            enabled=enabled, removed=False,
            last_fired_at=None, last_status=None, last_error=None,
            next_due_at=None, registered_at=now, source="runtime",
            run_once=run_once, bypass_approvals=bypass_approvals,
            model_id=(model_id or None),
            thinking_enabled=thinking_enabled,
            permission_policy=permission_policy,
            description=description_text,
        )
        next_due_iso = self._scheduled_next_due(tmp)

        # Mint a UUID for the new row. If we're re-creating a previously-
        # removed row (the ON CONFLICT path below), the existing id is
        # preserved by `excluded.id` not being in the SET clause —
        # operators clicking "duplicate" or recreating a deleted job
        # get the new row, but a runtime-recreated job stays stable.
        new_id = str(uuid.uuid4())

        with self._lock, self._conn() as c:
            existing = c.execute(
                "SELECT name FROM jobs WHERE name = ? AND removed = 0",
                (name,),
            ).fetchone()
            if existing is not None:
                raise ValueError(f"job {name!r} already exists")
            c.execute(
                "INSERT INTO jobs "
                "(name, id, cron, timezone, action_json, enabled, removed, "
                " next_due_at, registered_at, source, run_once, bypass_approvals, "
                " model_id, thinking_enabled, permission_policy_json, description) "
                "VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, 'runtime', ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(name) DO UPDATE SET "
                " cron = excluded.cron, timezone = excluded.timezone, "
                " action_json = excluded.action_json, "
                " enabled = excluded.enabled, removed = 0, "
                " next_due_at = excluded.next_due_at, "
                " registered_at = excluded.registered_at, "
                " source = 'runtime', "
                " run_once = excluded.run_once, "
                " bypass_approvals = excluded.bypass_approvals, "
                " model_id = excluded.model_id, "
                " thinking_enabled = excluded.thinking_enabled, "
                " permission_policy_json = excluded.permission_policy_json, "
                " description = excluded.description",
                (name, new_id, cron, timezone_name, json.dumps(action),
                 1 if enabled else 0, next_due_iso, now,
                 1 if run_once else 0,
                 1 if bypass_approvals else 0,
                 (model_id or None),
                 1 if thinking_enabled else 0,
                 json.dumps(permission_policy) if permission_policy else None,
                 description_text),
            )

        record_event(
            ACTION_JOB_REGISTERED,
            target=f"job:{name}",
            status="success",
            metadata={
                "job_name": name, "cron": cron, "timezone": timezone_name,
                "action_type": action.get("type"),
                "action_name": action.get("name"),
                "source": "runtime",
            },
        )
        out = self.get_job(name)
        if out is None:
            # Should never happen — INSERT just succeeded.
            raise RuntimeError(f"add_job: row {name!r} vanished after insert")
        # Mirror to disk AFTER the SQLite write succeeds. A YAML write
        # failure logs but doesn't abort — the job is still live in
        # SQLite and the operator can re-export later.
        try:
            self._write_job_yaml(out)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "YAML mirror failed for new job %s: %s — sqlite row is "
                "live and the job will fire normally. Check filesystem "
                "permissions on %s.",
                name, exc, self.yaml_dir,
            )
        return out

    def update_job(
        self,
        name: str,
        *,
        cron: str | None = None,
        timezone_name: str | None = None,
        action: dict[str, Any] | None = None,
        enabled: bool | None = None,
        bypass_approvals: bool | None = None,
        # Per-job model override.
        # `model_id` semantics: None = "operator did not touch this
        # field; preserve existing value." Empty string "" = "operator
        # explicitly cleared the override; revert to runtime default."
        # Any other string = "use this model id." (We use the empty-
        # string sentinel rather than a separate `clear_model_id` bool
        # because UI forms naturally produce "" when the operator
        # blanks a field; the existing `cron` field follows the same
        # convention.)
        model_id: str | None = None,
        thinking_enabled: bool | None = None,
        # Permission policy sentinel:
        #   None = preserve existing value (operator didn't touch)
        #   {} or empty dict = clear the policy (revert to no
        #         restrictions). Same shape as add_job's None default.
        #   non-empty dict = set the policy.
        permission_policy: dict[str, Any] | None = None,
        # Description sentinel: None = preserve, "" = clear, text = set.
        description: str | None = None,
        # run_once: None = preserve, True/False = set. Only the YAML
        # boot reconcile changes it; the PATCH route never sends it.
        run_once: bool | None = None,
    ) -> JobRow | None:
        """Update a job's mutable fields. Returns None if the job
        doesn't exist; raises ValueError on validation failure.

        Manifest jobs CAN be updated at runtime (cron tweaks,
        enable/disable), but on the next boot the manifest is the
        source of truth — manifest values reset cron/timezone/action.
        Runtime jobs survive untouched.

        `bypass_approvals` toggles whether this job's chat
        dispatches set `X-Phantom-Approval-Bypass: 1`. Only takes
        effect on the NEXT scheduled fire, not anything currently in
        flight.
        """
        existing = self.get_job(name)
        if existing is None:
            return None

        new_cron = cron if cron is not None else existing.cron
        new_tz = timezone_name if timezone_name is not None else existing.timezone
        new_action = action if action is not None else existing.action
        new_bypass = (
            bypass_approvals if bypass_approvals is not None
            else existing.bypass_approvals
        )
        # model_id sentinel — None = preserve, "" = clear,
        # other string = set. thinking_enabled follows the simpler
        # tri-state (None preserve / True / False).
        if model_id is None:
            new_model_id = existing.model_id
        elif model_id == "":
            new_model_id = None
        else:
            new_model_id = model_id
        new_thinking = (
            thinking_enabled if thinking_enabled is not None
            else existing.thinking_enabled
        )
        # permission_policy sentinel — distinguishing
        # "preserve" (None) from "clear" requires a different signal
        # than for model_id since the value type is dict. We use:
        #   None = preserve, {} = clear, non-empty dict = set.
        new_policy: dict[str, Any] | None
        if permission_policy is None:
            new_policy = existing.permission_policy
        else:
            # A policy that held only a legacy key becomes {} here, which
            # clears, like an explicit {}.
            new_policy = _without_legacy_policy_keys(permission_policy) or None

        new_description = (
            existing.description if description is None
            else self._validate_description(description)
        )
        new_run_once = existing.run_once if run_once is None else bool(run_once)

        if action is not None:
            self._validate_action(new_action)
        if cron is not None or timezone_name is not None:
            tz = self._resolve_tz(new_tz)
            self._validate_cron(new_cron, tz)

        # A run-once job that already fired is only armed again by a NEW
        # Run-at time; enabling it on its old cron would schedule the same
        # date next year (the stored cron has no year).
        if (
            enabled
            and self._is_completed_run_once(existing)
            and new_cron == existing.cron
            and new_tz == existing.timezone
        ):
            raise CompletedRunOnceError(_completed_run_once_message(name))

        # Recompute next_due on every update (cron/tz may have changed);
        # a job that ends up disabled has none.
        tmp = JobRow(
            name=name, cron=new_cron, timezone=new_tz, action=new_action,
            enabled=existing.enabled if enabled is None else enabled,
            removed=False,
            last_fired_at=None, last_status=None, last_error=None,
            next_due_at=None, registered_at=existing.registered_at,
            source=existing.source,
            run_once=new_run_once,
            bypass_approvals=new_bypass,
            model_id=new_model_id,
            thinking_enabled=new_thinking,
            permission_policy=new_policy,
            description=new_description,
        )
        next_due_iso = self._scheduled_next_due(tmp)

        with self._lock, self._conn() as c:
            c.execute(
                "UPDATE jobs SET cron = ?, timezone = ?, action_json = ?, "
                "enabled = ?, next_due_at = ?, bypass_approvals = ?, "
                "model_id = ?, thinking_enabled = ?, "
                "permission_policy_json = ?, description = ?, "
                "run_once = ?, removed = 0 WHERE name = ?",
                (new_cron, new_tz, json.dumps(new_action),
                 1 if (enabled if enabled is not None else existing.enabled) else 0,
                 next_due_iso, 1 if new_bypass else 0,
                 new_model_id, 1 if new_thinking else 0,
                 json.dumps(new_policy) if new_policy else None,
                 new_description,
                 1 if new_run_once else 0,
                 name),
            )
        out = self.get_job(name)
        # Re-export the YAML mirror so the operator-edited definition
        # tracks the SQLite row. Manifest jobs no-op (mirror only fires
        # on source='runtime').
        if out is not None:
            try:
                self._write_job_yaml(out)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "YAML mirror update failed for %s: %s", name, exc,
                )
        return out

    def delete_job(self, name: str) -> bool:
        """Delete a job. For runtime jobs this hard-deletes the row +
        run history; for manifest jobs it marks `removed=1` (which the
        next manifest reconciliation will undo if the job is still
        declared). Returns True if a row was found, False otherwise."""
        from usecase.audit_log import ACTION_JOB_REMOVED, record_event

        existing = self.get_job(name)
        if existing is None:
            return False
        with self._lock, self._conn() as c:
            if existing.source == "runtime":
                c.execute("DELETE FROM job_runs WHERE job_name = ?", (name,))
                c.execute("DELETE FROM jobs WHERE name = ?", (name,))
            else:
                c.execute(
                    "UPDATE jobs SET removed = 1, next_due_at = NULL "
                    "WHERE name = ?", (name,),
                )
        # Mirror the disk-delete: runtime jobs lose their YAML; manifest
        # jobs don't have one to begin with (their canonical def is in
        # manifest.yaml itself).
        if existing.source == "runtime":
            self._remove_job_yaml(name)
        record_event(
            ACTION_JOB_REMOVED,
            target=f"job:{name}",
            status="success",
            metadata={"job_name": name, "source": existing.source},
        )
        return True

    # ─── YAML dual-write (per spark-agents spec §7.1) ──────────
    #
    # Runtime jobs persist as YAML files at <data_root>/jobs/<name>.yaml
    # alongside the SQLite system-of-record. The YAML is the operator-
    # editable artifact (git-trackable, diff-friendly, restore-able);
    # SQLite is the runtime state (next_due_at, last_status, run_count).
    #
    # Lifecycle:
    #   - add_job() / update_job() write the YAML AFTER the SQLite write
    #     succeeds (so a write failure doesn't leave a half-baked file)
    #   - delete_job() removes the YAML for runtime jobs only
    #   - load_yaml_jobs() at boot reads every <data_root>/jobs/*.yaml
    #     and reconciles into SQLite (idempotent — see its docstring)
    #
    # Manifest jobs (source='manifest') do NOT get a YAML mirror — their
    # canonical def is in manifest.yaml itself; mirroring would create
    # a confusing "two sources of truth" situation. Only runtime jobs
    # land on disk here.

    @property
    def yaml_dir(self) -> Path:
        """<data_root>/jobs/ — created on demand. Operators can `git
        init` this directory to version-control runtime job definitions."""
        return self._data_root / "jobs"

    def _job_yaml_path(self, name: str) -> Path:
        # Job names are validated via add_job to be plain strings; the
        # filesystem-safe name check below is defense-in-depth against
        # someone curl-injecting a `../escape` name.
        if "/" in name or "\\" in name or name in (".", ".."):
            raise ValueError(f"job name {name!r} is not filesystem-safe")
        return self.yaml_dir / f"{name}.yaml"

    def _row_to_yaml_doc(self, row: JobRow) -> dict[str, Any]:
        """Render a JobRow as the YAML document we persist on disk.
        Excludes runtime state (last_fired_at, last_status, next_due_at,
        registered_at, removed) so the YAML stays a pure DEFINITION —
        diffable across operators without spurious "next_due_at moved
        by 24h" noise on every cron tick."""
        doc: dict[str, Any] = {
            "name": row.name,
            "cron": row.cron,
            "timezone": row.timezone,
            "enabled": row.enabled,
            "run_once": row.run_once,
            "action": row.action,
        }
        # Only when set, so a job without one keeps the same file as before.
        if row.description:
            doc["description"] = row.description
        return doc

    def _write_job_yaml(self, row: JobRow) -> None:
        """Write a runtime job's definition to <data_root>/jobs/<name>.yaml.
        No-op for manifest jobs (they don't need a sidecar file)."""
        if row.source != "runtime":
            return
        try:
            import yaml
        except ImportError:
            logger.warning(
                "PyYAML not available; skipping YAML write for job %s. "
                "Install pyyaml in the MCP image to enable git-trackable "
                "runtime job defs.",
                row.name,
            )
            return
        path = self._job_yaml_path(row.name)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Atomic write: tmp file + rename so a crash mid-write doesn't
        # leave a corrupt YAML behind.
        tmp = path.with_suffix(".yaml.tmp")
        tmp.write_text(self._render_job_yaml(row), encoding="utf-8")
        tmp.replace(path)
        logger.info("YAML mirror written: %s", path)

    def _render_job_yaml(self, row: JobRow) -> str:
        """The exact text of a runtime job's mirror file: banner + document."""
        import yaml

        body = yaml.safe_dump(
            self._row_to_yaml_doc(row),
            sort_keys=False,
            default_flow_style=False,
        )
        # Banner so an operator reading the file knows what it is.
        banner = (
            "# Phantom runtime job definition (source='runtime').\n"
            "# Edit cron, timezone, action, run_once or description and\n"
            "# restart phantom-agent to apply. Whether the job is paused or\n"
            "# enabled is kept in SQLite (this file only mirrors it), as is\n"
            "# runtime state (last_fired_at, next_due_at). Per spark-agents\n"
            "# spec §7.1.\n"
        )
        return banner + body

    def converge_job_mirrors(self) -> int:
        """Rewrite every runtime job's mirror whose text differs from what
        SQLite says it should be, and return how many were rewritten. Run at
        boot after load_yaml_jobs(), so a file written by an older build (an
        old banner, or `enabled: true` for a run-once job that has since
        completed) converges to the live state. Idempotent and cheap: a file
        that already matches is read once and left untouched, so a second
        boot writes nothing.

        A file that failed to load (see yaml_load_issues) is never rewritten:
        it may hold an operator's edit that has not been applied yet.
        Failures are logged per job and never stop boot."""
        try:
            import yaml  # noqa: F401
        except ImportError:
            return 0
        unreadable = {i["path"] for i in self.yaml_load_issues}
        rewritten = 0
        for row in self.list_jobs():
            if row.source != "runtime":
                continue
            try:
                path = self._job_yaml_path(row.name)
                if str(path) in unreadable:
                    continue
                wanted = self._render_job_yaml(row)
                try:
                    current = path.read_text(encoding="utf-8")
                except FileNotFoundError:
                    current = None
                if current == wanted:
                    continue
                self._write_job_yaml(row)
                rewritten += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning("YAML mirror refresh failed for %s: %s", row.name, exc)
        if rewritten:
            logger.info("YAML mirror: %d file(s) refreshed from SQLite", rewritten)
        return rewritten

    def _mirror_job_yaml(self, row: JobRow | None) -> None:
        """Best-effort re-export of a runtime job's mirror after a state
        change that does not go through add_job / update_job (pause,
        resume, a fire that disables the job). SQLite stays the source of
        truth for the live state, so a mirror failure only logs."""
        if row is None:
            return
        try:
            self._write_job_yaml(row)
        except Exception as exc:  # noqa: BLE001
            logger.warning("YAML mirror update failed for %s: %s", row.name, exc)

    def _remove_job_yaml(self, name: str) -> None:
        try:
            path = self._job_yaml_path(name)
        except ValueError:
            return
        if path.is_file():
            path.unlink()
            logger.info("YAML mirror removed: %s", path)

    def load_yaml_jobs(self) -> int:
        """At boot, read <data_root>/jobs/*.yaml and reconcile each into
        SQLite. Idempotent: replaying the same mirror any number of times
        changes nothing and reports no issue. Returns the count of YAML
        jobs now in step with SQLite (created, updated or already equal).

        Per file, by what SQLite already holds under that name:
          - nothing (fresh DB, or a deleted-then-restored job): create it
            exactly as the YAML describes, `enabled` included.
          - a runtime job: YAML is the definition, SQLite the live state.
            cron, timezone, action, run_once and description from the YAML
            win and are applied when they differ (that is what editing the
            file and restarting means). `enabled` and everything the YAML
            does not carry (last_fired_at, next_due_at, model_id,
            bypass_approvals, permission_policy) stay as SQLite has them,
            so a paused, auto-disabled or completed run-once job is never
            re-armed by a restart. Pause / resume / auto-disable are
            written back to the mirror, so it tracks the live state;
            converge_job_mirrors() then refreshes any file that still
            differs from SQLite (see there).
          - a manifest job: never overwritten. The collision is reported
            as a load issue (manifest is canonical for its own names).

        Called AFTER register_jobs() so manifest jobs are already in place.

        Per-file failures are collected into self.yaml_load_issues
        instead of logged at WARN per file. ONE summary INFO line is
        emitted at the end. Operators inspect details via
        GET /api/v1/jobs/yaml-issues — this surfaces the issues on the
        observability/jobs UI rather than burying them in docker logs
        (a WARN per file is too noisy on long-running installs and
        trains operators to ignore the WARN level).
        """
        # Reset on each call so /reload paths see a fresh list.
        self.yaml_load_issues: list[dict[str, Any]] = []
        if not self.yaml_dir.is_dir():
            return 0
        try:
            import yaml
        except ImportError:
            logger.warning(
                "PyYAML not available; skipping YAML job load. "
                "Runtime jobs from previous sessions remain in SQLite "
                "and continue to fire normally.",
            )
            return 0
        loaded = 0
        created = updated = 0
        for path in sorted(self.yaml_dir.glob("*.yaml")):
            try:
                doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                if not isinstance(doc, dict):
                    raise ValueError("top-level must be a mapping")
                outcome = self._reconcile_yaml_job(doc, default_name=path.stem)
                loaded += 1
                if outcome == "created":
                    created += 1
                elif outcome == "updated":
                    updated += 1
            except Exception as exc:  # noqa: BLE001
                # One malformed file shouldn't break boot — collect into
                # the issues list and continue. The summary at the end
                # tells the operator how many to investigate; details go
                # to the /api/v1/jobs/yaml-issues endpoint, surfaced in
                # the /jobs page banner when issues > 0.
                import os as _os
                try:
                    mtime = _os.path.getmtime(str(path))
                except OSError:
                    mtime = 0.0
                self.yaml_load_issues.append({
                    "path": str(path),
                    "basename": path.name,
                    "error": f"{type(exc).__name__}: {exc}",
                    "mtime": mtime,
                })
        if loaded:
            logger.info(
                "YAML mirror: %d runtime job(s) in step with %s "
                "(%d created, %d updated)",
                loaded, self.yaml_dir, created, updated,
            )
        if self.yaml_load_issues:
            logger.info(
                "YAML mirror: %d file(s) skipped due to load issues "
                "(GET /api/v1/jobs/yaml-issues for details)",
                len(self.yaml_load_issues),
            )
        return loaded

    def _reconcile_yaml_job(self, doc: dict[str, Any], *, default_name: str) -> str:
        """Bring one YAML mirror document into SQLite. Returns "created",
        "updated" or "unchanged"; raises (-> a load issue) on a parse /
        validation error or a manifest-name collision. See load_yaml_jobs
        for which side wins which field."""
        name = str(doc.get("name") or default_name)
        cron = str(doc.get("cron") or "")
        tz_name = str(doc.get("timezone") or "UTC")
        action = doc.get("action") or {}
        run_once = bool(doc.get("run_once", False))
        existing = self.get_job(name)

        if existing is None or existing.removed:
            # A soft-removed manifest row is taken over by the runtime job,
            # as add_job always did.
            self.add_job(
                name=name, cron=cron, timezone_name=tz_name, action=action,
                enabled=bool(doc.get("enabled", True)), run_once=run_once,
                description=doc.get("description"),
            )
            return "created"

        if existing.source != "runtime":
            raise ValueError(
                f"job {name!r} collides with a manifest job of the same "
                "name; the manifest definition is kept"
            )

        # Normalised exactly as stored, so an unedited mirror compares equal.
        description = self._validate_description(doc.get("description"))
        if (
            existing.cron == cron
            and existing.timezone == tz_name
            and existing.action == action
            and existing.run_once == run_once
            and existing.description == description
        ):
            return "unchanged"

        # `enabled` is deliberately not passed: SQLite owns pause state.
        self.update_job(
            name, cron=cron, timezone_name=tz_name, action=action,
            run_once=run_once, description=description,
        )
        return "updated"

    # ─── Mappers ───────────────────────────────────────────────

    @staticmethod
    def _row_to_jobrow(row: sqlite3.Row) -> JobRow:
        # `source` and `run_once` are best-effort — older rows pre-
        # migration may lack them; sqlite3.Row raises IndexError on
        # missing keys. The migration in _init_schema adds the columns
        # at boot, so this fallback only matters mid-flight on a
        # never-restarted process holding pre-migration row objects.
        try:
            source = row["source"] or "manifest"
        except (IndexError, KeyError):
            source = "manifest"
        try:
            run_once = bool(row["run_once"])
        except (IndexError, KeyError):
            run_once = False
        # bypass_approvals — same defensive read as run_once.
        try:
            bypass_approvals = bool(row["bypass_approvals"])
        except (IndexError, KeyError):
            bypass_approvals = False
        # model_id + thinking_enabled — same defensive read
        # pattern. Rows from before these columns fall through to None / False.
        try:
            model_id = row["model_id"] or None
        except (IndexError, KeyError):
            model_id = None
        try:
            thinking_enabled = bool(row["thinking_enabled"])
        except (IndexError, KeyError):
            thinking_enabled = False
        # permission_policy_json — JSON blob deserialized to
        # a dict. Same defensive-read pattern; malformed JSON degrades
        # to None (no policy) rather than crashing the row read.
        try:
            raw_policy = row["permission_policy_json"]
        except (IndexError, KeyError):
            raw_policy = None
        permission_policy: dict[str, Any] | None
        if raw_policy:
            try:
                parsed = json.loads(raw_policy)
                permission_policy = parsed if isinstance(parsed, dict) else None
            except json.JSONDecodeError:
                logger.warning(
                    "job row has malformed permission_policy_json: %r",
                    raw_policy,
                )
                permission_policy = None
        else:
            permission_policy = None
        # description: same defensive read; rows from before the column
        # existed (or a NULL) are the empty string.
        try:
            description = row["description"] or ""
        except (IndexError, KeyError):
            description = ""
        # `run_count` is added by list_jobs/get_job's SELECT but absent
        # on rows fetched via internal helpers (e.g. update_job's
        # RETURNING shape). Default to 0 — stale, but never wrong-by-
        # an-order-of-magnitude (a fresh insert legitimately has 0
        # runs). The display-side fixes up via re-fetch on refresh.
        try:
            run_count = int(row["run_count"])
        except (IndexError, KeyError, TypeError):
            run_count = 0
        # `id` may be missing on rows fetched before _init_schema's
        # backfill ran (extremely unlikely — schema init is sync at boot
        # before any read can hit). Default to "" so a missing id never
        # crashes a list query; the backfill covers it on next boot.
        try:
            row_id = row["id"] or ""
        except (IndexError, KeyError):
            row_id = ""
        return JobRow(
            name=row["name"],
            id=row_id,
            cron=row["cron"],
            timezone=row["timezone"],
            action=json.loads(row["action_json"]),
            enabled=bool(row["enabled"]),
            removed=bool(row["removed"]),
            last_fired_at=row["last_fired_at"],
            last_status=row["last_status"],
            last_error=row["last_error"],
            # A disabled or removed job has no next run. Rows paused by
            # an older build still carry a frozen next_due_at; never
            # surface it.
            next_due_at=(
                row["next_due_at"]
                if row["enabled"] and not row["removed"]
                else None
            ),
            registered_at=row["registered_at"],
            source=source,
            run_once=run_once,
            run_count=run_count,
            bypass_approvals=bypass_approvals,
            model_id=model_id,
            thinking_enabled=thinking_enabled,
            permission_policy=permission_policy,
            description=description,
        )

    @staticmethod
    def _row_to_jobrun(row: sqlite3.Row) -> JobRun:
        return JobRun(
            id=row["id"],
            job_name=row["job_name"],
            fired_at=row["fired_at"],
            finished_at=row["finished_at"],
            status=row["status"],
            duration_ms=row["duration_ms"],
            result_json=row["result_json"],
            error=row["error"],
            trigger=row["trigger"],
        )


# ─────────────────────────────────────────────────────────────────
# Tool dispatcher factory.
#
# The scheduler dispatches tool calls through `fastmcp.Client`
# pointed at the in-process FastMCP instance. This is the SAME
# JSON-RPC marshalling pipeline the LLM-driven agent uses:
#
#   1. Pydantic schema marshalling — `kwargs` get validated and
#      assembled into the tool's request model
#   2. Context injection — fastmcp constructs a `Context` carrying
#      the lifespan context (xlog_url, instance config from the
#      instance contextvar, etc.) and passes it as `ctx`
#   3. Result normalization — the `CallToolResult` we get back
#      already has structured_content, content, and isError fields
#
# Calling `fn(**kwargs)` directly would only work for kwargs-style
# built-in tools (memory_search, sessions_list); any connector tool
# with the canonical FastMCP signature
# `(request: PydanticModel, ctx: Context)` would fail with a TypeError.
# Going through fastmcp.Client lets us schedule any tool the agent
# can call — connector tools and built-ins alike.
# ─────────────────────────────────────────────────────────────────


def make_tool_dispatcher(
    tool_registry: dict[str, Callable],
    *,
    mcp: Any | None = None,
) -> ToolDispatcher:
    """Return an async dispatcher for scheduler-driven tool calls.

    When `mcp` is the FastMCP server instance, we route every call
    through `fastmcp.Client(mcp)` — the in-process variant of the
    same Client that LLM clients use over HTTP. This guarantees
    behavioral parity with agent-driven calls.

    When `mcp` is None (test harness, embedded use without a server),
    we fall back to invoking the wrapped callable from the registry
    directly with `**kwargs`. That path doesn't do Pydantic
    marshalling and doesn't inject Context — fine for built-in
    cognitive tools that take simple kwargs, breaks for the canonical
    FastMCP-shaped connector tools.

    `tool_registry` is consulted regardless to validate the tool name
    up front — gives a clear "no such tool" error before fastmcp's
    own (more cryptic) lookup error.
    """

    async def dispatch(name: str, kwargs: dict[str, Any]) -> Any:
        # Credential guardrail: scheduler `tool_call` actions and
        # agent_batch_propose's registry route both land here, so the one
        # check covers both. These tools are REST-only.
        assert_no_credential_tools([name], where="tool dispatcher")
        if name not in tool_registry:
            raise KeyError(
                f"job action references unknown tool {name!r}; "
                f"check that the connector is configured (instance must exist)"
            )

        # Preferred path — fastmcp.Client(mcp) for full marshalling.
        if mcp is not None:
            try:
                from fastmcp import Client  # noqa: PLC0415
            except ImportError:
                Client = None  # type: ignore[assignment]
            if Client is not None:
                # New Client per call. The in-memory transport's
                # session setup/teardown is cheap (no network), so
                # this is fine for cron-cadence dispatches.
                async with Client(mcp) as client:
                    result = await client.call_tool(name, kwargs or {})
                return _normalize_call_result(result)

        # Fallback path — direct callable. Only works for kwargs-
        # style tools; logged so it's visible if it gets used.
        logger.warning(
            "JobScheduler dispatching %s via fallback path (no fastmcp.Client) "
            "— this only works for kwargs-style tools",
            name,
        )
        fn = tool_registry[name]
        if inspect.iscoroutinefunction(fn):
            return await fn(**kwargs)
        return fn(**kwargs)

    return dispatch


def _normalize_call_result(result: Any) -> Any:
    """FastMCP's CallToolResult → plain dict/list/str for json.dumps.

    The CallToolResult shape (fastmcp 2.x):
      - structured_content: dict | None  ← preferred when present
      - content: list[TextContent | ImageContent | ...] ← always populated
      - isError: bool
      - data: Any | None (for tools annotated with structured output)

    Resolution order:
      1. `data` if set (FastMCP 2.x structured output)
      2. `structured_content` if set
      3. JSON-decode the first text content
      4. Raw text content
      5. repr() fallback
    """
    # Primitive pass-through (covers the no-mcp / tier-2 fallback path).
    if result is None or isinstance(result, (str, int, float, bool, list, dict)):
        return result

    # 1. fastmcp 2.x exposes `.data` for structured-output tools.
    data = getattr(result, "data", None)
    if data is not None:
        return data

    # 2. structured_content (dict) — set when the tool's return type is
    # a Pydantic model or dict and FastMCP serialized it explicitly.
    structured = getattr(result, "structured_content", None)
    if structured is not None:
        return structured

    # 3-4. Walk the content list (TextContent.text, etc.).
    content = getattr(result, "content", None)
    if content is not None:
        out: list[Any] = []
        for c in content:
            t = getattr(c, "text", None)
            if t is not None:
                try:
                    out.append(json.loads(t))
                except (TypeError, ValueError):
                    out.append(t)
            else:
                out.append(repr(c))
        if len(out) == 1:
            return out[0]
        return out

    # 5. Last resort.
    return repr(result)


# ─────────────────────────────────────────────────────────────────
# Module-level singleton accessor — set by main.py at boot
# ─────────────────────────────────────────────────────────────────

_scheduler: CroniterJobScheduler | None = None


def set_scheduler(s: CroniterJobScheduler | None) -> None:
    global _scheduler
    _scheduler = s


def scheduler() -> CroniterJobScheduler | None:
    return _scheduler
