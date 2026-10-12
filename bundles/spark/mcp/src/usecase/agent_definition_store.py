"""Agent definition store.

A persistent registry of operator-defined (and plugin-contributed)
agent definitions. Each definition declares: name, system_prompt,
tools_allowed (glob list), tools_denied (glob list), model,
max_turns.

Why a store (vs. inline in code):

  - Operator can author custom agents via /agents UI without a
    redeploy. The "blue-team-validator" agent might evolve its
    system_prompt as the SOC's investigation playbook matures.
  - Plugins contribute agent definitions on boot. Same
    storage path, same shape, just a different write origin.
  - Audit trail: every create/update/delete writes an audit row,
    so /observability/events answers "who edited the red-team
    agent's system prompt?"

# Agent definition contract

    AgentDefinition {
      id              uuid
      name            human-friendly identifier ("red-team-emulator")
      description     one-line operator-facing summary
      system_prompt   the system instruction the subagent runs with;
                      the parent's system prompt is NOT inherited
      tools_allowed   list of glob patterns; tools matching any
                      pattern are exposed to the subagent. Empty
                      list means "all tools" (NOT recommended);
                      default examples below.
      tools_denied    list of glob patterns; tools matching any
                      pattern are excluded EVEN IF tools_allowed
                      would include them. deny-wins.
      model           model name override. None = use parent's
                      effective model. Useful for "use a cheap
                      model for the verifier subagent."
      max_turns       loop budget for the subagent's tool-call
                      cycle. Default 10. Hard cap: 50 (a runaway
                      subagent burns operator money fast).
      isolation       'parent_session' | 'fresh_session' (default
                      'fresh_session'). 'parent_session' is the
                      escape hatch for advanced uses where the
                      subagent should see the parent's memory
                      scope. Most agents should stay 'fresh_session'.
      origin          'operator' | 'plugin:<name>' | 'builtin' —
                      provenance for the UI's "where did this
                      come from?" badge.
      enabled         bool — operator can disable an agent without
                      deleting it.
      created_at      ISO8601
      updated_at      ISO8601
    }

# Glob patterns

Same matcher as the hooks framework: comma-separated globs with
`*` (any chars) and `?` (single char). Examples:

    tools_allowed: ["caldera_*"]               # red-team only
    tools_allowed: ["xsiam_run_xql_query",
                    "xsiam_get_datasets",
                    "detections_list"]         # blue-team narrow
    tools_allowed: ["*_get_*", "*_list_*"]     # read-only everywhere

# Schema

    agent_definitions (
      id              TEXT PRIMARY KEY,
      name            TEXT NOT NULL UNIQUE,
      description     TEXT,
      system_prompt   TEXT NOT NULL,
      tools_allowed   TEXT NOT NULL DEFAULT '[]',  -- JSON list
      tools_denied    TEXT NOT NULL DEFAULT '[]',
      model           TEXT,                         -- nullable
      max_turns       INTEGER NOT NULL DEFAULT 10,
      isolation       TEXT NOT NULL DEFAULT 'fresh_session',
      origin          TEXT NOT NULL DEFAULT 'operator',
      enabled         INTEGER NOT NULL DEFAULT 1,
      created_at      TEXT NOT NULL,
      updated_at      TEXT NOT NULL
    );
    CREATE UNIQUE INDEX idx_agent_def_name  ON agent_definitions(name);
    CREATE INDEX idx_agent_def_origin       ON agent_definitions(origin);
    CREATE INDEX idx_agent_def_enabled      ON agent_definitions(enabled);
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

VALID_ISOLATION = {"parent_session", "fresh_session"}
MAX_TURNS_HARD_CAP = 50


@dataclass
class AgentDefinition:
    id: str
    name: str
    description: str
    system_prompt: str
    tools_allowed: list[str]
    tools_denied: list[str]
    model: str | None
    max_turns: int
    isolation: str
    origin: str
    enabled: bool
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "system_prompt": self.system_prompt,
            "tools_allowed": list(self.tools_allowed),
            "tools_denied": list(self.tools_denied),
            "model": self.model,
            "max_turns": self.max_turns,
            "isolation": self.isolation,
            "origin": self.origin,
            "enabled": self.enabled,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class SqliteAgentDefinitionStore:
    """Persistent registry of agent definitions. Multi-row, indexed
    on name (unique) + origin + enabled."""

    def __init__(self, data_root: Path | None = None) -> None:
        root = data_root or self._resolve_data_root()
        root.mkdir(parents=True, exist_ok=True)
        self._db_path = root / "agent_definitions.db"
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
                CREATE TABLE IF NOT EXISTS agent_definitions (
                    id              TEXT PRIMARY KEY,
                    name            TEXT NOT NULL UNIQUE,
                    description     TEXT,
                    system_prompt   TEXT NOT NULL,
                    tools_allowed   TEXT NOT NULL DEFAULT '[]',
                    tools_denied    TEXT NOT NULL DEFAULT '[]',
                    model           TEXT,
                    max_turns       INTEGER NOT NULL DEFAULT 10,
                    isolation       TEXT NOT NULL DEFAULT 'fresh_session',
                    origin          TEXT NOT NULL DEFAULT 'operator',
                    enabled         INTEGER NOT NULL DEFAULT 1,
                    created_at      TEXT NOT NULL,
                    updated_at      TEXT NOT NULL
                )
                """
            )
            c.execute(
                "CREATE INDEX IF NOT EXISTS idx_agent_def_origin "
                "ON agent_definitions(origin)"
            )
            c.execute(
                "CREATE INDEX IF NOT EXISTS idx_agent_def_enabled "
                "ON agent_definitions(enabled)"
            )

    @staticmethod
    def _now() -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    # ─── Public API ─────────────────────────────────────────────

    def list(
        self,
        *,
        origin: str | None = None,
        enabled_only: bool = False,
    ) -> list[AgentDefinition]:
        sql = (
            "SELECT id, name, description, system_prompt, "
            "tools_allowed, tools_denied, model, max_turns, "
            "isolation, origin, enabled, created_at, updated_at "
            "FROM agent_definitions"
        )
        clauses: list[str] = []
        params: list[Any] = []
        if origin is not None:
            clauses.append("origin = ?")
            params.append(origin)
        if enabled_only:
            clauses.append("enabled = 1")
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY name ASC"
        with self._conn() as c:
            rows = c.execute(sql, params).fetchall()
        return [self._row_to_def(r) for r in rows]

    def get(self, agent_id: str) -> AgentDefinition | None:
        with self._conn() as c:
            row = c.execute(
                "SELECT id, name, description, system_prompt, "
                "tools_allowed, tools_denied, model, max_turns, "
                "isolation, origin, enabled, created_at, updated_at "
                "FROM agent_definitions WHERE id = ?",
                (agent_id,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_def(row)

    def get_by_name(self, name: str) -> AgentDefinition | None:
        with self._conn() as c:
            row = c.execute(
                "SELECT id, name, description, system_prompt, "
                "tools_allowed, tools_denied, model, max_turns, "
                "isolation, origin, enabled, created_at, updated_at "
                "FROM agent_definitions WHERE name = ?",
                (name,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_def(row)

    def upsert(
        self,
        payload: dict[str, Any],
        *,
        origin: str = "operator",
    ) -> AgentDefinition:
        """Insert or update a definition. Caller MUST validate the
        shape; this method does minimal MCP-side checks (name +
        system_prompt required, max_turns clamped)."""
        name = str(payload.get("name") or "").strip()
        if not name:
            raise ValueError("'name' is required and must be non-empty")
        system_prompt = str(payload.get("system_prompt") or "").strip()
        if not system_prompt:
            raise ValueError(
                "'system_prompt' is required and must be non-empty"
            )
        isolation = str(
            payload.get("isolation") or "fresh_session"
        )
        if isolation not in VALID_ISOLATION:
            raise ValueError(
                f"isolation must be one of {VALID_ISOLATION}; "
                f"got {isolation!r}"
            )
        max_turns = int(payload.get("max_turns") or 10)
        max_turns = max(1, min(MAX_TURNS_HARD_CAP, max_turns))
        tools_allowed = payload.get("tools_allowed") or []
        tools_denied = payload.get("tools_denied") or []
        if not isinstance(tools_allowed, list):
            raise ValueError("'tools_allowed' must be a list of strings")
        if not isinstance(tools_denied, list):
            raise ValueError("'tools_denied' must be a list of strings")
        model = payload.get("model")
        description = str(payload.get("description") or "")
        enabled = bool(payload.get("enabled", True))

        # Find existing by id OR by name (idempotent upsert).
        existing: AgentDefinition | None = None
        if payload.get("id"):
            existing = self.get(str(payload["id"]))
        if existing is None:
            existing = self.get_by_name(name)
        agent_id = (
            existing.id if existing else
            str(payload.get("id") or uuid.uuid4())
        )
        now = self._now()
        created_at = (
            existing.created_at if existing else
            str(payload.get("created_at") or now)
        )
        # Origin: callers can override (plugin loader passes
        # origin='plugin:<name>'). Operator UI POSTs default to
        # 'operator'.
        effective_origin = origin

        with self._lock, self._conn() as c:
            c.execute(
                "INSERT INTO agent_definitions "
                "(id, name, description, system_prompt, tools_allowed, "
                " tools_denied, model, max_turns, isolation, origin, "
                " enabled, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET "
                "name=excluded.name, description=excluded.description, "
                "system_prompt=excluded.system_prompt, "
                "tools_allowed=excluded.tools_allowed, "
                "tools_denied=excluded.tools_denied, "
                "model=excluded.model, max_turns=excluded.max_turns, "
                "isolation=excluded.isolation, "
                "enabled=excluded.enabled, "
                "updated_at=excluded.updated_at",
                (
                    agent_id, name, description, system_prompt,
                    json.dumps(tools_allowed), json.dumps(tools_denied),
                    model, max_turns, isolation, effective_origin,
                    1 if enabled else 0, created_at, now,
                ),
            )
        return self.get(agent_id)  # type: ignore[return-value]

    def delete(self, agent_id: str) -> bool:
        with self._lock, self._conn() as c:
            cur = c.execute(
                "DELETE FROM agent_definitions WHERE id = ?",
                (agent_id,),
            )
            return cur.rowcount > 0

    def set_enabled(
        self, agent_id: str, *, enabled: bool
    ) -> AgentDefinition | None:
        with self._lock, self._conn() as c:
            cur = c.execute(
                "UPDATE agent_definitions SET enabled = ?, "
                "updated_at = ? WHERE id = ?",
                (1 if enabled else 0, self._now(), agent_id),
            )
            if cur.rowcount == 0:
                return None
        return self.get(agent_id)

    @staticmethod
    def _row_to_def(row: tuple[Any, ...]) -> AgentDefinition:
        (
            id_, name, description, system_prompt,
            tools_allowed_json, tools_denied_json, model,
            max_turns, isolation, origin, enabled,
            created_at, updated_at,
        ) = row
        try:
            tools_allowed = json.loads(tools_allowed_json or "[]")
        except json.JSONDecodeError:
            tools_allowed = []
        try:
            tools_denied = json.loads(tools_denied_json or "[]")
        except json.JSONDecodeError:
            tools_denied = []
        return AgentDefinition(
            id=id_,
            name=name,
            description=description or "",
            system_prompt=system_prompt or "",
            tools_allowed=[str(t) for t in tools_allowed],
            tools_denied=[str(t) for t in tools_denied],
            model=model,
            max_turns=int(max_turns or 10),
            isolation=isolation or "fresh_session",
            origin=origin or "operator",
            enabled=bool(enabled),
            created_at=created_at,
            updated_at=updated_at,
        )


_global_store: SqliteAgentDefinitionStore | None = None


def set_agent_definition_store(store: SqliteAgentDefinitionStore) -> None:
    global _global_store
    _global_store = store


def get_agent_definition_store() -> SqliteAgentDefinitionStore | None:
    return _global_store
