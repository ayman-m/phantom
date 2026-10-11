"""SqlitePersonalityStore — operator-tunable agent persona, persisted
in the MCP's data root so the embedded MCP and the agent UI share
one source of truth.

Why a dedicated store (rather than putting personality in
SettingsStore):

  - Settings are key-typed scalars constrained by
    manifest.settings.overridable[]. Personality is a richer JSON
    document with sliders, free-form markdown, and a model preference.
    Forcing it into key-value would either flatten the structure
    (losing arrays/nested) or balloon `overridable[]` with dozens of
    `personality.*` entries the manifest doesn't actually want to
    enumerate.
  - Personality has its own write semantics: read-modify-write with
    diff (the operator is shown the change before approval). Settings
    are typed individual sets/clears.
  - Migration story: pre-Phase-11 personality lived in the agent UI's
    `setup.json:values.personality` (a JSON blob). This store reads
    that blob on first init and copies it in (one-time migration), so
    operator-saved persona survives the move.

# Single-row store

Personality is global (single agent, single persona) — there's no
multi-tenancy here in standalone mode. A single row keyed by `id=1`
holds the full document; the table also keeps a small history (last
N versions) so the UI diff renderer can show "what
changed" without keeping app-side state.

# Schema

    personality (
      id           INTEGER PRIMARY KEY CHECK (id = 1),  -- single-row
      blob_json    TEXT NOT NULL,                       -- the persona doc
      updated_at   TEXT NOT NULL,                       -- ISO8601 UTC
      updated_by   TEXT,                                -- actor (audit)
      version      INTEGER NOT NULL DEFAULT 1           -- monotonic
    );

    personality_history (
      version      INTEGER PRIMARY KEY AUTOINCREMENT,
      blob_json    TEXT NOT NULL,
      updated_at   TEXT NOT NULL,
      updated_by   TEXT
    );

# Audit

The `personality_changed` event (listed in manifest.audit.events)
records every put with the actor identity. Values are
non-secret (no credentials live here) so the diff is safe to log.
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
HISTORY_KEEP = 20  # cap personality_history at the last 20 versions


# Bundle-default personality document. Used when:
#   1. The store is empty (first boot, no migration found).
#   2. The operator explicitly resets via personality_reset (Tier 3).
#
# Mirrors the DEFAULT_CONFIG of the agent UI's personality page
# (mcp/agent/app/settings/personality/page.tsx).
# Keeping the canonical default in the MCP avoids drift between the UI
# and the runtime that actually consumes the values.
DEFAULT_PERSONALITY: dict[str, Any] = {
    "responseStyle": "balanced",
    "proactivity": 60,
    "confidence": 70,
    "permissionLevel": 50,
    "logicDepth": "balanced",
    "planningDepth": 50,
    "delegationStyle": "selective",
    "defaultModel": "gemini-3.1-pro-preview",
    "fallbackModel": "gemini-2.5-flash",
    "maxConcurrentRuns": 3,
    "dailySummary": True,
    "escalationThreshold": 80,
    "personalityMd": (
        "# Phantom Personality\n\n"
        "You are Phantom, a continuous SOC simulation agent. Your job "
        "is to help operators generate synthetic security telemetry, "
        "exercise detections, run adversary emulation, and produce "
        "coverage reports.\n\n"
        "## Operating principles\n\n"
        "- Cite simulation IDs, worker IDs, and Caldera operation IDs "
        "in every final answer.\n"
        "- Prefer scenario packages and bundled skills before "
        "inventing a workflow.\n"
        "- Confirm with the operator before launching Caldera "
        "operations, and before any send that is large (over about "
        "500 events) or runs longer than about 10 minutes. A clear "
        "request to simulate or send something small is its own "
        "confirmation: do it, then say exactly what you sent.\n"
    ),
    # ─── Action policy (the local/external boundary) ───────────────
    #
    # Tells the agent how to classify each operator request: is it
    # asking the agent to CONFIGURE ITSELF (local) or to ACT ON the
    # SOC environment (external)? When ambiguous the agent asks the
    # operator to disambiguate rather than guess. The chat route
    # injects this block into the system instruction at request time
    # so operators editing the policy see immediate behavior change.
    #
    # Backwards-compat: personalities saved before this field landed
    # round-trip cleanly — `put()` accepts any dict and the
    # get_or_default() path fills the missing field on read.
    "actionPolicy": {
        # Tools that mutate the agent's own runtime state. Listed by
        # logical category, not bare tool name, so adding a new tool
        # to an existing category (e.g. a future jobs_pause) inherits
        # the routing without touching personalities. The chat route
        # maps category → tool prefixes when filtering.
        "localCategories": [
            "jobs",
            "settings",
            "personality",
            "instances",
            "providers",
            "approvals",
            "notifications",
            "skills",
            "api-keys",
            "memory",
            "knowledge",
        ],
        # Tools that act on the SOC environment outside the agent's
        # boundary. Logs sent to a real SIEM, Caldera ops launched
        # against real targets, scenarios that fire telemetry.
        "externalCategories": [
            "xlog",
            "caldera",
            "xsiam",
            "simulations",
        ],
        # When the agent's classification confidence is low, ASK the
        # operator instead of guessing. The agent must emit text with
        # numbered options + category labels rather than calling a
        # tool. Default true — operators who turn this off explicitly
        # accept that the agent will commit to its best guess.
        "askWhenUnsure": True,
        # Pre-execution confirmation cadence by surface.
        #   "approve-card"  — full inline approval card (Phase-11 UX).
        #                     For local writes this is already enforced
        #                     by manifest.approvals.humanRequired[].
        #   "soft"          — one-line "About to run X — fire it?".
        #                     Agent waits for "yes"/affirmative reply
        #                     before invoking the tool.
        #   "off"           — execute immediately (no extra friction
        #                     on top of any tool-level gates).
        "confirmLocalActions": "approve-card",
        # Off by default: a clear instruction on the
        # operator's own tenant runs without a question. The store seeds
        # this on first boot, so an install that already has a row keeps it.
        "confirmExternalActions": "off",
    },
}


@dataclass(frozen=True)
class Personality:
    """Materialized personality row."""

    blob: dict[str, Any]
    updated_at: str
    updated_by: str | None
    version: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "personality": self.blob,
            "updated_at": self.updated_at,
            "updated_by": self.updated_by,
            "version": self.version,
        }


class SqlitePersonalityStore:
    """Single-row personality store at <data_root>/personality.db."""

    def __init__(self, data_root: Path | None = None) -> None:
        self._data_root = (data_root or self._resolve_data_root()).resolve()
        self._data_root.mkdir(parents=True, exist_ok=True)
        self._db_path = self._data_root / "personality.db"
        self._lock = threading.Lock()
        self._init_schema()
        # First-boot migration: if we're empty AND a legacy setup.json
        # is reachable, copy that personality across so operators don't
        # lose their UI-saved persona.
        self._maybe_migrate_from_setup_json()
        logger.info("SqlitePersonalityStore at %s", self._db_path)

    @staticmethod
    def _resolve_data_root() -> Path:
        import os
        raw = os.getenv("DATA_ROOT", str(DEFAULT_DATA_ROOT))
        return Path(raw)

    @property
    def db_path(self) -> Path:
        return self._db_path

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(
            self._db_path, isolation_level=None, check_same_thread=False
        )
        c.row_factory = sqlite3.Row
        return c

    def _init_schema(self) -> None:
        with self._lock, self._conn() as c:
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS personality (
                    id           INTEGER PRIMARY KEY CHECK (id = 1),
                    blob_json    TEXT NOT NULL,
                    updated_at   TEXT NOT NULL,
                    updated_by   TEXT,
                    version      INTEGER NOT NULL DEFAULT 1
                )
                """
            )
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS personality_history (
                    version      INTEGER PRIMARY KEY AUTOINCREMENT,
                    blob_json    TEXT NOT NULL,
                    updated_at   TEXT NOT NULL,
                    updated_by   TEXT
                )
                """
            )

    @staticmethod
    def _now_iso() -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    def _maybe_migrate_from_setup_json(self) -> None:
        """One-time migration: read the agent UI's old setup.json
        location and copy `values.personality` into this store if we're
        currently empty. Idempotent (does nothing once the store is
        populated).

        The agent UI's legacy setup file carries personality at:
          /app/data/setup.json   (mounted same volume as this DB)
            → values.personality  (a JSON-stringified blob)

        After migration the agent UI's `/api/agent/personality` route
        proxies to `/api/v1/personality` (this store).
        """
        existing = self.get()
        if existing is not None:
            return  # already populated, no migration needed

        setup_paths = [
            self._data_root / "setup.json",
            Path("/app/data/setup.json"),  # explicit fallback
        ]
        for sp in setup_paths:
            if not sp.is_file():
                continue
            try:
                doc = json.loads(sp.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning(
                    "personality migration: could not read %s (%s)", sp, exc,
                )
                continue
            values = doc.get("values") or {}
            raw = values.get("personality")
            if not isinstance(raw, str) or not raw:
                continue
            try:
                blob = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not isinstance(blob, dict):
                continue
            # Migrate.
            self.put(blob, actor="migration:setup.json")
            logger.info(
                "personality migration: copied %d keys from %s into "
                "personality.db", len(blob), sp,
            )
            return

        # No migration source found — seed with the bundle default so
        # the chat agent and UI both see a coherent persona on day 1.
        self.put(DEFAULT_PERSONALITY, actor="bootstrap:default")
        logger.info("personality: seeded with bundle defaults")

    # ─── Read API ──────────────────────────────────────────────

    def get(self) -> Personality | None:
        """Fetch the current personality (single row). None when empty."""
        with self._lock, self._conn() as c:
            row = c.execute(
                "SELECT * FROM personality WHERE id = 1"
            ).fetchone()
        if row is None:
            return None
        return Personality(
            blob=json.loads(row["blob_json"]),
            updated_at=row["updated_at"],
            updated_by=row["updated_by"],
            version=int(row["version"]),
        )

    def get_or_default(self) -> Personality:
        """Fetch the current personality, or a default-filled placeholder
        if the store hasn't been initialized."""
        cur = self.get()
        if cur is not None:
            return cur
        # Return the default — caller may choose to put() it to persist.
        return Personality(
            blob=dict(DEFAULT_PERSONALITY),
            updated_at=self._now_iso(),
            updated_by="default",
            version=0,
        )

    def history(self, limit: int = 10) -> list[Personality]:
        """Recent versions, newest first. Used by the diff renderer in
        the chat UI: 'what changed since version N?'"""
        limit = max(1, min(int(limit), HISTORY_KEEP))
        with self._lock, self._conn() as c:
            rows = c.execute(
                "SELECT * FROM personality_history "
                "ORDER BY version DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            Personality(
                blob=json.loads(r["blob_json"]),
                updated_at=r["updated_at"],
                updated_by=r["updated_by"],
                version=int(r["version"]),
            )
            for r in rows
        ]

    # ─── Write API ─────────────────────────────────────────────

    def put(
        self,
        blob: dict[str, Any],
        *,
        actor: str | None = None,
    ) -> Personality:
        """Replace the personality blob (last-write-wins). Bumps version
        and writes the previous value into personality_history.

        Args:
            blob: the new personality document. Must be a dict.
            actor: who's writing (e.g. "user:operator", "agent:<session>").
                Recorded in audit + persisted alongside the row.

        Returns the updated Personality.
        """
        if not isinstance(blob, dict):
            raise TypeError("personality blob must be a dict")
        now = self._now_iso()
        body = json.dumps(blob, ensure_ascii=False, sort_keys=True)

        with self._lock, self._conn() as c:
            # Snapshot the existing row into history (if any).
            existing = c.execute(
                "SELECT * FROM personality WHERE id = 1"
            ).fetchone()
            new_version = 1
            if existing is not None:
                new_version = int(existing["version"]) + 1
                c.execute(
                    "INSERT INTO personality_history "
                    "(blob_json, updated_at, updated_by) "
                    "VALUES (?, ?, ?)",
                    (existing["blob_json"], existing["updated_at"],
                     existing["updated_by"]),
                )
                # Trim history to the last HISTORY_KEEP rows.
                c.execute(
                    "DELETE FROM personality_history WHERE version IN "
                    "(SELECT version FROM personality_history "
                    " ORDER BY version DESC LIMIT -1 OFFSET ?)",
                    (HISTORY_KEEP,),
                )
            # Upsert the current row.
            c.execute(
                "INSERT INTO personality "
                "(id, blob_json, updated_at, updated_by, version) "
                "VALUES (1, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET "
                "  blob_json = excluded.blob_json, "
                "  updated_at = excluded.updated_at, "
                "  updated_by = excluded.updated_by, "
                "  version = excluded.version",
                (body, now, actor, new_version),
            )

        # Audit event (best-effort; don't let audit failure block the write).
        try:
            from usecase.audit_log import (
                ACTION_PERSONALITY_CHANGED,
                record_event,
            )
            record_event(
                ACTION_PERSONALITY_CHANGED,
                target="personality:1",
                status="success",
                actor=actor,
                metadata={
                    "version": new_version,
                    "keys_changed": _diff_keys(
                        json.loads(existing["blob_json"]) if existing else {},
                        blob,
                    ),
                },
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("personality audit failed: %s", exc)

        return Personality(
            blob=blob, updated_at=now, updated_by=actor, version=new_version,
        )

    def reset_to_default(self, *, actor: str | None = None) -> Personality:
        """Revert to DEFAULT_PERSONALITY. Tier-3 destructive op (gated via
        approvals.humanRequired[])."""
        return self.put(dict(DEFAULT_PERSONALITY), actor=actor)


def _diff_keys(old: dict[str, Any], new: dict[str, Any]) -> list[str]:
    """List of key names that changed between old and new (added,
    removed, or value-changed). Used by the audit log to summarize
    what an update touched without dumping the full diff."""
    keys: set[str] = set()
    for k in set(old) | set(new):
        if old.get(k) != new.get(k):
            keys.add(k)
    return sorted(keys)


# ─────────────────────────────────────────────────────────────────
# Module-level singleton accessor — wired by main.py.
# ─────────────────────────────────────────────────────────────────


_personality_store: SqlitePersonalityStore | None = None


def set_personality_store(s: SqlitePersonalityStore | None) -> None:
    global _personality_store
    _personality_store = s


def personality_store() -> SqlitePersonalityStore | None:
    return _personality_store
