"""Marketplace install state — sqlite-backed canonical home.

The install state lives in this SQLite store — a single canonical home
inside the MCP's storage boundary, the same pattern used for
credentials + sessions — so the agent can see what is installed and the
install state gates instances.
Older installs kept the state in
`/app/data/marketplace_installs.json`, written by the Next.js layer;
that file is imported once and deleted (see below). The store sits
behind a proper API
(`POST /api/v1/marketplace/<id>/install`, `uninstall`), and ALL
upstream callers (Next.js, the agent's chat tool surface) read/write
through that API.

# Schema

    marketplace_installs(
      connector_id  TEXT PRIMARY KEY,
      installed_at  TEXT NOT NULL,        -- ISO 8601 UTC
      origin        TEXT NOT NULL,        -- 'bundle' | 'user'
      version       TEXT NOT NULL DEFAULT 'bundled'
    );

`origin` is the system/user-added distinction. It's set at install time:
  - 'bundle' for the 6 connectors shipped in the image
    (`bundles/spark/connectors/*`)
  - 'user' for connectors uploaded via the marketplace upload path
    (`POST /api/v1/marketplace/upload` writes the YAML to
    `/app/data/user_connectors/<id>/` and inserts a row here with
    origin='user')

`origin` gates deletion: `DELETE /api/v1/marketplace/<id>` returns 403
if origin='bundle' (cannot remove bundle connectors from the catalog
at runtime — the image holds the source). User connectors can be
deleted via the same endpoint.

# What this store does NOT hold

  - The connector catalogue itself (manifest + tool list + config
    schema). That's derived from `connector.yaml` files on disk —
    bundle ones in the image, user ones in
    `/app/data/user_connectors/`. Read at boot + on each
    `GET /api/v1/marketplace`.
  - Instance records (`instances.db` is the canonical home, see
    `instance_store.py`).
  - Per-connector state machine (`connector_state.db`, see
    `connector_state_store.py`).

This store is JUST the install-state flag + origin per connector_id.
Minimal by design.

# One-shot migration from marketplace_installs.json

On first boot the store checks for the legacy JSON file at
`/app/data/marketplace_installs.json`. If present, each connector_id
inside gets a row inserted with `origin='bundle'` (the legacy file
only ever held bundle connectors — there was no upload path
then). After successful import the JSON file is deleted, leaving
the DB as the sole source of truth. This is idempotent: re-running
won't re-insert rows (PRIMARY KEY constraint).

# Concurrency

All operations take the module-level `_lock` while inside SQLite.
Multiple async tasks reading/writing the store from the same MCP
process serialize on this lock. The DB itself is opened with
`check_same_thread=False` because the FastMCP handler pool runs
multiple workers; each call opens its own short-lived connection.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("Phantom MCP")

DEFAULT_DATA_ROOT = Path("/app/data")
LEGACY_JSON_FILE = "marketplace_installs.json"

ORIGIN_BUNDLE = "bundle"
ORIGIN_USER = "user"
VALID_ORIGINS = {ORIGIN_BUNDLE, ORIGIN_USER}


@dataclass(frozen=True)
class MarketplaceInstall:
    """One row from marketplace_installs. Read-only DTO."""

    connector_id: str
    installed_at: str  # ISO 8601 UTC
    origin: str  # 'bundle' | 'user'
    version: str = "bundled"


class MarketplaceStore:
    """SQLite-backed install state with one-shot JSON migration.

    Initialize once at MCP boot; long-lived. Methods are safe to call
    from any handler thread.
    """

    def __init__(self, data_root: Path | None = None) -> None:
        self._data_root = Path(data_root) if data_root else DEFAULT_DATA_ROOT
        self._data_root.mkdir(parents=True, exist_ok=True)
        self._db_path = self._data_root / "marketplace.db"
        self._lock = threading.RLock()
        self._init_schema()
        # Run the one-shot migration if the legacy JSON exists. Logged
        # explicitly so operators can confirm in /observability/logs.
        self._migrate_from_legacy_json()

    # ── connection + schema ───────────────────────────────────────

    def _connect(self) -> sqlite3.Connection:
        # check_same_thread=False because FastMCP's handler pool is
        # multi-threaded; we serialize with self._lock at the call
        # site instead. Each call opens a short-lived connection so we
        # don't pin a single thread.
        conn = sqlite3.connect(
            self._db_path, check_same_thread=False, isolation_level=None
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_schema(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS marketplace_installs (
                    connector_id TEXT PRIMARY KEY,
                    installed_at TEXT NOT NULL,
                    origin       TEXT NOT NULL,
                    version      TEXT NOT NULL DEFAULT 'bundled'
                )
                """
            )

    # ── one-shot migration from the legacy JSON file ───────────────

    def _migrate_from_legacy_json(self) -> None:
        """Import the legacy marketplace_installs.json into the DB.

        Runs once at boot — idempotent because PRIMARY KEY constraint
        rejects duplicate inserts. After successful import the JSON
        file is unlinked so it can't drift.

        The legacy file ONLY ever held bundle connector ids (there
        was no upload path), so every imported row gets origin='bundle'.
        """
        json_path = self._data_root / LEGACY_JSON_FILE
        if not json_path.is_file():
            return
        try:
            raw = json_path.read_text()
            payload = json.loads(raw) if raw.strip() else {}
        except (OSError, json.JSONDecodeError) as err:
            logger.warning(
                "marketplace: legacy JSON unreadable at %s (%s); leaving "
                "in place for human inspection",
                json_path,
                err,
            )
            return

        connector_ids = payload.get("installed") if isinstance(payload, dict) else None
        if not isinstance(connector_ids, list):
            logger.info(
                "marketplace: legacy JSON at %s has no installed[] list — "
                "nothing to migrate; deleting empty file",
                json_path,
            )
            try:
                json_path.unlink()
            except OSError:
                pass
            return

        imported = 0
        skipped = 0
        ts = _iso_now()
        with self._lock, self._connect() as conn:
            for cid in connector_ids:
                if not isinstance(cid, str) or not cid:
                    continue
                try:
                    conn.execute(
                        "INSERT INTO marketplace_installs "
                        "(connector_id, installed_at, origin, version) "
                        "VALUES (?, ?, ?, ?)",
                        (cid, ts, ORIGIN_BUNDLE, "bundled"),
                    )
                    imported += 1
                except sqlite3.IntegrityError:
                    skipped += 1
        try:
            json_path.unlink()
            logger.info(
                "marketplace: migrated %d connector(s) from %s into the "
                "DB (%d skipped as already present); legacy JSON deleted",
                imported,
                json_path.name,
                skipped,
            )
        except OSError as err:
            logger.warning(
                "marketplace: imported %d connector(s) from %s but failed "
                "to delete the JSON (%s) — manual cleanup needed",
                imported,
                json_path.name,
                err,
            )

    # ── public API ────────────────────────────────────────────────

    def list_installed(self) -> list[MarketplaceInstall]:
        """All installed connectors, ordered by install timestamp ASC."""
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT connector_id, installed_at, origin, version "
                "FROM marketplace_installs "
                "ORDER BY installed_at ASC"
            ).fetchall()
        return [
            MarketplaceInstall(
                connector_id=r["connector_id"],
                installed_at=r["installed_at"],
                origin=r["origin"],
                version=r["version"],
            )
            for r in rows
        ]

    def is_installed(self, connector_id: str) -> bool:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM marketplace_installs WHERE connector_id=?",
                (connector_id,),
            ).fetchone()
        return row is not None

    def get(self, connector_id: str) -> MarketplaceInstall | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT connector_id, installed_at, origin, version "
                "FROM marketplace_installs WHERE connector_id=?",
                (connector_id,),
            ).fetchone()
        if not row:
            return None
        return MarketplaceInstall(
            connector_id=row["connector_id"],
            installed_at=row["installed_at"],
            origin=row["origin"],
            version=row["version"],
        )

    def install(
        self,
        connector_id: str,
        *,
        origin: str = ORIGIN_BUNDLE,
        version: str = "bundled",
    ) -> MarketplaceInstall:
        """Mark connector as installed. Idempotent (returns existing row).

        `origin` is set at FIRST install only — if the row already
        exists, the existing origin/version are preserved (you can't
        promote a 'user' connector to 'bundle' by re-installing).
        """
        if origin not in VALID_ORIGINS:
            raise ValueError(
                f"invalid origin {origin!r}; must be one of {sorted(VALID_ORIGINS)}"
            )
        if not connector_id or not isinstance(connector_id, str):
            raise ValueError("connector_id must be a non-empty string")
        ts = _iso_now()
        with self._lock, self._connect() as conn:
            try:
                conn.execute(
                    "INSERT INTO marketplace_installs "
                    "(connector_id, installed_at, origin, version) "
                    "VALUES (?, ?, ?, ?)",
                    (connector_id, ts, origin, version),
                )
            except sqlite3.IntegrityError:
                # Already installed — idempotent. Return the existing
                # row so callers can read its origin/installed_at.
                pass
        existing = self.get(connector_id)
        # Should always be non-None here; the assertion is for type
        # narrowing and to catch corruption.
        assert existing is not None, (
            f"marketplace_installs row missing after install of {connector_id}"
        )
        return existing

    def uninstall(self, connector_id: str) -> bool:
        """Remove the install marker. Returns True if a row was deleted.

        DOES NOT touch instances. Callers must ensure no instances
        exist before invoking (see api/marketplace.py for the 409
        check). DOES NOT enforce the bundle/user origin distinction —
        that's a route-level concern (DELETE handler returns 403 for
        bundle deletes; this method is the underlying mutator).
        """
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM marketplace_installs WHERE connector_id=?",
                (connector_id,),
            )
            return cur.rowcount > 0

    # ── upgrade migration ──────────────────────────────────────────

    def upgrade_install_existing_instances(
        self,
        instance_connector_ids: list[str],
    ) -> list[str]:
        """One-shot upgrade migration for installs that predate the
        marketplace install gate.

        Install state is the gate: an instance can only exist if the
        connector is in `marketplace_installs`. Older installs created
        instances freely from any connector in the bundle.

        For those installs: every connector that already has an
        instance gets retroactively installed (origin='bundle', since
        only bundle connectors could have instances then —
        user-uploaded connectors didn't exist).

        This is idempotent: PRIMARY KEY rejects duplicate inserts,
        so a row already present stays untouched. Callers can re-run
        without harm.

        Returns the list of connector_ids that were newly auto-
        installed (empty list = nothing to do, e.g. fresh install
        or migration already ran).

        Called by main.py boot, AFTER both stores are constructed
        and the InstanceStore has had a chance to load existing rows.
        """
        newly_installed: list[str] = []
        ts = _iso_now()
        seen: set[str] = set()
        with self._lock, self._connect() as conn:
            for cid in instance_connector_ids:
                if not isinstance(cid, str) or not cid or cid in seen:
                    continue
                seen.add(cid)
                try:
                    conn.execute(
                        "INSERT INTO marketplace_installs "
                        "(connector_id, installed_at, origin, version) "
                        "VALUES (?, ?, ?, ?)",
                        (cid, ts, ORIGIN_BUNDLE, "bundled"),
                    )
                    newly_installed.append(cid)
                except sqlite3.IntegrityError:
                    # Already installed — idempotent. No-op.
                    pass
        return newly_installed


def _iso_now() -> str:
    """UTC ISO 8601 — same format the audit log + instance_store use."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# Re-export the env-resolved data root for callers that need it (e.g.
# the user_connectors directory lives sibling-of-DEFAULT_DATA_ROOT).
def resolved_data_root() -> Path:
    return Path(os.environ.get("DATA_ROOT", str(DEFAULT_DATA_ROOT)))


# ─────────────────────────────────────────────────────────────────
# Module-level singleton accessor.
#
# Same convention used by audit_log, instance_store, provider_store —
# the loader/route code reads via a getter rather than threading the
# store through every call site. Set once at boot from main.py.
# ─────────────────────────────────────────────────────────────────

_singleton: MarketplaceStore | None = None


def set_marketplace_store(store: MarketplaceStore | None) -> None:
    """Wire the process-wide marketplace store. Called once from main.py."""
    global _singleton
    _singleton = store


def get_marketplace_store() -> MarketplaceStore | None:
    """Return the active store (or None when not yet wired).

    Callers MUST tolerate None — early-boot code paths may run before
    main.py finishes wiring. Returning None == "no marketplace gate
    active" so callers can choose how to fail open vs closed.
    """
    return _singleton
