"""Read-only access to the active organization for per-instance connector containers.

The MCP's SqliteOrganizationStore (`bundles/spark/mcp/src/usecase/organization_store.py`) keeps the organizations in
`<data_root>/organization.db`. Every connector container already mounts that data volume read-only (phantom-updater mounts
`phantom_mcp_data` at /app/data, which is also how `instance_store_client.py` reads `instances.db`), so a connector reads the
organization straight from the file. No copy is handed over and nothing restarts: a save in the UI or by the agent changes
the row, and the next call here sees the new `version`.

# Contract with the store (tests/test_organization_reader_contract.py runs both ends)

    organizations (id, name, source, active, version, document_json, updated_at, updated_by)

# Behaviour

  - `load(pinned_id)` returns the document of the pinned organization, or of the active one when `pinned_id` is empty.
  - The document is cached; each call re-reads only `(id, version)`, a primary-key lookup, and re-parses the JSON only
    when that pair changed. A 50-person organization is about 60 KB.
  - The database is opened `mode=ro`. The store keeps it in rollback-journal mode (not WAL), the only mode a read-only
    mount can open.
  - A missing database, a missing row or an unreadable document raises OrganizationUnavailable with a message that says
    what to check. There is no built-in fallback roster: an organization that silently differs from the one the operator
    sees in the UI would defeat the point of having one.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from pathlib import Path
from typing import Any

DEFAULT_DATA_ROOT = "/app/data"


class OrganizationUnavailable(RuntimeError):
    """The organization cannot be read: no database, no such organization, or a malformed document."""


class OrganizationReader:
    def __init__(self, db_path: str | Path | None = None) -> None:
        root = os.getenv("DATA_ROOT", DEFAULT_DATA_ROOT)
        self._db_path = Path(db_path) if db_path else Path(root) / "organization.db"
        self._lock = threading.Lock()
        self._cache: dict[str, Any] | None = None
        self._cache_key: tuple[str, int] | None = None

    def _connect(self) -> sqlite3.Connection:
        if not self._db_path.is_file():
            raise OrganizationUnavailable(
                f"organization.db not found at {self._db_path}. The connector container must mount the phantom_mcp_data "
                "volume (phantom-updater does this) and the agent must have started once.")
        try:
            conn = sqlite3.connect(f"file:{self._db_path}?mode=ro", uri=True)
        except sqlite3.OperationalError:
            conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def load(self, pinned_id: str | None = None) -> dict[str, Any]:
        """The organization document: the pinned one, or the active one."""
        conn = self._connect()
        try:
            if pinned_id:
                row = conn.execute("SELECT id, version FROM organizations WHERE id = ?", (pinned_id,)).fetchone()
                if row is None:
                    raise OrganizationUnavailable(
                        f"no organization with id {pinned_id!r}: fix the Organization setting on this connector "
                        "instance or leave it empty to follow the active organization")
            else:
                row = conn.execute("SELECT id, version FROM organizations WHERE active = 1").fetchone()
                if row is None:
                    raise OrganizationUnavailable("no organization is active: open the Organization page and activate one")
            key = (row["id"], int(row["version"]))
            with self._lock:
                if self._cache is not None and self._cache_key == key:
                    return self._cache
            body = conn.execute("SELECT document_json FROM organizations WHERE id = ?", (key[0],)).fetchone()
            try:
                doc = json.loads(body["document_json"])
            except (TypeError, json.JSONDecodeError) as exc:
                raise OrganizationUnavailable(f"organization {key[0]!r} is not readable JSON: {exc}") from exc
            with self._lock:
                self._cache, self._cache_key = doc, key
            return doc
        except sqlite3.Error as exc:
            raise OrganizationUnavailable(f"organization.db could not be read: {exc}") from exc
        finally:
            conn.close()


_default: OrganizationReader | None = None


def load_organization(pinned_id: str | None = None) -> dict[str, Any]:
    """The organization for this connector, from the shared data volume (see the module docstring)."""
    global _default
    if _default is None:
        _default = OrganizationReader()
    return _default.load(pinned_id)
