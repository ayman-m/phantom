"""Provider instance store — sqlite-backed CRUD over the same data_root
as `instance_store.py` but for **model providers** (per spark-agents
spec §7.6) rather than tool-providing connectors.

The two stores are parallel: same lifecycle (create/list/get/delete),
same setup-form materialization pattern, same instance-gating
semantics. They live in separate sqlite tables (different file)
because their consumers are different — the embedded MCP gates tool
ADVERTISEMENT on connector instances; the agent's model registry reads
provider instances for their credentials (it keeps the model catalog).

Schema (`<data_root>/provider_instances.db`):

    provider_instances(
      id           TEXT PRIMARY KEY,    -- uuid4
      provider_id  TEXT NOT NULL,        -- e.g. "vertex", "anthropic"
      name         TEXT NOT NULL,        -- e.g. "primary-vertex"
      config_json  TEXT NOT NULL,        -- JSON-encoded {key: value} from
                                         -- setup.bindsProviders[].template.config
      secrets_json TEXT NOT NULL,        -- JSON-encoded {slot_name: value}
                                         -- from .secretRefs (resolved)
      created_at   TEXT NOT NULL         -- ISO8601 UTC
    );
    UNIQUE(provider_id, name)
"""

from __future__ import annotations

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

from usecase.secret_store import ForeignSecretRefError  # noqa: F401  (re-exported)

logger = logging.getLogger("Phantom MCP")

DEFAULT_DATA_ROOT = Path("/app/data")


@dataclass(frozen=True)
class ProviderInstance:
    """One materialized provider instance.

    `secret_refs` holds PATHS into the SecretStore (parallel
    to the connector Instance). See instance_store.Instance for the
    full doc on the path-vs-value distinction and migration rules.
    """

    id: str
    provider_id: str
    name: str
    config: dict[str, Any]
    secret_refs: dict[str, Any]
    created_at: str

    def merged_config(self, secret_store: Any | None = None) -> dict[str, Any]:
        """Return config + resolved secrets as one dict."""
        resolved: dict[str, Any] = {}
        for slot, ref_or_value in self.secret_refs.items():
            if (
                secret_store is not None
                and isinstance(ref_or_value, str)
                and ref_or_value.startswith("/")
            ):
                if not is_own_secret_ref(self.id, slot, ref_or_value):
                    # A row written before the write-side check existed. Never
                    # follow a reference into another owner's secret.
                    logger.warning(
                        "ProviderInstance %s/%s: slot %s holds a reference outside "
                        "its own secret path; not resolving it.",
                        self.provider_id, self.name, slot,
                    )
                    resolved[slot] = ""
                    continue
                try:
                    resolved[slot] = secret_store.read(ref_or_value)
                except Exception as exc:
                    logger.warning(
                        "ProviderInstance %s/%s: could not resolve secret %s at %s. (%s)",
                        self.provider_id, self.name, slot, ref_or_value, exc,
                    )
                    resolved[slot] = ""
            else:
                resolved[slot] = ref_or_value
        return {**self.config, **resolved}

    @property
    def secrets(self) -> dict[str, Any]:
        return self.secret_refs


def is_own_secret_ref(instance_id: str, slot: str, value: Any) -> bool:
    """True when `value` is exactly this instance's own path for `slot`."""
    from usecase.secret_store import provider_secret_path

    return isinstance(value, str) and value == provider_secret_path(instance_id, slot)


def _check_secret_input(instance_id: str, slot: Any, value: Any) -> None:
    """Refuse a slot name or secret value that could reach another secret.

    See `usecase.secret_store.check_secret_input`: the only "/"-prefixed value
    accepted is this instance's own path for the slot (the update round trip).
    """
    from usecase.secret_store import check_secret_input, provider_secret_path

    check_secret_input(
        lambda s: provider_secret_path(instance_id, s), slot, value
    )


