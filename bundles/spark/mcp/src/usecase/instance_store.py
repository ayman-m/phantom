"""Connector instance store — sqlite-backed CRUD over `data_root/instances.db`.

Per spark-agents spec §7.5: the embedded MCP materializes one
`connector_instances` row per `setup.bindsInstances[]` template when
the operator submits the setup form. The MCP then advertises a
connector's tools only when at least one instance for that connector
exists (objective 5).

This module is the local-mode equivalent of the platform's Postgres
`connector_instances` table (see upstream
services/connector-manager/internal/mcp/pg_instance_store.go).

Schema:
    instances(
      id           TEXT PRIMARY KEY,    -- uuid4
      connector_id TEXT NOT NULL,        -- e.g. "caldera", "xsiam", "xlog"
      name         TEXT NOT NULL,        -- e.g. "primary-caldera"
      config_json  TEXT NOT NULL,        -- JSON-encoded {key: value} from
                                         -- setup.bindsInstances[].template.config
                                         -- with ${setup.X} interpolated
      secrets_json TEXT NOT NULL,        -- JSON-encoded {slot_name: secret_value}
                                         -- from .secretRefs (resolved)
      created_at   TEXT NOT NULL         -- ISO8601 UTC
    );
    UNIQUE(connector_id, name)
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("Phantom MCP")

DEFAULT_DATA_ROOT = Path("/app/data")


@dataclass(frozen=True)
class Instance:
    """One materialized connector instance.

    `secret_refs` holds PATHS into the
    SecretStore, not literal secret values. Resolution happens at
    tool-call time via `merged_config(secret_store)` which reads each
    referenced secret fresh from the store.

    Backward compat: legacy rows store literal
    values in `secret_refs`. `merged_config()` detects this (values
    that don't start with `/`) and passes them through unchanged. The
    migration on InstanceStore boot moves those legacy values into the
    SecretStore and updates the rows in place to use paths.

    `enabled` is per-instance (separate from connector_state's
    enabled flag, which is per-CONNECTOR). The store enforces "at most
    one enabled instance per connector_id" at create + update time —
    operators can have multiple instances coexist (e.g. for testing
    alternate config) but only one can be the live one at a time.
    """

    id: str
    connector_id: str
    name: str
    config: dict[str, Any]
    secret_refs: dict[str, Any]
    created_at: str
    enabled: bool = True
    # Per-instance container URL (connectors run as per-instance
    # containers, `runtimeMapping.style: container`). NULL/None until
    # the container is up. Populated
    # by phantom-updater's `start` endpoint when it brings up the
    # connector container; cleared by `stop`. The connector_loader's
    # container branch (see _resolve_callable) reads this via
    # merged_config()→contextvar→get_config().container_url at every
    # tool call, so live URL changes (container restart with new IP)
    # propagate without an agent restart.
    container_url: str | None = None

    # Per-instance disabled-tools list. Operators
    # toggle which of the connector's tools the agent sees via the
    # /connectors/<connector_id>-<instance_name> Tools tab. Empty
    # list (the default) means every tool the connector ships is
    # exposed. Tool names in this list are filtered out by
    # connector_loader before FastMCP registration — the agent's
    # catalog never sees them. Stored as a JSON string in the
    # disabled_tools sqlite column; surfaced here as Python list.
    disabled_tools: list[str] = field(default_factory=list)

    def merged_config(self, secret_store: Any | None = None) -> dict[str, Any]:
        """Return config + resolved secrets + container_url as one dict.

        secret_refs values that look like SecretStore paths
        (start with `/`) are resolved through the store; legacy
        literal values pass through. Pass `secret_store=None` to get
        config + literal-values (used by the migration path).

        container_url is added to the merged dict (when set) so
        connector code reading get_config().container_url sees it.
        The connector proxy callables read this.
        """
        resolved: dict[str, Any] = {}
        for slot, ref_or_value in self.secret_refs.items():
            if (
                secret_store is not None
                and isinstance(ref_or_value, str)
                and ref_or_value.startswith("/")
            ):
                try:
                    resolved[slot] = secret_store.read(ref_or_value)
                except Exception as exc:
                    logger.warning(
                        "Instance %s/%s: could not resolve secret %s at %s — using empty. (%s)",
                        self.connector_id, self.name, slot, ref_or_value, exc,
                    )
                    resolved[slot] = ""
            else:
                resolved[slot] = ref_or_value
        merged = {**self.config, **resolved}
        # Only inject when set — None would shadow legitimate
        # connector-supplied container_url overrides if any future
        # connector defines that key in its own configSchema.
        if self.container_url is not None:
            merged["container_url"] = self.container_url
        return merged

    # Back-compat alias for callers that still use `.secrets`.
    @property
    def secrets(self) -> dict[str, Any]:
        return self.secret_refs

    def resolved_secrets(self, secret_store: Any | None = None) -> dict[str, Any]:
        """Just the secrets, with SecretStore paths resolved to plaintext.

        Companion to `merged_config()` for callers that want secrets
        (and only secrets) — e.g. the /test route passing them to
        connector_probes.real_probe(secrets=...). Without a SecretStore,
        legacy literal values pass through unchanged.
        """
        out: dict[str, Any] = {}
        for slot, ref in self.secret_refs.items():
            if (
                secret_store is not None
                and isinstance(ref, str)
                and ref.startswith("/")
            ):
                try:
                    out[slot] = secret_store.read(ref)
                except Exception as exc:
                    logger.warning(
                        "Instance %s/%s: could not resolve secret %s at %s — using empty. (%s)",
                        self.connector_id, self.name, slot, ref, exc,
                    )
                    out[slot] = ""
            else:
                out[slot] = ref
        return out


class InstanceStore:
    """Sqlite-backed store at ``<data_root>/instances.db``.

    Thread-safe via a single lock (sqlite handles the rest); MCP tool
    calls are async but each call's CRUD touches the DB briefly.
    """

    def __init__(
        self,
        data_root: Path | None = None,
        secret_store: Any | None = None,
    ) -> None:
        self._data_root = (data_root or self._resolve_data_root()).resolve()
        self._data_root.mkdir(parents=True, exist_ok=True)
        self._db_path = self._data_root / "instances.db"
        self._lock = threading.Lock()
        # Optional SecretStore. When provided, create() writes
        # secret VALUES to the store and persists only PATHS in the DB.
        # When None, secrets are persisted as values (legacy mode); used
        # by tests and the migration path.
        self._secret_store = secret_store
        self._init_schema()
        if secret_store is not None:
            self._migrate_legacy_secrets()
        logger.info("InstanceStore at %s", self._db_path)

    @property
    def secret_store(self) -> Any | None:
        """The SecretStore bound at construction. Phase-12 closed-loop
        tools use this to resolve instance secrets without rebuilding
        the secret-store wiring themselves. Returns None when the
        store is in legacy literal-value mode (tests + migration)."""
        return self._secret_store

    @staticmethod
    def _resolve_data_root() -> Path:
        raw = os.getenv("DATA_ROOT", str(DEFAULT_DATA_ROOT))
        return Path(raw)

    @property
    def db_path(self) -> Path:
        return self._db_path

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self._db_path, isolation_level=None)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys = ON")
        return c

    def _init_schema(self) -> None:
        with self._lock, self._conn() as c:
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS instances (
                    id           TEXT PRIMARY KEY,
                    connector_id TEXT NOT NULL,
                    name         TEXT NOT NULL,
                    config_json  TEXT NOT NULL,
                    secrets_json TEXT NOT NULL,
                    created_at   TEXT NOT NULL,
                    enabled      INTEGER NOT NULL DEFAULT 1,
                    UNIQUE(connector_id, name)
                )
                """
            )
            c.execute(
                "CREATE INDEX IF NOT EXISTS idx_instances_connector_id "
                "ON instances(connector_id)"
            )
            # Migration: tables created before the
            # `enabled` column existed need an ALTER. SQLite returns
            # "duplicate column" if it already exists, which we swallow.
            try:
                c.execute(
                    "ALTER TABLE instances ADD COLUMN enabled "
                    "INTEGER NOT NULL DEFAULT 1"
                )
                logger.info(
                    "InstanceStore: migrated existing schema — added enabled column"
                )
            except sqlite3.OperationalError as exc:
                if "duplicate column" not in str(exc).lower():
                    raise

            # Migration: container_url for per-instance
            # connector containers. Nullable — only set for connectors
            # with style: container; in-process connectors leave it
            # NULL. Populated by phantom-updater's start endpoint.
            # Same swallow-on-duplicate pattern as the
            # enabled migration above.
            try:
                c.execute(
                    "ALTER TABLE instances ADD COLUMN container_url TEXT"
                )
                logger.info(
                    "InstanceStore: migrated schema — added container_url column"
                )
            except sqlite3.OperationalError as exc:
                if "duplicate column" not in str(exc).lower():
                    raise

            # Migration: disabled_tools JSON array.
            # Per-instance opt-out list. Empty = all tools the
            # connector ships are exposed to the agent. Populated
            # name strings = those tool names are filtered out at
            # registration time in connector_loader.py.
            #
            # Default '[]' keeps backward-compat: existing instances
            # see no change in tool catalog. The agent picks up new
            # tools when the connector adds them, EXCEPT for names
            # the operator has explicitly disabled.
            try:
                c.execute(
                    "ALTER TABLE instances ADD COLUMN disabled_tools "
                    "TEXT NOT NULL DEFAULT '[]'"
                )
                logger.info(
                    "InstanceStore: migrated schema — added disabled_tools column"
                )
            except sqlite3.OperationalError as exc:
                if "duplicate column" not in str(exc).lower():
                    raise

    # ─── CRUD ──────────────────────────────────────────────────

    def create(
        self,
        connector_id: str,
        name: str,
        config: dict[str, Any],
        secrets: dict[str, Any] | None = None,
        *,
        enabled: bool = True,
        disabled_tools: list[str] | None = None,
    ) -> Instance:
        """Insert a new instance. Raises ValueError on:

        * (connector_id, name) collision
        * `enabled=True` while another instance for the same connector_id
          already has enabled=True (one-active-per-connector rule). The
          error message is operator-friendly so the API handler can
          surface it directly.

        When a SecretStore is wired (the production path),
        each secret VALUE is written to the store and the row holds
        only its `secretRefs` PATH. Without a SecretStore (tests /
        legacy), values are persisted as-is.
        """
        # Lazy import to avoid a circular dependency in test contexts.
        from usecase.secret_store import connector_secret_path

        if not connector_id or not isinstance(connector_id, str):
            raise ValueError("connector_id must be a non-empty string")
        if not name or not isinstance(name, str):
            raise ValueError("name must be a non-empty string")

        # Enforce one-active-per-connector before creating.
        if enabled:
            for other in self.list_for(connector_id):
                if other.enabled:
                    raise ValueError(
                        f"connector {connector_id!r} already has an active "
                        f"instance ({other.name!r}). Disable it first, or "
                        f"create this one with enabled=False."
                    )

        instance_id = str(uuid.uuid4())
        secrets_in = dict(secrets or {})

        # Compute what to persist: paths if we have a SecretStore,
        # values otherwise.
        if self._secret_store is not None and secrets_in:
            persisted_secret_refs: dict[str, Any] = {}
            for slot, value in secrets_in.items():
                if not isinstance(value, str):
                    # Non-string values can't be stored; coerce or skip.
                    persisted_secret_refs[slot] = value
                    continue
                if value.startswith("/"):
                    # Already a path (e.g. operator pre-bound an external
                    # secret). Store the path verbatim — don't double-write.
                    persisted_secret_refs[slot] = value
                    continue
                path = connector_secret_path(instance_id, slot)
                self._secret_store.write(path, value)
                persisted_secret_refs[slot] = path
        else:
            persisted_secret_refs = secrets_in

        # disabled_tools accepted at create time. Operator
        # can pre-disable specific tools via the create-instance form.
        # Deduped + string-coerced to match update_disabled_tools.
        clean_disabled: list[str] = []
        seen: set[str] = set()
        for t in disabled_tools or []:
            s = str(t).strip()
            if s and s not in seen:
                seen.add(s)
                clean_disabled.append(s)
        instance = Instance(
            id=instance_id,
            connector_id=connector_id,
            name=name,
            config=dict(config or {}),
            secret_refs=persisted_secret_refs,
            created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            enabled=enabled,
            disabled_tools=clean_disabled,
        )
        with self._lock, self._conn() as c:
            try:
                c.execute(
                    "INSERT INTO instances "
                    "(id, connector_id, name, config_json, secrets_json, "
                    " created_at, enabled, disabled_tools) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        instance.id,
                        instance.connector_id,
                        instance.name,
                        json.dumps(instance.config),
                        json.dumps(instance.secret_refs),
                        instance.created_at,
                        1 if instance.enabled else 0,
                        json.dumps(clean_disabled),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                # Roll back the secrets we just wrote — they'd be orphaned.
                if self._secret_store is not None:
                    for slot, ref in persisted_secret_refs.items():
                        if isinstance(ref, str) and ref.startswith("/"):
                            self._secret_store.delete(ref)
                raise ValueError(
                    f"instance ({connector_id!r}, {name!r}) already exists"
                ) from exc
        logger.info(
            "InstanceStore.create connector_id=%s name=%s id=%s "
            "(%d secret refs persisted as paths)",
            connector_id, name, instance.id,
            sum(1 for v in persisted_secret_refs.values()
                if isinstance(v, str) and v.startswith("/")),
        )
        # Audit. Lazy import sidesteps the boot-order issue
        # (audit_log singleton may not yet be wired when tests construct
        # the store directly). record_event() is a no-op when unwired.
        from usecase.audit_log import record_event, ACTION_INSTANCE_CREATED
        record_event(
            ACTION_INSTANCE_CREATED,
            target=f"instance:{instance.id}",
            status="success",
            metadata={
                "connector_id": connector_id,
                "name": name,
                "instance_id": instance.id,
                "config_keys": sorted(instance.config.keys()),
                "secret_slot_count": len(persisted_secret_refs),
            },
        )
        return instance

    def list_all(self) -> list[Instance]:
        with self._lock, self._conn() as c:
            rows = c.execute(
                "SELECT id, connector_id, name, config_json, secrets_json, created_at, enabled, container_url, disabled_tools "
                "FROM instances ORDER BY connector_id, name"
            ).fetchall()
        return [self._row_to_instance(r) for r in rows]

    def list_for(self, connector_id: str) -> list[Instance]:
        with self._lock, self._conn() as c:
            rows = c.execute(
                "SELECT id, connector_id, name, config_json, secrets_json, created_at, enabled, container_url, disabled_tools "
                "FROM instances WHERE connector_id = ? ORDER BY name",
                (connector_id,),
            ).fetchall()
        return [self._row_to_instance(r) for r in rows]

    def get(self, instance_id: str) -> Instance | None:
        with self._lock, self._conn() as c:
            row = c.execute(
                "SELECT id, connector_id, name, config_json, secrets_json, created_at, enabled, container_url, disabled_tools "
                "FROM instances WHERE id = ?",
                (instance_id,),
            ).fetchone()
        return self._row_to_instance(row) if row else None

    def update(
        self,
        instance_id: str,
        *,
        name: str | None = None,
        config: dict[str, Any] | None = None,
        secrets: dict[str, Any] | None = None,
        enabled: bool | None = None,
    ) -> Instance | None:
        """Partial update of an existing instance.

        Any kwarg left as None means "leave that field alone." For
        secrets, the value-level sentinel "***" also means "leave that
        slot alone" — matches the redaction sentinel returned by
        _instance_to_dict, so an operator who submits the form without
        editing a secret slot doesn't clobber it with "***" on save.

        Setting `enabled=True` while another instance for the same
        connector_id is also enabled raises ValueError ("one active
        per connector" rule). Setting `enabled=False` always succeeds.

        Returns the updated Instance, or None if no row with that id
        exists.
        """
        from usecase.secret_store import connector_secret_path

        existing = self.get(instance_id)
        if existing is None:
            return None

        # Enforce one-active-per-connector when enabling.
        if enabled is True and not existing.enabled:
            for other in self.list_for(existing.connector_id):
                if other.id != instance_id and other.enabled:
                    raise ValueError(
                        f"connector {existing.connector_id!r} already has "
                        f"an active instance ({other.name!r}). Disable it "
                        f"first before enabling {existing.name!r}."
                    )

        new_name = name if (name is not None and name != "") else existing.name
        new_config = (
            dict(config) if config is not None else dict(existing.config)
        )
        new_enabled = enabled if enabled is not None else existing.enabled

        # Secret merge with "***" sentinel handling.
        new_secret_refs: dict[str, Any] = dict(existing.secret_refs)
        secrets_to_write: list[tuple[str, str]] = []  # (slot, plaintext)
        if secrets is not None:
            for slot, value in secrets.items():
                if value == "***":
                    # Sentinel: keep the existing ref untouched.
                    continue
                if not isinstance(value, str):
                    new_secret_refs[slot] = value
                    continue
                if value.startswith("/"):
                    # Already a SecretStore path — store verbatim.
                    new_secret_refs[slot] = value
                    continue
                if self._secret_store is not None:
                    path = connector_secret_path(instance_id, slot)
                    secrets_to_write.append((path, value))
                    new_secret_refs[slot] = path
                else:
                    new_secret_refs[slot] = value

        # Persist secrets first so a sqlite failure below doesn't leave
        # stored secrets without a referencing row.
        if self._secret_store is not None:
            for path, plaintext in secrets_to_write:
                self._secret_store.write(path, plaintext)

        with self._lock, self._conn() as c:
            c.execute(
                "UPDATE instances SET name = ?, config_json = ?, "
                "secrets_json = ?, enabled = ? WHERE id = ?",
                (
                    new_name,
                    json.dumps(new_config),
                    json.dumps(new_secret_refs),
                    1 if new_enabled else 0,
                    instance_id,
                ),
            )

        logger.info(
            "InstanceStore.update id=%s name=%s enabled=%s "
            "(%d config keys, %d secret refs, %d secrets rotated)",
            instance_id, new_name, new_enabled, len(new_config),
            len(new_secret_refs), len(secrets_to_write),
        )
        from usecase.audit_log import record_event
        record_event(
            "instance_updated",
            target=f"instance:{instance_id}",
            status="success",
            metadata={
                "instance_id": instance_id,
                "name_changed": name is not None and name != existing.name,
                "config_changed": config is not None,
                "secrets_rotated": len(secrets_to_write),
            },
        )
        return self.get(instance_id)

    def set_container_url(
        self, instance_id: str, container_url: str | None,
    ) -> bool:
        """Set (or clear) the container_url for a connector instance.
        Called by phantom-updater's lifecycle endpoints:

          - start endpoint:   set_container_url(id, "http://phantom-connector-X-Y:9000")
          - stop endpoint:    set_container_url(id, None)
          - restart endpoint: set_container_url(id, "http://phantom-connector-X-Y:9000")
                              (URL may differ if Docker assigned a new IP, hence the
                              explicit re-set rather than no-op)

        Returns True if the row was found and updated, False if no
        instance with that id exists.

        Doesn't audit-log this — the upstream phantom-updater
        endpoint emits its own `connector_container_started` /
        `_stopped` audit row that's more operator-meaningful than
        the raw column update.
        """
        with self._lock, self._conn() as c:
            cur = c.execute(
                "UPDATE instances SET container_url = ? WHERE id = ?",
                (container_url, instance_id),
            )
        return cur.rowcount > 0

    def update_disabled_tools(
        self,
        instance_id: str,
        disabled_tools: list[str],
    ) -> bool:
        """Set the per-instance disabled-tools list.

        Operators toggle individual tools via the /connectors Tools tab;
        the agent's tool catalog rebuilds on the next instance load so
        the change takes effect without restarting the agent or the
        per-instance connector container.

        Idempotent: calling with the same list a second time is a
        no-op (rowcount=1 still, but content unchanged). Audit logging
        for individual toggle changes is the route handler's
        responsibility — this method is pure storage.

        Returns True if the row was found and updated, False if no
        instance with that id exists.
        """
        # Defensive — coerce all entries to strings + de-dupe stably.
        cleaned: list[str] = []
        seen: set[str] = set()
        for t in disabled_tools or []:
            s = str(t).strip()
            if s and s not in seen:
                seen.add(s)
                cleaned.append(s)
        payload = json.dumps(cleaned)
        with self._lock, self._conn() as c:
            cur = c.execute(
                "UPDATE instances SET disabled_tools = ? WHERE id = ?",
                (payload, instance_id),
            )
        return cur.rowcount > 0

    def delete(self, instance_id: str) -> bool:
        # Also clean up the instance's secrets in the store
        # so we don't leak orphaned secret files.
        from usecase.secret_store import connector_prefix

        # Capture row metadata for audit BEFORE we delete it,
        # so the audit row can record connector_id/name even after the
        # underlying instance is gone.
        existing = self.get(instance_id)
        with self._lock, self._conn() as c:
            cur = c.execute("DELETE FROM instances WHERE id = ?", (instance_id,))
        deleted = cur.rowcount > 0
        if deleted:
            if self._secret_store is not None:
                self._secret_store.delete_under(connector_prefix(instance_id))
            logger.info("InstanceStore.delete id=%s", instance_id)
            from usecase.audit_log import record_event, ACTION_INSTANCE_DELETED
            record_event(
                ACTION_INSTANCE_DELETED,
                target=f"instance:{instance_id}",
                status="success",
                metadata={
                    "instance_id": instance_id,
                    "connector_id": existing.connector_id if existing else None,
                    "name": existing.name if existing else None,
                },
            )
        return deleted

    def has_any(self, connector_id: str) -> bool:
        with self._lock, self._conn() as c:
            row = c.execute(
                "SELECT 1 FROM instances WHERE connector_id = ? LIMIT 1",
                (connector_id,),
            ).fetchone()
        return row is not None

    def configured_connector_ids(self) -> set[str]:
        """Return the set of connector_ids that have ≥1 instance."""
        with self._lock, self._conn() as c:
            rows = c.execute("SELECT DISTINCT connector_id FROM instances").fetchall()
        return {r[0] for r in rows}

    @staticmethod
    def _row_to_instance(row: sqlite3.Row) -> Instance:
        # container_url is nullable + may be missing entirely
        # on rows fetched mid-migration (very narrow window — should
        # not happen in production). Defensive read mirrors the
        # `enabled` pattern below.
        try:
            container_url = row["container_url"]
        except (IndexError, KeyError):
            container_url = None
        # disabled_tools is a JSON-encoded list. Missing
        # column / NULL / parse error → treat as empty (all enabled).
        # Same defensive pattern as container_url + enabled — keeps the
        # upgrade path forgiving.
        try:
            raw_disabled = row["disabled_tools"]
            disabled_tools = json.loads(raw_disabled) if raw_disabled else []
            if not isinstance(disabled_tools, list):
                disabled_tools = []
            # Defensive — coerce all entries to strings
            disabled_tools = [str(t) for t in disabled_tools]
        except (IndexError, KeyError, json.JSONDecodeError, TypeError):
            disabled_tools = []
        return Instance(
            id=row["id"],
            connector_id=row["connector_id"],
            name=row["name"],
            config=json.loads(row["config_json"]),
            secret_refs=json.loads(row["secrets_json"]),
            created_at=row["created_at"],
            # Legacy rows have no enabled column; the ALTER
            # TABLE sets the default to 1, but if for some reason the
            # column is missing or NULL, treat as enabled (safer for
            # the upgrade path — operators don't have to re-enable
            # working instances).
            enabled=bool(row["enabled"]) if "enabled" in row.keys() else True,
            container_url=container_url if container_url else None,
            disabled_tools=disabled_tools,
        )

    # ─── Migration: legacy values → SecretStore paths ───
    def _migrate_legacy_secrets(self) -> None:
        """Detect rows with literal secret values and move them into the
        SecretStore, replacing values with the resulting paths.

        A "legacy row" is one where any value in `secrets_json` doesn't
        start with `/` (i.e. isn't a SecretStore path). After migration
        the row's `secrets_json` holds only paths.

        Idempotent — safe to run on every boot. Rows that already use
        paths are left alone.
        """
        from usecase.secret_store import connector_secret_path

        if self._secret_store is None:
            return

        migrated = 0
        with self._lock, self._conn() as c:
            rows = c.execute(
                "SELECT id, connector_id, name, secrets_json FROM instances"
            ).fetchall()

            for row in rows:
                old = json.loads(row["secrets_json"])
                if not isinstance(old, dict) or not old:
                    continue
                new_refs: dict[str, Any] = {}
                changed = False
                for slot, value in old.items():
                    if isinstance(value, str) and value.startswith("/"):
                        # Already a path — leave alone.
                        new_refs[slot] = value
                        continue
                    if not isinstance(value, str):
                        # Non-string — leave verbatim (will be flagged
                        # by merged_config's pass-through).
                        new_refs[slot] = value
                        continue
                    path = connector_secret_path(row["id"], slot)
                    self._secret_store.write(path, value)
                    new_refs[slot] = path
                    changed = True
                if changed:
                    c.execute(
                        "UPDATE instances SET secrets_json = ? WHERE id = ?",
                        (json.dumps(new_refs), row["id"]),
                    )
                    migrated += 1
                    logger.info(
                        "InstanceStore: migrated legacy secrets for %s/%s "
                        "(%d slots → SecretStore paths)",
                        row["connector_id"], row["name"], len(new_refs),
                    )

        if migrated:
            logger.info(
                "InstanceStore: Phase-5 secret migration moved %d legacy "
                "row(s) into SecretStore. Sqlite now holds only paths.",
                migrated,
            )


# ─────────────────────────────────────────────────────────────────
# Module-level singleton accessor — wired by main.py.
#
# Phantom convention (mirrors memory_store, kb_store, audit_log,
# settings_store, etc.). Exists so the agent-self-modification
# built-in tools (instances_list / instances_get) can look up the
# active store at call time without being passed it through every
# function signature. Returns None pre-boot or in tests that don't
# wire main.py.
# ─────────────────────────────────────────────────────────────────

_instance_store: InstanceStore | None = None


def set_instance_store(s: InstanceStore | None) -> None:
    global _instance_store
    _instance_store = s


def instance_store() -> InstanceStore | None:
    return _instance_store
