"""SecretStore — bundle-local implementation of the spec's `secrets`
capability (spec.md §6.10 row 17).

Per spec §6.10, `secrets` has two backend impls:

  - **Standalone**: `_EnvSecretStore` reads `SPARK_SECRET_<KEY>` env vars.
  - **Platform**:   `InfisicalSecretStore` reads from Infisical at the
                    declared `secretRefs` path.

This module is a third backend — file-backed, encrypted-at-rest with
AES-256-GCM, with the same `read(path) → value` interface as the
planned Infisical backend. It exists because Phantom's UI-entered
secrets (the operator types them in the browser at /providers and
/connectors) don't fit the env-var pattern (which assumes secrets pre-exist in `process.env` before
container boot). When/if Phantom adopts Infisical for standalone,
the SecretStore becomes a thin router that delegates to either the
encrypted file backend (today) or the Infisical client (later).
The `read(path)`/`write(path, value)` interface stays unchanged.

# Encryption-at-rest

When `PHANTOM_SECRET_KEK` is set in the environment, every secret
value gets encrypted before it touches disk:

    plaintext value
        → AES-256-GCM encrypt with random 96-bit nonce
        → header `v1\\x00` + nonce(12) + ciphertext + tag(16)
        → base64-encoded to disk (atomic write, mode 0600)

KEK format: 32 bytes, base64-encoded. Generate with:

    openssl rand -base64 32

The KEK lives alongside MCP_TOKEN in operator `.env` — same lifecycle,
same backup discipline. **Lose the KEK and every operator-supplied
secret becomes unrecoverable** (the operator must re-enter them at
/providers and /connectors). This trade-off is the security win: the secrets directory +
backup tarball are useless without the KEK.

When `PHANTOM_SECRET_KEK` is unset, the store falls back to the
legacy plaintext mode with a loud startup warning. This preserves
upgrade compatibility for existing deploys; operators upgrade to
encryption by setting the env var and restarting (the next read of
each secret rewrites it as encrypted automatically — see migration
behavior in `read()`).

# Path conventions

Paths follow the spec's `/<scope>/<id>/<sub-id>/<slot>` form. For
Phantom-locally-materialized secrets (those entered through the
/providers and /connectors pages), the convention is:

    /agents/phantom/connectors/<instance_id>/<slot_name>
    /agents/phantom/providers/<instance_id>/<slot_name>

These paths get persisted in `instances.db:secrets_json` /
`provider_instances.db:secrets_json` instead of the secret VALUES,
so the sqlite databases hold ONLY references — even if leaked, the
attacker has no useful credential material.

# Filesystem layout

The file backend mirrors the path structure 1:1 under
`<data_root>/secrets/`:

    /app/data/secrets/
    └── agents/
        └── phantom/
            ├── connectors/
            │   ├── 64b06eab-.../api_key       (mode 0600)
            │   └── c2caee7b-.../bot_token
            └── providers/
                └── 9d3e1f.../service_account_json

When PHANTOM_SECRET_KEK is set, file contents are base64-encoded
ciphertext with a `v1\\x00` magic header. Without the KEK they're
UTF-8 plaintext (legacy / first-boot state).

# Audit

Every read/write/delete records to the SqliteAuditLog with
target=`secret:<path>`. Paths are logged, never values. The plaintext
material exists only transiently in process memory at the moment a
tool call resolves it.
"""

from __future__ import annotations

import base64
import logging
import os
import re
import threading
from pathlib import Path
from typing import Iterable

logger = logging.getLogger("Phantom MCP")

DEFAULT_DATA_ROOT = Path("/app/data")
SECRETS_SUBDIR = "secrets"

# Permitted characters in a secret path segment. The spec uses
# /<scope>/<id>/<sub-id>/<slot> with reasonably broad characters in
# each segment; we restrict to a safe subset that doesn't require
# escaping when projected onto the filesystem.
_SEGMENT_RE = re.compile(r"^[A-Za-z0-9._\-]+$")

# AES-GCM ciphertext blob format on disk:
#   ENVELOPE_HEADER (3 bytes)  + nonce (12 bytes) + ciphertext + tag (16 bytes)
# All wrapped in base64 to keep the file UTF-8 readable for tooling.
ENVELOPE_HEADER = b"v1\x00"
GCM_NONCE_LEN = 12
GCM_TAG_LEN = 16
KEK_BYTE_LEN = 32  # AES-256

