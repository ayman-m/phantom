"""Log destinations store.

SQLite-backed CRUD for operator-configured log forwarding targets.

Each row holds:
  * non-secret config (host/port/url/etc.) as a JSON dict
  * secret REFS (slot_name → SecretStore path) for any field whose
    type is `secret` or `password` in the type manifest
  * probe outcome columns (last_probe_at, last_probe_ok, last_probe_error,
    consecutive_failures) for observability

The row's `type_id` identifies which destination_types manifest +
handler the value goes through at probe + send time.

Invariants:
  * `name` is UNIQUE table-wide (operator-friendly handle)
  * at most one `is_default=1` per `type_id` (enforced in `set_default`)
  * secrets at `/agents/phantom/log_destinations/<id>/<slot>` —
    cascade-deleted on row delete

CLAUDE.md placement:
  * SECRETS  side of the catalog/credential boundary
  * Agent MCP tools registered: list, get (BOTH redacted; no
    `include_secrets` parameter exposed)
  * REST-only: POST, PATCH, DELETE, /probe, /set-default
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from .destination_types_loader import (
    get_destination_types_loader,
)
from .secret_store import (
    SecretStore,
    log_destination_prefix,
    log_destination_secret_path,
)

logger = logging.getLogger("Phantom MCP")


# ─── Dataclass ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class LogDestination:
    id: str
    name: str
    type_id: str
    config: dict[str, Any]
    secret_refs: dict[str, str]
    enabled: bool = True
    is_default: bool = False
    description: str | None = None
    created_at: str = ""
    updated_at: str = ""
    last_probe_at: str | None = None
    last_probe_ok: bool | None = None
    last_probe_error: str | None = None
    consecutive_failures: int = 0

    def to_dict(self, *, include_secrets: bool = False) -> dict[str, Any]:
        """Serialize for API responses.

        `include_secrets=False` (the default) returns the row with
        `"***"` sentinel in place of each `secret_refs` entry — the
        client knows the slot is populated but never sees the value.
        `include_secrets=True` returns the RESOLVED secret values
        (read fresh from SecretStore by `merged_config()` not by this
        method) — gated by the caller; this dataclass alone never
        emits plaintext.
        """
        secrets_view: dict[str, str] = {
            slot: "***" for slot in self.secret_refs.keys()
        }
        return {
            "id": self.id,
            "name": self.name,
            "type_id": self.type_id,
            "config": dict(self.config),
            "secrets": secrets_view,  # redacted by default
            "enabled": self.enabled,
            "is_default": self.is_default,
            "description": self.description,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "last_probe_at": self.last_probe_at,
            "last_probe_ok": self.last_probe_ok,
            "last_probe_error": self.last_probe_error,
            "consecutive_failures": self.consecutive_failures,
        }


# ─── Store ─────────────────────────────────────────────────────────


DEFAULT_DATA_ROOT = Path("/app/data")


class LogDestinationStore:
    """SQLite + SecretStore-backed CRUD for log destinations."""

    SCHEMA_SQL = """
    CREATE TABLE IF NOT EXISTS log_destinations (
        id                   TEXT PRIMARY KEY,
        name                 TEXT NOT NULL UNIQUE,
        type_id              TEXT NOT NULL,
        config_json          TEXT NOT NULL,
        secret_refs_json     TEXT NOT NULL,
        enabled              INTEGER NOT NULL DEFAULT 1,
        is_default           INTEGER NOT NULL DEFAULT 0,
        description          TEXT,
        created_at           TEXT NOT NULL,
        updated_at           TEXT NOT NULL,
        last_probe_at        TEXT,
        last_probe_ok        INTEGER,
        last_probe_error     TEXT,
        consecutive_failures INTEGER NOT NULL DEFAULT 0
    );
    CREATE INDEX IF NOT EXISTS idx_log_dest_type_id
        ON log_destinations(type_id);
    CREATE INDEX IF NOT EXISTS idx_log_dest_enabled
        ON log_destinations(enabled);
    """

    def __init__(
        self,
        data_root: Path | None = None,
        secret_store: SecretStore | None = None,
    ) -> None:
        root = data_root or self._resolve_data_root()
        root.mkdir(parents=True, exist_ok=True)
        self.db_path = root / "log_destinations.db"
        self._secret_store = secret_store or SecretStore(data_root=root)
        self._lock = threading.RLock()
        self._init_schema()

    @staticmethod
    def _resolve_data_root() -> Path:
        override = os.environ.get("PHANTOM_DATA_ROOT")
        return Path(override) if override else DEFAULT_DATA_ROOT

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._lock, self._conn() as c:
            for stmt in self.SCHEMA_SQL.strip().split(";"):
                stmt = stmt.strip()
                if stmt:
                    c.execute(stmt)

    # ─── Helpers ───────────────────────────────────────────────────

    def _row_to_dest(self, row: sqlite3.Row) -> LogDestination:
        return LogDestination(
            id=row["id"],
            name=row["name"],
            type_id=row["type_id"],
            config=json.loads(row["config_json"] or "{}"),
            secret_refs=json.loads(row["secret_refs_json"] or "{}"),
            enabled=bool(row["enabled"]),
            is_default=bool(row["is_default"]),
            description=row["description"],
            created_at=row["created_at"] or "",
            updated_at=row["updated_at"] or "",
            last_probe_at=row["last_probe_at"],
            last_probe_ok=(None if row["last_probe_ok"] is None
                           else bool(row["last_probe_ok"])),
            last_probe_error=row["last_probe_error"],
            consecutive_failures=int(row["consecutive_failures"] or 0),
        )

    @staticmethod
    def _now_iso() -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    def _split_fields(
        self, type_id: str, mixed: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, str]]:
        """Split a flat dict into (non_secret_config, secret_values).

        The manifest's `fields[]` is the discriminator — anything with
        type `secret` or `password` lands in the secret_values bucket;
        everything else lands in non_secret_config.

        Unknown fields (not in the manifest) are passed through to
        non_secret_config — the manifest may have grown a new field
        since the row was written; we don't want to lose data.
        """
        loader = get_destination_types_loader()
        manifest = loader.get(type_id)
        secret_names = set(manifest.secret_slot_names()) if manifest else set()
        cfg: dict[str, Any] = {}
        secrets: dict[str, str] = {}
        for k, v in mixed.items():
            if k in secret_names:
                if v is not None and v != "":
                    secrets[k] = str(v)
            else:
                cfg[k] = v
        return cfg, secrets

    def merged_config(self, id_or_name: str) -> dict[str, Any] | None:
        """Return config dict with secret_refs resolved to PLAINTEXT.

        SERVER-SIDE ONLY. Never crosses the agent's MCP tool surface
        (caller is xlog inside the agent container, or the /probe REST
        handler). Caller is responsible for not leaking the result.
        """
        dest = self.get(id_or_name)
        if dest is None:
            return None
        merged = dict(dest.config)
        for slot, path in dest.secret_refs.items():
            try:
                merged[slot] = self._secret_store.read(path)
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "merged_config: failed to read secret %s for %s: %s",
                    path, dest.id, e,
                )
                merged[slot] = None
        return merged

    # ─── CRUD ──────────────────────────────────────────────────────

    def create(
        self,
        *,
        name: str,
        type_id: str,
        config: dict[str, Any],
        secrets: dict[str, str] | None = None,
        description: str | None = None,
        enabled: bool = True,
        is_default: bool = False,
    ) -> LogDestination:
        """Insert a new destination. Raises ValueError on:
          * empty name
          * unknown type_id (no manifest)
          * duplicate name (UNIQUE collision)
        """
        if not name or not isinstance(name, str):
            raise ValueError("name is required (non-empty string)")
        loader = get_destination_types_loader()
        manifest = loader.get(type_id)
        if manifest is None:
            raise ValueError(
                f"unknown destination type {type_id!r} "
                f"(available: {sorted(loader.list_all().keys())})"
            )

        dest_id = str(uuid.uuid4())
        cfg, secret_values = self._split_fields(
            type_id, {**(config or {}), **(secrets or {})},
        )

        # Persist secret values into SecretStore at their paths
        secret_refs: dict[str, str] = {}
        for slot, value in secret_values.items():
            path = log_destination_secret_path(dest_id, slot)
            self._secret_store.write(path, value)
            secret_refs[slot] = path

        now = self._now_iso()
        with self._lock, self._conn() as c:
            try:
                c.execute(
                    "INSERT INTO log_destinations "
                    "(id, name, type_id, config_json, secret_refs_json, "
                    " enabled, is_default, description, created_at, "
                    " updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        dest_id, name, type_id,
                        json.dumps(cfg), json.dumps(secret_refs),
                        1 if enabled else 0,
                        1 if is_default else 0,
                        description, now, now,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                # Roll back secrets we just wrote
                self._secret_store.delete_under(
                    log_destination_prefix(dest_id),
                )
                raise ValueError(
                    f"destination name {name!r} already exists"
                ) from exc

            # If is_default=True, clear default on siblings of same type
            if is_default:
                c.execute(
                    "UPDATE log_destinations SET is_default = 0 "
                    "WHERE type_id = ? AND id <> ?",
                    (type_id, dest_id),
                )

        return self._must_get(dest_id)

    def get(self, id_or_name: str) -> LogDestination | None:
        """Fetch by id (uuid) OR name (case-sensitive)."""
        with self._lock, self._conn() as c:
            row = c.execute(
                "SELECT * FROM log_destinations WHERE id = ?",
                (id_or_name,),
            ).fetchone()
            if row is None:
                row = c.execute(
                    "SELECT * FROM log_destinations WHERE name = ?",
                    (id_or_name,),
                ).fetchone()
        return self._row_to_dest(row) if row else None

    def _must_get(self, dest_id: str) -> LogDestination:
        d = self.get(dest_id)
        if d is None:
            raise RuntimeError(
                f"INTERNAL: destination {dest_id} missing right after write"
            )
        return d

    def list_all(
        self,
        *,
        type_id: str | None = None,
        enabled_only: bool = False,
    ) -> list[LogDestination]:
        clauses: list[str] = []
        params: list[Any] = []
        if type_id is not None:
            clauses.append("type_id = ?")
            params.append(type_id)
        if enabled_only:
            clauses.append("enabled = 1")
        sql = "SELECT * FROM log_destinations"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY name"
        with self._lock, self._conn() as c:
            rows = c.execute(sql, params).fetchall()
        return [self._row_to_dest(r) for r in rows]

    def update(
        self,
        dest_id: str,
        *,
        name: str | None = None,
        config: dict[str, Any] | None = None,
        secrets: dict[str, str] | None = None,
        enabled: bool | None = None,
        is_default: bool | None = None,
        description: str | None = None,
    ) -> LogDestination | None:
        existing = self.get(dest_id)
        if existing is None:
            return None

        new_name = name if (name is not None and name != "") else existing.name
        new_description = (description
                           if description is not None
                           else existing.description)
        new_enabled = enabled if enabled is not None else existing.enabled

        # Merge config + secrets (replacement semantics for the keys
        # the caller provided; preserve existing for the rest).
        new_config = dict(existing.config)
        if config is not None:
            cfg, embedded_secrets = self._split_fields(
                existing.type_id, config,
            )
            new_config.update(cfg)
            # Caller might have passed secrets in the config dict by
            # accident; treat those the same as the secrets bucket.
            if embedded_secrets:
                secrets = {**(secrets or {}), **embedded_secrets}

        # Secret rotation: honor "***" sentinel (no-op for that slot)
        new_secret_refs = dict(existing.secret_refs)
        if secrets:
            for slot, value in secrets.items():
                if value == "***":
                    continue  # preserve existing
                path = log_destination_secret_path(dest_id, slot)
                if value == "" or value is None:
                    # Empty = delete the slot
                    if slot in new_secret_refs:
                        self._secret_store.delete(new_secret_refs[slot])
                        new_secret_refs.pop(slot, None)
                else:
                    self._secret_store.write(path, str(value))
                    new_secret_refs[slot] = path

        now = self._now_iso()
        with self._lock, self._conn() as c:
            try:
                c.execute(
                    "UPDATE log_destinations SET "
                    "name = ?, config_json = ?, secret_refs_json = ?, "
                    "enabled = ?, description = ?, updated_at = ? "
                    "WHERE id = ?",
                    (
                        new_name,
                        json.dumps(new_config),
                        json.dumps(new_secret_refs),
                        1 if new_enabled else 0,
                        new_description,
                        now,
                        dest_id,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError(
                    f"destination name {new_name!r} already exists"
                ) from exc

            if is_default is not None:
                if is_default:
                    c.execute(
                        "UPDATE log_destinations SET is_default = 0 "
                        "WHERE type_id = ? AND id <> ?",
                        (existing.type_id, dest_id),
                    )
                c.execute(
                    "UPDATE log_destinations SET is_default = ? "
                    "WHERE id = ?",
                    (1 if is_default else 0, dest_id),
                )

        return self.get(dest_id)

    def delete(self, dest_id: str) -> bool:
        """Remove the row and cascade-delete all secrets under its prefix."""
        with self._lock, self._conn() as c:
            cur = c.execute(
                "DELETE FROM log_destinations WHERE id = ?",
                (dest_id,),
            )
            removed = cur.rowcount > 0
        if removed:
            self._secret_store.delete_under(
                log_destination_prefix(dest_id),
            )
        return removed

    def set_default(self, dest_id: str) -> LogDestination | None:
        existing = self.get(dest_id)
        if existing is None:
            return None
        with self._lock, self._conn() as c:
            c.execute(
                "UPDATE log_destinations SET is_default = 0 "
                "WHERE type_id = ?",
                (existing.type_id,),
            )
            c.execute(
                "UPDATE log_destinations SET is_default = 1, "
                "updated_at = ? WHERE id = ?",
                (self._now_iso(), dest_id),
            )
        return self.get(dest_id)

    def record_probe(
        self,
        dest_id: str,
        *,
        ok: bool,
        error: str | None,
        latency_ms: int = 0,
    ) -> None:
        existing = self.get(dest_id)
        if existing is None:
            return
        new_failures = (
            0 if ok else existing.consecutive_failures + 1
        )
        with self._lock, self._conn() as c:
            c.execute(
                "UPDATE log_destinations SET "
                "last_probe_at = ?, last_probe_ok = ?, "
                "last_probe_error = ?, consecutive_failures = ?, "
                "updated_at = ? "
                "WHERE id = ?",
                (
                    self._now_iso(),
                    1 if ok else 0,
                    None if ok else (error or "")[:1000],
                    new_failures,
                    self._now_iso(),
                    dest_id,
                ),
            )


# ─── Singleton accessor ────────────────────────────────────────────


_store: LogDestinationStore | None = None


def get_log_destination_store() -> LogDestinationStore:
    global _store
    if _store is None:
        _store = LogDestinationStore()
    return _store


def reset_store_for_tests() -> None:
    global _store
    _store = None


# ─── First-boot migration ──────────────────────────────────────────


def migrate_webhook_endpoint_to_destination(
    store: LogDestinationStore | None = None,
) -> LogDestination | None:
    """Auto-create an XSIAM Default destination from the
    legacy WEBHOOK_ENDPOINT + WEBHOOK_KEY env vars.

    Older installs passed XSIAM credentials to xlog directly through the
    WEBHOOK_ENDPOINT and WEBHOOK_KEY env vars. The log_destinations
    table is the canonical handle. This migration runs on every MCP boot:

      1. Skip if NO xsiam_http destination exists AND env vars unset
         (nothing to migrate)
      2. Skip if any xsiam_http destination already exists (idempotent;
         operator may have created their own)
      3. Otherwise: create an "XSIAM Default" xsiam_http destination
         from the env vars, marked is_default=True. Logs an info event.

    Returns the created destination on success, None on skip/failure.
    """
    if store is None:
        store = get_log_destination_store()

    # Step 1: skip if env vars empty
    webhook_endpoint = os.environ.get("WEBHOOK_ENDPOINT", "").strip()
    webhook_key = os.environ.get("WEBHOOK_KEY", "").strip()
    if not webhook_endpoint and not webhook_key:
        return None

    # Step 2: skip if any xsiam_http destination already exists
    existing = store.list_all(type_id="xsiam_http")
    if existing:
        logger.debug(
            "log_destinations: xsiam_http destination already exists "
            "(%d row(s)); skipping WEBHOOK_ENDPOINT migration",
            len(existing),
        )
        return None

    # Step 3: create the XSIAM Default
    try:
        dest = store.create(
            name="XSIAM Default",
            type_id="xsiam_http",
            config={
                "url": webhook_endpoint,
                "source": "phantom",
            },
            secrets={"auth_key": webhook_key} if webhook_key else {},
            description=(
                "Auto-migrated from WEBHOOK_ENDPOINT / WEBHOOK_KEY env "
                "vars at first boot. The operator can rename "
                "or delete this row; the env vars stay as fallback for "
                "any path that hasn't switched to destination_id yet."
            ),
            is_default=True,
        )
        logger.info(
            "log_destinations: migrated WEBHOOK_ENDPOINT into destination %r (id=%s)",
            dest.name, dest.id,
        )
        return dest
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "log_destinations: WEBHOOK_ENDPOINT migration failed: %s", e,
        )
        return None
