"""SqliteApiKeyStore — long-lived API keys for external integrations.

The MCP's primary auth is the bundle-internal `MCP_TOKEN` (see api/auth.py)
which the agent UI uses on every internal call. That works for the
phantom-agent ↔ embedded MCP path but is wrong for external callers:

  * external SOC tools polling the audit log for SIEM ingestion
  * cross-host integrations (xlog/caldera on Machine B exposing
    automation hooks back at the agent's webhook surface)
  * scripts an operator wants to run from a workstation

For those, an operator needs to mint a stable, revocable, scoped
secret without sharing the bundle-internal `MCP_TOKEN` (which has
implicit unrestricted access and rotates on every container restart
when not pinned in `.env`).

# Token format

Plaintext API keys returned to callers look like:

    phantom_ak_<id>_<secret>

  * `phantom_ak_` prefix — distinguishes from MCP_TOKEN at the
    auth layer; lets operators grep their secret managers.
  * `<id>` — 8 hex chars, the api_keys.id row primary key. Allows
    O(1) lookup without scanning all rows.
  * `<secret>` — 32 hex chars (16 random bytes hex-encoded). The
    DB stores only sha256(<secret>).

# Schema

    api_keys(
      id            TEXT PRIMARY KEY,    -- 8 hex chars
      label         TEXT NOT NULL,        -- human description
      hash          TEXT NOT NULL,        -- sha256(secret)
      scopes_json   TEXT NOT NULL,        -- JSON list of scope strings
      created_at    TEXT NOT NULL,        -- ISO8601 UTC
      created_by    TEXT,                 -- operator id from request
      last_used_at  TEXT,                 -- ISO8601 UTC; updated on each verify
      revoked_at    TEXT                  -- nullable; non-null = inactive
    );

# Scope semantics

Scopes are advisory at the storage level — the store just persists
them. The auth layer (api/auth.py) reads the scope list to decide
whether a given route should accept this key. Initial scopes are
the same set as our manifest's audit.events plus a few coarse roles:

    "audit:read"             — GET /api/v1/audit*
    "settings:read"          — GET /api/v1/settings
    "settings:write"         — PUT /api/v1/settings
    "approvals:resolve"      — POST /api/v1/approvals/*/resolve
    "tools:call"             — JSON-RPC tool dispatch (read-only by default)
    "*"                      — superset (admin equivalent)

# Verify path

Callers present `Authorization: Bearer phantom_ak_<id>_<secret>`. We
parse out `<id>`, fetch the row, sha256 the presented `<secret>`, and
constant-time compare against `hash`. Match → update last_used_at,
return the row's scopes. Miss/revoked → 401.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets as _secrets
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

logger = logging.getLogger("Phantom MCP")

DEFAULT_DATA_ROOT = Path("/app/data")

API_KEY_PREFIX = "phantom_ak_"
ID_LEN = 8         # hex chars
SECRET_LEN = 32    # hex chars


@dataclass(frozen=True)
class ApiKey:
    id: str
    label: str
    scopes: list[str]
    created_at: str
    created_by: str | None
    last_used_at: str | None
    revoked_at: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "scopes": self.scopes,
            "created_at": self.created_at,
            "created_by": self.created_by,
            "last_used_at": self.last_used_at,
            "revoked_at": self.revoked_at,
            "active": self.revoked_at is None,
        }


@dataclass(frozen=True)
class CreatedApiKey:
    """The full mint result. `plaintext` is returned to the caller ONCE
    at creation; never persisted, never recoverable."""

    record: ApiKey
    plaintext: str


class SqliteApiKeyStore:
    """Sqlite-backed API-key store at ``<data_root>/api_keys.db``."""

    def __init__(
        self,
        data_root: Path | None = None,
        audit_log: Any | None = None,
    ) -> None:
        self._data_root = (data_root or self._resolve_data_root()).resolve()
        self._data_root.mkdir(parents=True, exist_ok=True)
        self._db_path = self._data_root / "api_keys.db"
        self._lock = threading.Lock()
        self._audit = audit_log
        self._init_schema()

    @staticmethod
    def _resolve_data_root() -> Path:
        env = os.getenv("DATA_ROOT")
        if env:
            return Path(env)
        return DEFAULT_DATA_ROOT

    def _init_schema(self) -> None:
        with self._lock, sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS api_keys (
                    id            TEXT PRIMARY KEY,
                    label         TEXT NOT NULL,
                    hash          TEXT NOT NULL,
                    scopes_json   TEXT NOT NULL,
                    created_at    TEXT NOT NULL,
                    created_by    TEXT,
                    last_used_at  TEXT,
                    revoked_at    TEXT
                )
                """
            )

    # ─────────────────────────────────────────────────────────────
    # Mint, verify, list, revoke
    # ─────────────────────────────────────────────────────────────

    def create(
        self,
        label: str,
        scopes: Iterable[str] | None = None,
        actor: str | None = None,
    ) -> CreatedApiKey:
        if not label or not isinstance(label, str):
            raise ValueError("label is required")
        scope_list = sorted({str(s) for s in (scopes or ["*"])})
        key_id = _secrets.token_hex(ID_LEN // 2)            # 8 hex chars
        secret = _secrets.token_hex(SECRET_LEN // 2)         # 32 hex chars
        plaintext = f"{API_KEY_PREFIX}{key_id}_{secret}"
        digest = hashlib.sha256(secret.encode("utf-8")).hexdigest()
        ts = self._utc_now()
        with self._lock, sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO api_keys (
                    id, label, hash, scopes_json, created_at, created_by,
                    last_used_at, revoked_at
                ) VALUES (?, ?, ?, ?, ?, ?, NULL, NULL)
                """,
                (key_id, label, digest, json.dumps(scope_list), ts, actor),
            )
        record = ApiKey(
            id=key_id, label=label, scopes=scope_list, created_at=ts,
            created_by=actor, last_used_at=None, revoked_at=None,
        )
        self._audit_event("api_key_created", actor=actor, target=f"api_key:{key_id}",
                          metadata={"label": label, "scopes": scope_list})
        return CreatedApiKey(record=record, plaintext=plaintext)

    def verify(self, presented: str) -> ApiKey | None:
        """Return the active ApiKey if the presented token matches; None
        on any miss (no row, hash mismatch, revoked). Constant-time
        compare on the hash."""
        if not presented or not presented.startswith(API_KEY_PREFIX):
            return None
        body = presented[len(API_KEY_PREFIX):]
        try:
            key_id, secret = body.split("_", 1)
        except ValueError:
            return None
        if len(key_id) != ID_LEN or len(secret) != SECRET_LEN:
            return None
        with self._lock, sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM api_keys WHERE id = ?", (key_id,)
            ).fetchone()
            if not row:
                return None
            if row["revoked_at"]:
                return None
            digest = hashlib.sha256(secret.encode("utf-8")).hexdigest()
            if not hmac.compare_digest(digest, row["hash"]):
                return None
            ts = self._utc_now()
            conn.execute(
                "UPDATE api_keys SET last_used_at = ? WHERE id = ?",
                (ts, key_id),
            )
        return ApiKey(
            id=row["id"],
            label=row["label"],
            scopes=json.loads(row["scopes_json"]),
            created_at=row["created_at"],
            created_by=row["created_by"],
            last_used_at=ts,
            revoked_at=None,
        )

    def list(self) -> list[ApiKey]:
        with self._lock, sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM api_keys ORDER BY created_at DESC"
            ).fetchall()
        return [
            ApiKey(
                id=r["id"], label=r["label"],
                scopes=json.loads(r["scopes_json"]),
                created_at=r["created_at"], created_by=r["created_by"],
                last_used_at=r["last_used_at"], revoked_at=r["revoked_at"],
            )
            for r in rows
        ]

    def revoke(self, key_id: str, actor: str | None = None) -> bool:
        """Mark a key revoked. Returns True iff a row was updated.
        Idempotent — revoking an already-revoked key returns False."""
        ts = self._utc_now()
        with self._lock, sqlite3.connect(self._db_path) as conn:
            cur = conn.execute(
                "UPDATE api_keys SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL",
                (ts, key_id),
            )
            updated = cur.rowcount > 0
        if updated:
            self._audit_event(
                "api_key_revoked", actor=actor,
                target=f"api_key:{key_id}", metadata={"revoked_at": ts},
            )
        return updated

    # ─────────────────────────────────────────────────────────────
    # Internals
    # ─────────────────────────────────────────────────────────────

    def _audit_event(
        self,
        action: str,
        *,
        actor: str | None = None,
        target: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if self._audit is None:
            return
        try:
            record = getattr(self._audit, "record", None)
            if record is None:
                return
            record(action, target=target, actor=actor, metadata=metadata or {})
        except Exception as exc:  # pragma: no cover
            logger.warning("API key audit record failed for %s: %s", action, exc)

    @staticmethod
    def _utc_now() -> str:
        # Microsecond precision so ORDER BY created_at gives a stable
        # total order for keys minted in the same wall-clock second
        # (CI test reproduced second-collision deflakes).
        from usecase._time_utils import utc_now_micros
        return utc_now_micros()


# ─────────────────────────────────────────────────────────────────
# Module-level singleton accessor
# ─────────────────────────────────────────────────────────────────

_api_key_store: SqliteApiKeyStore | None = None


def set_api_key_store(store: SqliteApiKeyStore | None) -> None:
    global _api_key_store
    _api_key_store = store


def api_key_store() -> SqliteApiKeyStore | None:
    return _api_key_store