KEK_ENV_VAR = "PHANTOM_SECRET_KEK"


class SecretStoreError(RuntimeError):
    """Raised when a path is malformed or a read targets a missing secret."""


class SecretNotFoundError(SecretStoreError):
    """Raised specifically when a secret path has no file on disk.

    A distinct subclass so callers can tell TRUE absence apart from a
    secret that exists but can't be decrypted with the current KEK
    (wrong/rotated PHANTOM_SECRET_KEK) or is otherwise corrupt — both of
    those still raise the base SecretStoreError. A caller that wants to
    ask "has this secret ever been set?" (e.g. auth_store's boot-time
    seed check) must catch only this subclass; collapsing it with a
    decrypt failure means "can't decrypt" gets silently treated as
    "never existed", which for a credential hash means silently
    overwriting it instead of failing loud."""


def _resolve_kek() -> bytes | None:
    """Return the operator-supplied KEK as raw 32 bytes, or None when
    encryption is disabled.

    Accepts base64 (preferred — what `openssl rand -base64 32` emits)
    or hex (what `openssl rand -hex 32` emits) or raw 32-byte ASCII
    when the operator pasted exactly 32 chars. Anything that decodes
    to a different length raises — silently truncating would be a
    correctness/security bug.
    """
    raw = os.getenv(KEK_ENV_VAR)
    if not raw:
        return None
    raw = raw.strip()
    # Try standard base64 (with padding fix-up).
    padded = raw + "=" * (-len(raw) % 4)
    try:
        decoded = base64.b64decode(padded, validate=True)
        if len(decoded) == KEK_BYTE_LEN:
            return decoded
    except (ValueError, base64.binascii.Error):
        pass
    # Try URL-safe base64. `urlsafe_b64decode` doesn't take `validate`;
    # invalid chars surface via binascii.Error.
    try:
        decoded = base64.urlsafe_b64decode(padded)
        if len(decoded) == KEK_BYTE_LEN:
            return decoded
    except (ValueError, base64.binascii.Error):
        pass
    # Try hex.
    try:
        decoded = bytes.fromhex(raw)
        if len(decoded) == KEK_BYTE_LEN:
            return decoded
    except ValueError:
        pass
    # Last resort: raw 32 ASCII chars (operator may paste a passphrase
    # of exactly that length, though base64 is the documented form).
    if len(raw.encode("utf-8")) == KEK_BYTE_LEN:
        return raw.encode("utf-8")
    raise SecretStoreError(
        f"{KEK_ENV_VAR} must decode to {KEK_BYTE_LEN} bytes "
        f"(got {len(raw)} chars; tried base64, hex, raw). "
        f"Generate with: openssl rand -base64 32"
    )


