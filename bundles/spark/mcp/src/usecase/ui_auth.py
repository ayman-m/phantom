"""UI password hashing + verification, backed by SecretStore.

What this module owns:
  - Hashing operator passwords with a slow KDF (PBKDF2-HMAC-SHA256,
    600k iterations — OWASP 2023 recommendation for passwords).
  - Versioned envelope `pbkdf2_sha256$<iterations>$<salt_b64>$<hash_b64>`
    so we can rotate the algorithm later without breaking existing
    hashes.
  - Constant-time comparison on verify so timing-attack-by-prefix
    isn't possible.
  - SecretStore as the on-disk format: one file per username at
    `/ui/auth/<username>/password_hash`, AES-256-GCM encrypted at
    rest when PHANTOM_SECRET_KEK is set.

What this module does NOT do:
  - Session cookies / JWTs — handled by the Next.js side (the agent's
    /api/auth/login/route.ts sets the phantom_auth cookie after a
    successful verify here).
  - Multi-user — there's a single operator account on Phantom.
    The username is still stored separately so we can grow
    into multi-user without breaking the schema.

Why pbkdf2 and not bcrypt/argon2:
  - Built into Python's hashlib (no new dep on the MCP image).
  - 600k SHA-256 iterations is ~250ms on a modern CPU — slow enough
    to make brute-force impractical for any plausible password.
  - Migration path to argon2 is a one-line change in `_hash_v1` if
    we ever want to. Existing hashes stay valid because the envelope
    encodes its algorithm.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import secrets
from dataclasses import dataclass

from usecase.secret_store import SecretNotFoundError, SecretStore, SecretStoreError


logger = logging.getLogger("Phantom MCP.ui_auth")


# Tunable. 600k matches OWASP 2023's PBKDF2-SHA256 recommendation for
# password storage. ~250ms per hash on a 2024-era laptop CPU.
_PBKDF2_ITERATIONS = 600_000
# 16 random bytes is the minimum salt length recommended by NIST
# SP 800-132 (§5.1). 32 is generous + future-proof.
_SALT_BYTES = 32

# Path inside the SecretStore where we keep the per-user hash file.
# Single-user today; the username segment makes multi-user trivial
# whenever it lands.
_HASH_PATH_FMT = "/ui/auth/{username}/password_hash"


@dataclass
class HashEnvelope:
    """Parsed `pbkdf2_sha256$<iterations>$<salt_b64>$<hash_b64>` line."""
    algorithm: str
    iterations: int
    salt: bytes
    hash: bytes


def _hash_v1(password: str, salt: bytes, iterations: int) -> bytes:
    """The active hash function. Returns the raw 32-byte digest.

    Encapsulated here so a future rotation (e.g. swap to argon2) only
    needs to change this function + add a new envelope prefix in the
    parser below."""
    return hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations,
        dklen=32,
    )


def _serialize(env: HashEnvelope) -> str:
    return (
        f"{env.algorithm}${env.iterations}$"
        f"{base64.b64encode(env.salt).decode('ascii')}$"
        f"{base64.b64encode(env.hash).decode('ascii')}"
    )


def _parse(serialized: str) -> HashEnvelope:
    parts = serialized.split("$")
    if len(parts) != 4:
        raise UiAuthError(
            "malformed password envelope (expected 4 fields separated by $)"
        )
    algorithm, iter_str, salt_b64, hash_b64 = parts
    if algorithm != "pbkdf2_sha256":
        # Hook for future rotation: when we add argon2, add a branch
        # here. Until then, anything else is a corrupted/tampered
        # envelope and we refuse the login rather than fall through to
        # plaintext compare (defense-in-depth).
        raise UiAuthError(f"unsupported password algorithm {algorithm!r}")
    try:
        iterations = int(iter_str)
    except ValueError as exc:
        raise UiAuthError(f"bad iteration count {iter_str!r}: {exc}") from exc
    try:
        salt = base64.b64decode(salt_b64)
        digest = base64.b64decode(hash_b64)
    except Exception as exc:  # noqa: BLE001
        raise UiAuthError(f"bad base64 in envelope: {exc}") from exc
    return HashEnvelope(algorithm, iterations, salt, digest)


class UiAuthError(RuntimeError):
    """Raised when a password operation fails for any reason. Caller
    should map to an HTTP status — we don't import starlette here so
    this module stays unit-testable without web framework."""


class UiAuthStore:
    """Wraps SecretStore with the per-username password-hash semantics.

    Construction:
      store = UiAuthStore(secret_store)

    Operations:
      store.set_password(username, password)         # hashes + writes
      store.verify(username, password) -> bool       # constant-time
      store.has_password(username) -> bool           # for migration
      store.clear(username)                          # for tests / reset
    """

    def __init__(self, secret_store: SecretStore) -> None:
        self._secret_store = secret_store

    # ─── Path helper ──────────────────────────────────────

    @staticmethod
    def _validate_username(username: str) -> str:
        # Conservative — passes through letters/digits/underscore/hyphen
        # only. Path-traversal protection is mostly handled by SecretStore's
        # own _validate_path; this layer rejects anything that would put
        # an unprintable char in a filename.
        if not isinstance(username, str) or not username:
            raise UiAuthError("username is required")
        if len(username) > 64:
            raise UiAuthError("username exceeds 64 characters")
        if not all(c.isalnum() or c in "_-." for c in username):
            raise UiAuthError(
                "username must contain only alphanumerics, underscore, "
                "hyphen, or dot"
            )
        return username

    def _path(self, username: str) -> str:
        return _HASH_PATH_FMT.format(username=self._validate_username(username))

    # ─── Public API ───────────────────────────────────────

    @staticmethod
    def _normalize_password(password: str) -> str:
        """Strip leading/trailing whitespace.

        Why: mobile keyboards autocomplete passwords and often append a
        trailing space; copy-paste from a password manager occasionally
        introduces leading whitespace. Operators don't intend either,
        but the result is a hash like \"hunter2 \" that never matches
        the \"hunter2\" the operator types next time. We normalize on
        BOTH set and verify (must be symmetric — trim on only one side
        would corrupt the round-trip).

        Internal whitespace is preserved (a password like \"my long
        passphrase\" is intentional). Only leading/trailing strips.
        """
        return password.strip()

    def set_password(self, username: str, password: str) -> None:
        """Hash `password` (PBKDF2-HMAC-SHA256, fresh random salt) and
        write the envelope to the SecretStore at the per-user path."""
        if not isinstance(password, str):
            raise UiAuthError("password is required")
        password = self._normalize_password(password)
        if not password:
            raise UiAuthError("password is required")
        if len(password) < 8:
            # Soft minimum. Operators can tighten via a future
            # password policy setting; for now this is the shortest
            # reasonable hurdle that keeps "x" out of the system.
            raise UiAuthError("password must be at least 8 characters")
        salt = secrets.token_bytes(_SALT_BYTES)
        digest = _hash_v1(password, salt, _PBKDF2_ITERATIONS)
        env = HashEnvelope("pbkdf2_sha256", _PBKDF2_ITERATIONS, salt, digest)
        try:
            self._secret_store.write(self._path(username), _serialize(env))
        except SecretStoreError as exc:
            raise UiAuthError(f"could not persist password hash: {exc}") from exc
        logger.info(
            "ui_auth: password set for user %r (algo=pbkdf2_sha256 iter=%d)",
            username, _PBKDF2_ITERATIONS,
        )

    def verify(self, username: str, password: str) -> bool:
        """Return True iff the presented password hashes to the stored
        envelope. Constant-time compare on the digest. Returns False
        on any miss — no info leakage about whether the username
        exists vs. password was wrong (the login route maps both to
        the same 401 anyway, but defense-in-depth)."""
        if not isinstance(password, str):
            return False
        # Symmetric with set_password — strip leading/trailing
        # whitespace so a copy-paste with stray space verifies cleanly.
        password = self._normalize_password(password)
        try:
            path = self._path(username)
        except UiAuthError:
            return False
        try:
            serialized = self._secret_store.read(path)
        except SecretStoreError:
            # File doesn't exist (no hash set yet) or read failed.
            # Either way, can't verify — fall through to False.
            return False
        try:
            env = _parse(serialized)
        except UiAuthError as exc:
            logger.warning(
                "ui_auth: stored envelope for %r is malformed (%s); "
                "treating as no match. Re-set the password to recover.",
                username, exc,
            )
            return False
        candidate = _hash_v1(password, env.salt, env.iterations)
        return hmac.compare_digest(candidate, env.hash)

    def has_password(self, username: str) -> bool:
        """Whether a hash exists for this user. The login route uses
        this to decide whether to fall back to legacy plaintext
        compare (no hash yet) or treat the absence as a definitive
        'wrong password' (hash exists, verify returned False).

        Also used by auth_store's boot-time seed check to decide
        whether to seed default credentials — so this must distinguish
        TRUE absence from "a hash exists but can't be decrypted with
        the current KEK". Only SecretNotFoundError means
        "no password was ever set"; any other SecretStoreError (wrong
        KEK, corrupt envelope) means a hash DOES exist and must not be
        silently treated as empty — propagate it so the boot-time
        seeder fails loud instead of overwriting a real credential."""
        try:
            path = self._path(username)
        except UiAuthError:
            return False
        try:
            self._secret_store.read(path)
            return True
        except SecretNotFoundError:
            return False

    def clear(self, username: str) -> bool:
        """Remove the stored hash. Returns True if a file was deleted,
        False if there was nothing there. Used by /reset flows + tests."""
        try:
            return self._secret_store.delete(self._path(username))
        except SecretStoreError as exc:
            raise UiAuthError(f"could not clear password hash: {exc}") from exc


# Module-level lazy singleton, parallel to api_key_store() in api_keys.py.
# Constructed on first use so test code can swap in a fake SecretStore
# before the real one is touched.
_store: UiAuthStore | None = None


def ui_auth_store() -> UiAuthStore:
    global _store
    if _store is None:
        # SecretStore() picks up DATA_ROOT + PHANTOM_SECRET_KEK from env,
        # same as every other SecretStore consumer (instance_store,
        # provider_store).
        _store = UiAuthStore(SecretStore())
    return _store


def reset_for_tests() -> None:
    """Drop the singleton so unit tests can re-construct with a fake
    SecretStore. Production callers must NOT use this."""
    global _store
    _store = None
