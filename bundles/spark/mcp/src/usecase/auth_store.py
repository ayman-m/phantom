"""Phantom auth store — sessions + first-boot flag.

Layers on top of `usecase.ui_auth.ui_auth_store` (which owns the
PBKDF2 password hash in SecretStore) to add:

  1. Server-side session tokens. A successful login mints a 32-byte
     CSPRNG token; the SHA-256 hash of that token + metadata
     (username, expires_at, user_agent_hash) lives in
     `auth_sessions.db`. The cookie carries the raw token; the server
     hashes on every validation. Storing only the hash means a leaked
     DB doesn't immediately surface live sessions.

  2. The `credentials_changed` flag. Initial-boot state is `false`
     (operator is using the baked default password). After the
     operator successfully changes their password, the flag flips to
     `true`. The /profile page banner is gated on this — once true,
     the banner never appears again.

  3. Default seeding (idempotent). The entrypoint calls
     `seed_admin_defaults_if_empty(default_password)` once on boot. If
     a password hash is already present, this is a no-op. If absent,
     it writes the PBKDF2 hash of the default password and sets
     `credentials_changed=false`. The clean-volume case is the only
     time the seed fires.

Why a new module rather than expanding ui_auth.py:

ui_auth.py owns PBKDF2 + envelope serialization — pure cryptography.
That's clean and unit-testable without any SQLite. Sessions are
orthogonal: they need a queryable store (revoke-all, expire-stale).
Mixing the two would couple crypto changes to database changes for
no benefit. So sessions get their own module + their own SQLite file.

Why SQLite for sessions vs SecretStore:

SecretStore is per-path encrypted file storage. Listing sessions
(`revoke all sessions for user X`) would require enumerating every
file under `/ui/sessions/`, which the store API doesn't expose
cleanly. SQLite gives us SELECT/DELETE for free. The token itself
(the raw 32 bytes) only ever exists in the operator's cookie; the
server stores SHA-256 hashes, which are not secrets — they're
indices.
"""

from __future__ import annotations

import hashlib
import logging
import os
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from usecase.secret_store import SecretNotFoundError, SecretStore, SecretStoreError
from usecase.ui_auth import UiAuthError, UiAuthStore

logger = logging.getLogger("Phantom MCP.auth_store")


# SecretStore path for the credentials_changed boolean. Sibling of the
# password_hash path that ui_auth.py owns; co-locating keeps the
# auth.v1 surface tidy.
_FLAG_PATH_FMT = "/ui/auth/{username}/credentials_changed"

# Default session TTL when the caller doesn't specify. Matches the
# Next.js cookie Max-Age in mcp/agent/lib/auth-defaults.ts.
DEFAULT_SESSION_TTL_SECONDS = 7200  # 2 hours

# How often expired sessions get pruned (lazily, on validate-session
# calls). 10 minutes is a tradeoff between table growth and
# per-validate overhead.
_PRUNE_INTERVAL_SECONDS = 600

# Default SQLite location. Mirrors the convention of every other store
# in this module (audit.db, jobs.db, etc.) — DATA_ROOT env wins, falls
# back to /app/data for the container image, or ./data for local dev.
_DEFAULT_DB_PATH = Path(os.getenv("DATA_ROOT", "/app/data")) / "auth_sessions.db"


# ─────────────────────────────────────────────────────────────────
# SQLite schema
# ─────────────────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    token_hash         TEXT PRIMARY KEY NOT NULL,
    username           TEXT NOT NULL,
    created_at_ms      INTEGER NOT NULL,
    expires_at_ms      INTEGER NOT NULL,
    user_agent_hash    TEXT,
    revoked_at_ms      INTEGER
);

CREATE INDEX IF NOT EXISTS idx_sessions_username
    ON sessions (username);
CREATE INDEX IF NOT EXISTS idx_sessions_expires
    ON sessions (expires_at_ms);
"""


def _token_hash(raw_token: str) -> str:
    """SHA-256 of the raw token. Used as the SQLite primary key so we
    never persist the cleartext token. Hex-encoded for easy logging /
    comparison."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _user_agent_hash(ua: str | None) -> str | None:
    """Truncated hash of the User-Agent header. Optional metadata used
    only for human-readable session listings; not a security control.
    Returning the hash (not the raw UA) keeps the table compact and
    doesn't carry PII into the auth DB."""
    if not ua:
        return None
    return hashlib.sha256(ua.encode("utf-8")).hexdigest()[:16]


# ─────────────────────────────────────────────────────────────────
# Sessions DB connection helper
# ─────────────────────────────────────────────────────────────────