class SecretStore:
    """File-backed key/value store for secret material.

    Same `read(path)`/`write(path, value)`/`delete(path)`/`list_under(prefix)`
    interface as the planned Infisical-backend variant; the only thing
    that changes when we adopt Infisical is the `_resolve_path` /
    `_read_file` / `_write_file` internals.

    When `PHANTOM_SECRET_KEK` is set (32-byte base64 / hex / raw),
    values are encrypted with AES-256-GCM before write and decrypted
    on read. Legacy plaintext files are detected at read time
    (no envelope header) and rewritten as encrypted in-place — so
    the operator gets transparent migration the moment they set the
    env var and the agent reads each secret again.

    The KEK is REQUIRED. If `PHANTOM_SECRET_KEK` is unset, the
    store raises at construction time instead of falling back to
    plaintext-on-disk mode. The fallback was a silent-by-default gap:
    secrets like Vertex SA JSON would land cleartext under
    `/app/data/secrets/...` if the operator never set the env var. The
    `phantom-installer` always generates a fresh KEK on first install
    (`openssl rand -base64 32` at
    installer/phantom-installer.template.sh:387) so customer installs
    are unaffected; only manual deploys without the env var hit the
    new error. Operator escape hatch — set `PHANTOM_SECRET_KEK_ALLOW_PLAINTEXT=1`
    explicitly to acknowledge the risk and proceed without encryption
    (still emits the loud startup warning). This is the only sanctioned
    path to plaintext mode now; silent fallback is gone.
    """

    def __init__(self, data_root: Path | None = None) -> None:
        self._data_root = (data_root or self._resolve_data_root()).resolve()
        self._secrets_root = self._data_root / SECRETS_SUBDIR
        # mode 0700 on the parent dir so other processes can't list
        # what's there even with file-level enumeration.
        self._secrets_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            os.chmod(self._secrets_root, 0o700)
        except OSError:
            # On some bind-mount setups the chmod fails silently; the
            # important protection is the file-level 0600 below.
            pass
        self._lock = threading.Lock()
        # Resolve the KEK once at construction. None ⇒ plaintext mode
        # with a loud warning. Operators upgrade by setting the env
        # var and restarting; legacy plaintext files migrate on first
        # read after that.
        try:
            self._kek = _resolve_kek()
        except SecretStoreError as exc:
            logger.error("SecretStore: %s", exc)
            raise
        if self._kek is None:
            # Refuse to start without a KEK by default. Operator
            # must explicitly opt into plaintext mode via the escape-hatch
            # env var. Customer installs via phantom-installer always
            # generate a KEK on first install, so this path is only
            # reachable on manual deploys that skipped the installer.
            allow_plaintext = os.getenv(
                "PHANTOM_SECRET_KEK_ALLOW_PLAINTEXT", ""
            ).strip().lower() in ("1", "true", "yes")
            if not allow_plaintext:
                raise SecretStoreError(
                    f"{KEK_ENV_VAR} is required but not set. Customer installs "
                    "via phantom-installer always generate this automatically; "
                    "this error means you've deployed without the installer. "
                    "Fix by either:\n"
                    f"  1. Generate a KEK: {KEK_ENV_VAR}=$(openssl rand -base64 32)\n"
                    "  2. Or acknowledge the risk and proceed without encryption:\n"
                    "     PHANTOM_SECRET_KEK_ALLOW_PLAINTEXT=1\n"
                    "The store never falls back to plaintext mode silently, because "
                    "that would let secrets like Vertex SA JSON land unencrypted "
                    "on disk without operator awareness."
                )
            logger.warning(
                "SecretStore: %s is NOT set and %s=1 is in effect — secrets stored as PLAINTEXT on disk. "
                "This is the operator-acknowledged escape hatch; clear it once you set %s.",
                KEK_ENV_VAR,
                "PHANTOM_SECRET_KEK_ALLOW_PLAINTEXT",
                KEK_ENV_VAR,
            )
        else:
            logger.info(
                "SecretStore at %s (mode 0700, AES-256-GCM encryption-at-rest enabled)",
                self._secrets_root,
            )

        # Env-var overlay scan. Inventory which env vars
        # are bound at boot so SOC operators can tell at-a-glance
        # which secrets are coming from the runtime environment vs.
        # the file backend. Values are NEVER logged — only the env
        # var name + the corresponding secret-path it overrides.
        if os.environ.get("PHANTOM_ENV_SECRETS_DISABLED", "").strip() in (
            "1", "true", "True", "yes", "YES",
        ):
            logger.info(
                "SecretStore env-overlay: DISABLED via PHANTOM_ENV_SECRETS_DISABLED",
            )
        else:
            overlay_envs = [
                name for name in os.environ
                if name.startswith(self._ENV_PREFIX)
            ]
            if overlay_envs:
                # Map back to their target secret paths so the log
                # entry tells operators what's being shadowed. The
                # mapping is the inverse of _path_to_env_var: drop
                # the prefix, lowercase, replace `__` with `/`,
                # prepend `/`. Keeps the ENV name in the log too so
                # operators can grep their compose / .env easily.
                lines = []
                for env_name in sorted(overlay_envs):
                    body = env_name[len(self._ENV_PREFIX):]
                    secret_path = "/" + body.replace("__", "/").lower()
                    lines.append(f"  {env_name} → {secret_path}")
                logger.info(
                    "SecretStore env-overlay: %d secret(s) sourced from env vars:\n%s",
                    len(overlay_envs), "\n".join(lines),
                )
            else:
                logger.debug(
                    "SecretStore env-overlay: no env vars bound (file backend only)",
                )

    @staticmethod
    def _resolve_data_root() -> Path:
        raw = os.getenv("DATA_ROOT", str(DEFAULT_DATA_ROOT))
        return Path(raw)

    @property
    def secrets_root(self) -> Path:
        return self._secrets_root

    # ─── Env-var overlay ─────────────────────────────────────
    #
    # Layered backend per the multi-backend strategy in the module
    # docstring. When a secret's env-var-mapped name is set in the
    # process environment, `read()` returns its value instead of
    # going to disk. Writes still hit the file backend — env vars are
    # owned by whatever provisioned the container (Kubernetes
    # `Secret`, Helm chart, Terraform, CI runner, .env file, …) and
    # we can't push back to those sources.
    #
    # Use cases this unlocks:
    #   - K8s deployments (mount Secret as env vars; rotation = pod
    #     restart)
    #   - CI end-to-end tests (set env vars instead of driving the UI
    #     forms via Playwright)
    #   - Terraform/Helm bootstrap (write secrets once into IaC, every
    #     install of that site picks them up automatically)
    #   - Air-gapped re-installs (no need to retype 10+ secrets in a
    #     browser at every install)
    #
    # Path → env-var mapping (deterministic):
    #   /agents/phantom/connectors/foo/api_key
    #     → PHANTOM_SECRET__AGENTS__PHANTOM__CONNECTORS__FOO__API_KEY
    #
    # Why double-underscore separator: secret slot names (e.g.
    # `password_hash`, `api_token`) contain single underscores, so
    # path-segment delimiters need to be visually distinct from
    # within-segment underscores. `__` is unambiguous, and the result
    # round-trips: split on `__`, lowercase each segment.
    #
    # Disable knob: set `PHANTOM_ENV_SECRETS_DISABLED=1` to turn off
    # the overlay entirely (read returns to file-only behavior). Useful
    # for testing or for deployments that intentionally don't want
    # env-var precedence.

    _ENV_PREFIX = "PHANTOM_SECRET__"

    @classmethod
    def _path_to_env_var(cls, path: str) -> str:
        """Map a secret path to its overlay env-var name.

        Example: `/ui/auth/admin/password_hash` →
                 `PHANTOM_SECRET__UI__AUTH__ADMIN__PASSWORD_HASH`
        """
        # _validate_path will raise if the path is malformed; we don't
        # need to revalidate here because callers always reach this
        # via read() which already called _resolve_file() which called
        # _validate_path. But this method is also useful from the boot
        # log scan, which doesn't go through read(), so we revalidate
        # to keep the function safe to call standalone.
        segments = cls._validate_path(path)
        return cls._ENV_PREFIX + "__".join(s.upper() for s in segments)

    def _env_overlay_value(self, path: str) -> str | None:
        """Return the env-var-overlay value for `path`, or None when
        no overlay applies (env var unset, or overlay globally
        disabled). Secrets are read from `os.environ` on every call —
        deliberate, so a future env-var rotation (rare; usually a pod
        restart) is picked up without process restart.
        """
        if os.environ.get("PHANTOM_ENV_SECRETS_DISABLED", "").strip() in (
            "1", "true", "True", "yes", "YES",
        ):
            return None
        env_name = self._path_to_env_var(path)
        return os.environ.get(env_name)

    # ─── Path validation ──────────────────────────────────────

    @classmethod
    def _validate_path(cls, path: str) -> list[str]:
        """Validate a secret path and return its segments.

        Raises SecretStoreError on malformed input. Paths must be
        absolute (start with `/`), non-empty, and use only the
        permitted character set per segment. No `..` or empty segments.
        """
        if not isinstance(path, str) or not path.startswith("/"):
            raise SecretStoreError(f"secret path must be a string starting with '/' (got {path!r})")
        segments = [s for s in path.split("/") if s]
        if not segments:
            raise SecretStoreError(f"secret path is empty: {path!r}")
        for s in segments:
            if s in (".", ".."):
                raise SecretStoreError(f"secret path contains traversal segment: {path!r}")
            if not _SEGMENT_RE.match(s):
                raise SecretStoreError(
                    f"secret path segment {s!r} contains illegal characters; allowed: [A-Za-z0-9._-]"
                )
        return segments

    def _resolve_file(self, path: str) -> Path:
        """Resolve a secret path to its filesystem location, with traversal safety."""
        segments = self._validate_path(path)
        target = self._secrets_root.joinpath(*segments).resolve()
        # Defense-in-depth: ensure the resolved path is still under secrets_root.
        try:
            target.relative_to(self._secrets_root)
        except ValueError as exc:
            raise SecretStoreError(
                f"secret path {path!r} escapes the secrets root"
            ) from exc
        return target

    # ─── CRUD ─────────────────────────────────────────────────

    # ─── Crypto helpers ───────────────────────────────────────

    def _encrypt(self, value: str) -> bytes:
        """Encrypt a UTF-8 value to base64(envelope-header || nonce || ct || tag).
        Caller already holds self._lock; this is pure CPU work, no I/O.
        """
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        if self._kek is None:
            # Plaintext mode (KEK absent) — caller falls back via _write_plaintext.
            raise SecretStoreError("KEK not configured; cannot encrypt")
        aesgcm = AESGCM(self._kek)
        nonce = os.urandom(GCM_NONCE_LEN)
        ct_with_tag = aesgcm.encrypt(nonce, value.encode("utf-8"), associated_data=None)
        blob = ENVELOPE_HEADER + nonce + ct_with_tag
        return base64.b64encode(blob)

    def _decrypt(self, b64_blob: bytes) -> str:
        """Decrypt a base64'd envelope. Raises SecretStoreError on
        any failure — wrong KEK, truncation, tampering — never
        returning bogus plaintext."""
        from cryptography.exceptions import InvalidTag
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        if self._kek is None:
            raise SecretStoreError("KEK not configured; cannot decrypt")
        try:
            blob = base64.b64decode(b64_blob, validate=True)
        except (ValueError, base64.binascii.Error) as exc:
            raise SecretStoreError(f"secret blob is not valid base64: {exc}")
        if not blob.startswith(ENVELOPE_HEADER):
            raise SecretStoreError("secret blob has no envelope header")
        body = blob[len(ENVELOPE_HEADER):]
        if len(body) < GCM_NONCE_LEN + GCM_TAG_LEN:
            raise SecretStoreError("secret blob truncated (nonce + tag too short)")
        nonce, ct_with_tag = body[:GCM_NONCE_LEN], body[GCM_NONCE_LEN:]
        aesgcm = AESGCM(self._kek)
        try:
            plaintext = aesgcm.decrypt(nonce, ct_with_tag, associated_data=None)
        except InvalidTag:
            raise SecretStoreError(
                "secret AES-GCM tag verification failed — wrong KEK or tampered ciphertext"
            )
        return plaintext.decode("utf-8")

    @staticmethod
    def _is_envelope(raw: bytes) -> bool:
        """Detect whether on-disk bytes look like our base64-wrapped
        envelope. False ⇒ legacy plaintext file."""
        try:
            decoded = base64.b64decode(raw, validate=True)
        except (ValueError, base64.binascii.Error):
            return False
        return decoded.startswith(ENVELOPE_HEADER)

    # ─── CRUD ─────────────────────────────────────────────────

    def write(self, path: str, value: str) -> None:
        """Write a secret value atomically with mode 0600.

        Atomicity: write to a tempfile in the same directory, then
        rename. If the same path already has a value, it's replaced.
        Encryption happens here when KEK is set; otherwise the bytes
        on disk are UTF-8 plaintext (legacy mode).
        """
        if not isinstance(value, str):
            raise SecretStoreError(
                f"secret value for {path!r} must be a string (got {type(value).__name__})"
            )
        target = self._resolve_file(path)
        with self._lock:
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            try:
                os.chmod(target.parent, 0o700)
            except OSError:
                pass
            tmp = target.with_suffix(target.suffix + ".tmp")
            if self._kek is not None:
                # Encrypted path — write base64-wrapped envelope bytes.
                payload = self._encrypt(value)
                with open(tmp, "wb") as fh:
                    fh.write(payload)
                byte_count = len(value)  # log original size, not ciphertext
            else:
                # Plaintext path (KEK absent) — preserves upgrade compat.
                with open(tmp, "w", encoding="utf-8") as fh:
                    fh.write(value)
                byte_count = len(value)
            os.chmod(tmp, 0o600)
            os.replace(tmp, target)
        logger.info(
            "SecretStore.write path=%s bytes=%d encrypted=%s",
            path, byte_count, self._kek is not None,
        )
        # Append-only audit. Lazy import avoids a circular at
        # import time (audit_log doesn't depend on secret_store, but
        # main.py imports both).
        from usecase.audit_log import record_event, ACTION_SECRET_WRITE
        record_event(
            ACTION_SECRET_WRITE,
            target=f"secret:{path}",
            status="success",
            metadata={
                "path": path,
                "byte_count": byte_count,
                "encrypted": self._kek is not None,
            },
        )

    def read(self, path: str) -> str:
        """Read a secret value. Raises SecretNotFoundError when nothing
        is stored at `path`; raises the base SecretStoreError for every
        other failure (wrong KEK, corrupted/tampered ciphertext,
        malformed path) — callers that only want to ask "does this
        secret exist at all" should catch SecretNotFoundError
        specifically, not the base class, or a decrypt failure silently
        reads as "doesn't exist".

        Resolution order:
          1. Env-var overlay — if PHANTOM_SECRET__<UPPERCASE_PATH> is
             set in the process environment, return its value. Lets
             operators pre-bake secrets via Kubernetes / Terraform /
             .env without typing them into the UI. See
             _path_to_env_var() above for the mapping rules.
          2. File-backed AES-256-GCM at /app/data/secrets/...
          3. Otherwise raise SecretNotFoundError("secret not found").

        Migration: when KEK is set and we encounter a plaintext file
        on disk (no envelope header), we decode it as UTF-8, RE-WRITE
        the same path as encrypted ciphertext, then return the value.
        Operators get transparent at-rest encryption simply by setting
        the env var and waiting for each secret to be touched once.
        """
        # Step 1: env-var overlay. Honors PHANTOM_ENV_SECRETS_DISABLED
        # so deployments can opt out. Audit captures the source so
        # SOC operators can tell at-a-glance which secrets came from
        # env-var bootstrap vs. the file backend.
        overlay = self._env_overlay_value(path)
        if overlay is not None:
            from usecase.audit_log import record_event, ACTION_SECRET_READ
            record_event(
                ACTION_SECRET_READ,
                target=f"secret:{path}",
                status="success",
                metadata={"path": path, "source": "env"},
            )
            return overlay

        target = self._resolve_file(path)
        if not target.is_file():
            # A failed read is also worth recording — tells
            # the operator when a tool tried to use a deleted secret.
            from usecase.audit_log import record_event, ACTION_SECRET_READ
            record_event(
                ACTION_SECRET_READ,
                target=f"secret:{path}",
                status="failure",
                metadata={"path": path, "reason": "not_found"},
            )
            raise SecretNotFoundError(f"secret not found at {path!r}")
        with self._lock:
            with open(target, "rb") as fh:
                raw = fh.read()

        decrypted_via_migration = False
        if self._kek is not None and self._is_envelope(raw):
            value = self._decrypt(raw)
        elif self._kek is not None and not self._is_envelope(raw):
            # Legacy plaintext file with KEK now configured. Decode +
            # re-write as encrypted in place. Log the migration so the
            # operator can see it happen during the upgrade window.
            try:
                value = raw.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise SecretStoreError(
                    f"secret at {path!r} is neither valid envelope nor UTF-8 plaintext: {exc}"
                )
            logger.info(
                "SecretStore.migrate path=%s — re-writing legacy plaintext as AES-GCM",
                path,
            )
            # Recursive write under the same lock would deadlock; the
            # write() above released and we re-acquire there. That's
            # fine because read() releases its own lock before calling
            # write() — see the structure below.
            decrypted_via_migration = True
        elif self._kek is None and self._is_envelope(raw):
            # KEK absent but file is encrypted. Operator removed the
            # env var without realizing it. Refuse rather than return
            # garbage — the agent fails fast with a clear error.
            raise SecretStoreError(
                f"secret at {path!r} is encrypted but {KEK_ENV_VAR} is not set"
            )
        else:
            # Both KEK absent and file plaintext — legacy mode.
            try:
                value = raw.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise SecretStoreError(
                    f"secret at {path!r} is not valid UTF-8: {exc}"
                )

        if decrypted_via_migration:
            # Re-write encrypted (now outside the read lock).
            self.write(path, value)

        # Log the path (NOT the value) so a SOC operator can
        # see which credentials the agent used and when. Path-only
        # exposure is intentional — that's the audit grain we want.
        # Include `source` so SOC can distinguish file-
        # backed vs. env-var-overlay reads (the env-var path returns
        # earlier in this method).
        from usecase.audit_log import record_event, ACTION_SECRET_READ
        record_event(
            ACTION_SECRET_READ,
            target=f"secret:{path}",
            status="success",
            metadata={
                "path": path,
                "source": "file",
                "migrated_to_encrypted": decrypted_via_migration,
            },
        )
        return value

    def has(self, path: str) -> bool:
        """Return True iff a secret is stored at `path`.

        Also returns True when an env-var overlay is
        bound, so callers like ui_auth_store.has_password() see the
        same view of the world that read() will resolve. Without
        this, login could decide "no hash exists, fall back to
        legacy plaintext" while read() would happily return the
        env-var value — inconsistent.
        """
        if self._env_overlay_value(path) is not None:
            return True
        try:
            target = self._resolve_file(path)
        except SecretStoreError:
            return False
        return target.is_file()

    def delete(self, path: str) -> bool:
        """Delete a secret. Returns True if a secret was removed."""
        try:
            target = self._resolve_file(path)
        except SecretStoreError:
            return False
        with self._lock:
            if not target.is_file():
                return False
            target.unlink()
        logger.info("SecretStore.delete path=%s", path)
        from usecase.audit_log import record_event, ACTION_SECRET_DELETED
        record_event(
            ACTION_SECRET_DELETED,
            target=f"secret:{path}",
            status="success",
            metadata={"path": path, "count": 1},
        )
        return True

    def delete_under(self, prefix: str) -> int:
        """Delete every secret whose path is at-or-under `prefix`.

        Used when a connector/provider instance is removed: all of
        its slot-files get cleaned up. Returns the number of files
        deleted.
        """
        # Resolve prefix to a directory (or single file)
        try:
            base = self._resolve_file(prefix)
        except SecretStoreError:
            return 0
        deleted = 0
        with self._lock:
            if base.is_file():
                base.unlink()
                deleted = 1
            elif base.is_dir():
                for p in base.rglob("*"):
                    if p.is_file():
                        p.unlink()
                        deleted += 1
                # Try to clean up empty directories on the way back up,
                # but leave the secrets_root itself alone.
                for p in sorted(base.rglob("*"), key=lambda p: -len(p.parts)):
                    try:
                        if p.is_dir() and not any(p.iterdir()):
                            p.rmdir()
                    except OSError:
                        pass
                try:
                    if base.is_dir() and not any(base.iterdir()):
                        base.rmdir()
                except OSError:
                    pass
        if deleted:
            logger.info("SecretStore.delete_under prefix=%s removed=%d", prefix, deleted)
            from usecase.audit_log import record_event, ACTION_SECRET_DELETED
            record_event(
                ACTION_SECRET_DELETED,
                target=f"secret:{prefix}",
                status="success",
                metadata={"prefix": prefix, "count": deleted},
            )
        return deleted

    def list_under(self, prefix: str) -> Iterable[str]:
        """Enumerate secret paths under `prefix`. Returns paths, not values.

        Useful for diagnostics and migration; never used in hot paths.
        """
        try:
            base = self._resolve_file(prefix)
        except SecretStoreError:
            return
        if base.is_file():
            yield prefix
            return
        if not base.is_dir():
            return
        SecretStore._validate_path(prefix)
        for p in base.rglob("*"):
            if p.is_file():
                rel = p.relative_to(self._secrets_root)
                yield "/" + str(rel).replace(os.sep, "/")


