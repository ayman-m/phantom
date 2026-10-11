"""Version store for data-source edits.

One SQLite db holding every version of every edited data source as a full
YAML snapshot. The YAML loader reads the *current* version as an overlay so
edits take effect without mutating the read-only bundle (or user) file on
disk; the original is preserved as version 1 (the "bundle-baseline").

Mirrors `data_sources_store.py` conventions: sqlite3 with a Row factory and a
module-level singleton wired at boot. Catalog-side state (no secrets).
"""
from __future__ import annotations

import datetime
import os
import sqlite3
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS data_source_versions (
  data_source_id TEXT NOT NULL,
  version        INTEGER NOT NULL,
  yaml_snapshot  TEXT NOT NULL,
  created_at     TEXT NOT NULL,
  author         TEXT NOT NULL,
  note           TEXT,
  is_current     INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (data_source_id, version)
);
CREATE INDEX IF NOT EXISTS idx_dsv_current
  ON data_source_versions(data_source_id, is_current);
"""


def _resolve_db_path() -> Path:
    """Container: /app/data/. Dev/test: PHANTOM_DATA_DIR override."""
    override = os.environ.get("PHANTOM_DATA_DIR")
    base = Path(override) if override else Path("/app/data")
    return base / "data_source_versions.db"


class DataSourceVersionsStore:
    def __init__(self, db_path: Path | None = None):
        self.db_path = Path(db_path) if db_path else _resolve_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.executescript(_SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.db_path)
        c.row_factory = sqlite3.Row
        return c

    def has_versions(self, ds_id: str) -> bool:
        with self._conn() as c:
            r = c.execute(
                "SELECT 1 FROM data_source_versions WHERE data_source_id=? LIMIT 1",
                (ds_id,),
            ).fetchone()
        return r is not None

    def _next_version(self, c: sqlite3.Connection, ds_id: str) -> int:
        r = c.execute(
            "SELECT MAX(version) AS m FROM data_source_versions WHERE data_source_id=?",
            (ds_id,),
        ).fetchone()
        return (r["m"] or 0) + 1

    def snapshot(
        self, ds_id: str, yaml_text: str, *, author: str, note: str | None = None
    ) -> dict[str, Any]:
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with self._conn() as c:
            v = self._next_version(c, ds_id)
            c.execute(
                "UPDATE data_source_versions SET is_current=0 WHERE data_source_id=?",
                (ds_id,),
            )
            c.execute(
                "INSERT INTO data_source_versions"
                "(data_source_id,version,yaml_snapshot,created_at,author,note,is_current)"
                " VALUES (?,?,?,?,?,?,1)",
                (ds_id, v, yaml_text, now, author, note),
            )
        return self.get_version(ds_id, v)  # type: ignore[return-value]

    def get_current(self, ds_id: str) -> dict[str, Any] | None:
        with self._conn() as c:
            r = c.execute(
                "SELECT * FROM data_source_versions "
                "WHERE data_source_id=? AND is_current=1",
                (ds_id,),
            ).fetchone()
        return dict(r) if r else None

    def get_version(self, ds_id: str, version: int) -> dict[str, Any] | None:
        with self._conn() as c:
            r = c.execute(
                "SELECT * FROM data_source_versions "
                "WHERE data_source_id=? AND version=?",
                (ds_id, version),
            ).fetchone()
        return dict(r) if r else None

    def list_versions(self, ds_id: str) -> list[dict[str, Any]]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM data_source_versions "
                "WHERE data_source_id=? ORDER BY version",
                (ds_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def all_current(self) -> dict[str, str]:
        """{data_source_id: yaml_snapshot} for every source's current version.

        One query — the loader calls this once per `list_all()` to apply the
        overlay in bulk (only edited sources appear, so it's small).
        """
        with self._conn() as c:
            rows = c.execute(
                "SELECT data_source_id, yaml_snapshot FROM data_source_versions "
                "WHERE is_current=1"
            ).fetchall()
        return {r["data_source_id"]: r["yaml_snapshot"] for r in rows}

    def rollback(self, ds_id: str, version: int, *, author: str = "operator") -> dict[str, Any]:
        """Non-destructive: copy `version`'s snapshot forward as a new current.
        History (incl. versions after `version`) is preserved. `author`
        attributes who triggered the rollback ("operator" via REST,
        "agent" via the data_sources_rollback tool)."""
        target = self.get_version(ds_id, version)
        if target is None:
            raise ValueError(f"version {version} not found for {ds_id}")
        return self.snapshot(
            ds_id, target["yaml_snapshot"], author=author,
            note=f"rolled back to v{version}",
        )


# Module singleton — wired at boot (see main.py), like data_sources_store.
_STORE: DataSourceVersionsStore | None = None


def get_data_source_versions_store() -> DataSourceVersionsStore | None:
    return _STORE


def set_data_source_versions_store(s: DataSourceVersionsStore | None) -> None:
    global _STORE
    _STORE = s