class _SessionsDb:
    """Thin SQLite wrapper for the sessions table. One instance per
    AuthStore — instances are cheap (no connection pool needed; each
    operation opens its own short-lived connection like every other
    *_store in this codebase)."""

    def __init__(self, db_path: Path) -> None:
        self._path = db_path
        self._lock = threading.Lock()
        self._init_schema()
        self._last_prune_ms = 0

    def _init_schema(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as c:
            c.executescript(_SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._path, timeout=10)
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA journal_mode = WAL")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def insert(
        self,
        token_hash: str,
        username: str,
        created_at_ms: int,
        expires_at_ms: int,
        user_agent_hash: str | None,
    ) -> None:
        with self._lock, self._connect() as c:
            c.execute(
                "INSERT INTO sessions "
                "(token_hash, username, created_at_ms, expires_at_ms, "
                " user_agent_hash) VALUES (?, ?, ?, ?, ?)",
                (token_hash, username, created_at_ms, expires_at_ms, user_agent_hash),
            )

    def lookup(self, token_hash: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as c:
            row = c.execute(
                "SELECT username, created_at_ms, expires_at_ms, "
                "       user_agent_hash, revoked_at_ms "
                "FROM sessions WHERE token_hash = ?",
                (token_hash,),
            ).fetchone()
        if row is None:
            return None
        return {
            "username": row[0],
            "created_at_ms": row[1],
            "expires_at_ms": row[2],
            "user_agent_hash": row[3],
            "revoked_at_ms": row[4],
        }

    def revoke(self, token_hash: str, when_ms: int) -> bool:
        with self._lock, self._connect() as c:
            cur = c.execute(
                "UPDATE sessions SET revoked_at_ms = ? "
                "WHERE token_hash = ? AND revoked_at_ms IS NULL",
                (when_ms, token_hash),
            )
            return cur.rowcount > 0

    def revoke_all_for_user(self, username: str, when_ms: int) -> int:
        with self._lock, self._connect() as c:
            cur = c.execute(
                "UPDATE sessions SET revoked_at_ms = ? "
                "WHERE username = ? AND revoked_at_ms IS NULL",
                (when_ms, username),
            )
            return cur.rowcount

    def prune_expired(self, now_ms: int) -> int:
        """Drop expired or long-revoked sessions. Called lazily from
        validate(); keeps the table small over time. We keep recently-
        revoked rows for ~24h so audit replay can see them; older
        entries get removed."""
        cutoff_ms = now_ms - 86_400_000  # 24h
        with self._lock, self._connect() as c:
            cur = c.execute(
                "DELETE FROM sessions "
                "WHERE expires_at_ms < ? "
                "   OR (revoked_at_ms IS NOT NULL AND revoked_at_ms < ?)",
                (now_ms, cutoff_ms),
            )
            return cur.rowcount

    def maybe_prune(self, now_ms: int) -> None:
        if now_ms - self._last_prune_ms < _PRUNE_INTERVAL_SECONDS * 1000:
            return
        self._last_prune_ms = now_ms
        try:
            removed = self.prune_expired(now_ms)
            if removed:
                logger.info("auth_store: pruned %d expired/revoked session(s)", removed)
        except sqlite3.DatabaseError as exc:
            logger.warning("auth_store: prune failed (%s); continuing", exc)


# ─────────────────────────────────────────────────────────────────
# AuthStore — sessions + flag, wraps UiAuthStore for password ops
# ─────────────────────────────────────────────────────────────────


class AuthStore:
    """Single-user-aware auth surface used by the HTTP layer.

    Password hash + credentials_changed flag live in SecretStore via
    UiAuthStore. Session tokens live in `auth_sessions.db` via
    _SessionsDb. Both reads + writes are coordinated here so the
    HTTP layer never touches the underlying stores directly."""

    def __init__(
        self,
        secret_store: SecretStore,
        sessions_db_path: Path | None = None,
    ) -> None:
        self._secret_store = secret_store
        self._ui_auth = UiAuthStore(secret_store)
        self._sessions = _SessionsDb(sessions_db_path or _DEFAULT_DB_PATH)

    # ─── First-boot seeding (idempotent) ─────────────────

    def seed_admin_defaults_if_empty(
        self, username: str, default_password: str
    ) -> bool:
        """If no password hash exists for `username`, seed one using
        `default_password` and set credentials_changed=false. Returns
        True iff the seed actually fired (i.e. this was a true
        first-boot). Subsequent boots are no-ops.

        Fails loud if seeding is needed but `default_password` is
        empty. The default password is not baked into the image; it
        comes from PHANTOM_DEFAULT_ADMIN_PASSWORD (sourced from .env). An
        empty `default_password` here means the env var wasn't set,
        which on a fresh install would land an empty PBKDF2 hash and
        nobody could log in. Refuse instead.

        Note: this only fires when the store is EMPTY. On upgrade
        installs where the operator already set a password, this
        method returns False without consulting `default_password`,
        so upgraded installs don't need the
        env var to exist (back-fill on the next installer run handles
        the long-term future, but a one-boot gap is non-fatal).
        """
        if self._ui_auth.has_password(username):
            return False
        if not default_password:
            raise ValueError(
                "seed_admin_defaults_if_empty: SecretStore is empty for "
                f"user {username!r} but default_password is empty. The default "
                "admin password is sourced from PHANTOM_DEFAULT_ADMIN_PASSWORD in "
                "/opt/phantom/.env. The installer auto-generates a random "
                "value on first install; if this is missing, re-run the "
                "installer (sudo /opt/phantom/phantom-installer) or run "
                "sudo /opt/phantom/phantom-reset-admin-password to set "
                "credentials interactively."
            )
        try:
            self._ui_auth.set_password(username, default_password)
        except UiAuthError as exc:
            logger.error(
                "auth_store: seeding default password failed (%s)", exc,
            )
            raise
        try:
            self._secret_store.write(
                _FLAG_PATH_FMT.format(username=username), "false",
            )
        except SecretStoreError as exc:
            logger.error(
                "auth_store: writing credentials_changed=false failed (%s)", exc,
            )
            raise
        logger.info(
            "auth_store: seeded default admin credentials for user %r. "
            "Operator MUST change at first login.",
            username,
        )
        return True

    # ─── Password operations (delegate to UiAuthStore) ───

    def verify_password(self, username: str, password: str) -> bool:
        """Returns True iff the password matches the stored hash. False
        for any miss (wrong password, no hash, malformed envelope) —
        does not distinguish so the login route can't leak which."""
        return self._ui_auth.verify(username, password)

    def set_password(
        self, username: str, new_password: str, *, mark_changed: bool
    ) -> None:
        """Hash + write the new password. Optionally flips the
        credentials_changed flag (UI change-password sets True, CLI
        reset also sets True, the boot-time seed leaves it as
        whatever it set initially — i.e. False)."""
        self._ui_auth.set_password(username, new_password)
        if mark_changed:
            try:
                self._secret_store.write(
                    _FLAG_PATH_FMT.format(username=username), "true",
                )
            except SecretStoreError as exc:
                raise UiAuthError(
                    f"failed to update credentials_changed flag: {exc}"
                ) from exc

    def credentials_changed(self, username: str) -> bool:
        """Return the current credentials_changed flag. A genuinely
        missing flag is treated as False (defensive: a boot that
        crashed mid-seed should re-trigger the banner). A flag that
        exists but can't be decrypted (KEK mismatch) is a
        real error, not "unchanged" — propagate it rather than quietly
        showing the operator a misleading first-login banner."""
        try:
            raw = self._secret_store.read(
                _FLAG_PATH_FMT.format(username=username),
            )
        except SecretNotFoundError:
            return False
        return raw.strip().lower() == "true"

    # ─── Session operations ───────────────────────────────

    def create_session(
        self,
        username: str,
        *,
        ttl_seconds: int = DEFAULT_SESSION_TTL_SECONDS,
        user_agent: str | None = None,
    ) -> str:
        """Mint a new session token (32 random bytes, hex-encoded).
        Persists the SHA-256 hash + metadata; returns the RAW token
        (the only place it ever exists in cleartext). Caller is
        responsible for setting the response cookie. The raw token is
        never logged or echoed."""
        raw_token = secrets.token_urlsafe(32)
        now_ms = int(time.time() * 1000)
        self._sessions.insert(
            token_hash=_token_hash(raw_token),
            username=username,
            created_at_ms=now_ms,
            expires_at_ms=now_ms + ttl_seconds * 1000,
            user_agent_hash=_user_agent_hash(user_agent),
        )
        return raw_token

    def validate_session(self, raw_token: str) -> dict[str, Any] | None:
        """Look up the token. Returns dict with `username`,
        `expires_at_ms`, `credentials_changed` if valid; None if
        unknown, revoked, or expired. Lazily prunes expired rows
        every ~10 minutes."""
        if not raw_token:
            return None
        now_ms = int(time.time() * 1000)
        self._sessions.maybe_prune(now_ms)
        row = self._sessions.lookup(_token_hash(raw_token))
        if row is None:
            return None
        if row["revoked_at_ms"] is not None:
            return None
        if row["expires_at_ms"] <= now_ms:
            return None
        return {
            "username": row["username"],
            "expires_at_ms": row["expires_at_ms"],
            "credentials_changed": self.credentials_changed(row["username"]),
        }

    def revoke_session(self, raw_token: str) -> bool:
        """Mark a single session revoked. Idempotent — returns True if
        a row was updated, False if the session was already revoked
        or didn't exist. Used by /logout."""
        if not raw_token:
            return False
        return self._sessions.revoke(
            _token_hash(raw_token), int(time.time() * 1000),
        )

    def revoke_all_sessions(self, username: str) -> int:
        """Mark all active sessions for a user revoked. Returns the
        count. Called after password change + admin reset so every
        existing browser session is invalidated."""
        return self._sessions.revoke_all_for_user(
            username, int(time.time() * 1000),
        )


# ─── Lazy module-level singleton ─────────────────────────────────


_store: AuthStore | None = None
_store_lock = threading.Lock()


def auth_store() -> AuthStore:
    """Return the process-wide AuthStore singleton, constructing on
    first access. Same pattern as ui_auth_store(), api_key_store(),
    etc. — keeps tests able to swap in a fake SecretStore via
    reset_for_tests() before any real one is constructed."""
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = AuthStore(SecretStore())
    return _store


def reset_for_tests() -> None:
    """Drop the singleton so unit tests can re-construct with a fake
    backing store. Production callers must NOT use this."""
    global _store
    _store = None
