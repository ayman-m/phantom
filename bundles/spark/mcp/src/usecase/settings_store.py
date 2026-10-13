"""SqliteSettingsStore — bundle-local implementation of the spec's
`settings` capability (manifest.yaml `settings: { defaults, overridable }`).

The bundle declares two surfaces:

  * **defaults** — typed values baked into the manifest at build time.
    Immutable at runtime; the operator can't change them without
    re-bundling. Source of truth for "what does this agent do
    out-of-the-box?"
  * **overridable** — a subset of keys the operator IS permitted to
    tweak at runtime. Their values live in this store; reads MERGE
    defaults with overrides on top.

# Why a separate store rather than re-using `SecretStore`

Settings are non-sensitive, multi-typed (str/int/bool/list/dict),
and read on every relevant tool call. The SecretStore is a
file-backed mode-0700 vault for secret VALUES; routing settings
through it would be a category error (no secrecy needed) and a
performance one (filesystem reads per setting access vs in-memory
sqlite cache).

# Schema

    setting_overrides(
      key         TEXT PRIMARY KEY,    -- must be in manifest's overridable list
      value_json  TEXT NOT NULL,        -- JSON-encoded value (preserves type)
      updated_at  TEXT NOT NULL,        -- ISO8601 UTC
      updated_by  TEXT                   -- operator identity if known (audit)
    );

# Audit

Per manifest.audit.events, "settings_changed" is recorded on every
set/clear via the wired audit log. The audit row carries
{key, old_value, new_value, actor}; values are non-secret so safe to log.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

logger = logging.getLogger("Phantom MCP")

DEFAULT_DATA_ROOT = Path("/app/data")

# Model-selection settings are operator/REST-only. A chat session picks its
# model per session (header dropdown or `/model <name>`, stored in the session
# metadata) and that choice must never reach the global default. The agent's
# `settings_update` / `settings_reset` tools refuse these keys (see
# builtin_components/self_mod_tools.py); the REST surface
# (PUT /api/v1/settings) is unaffected, so the operator can still change the
# default model there. A key counts as model-selection when it is
# `defaultModel` or any key whose name ends in "model" (a future
# `fallbackModel` is covered without a code change).
AGENT_PROTECTED_SETTINGS: frozenset[str] = frozenset({"defaultModel"})

# The install's default model is one canonical ref, "provider/model", held in
# the `defaultModel` setting. It replaced `geminiModel`, which held a bare
# Gemini id that no code read. A stored `geminiModel` override is renamed on
# store init (see `_migrate_renamed_settings`); the rename is deleted, not
# shimmed: after it runs nothing reads the old key.
RENAMED_SETTINGS: dict[str, str] = {"geminiModel": "defaultModel"}


# The Gemini chat ids the agent's catalog serves
# (mcp/agent/lib/providers/registry/catalog-vertex.ts). The old `geminiModel`
# value is carried over only when it is one of these: an id the catalog does not
# know would make every turn fail with MODEL_UNKNOWN until the operator noticed.
# tests/test_settings_store.py compares this tuple with the catalog file, so a
# catalog change that is not mirrored here fails there.
KNOWN_VERTEX_CHAT_MODEL_IDS: tuple[str, ...] = (
    "gemini-3.8-flash",
    "gemini-3.7-flash",
    "gemini-3.5-flash",
    "gemini-3.1-pro-preview",
    "gemini-3.0-pro",
    "gemini-2.5-pro",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
)


def _canonical_default_model(value: Any) -> Any:
    """A bare Gemini id from the old key becomes a `vertex/` ref.

    A value that already names a provider (contains "/") is left alone, and so
    is anything that is not a string (it cannot have been written through the
    type check, so there is nothing sensible to prefix).
    """
    if isinstance(value, str) and value.strip() and "/" not in value:
        return f"vertex/{value.strip()}"
    return value


def _is_servable_default(raw: Any, canonical: Any) -> bool:
    """True when a migrated `geminiModel` value names a model the catalog serves.

    A bare id, or one prefixed `vertex/`, must be a known Vertex chat id. A
    value prefixed with another provider (Claude and OpenAI ids come from live
    lists this module cannot see) is left to the model registry to judge.
    """
    if not isinstance(raw, str) or not raw.strip() or not isinstance(canonical, str):
        return False
    provider, sep, model = raw.strip().partition("/")
    if not sep:
        return provider in KNOWN_VERTEX_CHAT_MODEL_IDS
    if provider == "vertex":
        return model in KNOWN_VERTEX_CHAT_MODEL_IDS
    return True


def is_agent_protected_setting(key: object) -> bool:
    """True when `key` is a model-selection setting the agent may not write."""
    if not isinstance(key, str):
        return False
    return key in AGENT_PROTECTED_SETTINGS or key.lower().endswith("model")


@dataclass(frozen=True)
class SettingOverride:
    """One persisted override.

    `default_value` is filled in by the store from the manifest at
    read time so callers see "what would this be without my override"
    next to the override itself.
    """

    key: str
    value: Any
    default_value: Any
    updated_at: str
    updated_by: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "value": self.value,
            "default_value": self.default_value,
            "updated_at": self.updated_at,
            "updated_by": self.updated_by,
        }


class SqliteSettingsStore:
    """Sqlite-backed runtime settings store at ``<data_root>/settings.db``.

    Only keys present in `overridable` may be set; attempts to set
    other keys raise PermissionError. Defaults flow in via the
    constructor — main.py reads them from manifest.yaml at boot.

    Thread-safe via a single lock; sqlite handles the rest.
    """

    def __init__(
        self,
        defaults: dict[str, Any],
        overridable: Iterable[str],
        data_root: Path | None = None,
        audit_log: Any | None = None,
    ) -> None:
        self._defaults = dict(defaults)
        self._overridable: frozenset[str] = frozenset(overridable)
        # Sanity check: every overridable key must have a default. A
        # bundle that lists a key as overridable without giving it a
        # default would let operators set values that have no anchor.
        unknown = self._overridable - self._defaults.keys()
        if unknown:
            logger.warning(
                "Settings store: overridable keys without defaults — %s. "
                "These will accept overrides but `effective()` will surface "
                "them only when set.",
                sorted(unknown),
            )

        self._data_root = (data_root or self._resolve_data_root()).resolve()
        self._data_root.mkdir(parents=True, exist_ok=True)
        self._db_path = self._data_root / "settings.db"
        self._lock = threading.Lock()
        self._audit = audit_log
        self._init_schema()
        self._migrate_renamed_settings()

    @staticmethod
    def _resolve_data_root() -> Path:
        import os
        env = os.getenv("DATA_ROOT")
        if env:
            return Path(env)
        return DEFAULT_DATA_ROOT

    def _init_schema(self) -> None:
        with self._lock, sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS setting_overrides (
                    key         TEXT PRIMARY KEY,
                    value_json  TEXT NOT NULL,
                    updated_at  TEXT NOT NULL,
                    updated_by  TEXT
                )
                """
            )

    def _migrate_renamed_settings(self) -> None:
        """Move an override stored under a retired key to its new key.

        One transaction, so a crash leaves either the old row or the new one.
        Idempotent: with no old row it does nothing. An existing row under the
        new key wins (the operator already set it with the new UI), and the old
        row is dropped either way. `updated_at` and `updated_by` carry over.
        The new key must be overridable, otherwise the row stays where it is.

        A `geminiModel` value that is not a known catalog id (a typo, a retired
        or private id) is NOT carried over: `defaultModel` stays at the manifest
        default, the old row is dropped, and the drop is logged and audited so
        the operator can see what was discarded and re-pick on /models.
        """
        for old_key, new_key in RENAMED_SETTINGS.items():
            if new_key not in self._overridable:
                continue
            migrated: tuple[Any, Any] | None = None
            dropped: tuple[Any] | None = None
            with self._lock, sqlite3.connect(self._db_path) as conn:
                conn.row_factory = sqlite3.Row
                old = conn.execute(
                    "SELECT value_json, updated_at, updated_by FROM setting_overrides WHERE key = ?",
                    (old_key,),
                ).fetchone()
                if old is None:
                    continue
                exists = conn.execute(
                    "SELECT 1 FROM setting_overrides WHERE key = ?", (new_key,),
                ).fetchone()
                raw = json.loads(old["value_json"])
                value = _canonical_default_model(raw)
                if not exists and not _is_servable_default(raw, value):
                    dropped = (raw,)
                elif not exists:
                    conn.execute(
                        "INSERT INTO setting_overrides (key, value_json, updated_at, updated_by) "
                        "VALUES (?, ?, ?, ?)",
                        (new_key, json.dumps(value), old["updated_at"], old["updated_by"]),
                    )
                    migrated = (raw, value)
                conn.execute("DELETE FROM setting_overrides WHERE key = ?", (old_key,))
            if dropped is not None:
                logger.warning(
                    "Settings migration: %s=%r is not a model in the catalog; "
                    "%s stays at its default. Pick a default on /models.",
                    old_key, dropped[0], new_key,
                )
                self._record_audit(
                    "settings_changed", key=new_key, old=dropped[0], new=None,
                    cleared=True, actor="migration", migrated_from=old_key,
                    note="value is not a known model id; not migrated",
                )
            if migrated is not None:
                self._record_audit(
                    "settings_changed", key=new_key, old=migrated[0], new=migrated[1],
                    actor="migration", migrated_from=old_key,
                )

    # ─────────────────────────────────────────────────────────────
    # Read paths
    # ─────────────────────────────────────────────────────────────

    def get(self, key: str) -> Any:
        """Return the effective value: override if set, else default."""
        override = self._read_override(key)
        if override is not None:
            return override.value
        return self._defaults.get(key)

    def effective(self) -> dict[str, Any]:
        """Return the merged {key: value} dict — defaults with overrides applied."""
        merged: dict[str, Any] = dict(self._defaults)
        for o in self._all_overrides():
            merged[o.key] = o.value
        return merged

    def overrides(self) -> list[SettingOverride]:
        """Return all current overrides (only keys with explicit values)."""
        return list(self._all_overrides())

    def is_overridable(self, key: str) -> bool:
        return key in self._overridable

    def is_overridden(self, key: str) -> bool:
        return self._read_override(key) is not None

    def describe(self) -> dict[str, Any]:
        """Whole-store snapshot for the API surface.

        Returns a single dict with:
          * defaults   — full manifest defaults (read-only reference)
          * overridable — keys the operator may set
          * effective  — merged values (what the agent actually sees)
          * overrides  — list of current overrides with metadata
        """
        return {
            "defaults": dict(self._defaults),
            "overridable": sorted(self._overridable),
            "effective": self.effective(),
            "overrides": [o.to_dict() for o in self.overrides()],
        }

    # ─────────────────────────────────────────────────────────────
    # Write paths
    # ─────────────────────────────────────────────────────────────

    def set(self, key: str, value: Any, actor: str | None = None) -> SettingOverride:
        """Set or replace an override. Raises PermissionError for non-overridable keys."""
        if key not in self._overridable:
            raise PermissionError(
                f"Setting '{key}' is not overridable per the bundle manifest. "
                f"Overridable keys: {sorted(self._overridable)}"
            )
        self._check_type(key, value)
        old = self.get(key)
        ts = self._utc_now()
        with self._lock, sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO setting_overrides (key, value_json, updated_at, updated_by)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value_json  = excluded.value_json,
                    updated_at  = excluded.updated_at,
                    updated_by  = excluded.updated_by
                """,
                (key, json.dumps(value), ts, actor),
            )
        self._record_audit("settings_changed", key=key, old=old, new=value, actor=actor)
        return SettingOverride(
            key=key, value=value, default_value=self._defaults.get(key),
            updated_at=ts, updated_by=actor,
        )

    def _check_type(self, key: str, value: Any) -> None:
        """Reject a value of a different JSON type than the setting's default.

        A bool flag set to the string "false" is truthy and an int model name
        breaks provider selection, and nothing downstream re-checks. The default
        is the only declaration of what a setting holds, so it is the contract.
        """
        default = self._defaults.get(key)
        if default is None:
            return
        if isinstance(default, bool):
            ok = isinstance(value, bool)
        elif isinstance(default, (int, float)):
            ok = isinstance(value, (int, float)) and not isinstance(value, bool)
        elif isinstance(default, str):
            ok = isinstance(value, str)
        else:
            ok = isinstance(value, type(default))
        if not ok:
            raise ValueError(
                f"Setting '{key}' takes a {type(default).__name__} "
                f"(default {default!r}); got {type(value).__name__}."
            )

    def clear(self, key: str, actor: str | None = None) -> bool:
        """Remove an override. Returns True if a row was deleted."""
        if key not in self._overridable:
            raise PermissionError(f"Setting '{key}' is not overridable.")
        old = self.get(key)
        with self._lock, sqlite3.connect(self._db_path) as conn:
            cur = conn.execute("DELETE FROM setting_overrides WHERE key = ?", (key,))
            removed = cur.rowcount > 0
        if removed:
            self._record_audit(
                "settings_changed", key=key, old=old,
                new=self._defaults.get(key), actor=actor, cleared=True,
            )
        return removed

    # ─────────────────────────────────────────────────────────────
    # Internals
    # ─────────────────────────────────────────────────────────────

    def _read_override(self, key: str) -> SettingOverride | None:
        with self._lock, sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT key, value_json, updated_at, updated_by FROM setting_overrides WHERE key = ?",
                (key,),
            ).fetchone()
        if not row:
            return None
        return SettingOverride(
            key=row["key"],
            value=json.loads(row["value_json"]),
            default_value=self._defaults.get(row["key"]),
            updated_at=row["updated_at"],
            updated_by=row["updated_by"],
        )

    def _all_overrides(self) -> Iterable[SettingOverride]:
        with self._lock, sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT key, value_json, updated_at, updated_by FROM setting_overrides ORDER BY key"
            ).fetchall()
        for row in rows:
            yield SettingOverride(
                key=row["key"],
                value=json.loads(row["value_json"]),
                default_value=self._defaults.get(row["key"]),
                updated_at=row["updated_at"],
                updated_by=row["updated_by"],
            )

    def _record_audit(self, event: str, **payload: Any) -> None:
        """Record a settings audit event. Defensive — audit failures
        never break the underlying setting write.

        Maps the settings call to SqliteAuditLog's `record(action, *,
        target, metadata)` shape:
          action   = event name (e.g. "settings_changed")
          target   = "setting:<key>" so audit queries filter cleanly
          actor    = the operator id we received via PUT body
          metadata = old/new values + cleared flag
        """
        if self._audit is None:
            return
        try:
            record = getattr(self._audit, "record", None)
            if record is None:
                return
            actor = payload.pop("actor", None)
            key = payload.get("key")
            record(
                event,
                target=f"setting:{key}" if key else None,
                actor=actor,
                metadata=payload,
            )
        except Exception as exc:  # pragma: no cover
            logger.warning("Settings audit record failed for %s: %s", event, exc)

    @staticmethod
    def _utc_now() -> str:
        from usecase._time_utils import utc_now_micros
        return utc_now_micros()


# ─────────────────────────────────────────────────────────────────
# Module-level singleton accessor — wired by main.py
# ─────────────────────────────────────────────────────────────────

_settings_store: SqliteSettingsStore | None = None


def set_settings_store(store: SqliteSettingsStore | None) -> None:
    global _settings_store
    _settings_store = store


def settings_store() -> SqliteSettingsStore | None:
    return _settings_store