# ─────────────────────────────────────────────────────────────────
# Path builders — keep callers consistent
# ─────────────────────────────────────────────────────────────────

AGENT_SCOPE = "/agents/phantom"


def connector_secret_path(instance_id: str, slot_name: str) -> str:
    """Path convention for a connector instance's secret slot."""
    return f"{AGENT_SCOPE}/connectors/{instance_id}/{slot_name}"


def provider_secret_path(instance_id: str, slot_name: str) -> str:
    """Path convention for a provider instance's secret slot."""
    return f"{AGENT_SCOPE}/providers/{instance_id}/{slot_name}"


def connector_prefix(instance_id: str) -> str:
    return f"{AGENT_SCOPE}/connectors/{instance_id}"


def provider_prefix(instance_id: str) -> str:
    return f"{AGENT_SCOPE}/providers/{instance_id}"


# Log destinations (forwarding targets configured by the
# operator under /log-destinations). Each row gets its own scope; the
# type manifest declares which fields are secrets (type: secret /
# password) and the LogDestinationStore writes their values to these
# paths at create/update time. The agent's MCP tools NEVER resolve
# secrets (`?include_secrets=true` is rejected from non-loopback callers).
def log_destination_secret_path(destination_id: str, slot_name: str) -> str:
    """Path convention for a log destination's secret slot."""
    return f"{AGENT_SCOPE}/log_destinations/{destination_id}/{slot_name}"


def log_destination_prefix(destination_id: str) -> str:
    return f"{AGENT_SCOPE}/log_destinations/{destination_id}"
