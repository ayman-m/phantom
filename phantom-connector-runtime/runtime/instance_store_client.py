"""Read-only InstanceStore client for per-instance connector containers.

Looks up a single instance row from `<data_root>/instances.db` by
INSTANCE_ID at boot. Returns the instance's config dict + secret_refs
dict (as stored by phantom-agent) so the runtime can:

  1. Resolve secret_refs through SecretStoreReader,
  2. Build a flattened {config + resolved_secrets} blob,
  3. Stash it on the contextvar shim that connector code reads via
     `from config.config import get_config`.

# Why a thin reader vs vendoring the full InstanceStore class

Same reasoning as SecretStoreReader: the agent's full InstanceStore
is ~620 lines covering CRUD, audit hooks, listing, secret-store
coupling, and migration logic. The runtime container only needs the
single-row READ path. Vendoring would drag in the whole transitive
dep tree for a 20-line SELECT.

# On-disk schema (as defined by InstanceStore._init_schema):
  CREATE TABLE instances (
      id           TEXT PRIMARY KEY,
      connector_id TEXT NOT NULL,
      name         TEXT NOT NULL,
      config       TEXT NOT NULL,    -- JSON
      secret_refs  TEXT NOT NULL,    -- JSON
      created_at   TEXT NOT NULL,
      enabled      INTEGER NOT NULL DEFAULT 1
  );

The reader is locked to this schema. If the agent's InstanceStore
adds columns, this client either picks them up via SELECT * (if
they have defaults) or surfaces an explicit error if they don't.
The runtime image and phantom-agent always ship from the same
release tag, so schema drift is bounded by release boundaries.

# Why read-only

The connector container has no business writing to the instance
store — that's an agent-side operator concern (creating, editing,
deleting instances goes through the agent's UI + REST). Read-only
mount of `phantom_mcp_data` (or wherever instances.db lives) is a
defense-in-depth: even if a connector is compromised, it can't
mutate the agent's source of truth for what's deployed.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class InstanceRow:
    """One materialized instance row, matching what
    bundles/spark/mcp/src/usecase/instance_store.py:Instance writes to disk
    (minus the runtime methods like merged_config())."""

    id: str
    connector_id: str
    name: str
    config: dict[str, Any] = field(default_factory=dict)
    secret_refs: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    enabled: bool = True


class InstanceStoreClientError(RuntimeError):
    """Raised when the instances.db file is missing, the row doesn't
    exist, or its config/secret_refs JSON is malformed."""


class InstanceStoreReader:
    """Read-only client for instance row lookup.

    Usage:
        reader = InstanceStoreReader("/app/data/instances.db")
        instance = reader.get("a3f2c8b1-...")  # raises if missing
    """

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path)
        if not self._db_path.is_file():
            raise InstanceStoreClientError(
                f"instances.db not found at {self._db_path} — verify the "
                f"phantom_mcp_data volume is mounted into this container "
                f"and points at the agent's data directory."
            )

    def get(self, instance_id: str) -> InstanceRow:
        """Return the instance with the given id, or raise.

        Use `?ro=1` URI mode so the connection is read-only — defense
        in depth against any code path that might accidentally try
        to write.
        """
        if not instance_id:
            raise InstanceStoreClientError("instance_id is required")

        # `mode=ro` requires the URI form. Fall back to plain path on
        # systems where URI mode isn't available (very old SQLite).
        try:
            uri = f"file:{self._db_path}?mode=ro"
            conn = sqlite3.connect(uri, uri=True)
        except sqlite3.OperationalError:
            conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row

        try:
            # Column names mirror the agent-side InstanceStore schema in
            # bundles/spark/mcp/src/usecase/instance_store.py:
            #   config_json   TEXT  — JSON of the merged config
            #   secrets_json  TEXT  — JSON of secret_refs (slot → path/value)
            # The agent stores them with the `_json` suffix to make the
            # serialization explicit; the runtime client decodes both
            # into dicts before exposing them on InstanceRow.
            cur = conn.execute(
                "SELECT id, connector_id, name, config_json, secrets_json, "
                "created_at, enabled FROM instances WHERE id = ?",
                (instance_id,),
            )
            row = cur.fetchone()
        finally:
            conn.close()

        if row is None:
            raise InstanceStoreClientError(
                f"no instance row with id={instance_id!r} found in "
                f"{self._db_path}. Either the agent hasn't created the "
                f"instance yet, or INSTANCE_ID env var is wrong."
            )

        try:
            config = json.loads(row["config_json"]) if row["config_json"] else {}
        except json.JSONDecodeError as exc:
            raise InstanceStoreClientError(
                f"instance {instance_id} has malformed config JSON: {exc}"
            ) from exc

        try:
            secret_refs = (
                json.loads(row["secrets_json"]) if row["secrets_json"] else {}
            )
        except json.JSONDecodeError as exc:
            raise InstanceStoreClientError(
                f"instance {instance_id} has malformed secret_refs JSON: "
                f"{exc}"
            ) from exc

        return InstanceRow(
            id=row["id"],
            connector_id=row["connector_id"],
            name=row["name"],
            config=config,
            secret_refs=secret_refs,
            created_at=row["created_at"] or "",
            enabled=bool(row["enabled"]),
        )

    def resolve_merged_config(
        self,
        instance: InstanceRow,
        secret_reader: Any,
    ) -> dict[str, Any]:
        """Return `{**instance.config, **resolved_secrets}` — the same
        shape phantom-agent's `Instance.merged_config(secret_store)`
        returns.

        secret_refs values that look like SecretStore paths (start with
        `/`) get resolved through the secret_reader; literal values
        pass through. This matches the agent's behavior at
        instance_store.py:merged_config so connector code that reads
        get_config() sees identical content regardless of which side
        loaded the instance.
        """
        resolved: dict[str, Any] = {}
        for slot, ref_or_value in instance.secret_refs.items():
            if isinstance(ref_or_value, str) and ref_or_value.startswith("/"):
                try:
                    resolved[slot] = secret_reader.read(ref_or_value)
                except Exception as exc:  # noqa: BLE001
                    # Same defensive behavior as agent: missing/invalid
                    # secret yields empty string, surfaced via a warning
                    # (the connector can decide whether that's fatal at
                    # tool-call time vs at boot).
                    import logging
                    logging.getLogger(__name__).warning(
                        "instance %s/%s: could not resolve secret slot %r "
                        "at %r — using empty (%s)",
                        instance.connector_id, instance.name,
                        slot, ref_or_value, exc,
                    )
                    resolved[slot] = ""
            else:
                resolved[slot] = ref_or_value
        return {**instance.config, **resolved}