class ProviderStore:
    """Sqlite-backed store at ``<data_root>/provider_instances.db``."""

    def __init__(
        self,
        data_root: Path | None = None,
        secret_store: Any | None = None,
    ) -> None:
        self._data_root = (data_root or self._resolve_data_root()).resolve()
        self._data_root.mkdir(parents=True, exist_ok=True)
        self._db_path = self._data_root / "provider_instances.db"
        self._lock = threading.Lock()
        self._secret_store = secret_store
        self._init_schema()
        if secret_store is not None:
            self._migrate_legacy_secrets()
        logger.info("ProviderStore at %s", self._db_path)

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
                CREATE TABLE IF NOT EXISTS provider_instances (
                    id           TEXT PRIMARY KEY,
                    provider_id  TEXT NOT NULL,
                    name         TEXT NOT NULL,
                    config_json  TEXT NOT NULL,
                    secrets_json TEXT NOT NULL,
                    created_at   TEXT NOT NULL,
                    UNIQUE(provider_id, name)
                )
                """
            )
            c.execute(
                "CREATE INDEX IF NOT EXISTS idx_provider_instances_provider_id "
                "ON provider_instances(provider_id)"
            )

    # ─── CRUD ──────────────────────────────────────────────────

    def create(
        self,
        provider_id: str,
        name: str,
        config: dict[str, Any],
        secrets: dict[str, Any] | None = None,
    ) -> ProviderInstance:
        """Insert a new provider instance. Raises ValueError on (provider_id, name) collision."""
        from usecase.secret_store import provider_secret_path

        if not provider_id or not isinstance(provider_id, str):
            raise ValueError("provider_id must be a non-empty string")
        if not name or not isinstance(name, str):
            raise ValueError("name must be a non-empty string")
        instance_id = str(uuid.uuid4())
        secrets_in = dict(secrets or {})
        # Before anything is written. The id is new, so no "/" value can be this
        # instance's own path: every one is refused.
        for slot, value in secrets_in.items():
            _check_secret_input(instance_id, slot, value)

        if self._secret_store is not None and secrets_in:
            persisted_secret_refs: dict[str, Any] = {}
            for slot, value in secrets_in.items():
                if not isinstance(value, str):
                    persisted_secret_refs[slot] = value
                    continue
                path = provider_secret_path(instance_id, slot)
                self._secret_store.write(path, value)
                persisted_secret_refs[slot] = path
        else:
            persisted_secret_refs = secrets_in

        instance = ProviderInstance(
            id=instance_id,
            provider_id=provider_id,
            name=name,
            config=dict(config or {}),
            secret_refs=persisted_secret_refs,
            created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        )
        with self._lock, self._conn() as c:
            try:
                c.execute(
                    "INSERT INTO provider_instances "
                    "(id, provider_id, name, config_json, secrets_json, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        instance.id,
                        instance.provider_id,
                        instance.name,
                        json.dumps(instance.config),
                        json.dumps(instance.secret_refs),
                        instance.created_at,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                if self._secret_store is not None:
                    for ref in persisted_secret_refs.values():
                        if isinstance(ref, str) and ref.startswith("/"):
                            self._secret_store.delete(ref)
                raise ValueError(
                    f"provider instance ({provider_id!r}, {name!r}) already exists"
                ) from exc
        logger.info(
            "ProviderStore.create provider_id=%s name=%s id=%s "
            "(%d secret refs persisted as paths)",
            provider_id, name, instance.id,
            sum(1 for v in persisted_secret_refs.values()
                if isinstance(v, str) and v.startswith("/")),
        )
        # Audit (parallel to InstanceStore.create).
        from usecase.audit_log import record_event, ACTION_PROVIDER_CREATED
        record_event(
            ACTION_PROVIDER_CREATED,
            target=f"provider_instance:{instance.id}",
            status="success",
            metadata={
                "provider_id": provider_id,
                "name": name,
                "instance_id": instance.id,
                "config_keys": sorted(instance.config.keys()),
                "secret_slot_count": len(persisted_secret_refs),
            },
        )
        return instance

    def list_all(self) -> list[ProviderInstance]:
        with self._lock, self._conn() as c:
            rows = c.execute(
                "SELECT id, provider_id, name, config_json, secrets_json, created_at "
                "FROM provider_instances ORDER BY provider_id, name"
            ).fetchall()
        return [self._row_to_instance(r) for r in rows]

    def list_for(self, provider_id: str) -> list[ProviderInstance]:
        with self._lock, self._conn() as c:
            rows = c.execute(
                "SELECT id, provider_id, name, config_json, secrets_json, created_at "
                "FROM provider_instances WHERE provider_id = ? ORDER BY name",
                (provider_id,),
            ).fetchall()
        return [self._row_to_instance(r) for r in rows]

    def get(self, instance_id: str) -> ProviderInstance | None:
        with self._lock, self._conn() as c:
            row = c.execute(
                "SELECT id, provider_id, name, config_json, secrets_json, created_at "
                "FROM provider_instances WHERE id = ?",
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
    ) -> "ProviderInstance | None":
        """Partial update of an existing provider instance.

        Mirrors InstanceStore.update — any kwarg left None means "leave
        that field alone". For secrets, the value-level sentinel "***"
        also means "leave that slot alone" so an operator who submits
        the providers form without touching a sensitive field doesn't
        clobber the stored value with the redaction sentinel.

        Returns the refreshed ProviderInstance, or None if no row with
        that id exists.

        Lets /providers PUT write directly to the ProviderStore. See
        /help/architecture#setup-wiring.
        """
        from usecase.secret_store import provider_secret_path

        existing = self.get(instance_id)
        if existing is None:
            return None

        new_name = name if (name is not None and name != "") else existing.name
        new_config = (
            dict(config) if config is not None else dict(existing.config)
        )

        # Secret merge with "***" sentinel handling. Mirrors the
        # InstanceStore.update logic so the two stores have identical
        # write semantics for partial updates.
        new_secret_refs: dict[str, Any] = dict(existing.secret_refs)
        secrets_to_write: list[tuple[str, str]] = []  # (path, plaintext)
        if secrets is not None:
            # Validate every slot first so a refusal leaves nothing half-applied.
            for slot, value in secrets.items():
                if value != "***":
                    _check_secret_input(instance_id, slot, value)
            for slot, value in secrets.items():
                if value == "***":
                    # Sentinel: keep the existing ref untouched.
                    continue
                if not isinstance(value, str):
                    new_secret_refs[slot] = value
                    continue
                if value.startswith("/"):
                    # This slot's own SecretStore path (checked above).
                    new_secret_refs[slot] = value
                    continue
                if self._secret_store is not None:
                    path = provider_secret_path(instance_id, slot)
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
                "UPDATE provider_instances SET name = ?, config_json = ?, "
                "secrets_json = ? WHERE id = ?",
                (
                    new_name,
                    json.dumps(new_config),
                    json.dumps(new_secret_refs),
                    instance_id,
                ),
            )

        logger.info(
            "ProviderStore.update id=%s name=%s "
            "(%d config keys, %d secret refs, %d secrets rotated)",
            instance_id, new_name, len(new_config),
            len(new_secret_refs), len(secrets_to_write),
        )
        from usecase.audit_log import record_event
        record_event(
            "provider_updated",
            target=f"provider_instance:{instance_id}",
            status="success",
            metadata={
                "instance_id": instance_id,
                "provider_id": existing.provider_id,
                "name_changed": name is not None and name != existing.name,
                "config_changed": config is not None,
                "secrets_rotated": len(secrets_to_write),
            },
        )
        return self.get(instance_id)

    def delete(self, instance_id: str) -> bool:
        from usecase.secret_store import provider_prefix

        # Capture row metadata for audit BEFORE deletion
        existing = self.get(instance_id)
        with self._lock, self._conn() as c:
            cur = c.execute(
                "DELETE FROM provider_instances WHERE id = ?", (instance_id,)
            )
        deleted = cur.rowcount > 0
        if deleted:
            if self._secret_store is not None:
                self._secret_store.delete_under(provider_prefix(instance_id))
            logger.info("ProviderStore.delete id=%s", instance_id)
            from usecase.audit_log import record_event, ACTION_PROVIDER_DELETED
            record_event(
                ACTION_PROVIDER_DELETED,
                target=f"provider_instance:{instance_id}",
                status="success",
                metadata={
                    "instance_id": instance_id,
                    "provider_id": existing.provider_id if existing else None,
                    "name": existing.name if existing else None,
                },
            )
        return deleted

    def has_any(self, provider_id: str) -> bool:
        with self._lock, self._conn() as c:
            row = c.execute(
                "SELECT 1 FROM provider_instances WHERE provider_id = ? LIMIT 1",
                (provider_id,),
            ).fetchone()
        return row is not None

    def configured_provider_ids(self) -> set[str]:
        with self._lock, self._conn() as c:
            rows = c.execute(
                "SELECT DISTINCT provider_id FROM provider_instances"
            ).fetchall()
        return {r[0] for r in rows}

    @staticmethod
    def _row_to_instance(row: sqlite3.Row) -> ProviderInstance:
        return ProviderInstance(
            id=row["id"],
            provider_id=row["provider_id"],
            name=row["name"],
            config=json.loads(row["config_json"]),
            secret_refs=json.loads(row["secrets_json"]),
            created_at=row["created_at"],
        )

    # ─── Migration: legacy values → SecretStore paths ───
    def _migrate_legacy_secrets(self) -> None:
        from usecase.secret_store import provider_secret_path

        if self._secret_store is None:
            return
        migrated = 0
        with self._lock, self._conn() as c:
            rows = c.execute(
                "SELECT id, provider_id, name, secrets_json FROM provider_instances"
            ).fetchall()
            for row in rows:
                old = json.loads(row["secrets_json"])
                if not isinstance(old, dict) or not old:
                    continue
                new_refs: dict[str, Any] = {}
                changed = False
                for slot, value in old.items():
                    if isinstance(value, str) and value.startswith("/"):
                        new_refs[slot] = value
                        continue
                    if not isinstance(value, str):
                        new_refs[slot] = value
                        continue
                    path = provider_secret_path(row["id"], slot)
                    self._secret_store.write(path, value)
                    new_refs[slot] = path
                    changed = True
                if changed:
                    c.execute(
                        "UPDATE provider_instances SET secrets_json = ? WHERE id = ?",
                        (json.dumps(new_refs), row["id"]),
                    )
                    migrated += 1
        if migrated:
            logger.info(
                "ProviderStore: migrated %d legacy provider row(s) into SecretStore.",
                migrated,
            )


# ─────────────────────────────────────────────────────────────────
# Module-level singleton accessor — wired by main.py.
#
# Phantom convention (mirrors memory_store, kb_store, audit_log, etc.).
# Used by the agent-self-modification built-in tools (providers_list /
# providers_get) so they don't need to be plumbed an explicit store
# reference through every call site.
# ─────────────────────────────────────────────────────────────────

_provider_store: ProviderStore | None = None


def set_provider_store(s: ProviderStore | None) -> None:
    global _provider_store
    _provider_store = s


def provider_store() -> ProviderStore | None:
    return _provider_store
