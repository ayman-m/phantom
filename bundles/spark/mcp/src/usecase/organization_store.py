"""SqliteOrganizationStore: the organizations Phantom can generate telemetry for, and which one is active.

One organization is active at a time. Every generator reads it: the agent through the `organization_*` tools, the
connector containers straight from `organization.db` (they already mount the data volume read-only for `instances.db`),
the UI through `/api/v1/organizations`. This store is the one canonical home; nothing keeps a copy.

Bundled organizations (`bundles/spark/organization/*.yaml`, the shipped Phantom Lab) are loaded on every boot and are
READ-ONLY: an edit forks the organization into an operator copy (`<id>-custom`), so "reset" is always just activating the
bundled one again. Operator organizations are fully editable and keep their last HISTORY_KEEP versions.

# Schema (the contract `phantom-connector-runtime/runtime/organization_reader.py` reads; tests pin it)

    organizations (
      id            TEXT PRIMARY KEY,
      name          TEXT NOT NULL,
      source        TEXT NOT NULL,            -- 'bundled' | 'operator'
      active        INTEGER NOT NULL,         -- 0/1; a unique partial index allows one 1
      version       INTEGER NOT NULL,         -- bumps on every change to the document
      document_json TEXT NOT NULL,
      updated_at    TEXT NOT NULL,
      updated_by    TEXT
    );
    organization_history (
      seq INTEGER PRIMARY KEY AUTOINCREMENT, org_id TEXT, version INTEGER, document_json TEXT, updated_at TEXT,
      updated_by TEXT, note TEXT
    );

# Journal mode

The database stays in SQLite's default rollback-journal mode, NOT WAL. Connector containers open it with `mode=ro` on a
read-only bind mount, and a WAL database needs a writable `-shm` file next to it, so a WAL reader fails there.
tests/test_organization_store.py pins this.

# Not a secret

An organization holds no credentials, ever. It is operator workflow state the agent may read and edit.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from usecase import organization_model as om

logger = logging.getLogger("Phantom MCP")

DEFAULT_DATA_ROOT = Path("/app/data")
HISTORY_KEEP = 20
DEFAULT_ORGANIZATION_ID = "phantom-lab"


def _slugify(name: str) -> str:
    """`name` as an organization id: lowercase, non-alphanumerics collapsed to one `-`, trimmed."""
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", name.lower())).strip("-")


@dataclass(frozen=True)
class OrganizationRecord:
    id: str
    name: str
    source: str
    active: bool
    version: int
    updated_at: str
    updated_by: str | None
    document: dict[str, Any]
    note: str | None = None

    def meta(self) -> dict[str, Any]:
        s = om.summary(self.document)
        return {"id": self.id, "name": self.name, "source": self.source, "active": self.active,
                "version": self.version, "updated_at": self.updated_at, "updated_by": self.updated_by,
                "people": s["people"], "hosts": sum(s["hosts"].values()), "domain": s["domain"]["dns"],
                "description": s["description"]}

    def to_dict(self) -> dict[str, Any]:
        return {**self.meta(), "document": self.document}


class OrganizationStoreError(RuntimeError):
    """A store-level refusal (not found, bundled is read-only, cannot delete the active one, id taken)."""

    def __init__(self, message: str, code: str = "invalid") -> None:
        super().__init__(message)
        self.code = code


class SqliteOrganizationStore:
    """Organizations at <data_root>/organization.db."""

    def __init__(self, data_root: Path | None = None, bundled_dir: Path | None = None) -> None:
        root = data_root or Path(os.getenv("DATA_ROOT", str(DEFAULT_DATA_ROOT)))
        self._data_root = Path(root).resolve()
        self._data_root.mkdir(parents=True, exist_ok=True)
        self._db_path = self._data_root / "organization.db"
        self._bundled_dir = Path(bundled_dir) if bundled_dir else om.bundle_dir()
        self._lock = threading.RLock()
        self._listeners: list[Callable[[OrganizationRecord | None], None]] = []
        self._init_schema()
        self.ensure_bundled()
        logger.info("SqliteOrganizationStore at %s", self._db_path)

    # ── plumbing ────────────────────────────────────────────────────────────────────────────────────────────────────

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
                CREATE TABLE IF NOT EXISTS organizations (
                    id            TEXT PRIMARY KEY,
                    name          TEXT NOT NULL,
                    source        TEXT NOT NULL,
                    active        INTEGER NOT NULL DEFAULT 0,
                    version       INTEGER NOT NULL DEFAULT 1,
                    document_json TEXT NOT NULL,
                    updated_at    TEXT NOT NULL,
                    updated_by    TEXT,
                    note          TEXT
                )
                """
            )
            # Migration for existing organizations.db's that pre-date the `note` column
            # (same PRAGMA introspection + ADD COLUMN pattern as audit_log.py's `trigger`
            # column). `note` holds the note that describes how THIS live version came to
            # be, so that when it is later snapshotted into history (see `_snapshot`) the
            # history row is labelled with its own origin, not with whatever edit is about
            # to replace it (F4, measured 2026-10-18).
            cols = {r["name"] for r in c.execute("PRAGMA table_info(organizations)").fetchall()}
            if "note" not in cols:
                c.execute("ALTER TABLE organizations ADD COLUMN note TEXT")
            c.execute("CREATE UNIQUE INDEX IF NOT EXISTS organizations_one_active ON organizations(active) WHERE active = 1")
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS organization_history (
                    seq           INTEGER PRIMARY KEY AUTOINCREMENT,
                    org_id        TEXT NOT NULL,
                    version       INTEGER NOT NULL,
                    document_json TEXT NOT NULL,
                    updated_at    TEXT NOT NULL,
                    updated_by    TEXT,
                    note          TEXT
                )
                """
            )

    @staticmethod
    def _now() -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    @staticmethod
    def _row(r: sqlite3.Row) -> OrganizationRecord:
        return OrganizationRecord(
            id=r["id"], name=r["name"], source=r["source"], active=bool(r["active"]), version=int(r["version"]),
            updated_at=r["updated_at"], updated_by=r["updated_by"], document=json.loads(r["document_json"]),
            note=r["note"] if "note" in r.keys() else None,
        )

    def add_listener(self, fn: Callable[[OrganizationRecord | None], None]) -> None:
        """Call `fn(active record or None)` after any change that could alter what the active organization says."""
        self._listeners.append(fn)

    def _notify(self) -> None:
        active = self.get_active()
        for fn in list(self._listeners):
            try:
                fn(active)
            except Exception as exc:  # noqa: BLE001 - a listener must never fail a save
                logger.warning("organization listener failed: %s", exc)

    @staticmethod
    def _audit(op: str, org_id: str, actor: str | None, **meta: Any) -> None:
        try:
            from usecase.audit_log import ACTION_ORGANIZATION_CHANGED, record_event
            record_event(ACTION_ORGANIZATION_CHANGED, target=f"organization:{org_id}", status="success", actor=actor,
                         metadata={"op": op, **meta})
        except Exception as exc:  # noqa: BLE001
            logger.warning("organization audit failed: %s", exc)

    # ── bundled organizations ───────────────────────────────────────────────────────────────────────────────────────

    def ensure_bundled(self) -> None:
        """Load every shipped organization (overwriting the stored copy when the file changed) and make Phantom Lab
        active when nothing is. A shipped file that does not validate is skipped with an error log."""
        if not self._bundled_dir.is_dir():
            logger.warning("no bundled organizations at %s", self._bundled_dir)
            return
        for path in sorted(self._bundled_dir.glob("*.yaml")):
            try:
                doc = om.parse_document(path.read_text(encoding="utf-8"), "yaml")
                om.require_valid(doc)
            except om.OrganizationError as exc:
                logger.error("bundled organization %s is invalid: %s", path.name, exc)
                continue
            with self._lock, self._conn() as c:
                body = json.dumps(doc, ensure_ascii=False)
                row = c.execute("SELECT * FROM organizations WHERE id = ?", (doc["id"],)).fetchone()
                if row is None:
                    c.execute(
                        "INSERT INTO organizations (id, name, source, active, version, document_json, updated_at, "
                        "updated_by) VALUES (?, ?, 'bundled', 0, 1, ?, ?, 'bundle')",
                        (doc["id"], doc["name"], body, self._now()),
                    )
                elif row["source"] == "bundled" and row["document_json"] != body:
                    c.execute(
                        "UPDATE organizations SET name = ?, document_json = ?, version = version + 1, updated_at = ?, "
                        "updated_by = 'bundle' WHERE id = ?",
                        (doc["name"], body, self._now(), doc["id"]),
                    )
                elif row["source"] != "bundled":
                    logger.warning("bundled organization %s is shadowed by an operator organization of the same id",
                                   doc["id"])
        with self._lock, self._conn() as c:
            if c.execute("SELECT 1 FROM organizations WHERE active = 1").fetchone() is None:
                target = c.execute("SELECT id FROM organizations WHERE id = ?", (DEFAULT_ORGANIZATION_ID,)).fetchone()
                target = target or c.execute("SELECT id FROM organizations ORDER BY id LIMIT 1").fetchone()
                if target is not None:
                    c.execute("UPDATE organizations SET active = 1 WHERE id = ?", (target["id"],))
        self._notify()

    # ── reads ───────────────────────────────────────────────────────────────────────────────────────────────────────

    def list(self) -> list[OrganizationRecord]:
        with self._lock, self._conn() as c:
            rows = c.execute("SELECT * FROM organizations ORDER BY active DESC, source ASC, name ASC").fetchall()
        return [self._row(r) for r in rows]

    def get(self, org_id: str) -> OrganizationRecord | None:
        with self._lock, self._conn() as c:
            r = c.execute("SELECT * FROM organizations WHERE id = ?", (org_id,)).fetchone()
        return self._row(r) if r else None

    def get_active(self) -> OrganizationRecord | None:
        with self._lock, self._conn() as c:
            r = c.execute("SELECT * FROM organizations WHERE active = 1").fetchone()
        return self._row(r) if r else None

    def history(self, org_id: str, limit: int = 10) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), HISTORY_KEEP))
        with self._lock, self._conn() as c:
            rows = c.execute(
                "SELECT seq, version, updated_at, updated_by, note FROM organization_history WHERE org_id = ? "
                "ORDER BY seq DESC LIMIT ?", (org_id, limit)).fetchall()
        return [dict(r) for r in rows]

    # ── writes ──────────────────────────────────────────────────────────────────────────────────────────────────────

    def _require(self, org_id: str) -> OrganizationRecord:
        rec = self.get(org_id)
        if rec is None:
            raise OrganizationStoreError(f"no organization with id {org_id!r}", "not_found")
        return rec

    def _snapshot(self, c: sqlite3.Connection, rec: OrganizationRecord) -> None:
        """Archive `rec` (the version about to be replaced) into history, labelled with `rec.note` -- the note that
        describes how `rec` itself came to be, NOT the note of the edit that is replacing it right now (that new note
        belongs to the NEW version being created, and is written onto the live row by the caller; it will become
        this same history row's label only once a LATER edit snapshots it in turn). Measured 2026-10-18 (F4): the
        previous code passed the incoming edit's own note straight into this snapshot, so every history row read as
        "what replaced me" instead of "how I was made" -- a restore's "restored history entry 1" note, for example,
        landed on the OLD version being overwritten rather than on the new version the restore itself produced."""
        c.execute(
            "INSERT INTO organization_history (org_id, version, document_json, updated_at, updated_by, note) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (rec.id, rec.version, json.dumps(rec.document, ensure_ascii=False), rec.updated_at, rec.updated_by,
             rec.note),
        )
        c.execute(
            "DELETE FROM organization_history WHERE org_id = ? AND seq NOT IN "
            "(SELECT seq FROM organization_history WHERE org_id = ? ORDER BY seq DESC LIMIT ?)",
            (rec.id, rec.id, HISTORY_KEEP),
        )

    def create(self, doc: dict[str, Any], *, actor: str | None = None, activate: bool = False,
               note: str | None = None) -> OrganizationRecord:
        om.require_valid(doc)
        with self._lock, self._conn() as c:
            if c.execute("SELECT 1 FROM organizations WHERE id = ?", (doc["id"],)).fetchone():
                raise OrganizationStoreError(f"an organization with id {doc['id']!r} already exists", "exists")
            c.execute(
                "INSERT INTO organizations (id, name, source, active, version, document_json, updated_at, "
                "updated_by, note) VALUES (?, ?, 'operator', 0, 1, ?, ?, ?, ?)",
                (doc["id"], doc["name"], json.dumps(doc, ensure_ascii=False), self._now(), actor, note),
            )
        self._audit("create", doc["id"], actor)
        if activate:
            return self.activate(doc["id"], actor=actor)
        self._notify()
        return self._require(doc["id"])

    def put(self, org_id: str, doc: dict[str, Any], *, actor: str | None = None,
            note: str | None = None) -> OrganizationRecord:
        rec = self._require(org_id)
        if rec.source == "bundled":
            raise OrganizationStoreError(
                f"{org_id!r} is a bundled organization and cannot be edited; fork it first", "bundled_read_only")
        if doc.get("id") != org_id:
            raise OrganizationStoreError(f"the document id {doc.get('id')!r} does not match {org_id!r}", "id_mismatch")
        om.require_valid(doc)
        with self._lock, self._conn() as c:
            self._snapshot(c, rec)
            c.execute(
                "UPDATE organizations SET name = ?, document_json = ?, version = version + 1, updated_at = ?, "
                "updated_by = ?, note = ? WHERE id = ?",
                (doc["name"], json.dumps(doc, ensure_ascii=False), self._now(), actor, note, org_id),
            )
        self._audit("put", org_id, actor, note=note)
        self._notify()
        return self._require(org_id)

    def fork(self, org_id: str, *, new_id: str | None = None, new_name: str | None = None,
             actor: str | None = None) -> OrganizationRecord:
        """A copy of `org_id` as an editable operator organization."""
        src = self._require(org_id)
        # The Duplicate dialog collects a NAME, not an id, so `new_id` is usually None here.
        # Measured 2026-10-18 (F3): falling back straight to `f"{org_id}-custom"` ignored the
        # name the operator typed and, forked again, chained into `<id>-custom-custom`. Slugify
        # the name instead, so a duplicate named "Test Copy B" becomes `test-copy-b`, not a suffix
        # pile on whatever id its source happened to have.
        if new_id:
            base = new_id
        elif new_name:
            base = _slugify(new_name) or f"{org_id}-custom"
        else:
            base = f"{org_id}-custom"
        candidate, n = base, 1
        while self.get(candidate) is not None:
            n += 1
            candidate = f"{base}-{n}"
        doc = json.loads(json.dumps(src.document))
        doc["id"] = candidate
        doc["name"] = new_name or (f"{src.name} (custom)" if candidate == base else f"{src.name} (custom {n})")
        return self.create(doc, actor=actor, note=f"forked from {org_id}")

    def apply_changes(self, org_id: str, changes: dict[str, Any], *, actor: str | None = None,
                      note: str | None = None) -> tuple[OrganizationRecord, list[str], str | None]:
        """Apply structured changes (see organization_model.apply_changes). A bundled organization is forked first: the
        fork becomes active when the bundled one was. Returns (record, notes, forked_from or None)."""
        rec = self._require(org_id)
        forked_from = None
        new_doc, notes = om.apply_changes(rec.document, changes)
        om.require_valid(new_doc)  # reject before forking, so a bad edit leaves nothing behind
        if rec.source == "bundled":
            was_active = rec.active
            fork = self.fork(org_id, actor=actor)
            forked_from = org_id
            new_doc["id"], new_doc["name"] = fork.document["id"], fork.document["name"]
            rec = fork
            if was_active:
                self.activate(fork.id, actor=actor)
            notes.insert(0, f"{org_id} is bundled and read-only, so the change was made to a copy: {fork.id}")
        updated = self.put(rec.id, new_doc, actor=actor, note=note or "; ".join(notes[:3]))
        return updated, notes, forked_from

    def activate(self, org_id: str, *, actor: str | None = None) -> OrganizationRecord:
        self._require(org_id)
        with self._lock, self._conn() as c:
            c.execute("BEGIN IMMEDIATE")
            try:
                c.execute("UPDATE organizations SET active = 0 WHERE active = 1")
                c.execute("UPDATE organizations SET active = 1 WHERE id = ?", (org_id,))
                c.execute("COMMIT")
            except Exception:
                c.execute("ROLLBACK")
                raise
        self._audit("activate", org_id, actor)
        self._notify()
        return self._require(org_id)

    def delete(self, org_id: str, *, actor: str | None = None) -> None:
        rec = self._require(org_id)
        if rec.source == "bundled":
            raise OrganizationStoreError("a bundled organization cannot be deleted", "bundled_read_only")
        if rec.active:
            raise OrganizationStoreError("the active organization cannot be deleted; activate another first", "active")
        with self._lock, self._conn() as c:
            c.execute("DELETE FROM organizations WHERE id = ?", (org_id,))
            c.execute("DELETE FROM organization_history WHERE org_id = ?", (org_id,))
        self._audit("delete", org_id, actor)

    def restore(self, org_id: str, seq: int, *, actor: str | None = None) -> OrganizationRecord:
        """Put back the document saved in history row `seq` (as a new version, so the restore itself is undoable)."""
        self._require(org_id)
        with self._lock, self._conn() as c:
            r = c.execute("SELECT document_json FROM organization_history WHERE org_id = ? AND seq = ?",
                          (org_id, int(seq))).fetchone()
        if r is None:
            raise OrganizationStoreError(f"no history entry {seq} for {org_id!r}", "not_found")
        return self.put(org_id, json.loads(r["document_json"]), actor=actor, note=f"restored history entry {seq}")

    def import_text(self, text: str, fmt: str | None = None, *, actor: str | None = None, activate: bool = False,
                    replace: bool = False) -> OrganizationRecord:
        """Add an organization from YAML or JSON text. An id that already names an operator organization is replaced
        only when `replace` is true; a bundled id is never replaced (import it under another id)."""
        doc = om.parse_document(text, fmt)
        om.require_valid(doc)
        existing = self.get(doc["id"])
        if existing is not None:
            if existing.source == "bundled":
                raise OrganizationStoreError(
                    f"{doc['id']!r} is a bundled organization; change the id in the file and import again", "exists")
            if not replace:
                raise OrganizationStoreError(f"an organization with id {doc['id']!r} already exists", "exists")
            rec = self.put(doc["id"], doc, actor=actor, note="imported")
            return self.activate(rec.id, actor=actor) if activate else rec
        return self.create(doc, actor=actor, activate=activate)

    def export_text(self, org_id: str, fmt: str = "yaml") -> str:
        rec = self._require(org_id)
        return om.to_json(rec.document) if fmt == "json" else om.to_yaml(rec.document)


_store: SqliteOrganizationStore | None = None


def set_organization_store(s: SqliteOrganizationStore | None) -> None:
    global _store
    _store = s


def organization_store() -> SqliteOrganizationStore | None:
    return _store


_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")


def is_valid_id(value: str) -> bool:
    return bool(_SLUG.match(value or ""))
