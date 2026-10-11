"""Read-only SecretStore client for per-instance connector containers.

Mirrors the on-disk crypto envelope used by phantom-agent's
SecretStore (bundles/spark/mcp/src/usecase/secret_store.py) so a
connector container reading from the same `phantom_secret_store`
volume sees identical plaintext.

# Why a thin reader instead of vendoring the full SecretStore class

The agent's full SecretStore is ~580 lines and pulls in audit_log,
instance_store, several other usecase modules. The runtime container
only needs the READ + DECRYPT path — no writes, no migrations, no
list-under, no audit hooks. Vendoring the full class would drag in
the whole transitive dep tree for a 30-line crypto operation.

The trade-off: this reader is locked to v1 envelope format. If the
agent's SecretStore ever bumps to v2 (different cipher, different
header), this reader breaks. Mitigation: same major+minor version of
phantom-agent and phantom-connector-runtime always ship from the same
release tag, so the envelope format is implicitly aligned. A v2
envelope would land in BOTH at the same version, with a coordinated
migration step.

# On-disk envelope format (v1, matches secret_store.py:108-114):
  ENVELOPE_HEADER (3 bytes b"v1\x00")
  + nonce (12 bytes)
  + ciphertext + GCM tag (variable)
  All wrapped in base64 to keep files UTF-8 readable for tooling.

KEK_ENV_VAR is the same `PHANTOM_SECRET_KEK` the agent uses; the
operator sets it once on the host's docker-compose env and it's
passed to BOTH phantom-agent and connector containers via env-var
inheritance.
"""

from __future__ import annotations

import base64
import os
import re
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


# Match secret_store.py:108-116 exactly. If you change anything here,
# change it there too — they MUST match for crypto compat.
ENVELOPE_HEADER = b"v1\x00"
GCM_NONCE_LEN = 12
GCM_TAG_LEN = 16
KEK_BYTE_LEN = 32  # AES-256
KEK_ENV_VAR = "PHANTOM_SECRET_KEK"

# Permitted characters in a path segment. Matches secret_store.py:_SEGMENT_RE.
_SEGMENT_RE = re.compile(r"^[A-Za-z0-9._\-]+$")


class SecretStoreClientError(RuntimeError):
    """Raised on path validation, missing files, or decrypt failures."""


def _resolve_kek() -> bytes | None:
    """Return KEK as 32 raw bytes, or None when encryption is disabled.

    Accepts standard base64, URL-safe base64, hex, or 32 raw ASCII
    chars (in that order). Matches the resolver in
    secret_store.py:_resolve_kek so a KEK that decodes one way for the
    agent decodes the same way here.

    Returns None when KEK is unset (operator running in plaintext-mode,
    e.g. for development). The reader still works in that mode —
    files without an envelope header are treated as plaintext.
    """
    raw = os.getenv(KEK_ENV_VAR)
    if not raw:
        return None
    raw = raw.strip()
    padded = raw + "=" * (-len(raw) % 4)
    try:
        decoded = base64.b64decode(padded, validate=True)
        if len(decoded) == KEK_BYTE_LEN:
            return decoded
    except (ValueError, base64.binascii.Error):
        pass
    try:
        decoded = base64.urlsafe_b64decode(padded)
        if len(decoded) == KEK_BYTE_LEN:
            return decoded
    except (ValueError, base64.binascii.Error):
        pass
    try:
        decoded = bytes.fromhex(raw)
        if len(decoded) == KEK_BYTE_LEN:
            return decoded
    except ValueError:
        pass
    if len(raw.encode("utf-8")) == KEK_BYTE_LEN:
        return raw.encode("utf-8")
    raise SecretStoreClientError(
        f"{KEK_ENV_VAR} must decode to {KEK_BYTE_LEN} bytes "
        f"(got {len(raw)} chars; tried base64, hex, raw)."
    )


def _validate_path(path: str) -> tuple[str, ...]:
    """Validate a /-separated secret path against the segment regex.

    Returns the path's segments tuple for filesystem projection.
    Raises if any segment contains characters outside the safe set.
    """
    if not path or not path.startswith("/"):
        raise SecretStoreClientError(
            f"secret path must start with /, got {path!r}"
        )
    segments = tuple(s for s in path.split("/") if s)
    if not segments:
        raise SecretStoreClientError("secret path is empty")
    for seg in segments:
        if not _SEGMENT_RE.match(seg):
            raise SecretStoreClientError(
                f"secret path segment {seg!r} contains disallowed "
                f"characters (allowed: A-Z, a-z, 0-9, ., _, -)"
            )
    return segments


class SecretStoreReader:
    """Read-only client for the SecretStore on-disk format.

    Construct with the same DATA_ROOT phantom-agent uses; the secrets
    live under `<data_root>/secrets/<scope>/<id>/<slot>`. The KEK is
    read from the environment at construction time.

    Usage:
        reader = SecretStoreReader("/app/data")
        plaintext_bytes = reader.read("/agents/phantom/instances/x/api-token")
    """

    SECRETS_SUBDIR = "secrets"

    def __init__(self, data_root: str | Path) -> None:
        self._data_root = Path(data_root)
        self._kek = _resolve_kek()

    def read(self, path: str) -> str:
        """Return the decrypted secret at `path` as a UTF-8 string.

        Raises SecretStoreClientError on missing file, malformed path,
        or decrypt failure.
        """
        segments = _validate_path(path)
        file_path = self._data_root / self.SECRETS_SUBDIR
        for seg in segments:
            file_path = file_path / seg
        if not file_path.is_file():
            raise SecretStoreClientError(
                f"secret not found at {path!r} "
                f"(resolved to {file_path})"
            )
        raw = file_path.read_bytes()
        return self._decrypt(raw, path).decode("utf-8")

    def _decrypt(self, raw: bytes, path: str) -> bytes:
        """Decrypt raw file bytes per the v1 envelope format.

        Plaintext-mode (no KEK, no envelope header) returns bytes as-is.
        Encrypted files are base64-decoded, header-stripped, and AES-GCM
        decrypted.
        """
        # Plaintext fallback — same as the agent's behavior when KEK is unset.
        # If a file has the envelope header but KEK is missing, that's an
        # error (operator forgot to set KEK on the connector container).
        try:
            decoded = base64.b64decode(raw, validate=False)
        except Exception:
            decoded = None

        if decoded and decoded.startswith(ENVELOPE_HEADER):
            if self._kek is None:
                raise SecretStoreClientError(
                    f"secret at {path!r} is encrypted (v1 envelope) but "
                    f"{KEK_ENV_VAR} is not set on this connector container. "
                    f"Pass it via docker-compose env-var inheritance from "
                    f"the host's .env."
                )
            payload = decoded[len(ENVELOPE_HEADER):]
            if len(payload) < GCM_NONCE_LEN + GCM_TAG_LEN:
                raise SecretStoreClientError(
                    f"secret at {path!r} has truncated envelope "
                    f"(payload {len(payload)} bytes, "
                    f"need at least {GCM_NONCE_LEN + GCM_TAG_LEN})"
                )
            nonce = payload[:GCM_NONCE_LEN]
            ciphertext = payload[GCM_NONCE_LEN:]
            try:
                return AESGCM(self._kek).decrypt(nonce, ciphertext, None)
            except InvalidTag as exc:
                raise SecretStoreClientError(
                    f"AES-GCM tag mismatch for {path!r} — KEK on this "
                    f"container doesn't match what the agent used to encrypt. "
                    f"Verify {KEK_ENV_VAR} matches across containers."
                ) from exc
        # Plaintext file (legacy or KEK-unset deploy).
        return raw
