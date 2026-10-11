"""Tests for SecretStore — file-backed AES-GCM encryption-at-rest with
operator-supplied KEK + transparent legacy-plaintext migration."""

from __future__ import annotations

import base64
import os

import pytest

# Use unprefixed paths so the audit_log lookup inside SecretStore
# (which does `from usecase.audit_log import record_event`) sees
# the same module the test sees. Same lesson as test_event_log.py.
from usecase.secret_store import (
    ENVELOPE_HEADER,
    KEK_ENV_VAR,
    SecretNotFoundError,
    SecretStore,
    SecretStoreError,
    _resolve_kek,
)


# ─── KEK resolution ───────────────────────────────────────────────


def test_kek_unset_returns_none(monkeypatch) -> None:
    monkeypatch.delenv(KEK_ENV_VAR, raising=False)
    assert _resolve_kek() is None


def test_kek_base64_resolves_to_32_bytes(monkeypatch) -> None:
    raw = os.urandom(32)
    monkeypatch.setenv(KEK_ENV_VAR, base64.b64encode(raw).decode())
    assert _resolve_kek() == raw


def test_kek_urlsafe_base64_resolves(monkeypatch) -> None:
    raw = os.urandom(32)
    monkeypatch.setenv(KEK_ENV_VAR, base64.urlsafe_b64encode(raw).decode())
    assert _resolve_kek() == raw


def test_kek_hex_resolves(monkeypatch) -> None:
    raw = os.urandom(32)
    monkeypatch.setenv(KEK_ENV_VAR, raw.hex())
    assert _resolve_kek() == raw


def test_kek_raw_32_chars_resolves(monkeypatch) -> None:
    raw = "a" * 32
    monkeypatch.setenv(KEK_ENV_VAR, raw)
    assert _resolve_kek() == raw.encode("utf-8")


def test_kek_wrong_length_raises(monkeypatch) -> None:
    monkeypatch.setenv(KEK_ENV_VAR, "tooshort")
    with pytest.raises(SecretStoreError):
        _resolve_kek()


# ─── Plaintext mode (explicit escape-hatch only) ─────────


def test_no_kek_no_escape_hatch_raises(tmp_path, monkeypatch) -> None:
    """SecretStore refuses to start without a KEK unless the operator
    explicitly opts into plaintext mode via the escape-hatch env var. A
    silent fallback to plaintext-on-disk would let Vertex SA JSON and
    other sensitive blobs land unencrypted on the host filesystem
    whenever an operator deploys without the installer (which is the
    only path that auto-generates a KEK). The store therefore refuses
    to construct in that scenario; the operator either generates a KEK
    or explicitly acknowledges the risk via the escape hatch."""
    monkeypatch.delenv(KEK_ENV_VAR, raising=False)
    monkeypatch.delenv("PHANTOM_SECRET_KEK_ALLOW_PLAINTEXT", raising=False)
    with pytest.raises(SecretStoreError, match="is required but not set"):
        SecretStore(data_root=tmp_path)


def test_plaintext_round_trip_with_escape_hatch(tmp_path, monkeypatch) -> None:
    """Plaintext mode is still reachable via the explicit escape-hatch
    env var. This preserves the upgrade path for manual-deploy use
    cases where the operator has knowingly accepted the risk (e.g.
    isolated test environments). The startup warning still fires."""
    monkeypatch.delenv(KEK_ENV_VAR, raising=False)
    monkeypatch.setenv("PHANTOM_SECRET_KEK_ALLOW_PLAINTEXT", "1")
    s = SecretStore(data_root=tmp_path)
    s.write("/agents/phantom/connectors/abc/api_key", "sk_live_xyz")
    assert s.read("/agents/phantom/connectors/abc/api_key") == "sk_live_xyz"


def test_plaintext_file_is_actually_plaintext_on_disk(tmp_path, monkeypatch) -> None:
    """When the operator has opted into plaintext mode the literal
    value must be on disk (no envelope, no encryption). This locks the
    upgrade-compat baseline: a legacy plaintext file stays readable if
    the operator sets the escape-hatch env var."""
    monkeypatch.delenv(KEK_ENV_VAR, raising=False)
    monkeypatch.setenv("PHANTOM_SECRET_KEK_ALLOW_PLAINTEXT", "1")
    s = SecretStore(data_root=tmp_path)
    s.write("/agents/phantom/connectors/abc/api_key", "sk_live_xyz")
    on_disk = (
        tmp_path / "secrets" / "agents" / "phantom"
        / "connectors" / "abc" / "api_key"
    ).read_bytes()
    assert on_disk == b"sk_live_xyz"


# ─── Encrypted mode ───────────────────────────────────────────────


@pytest.fixture
def kek_set(monkeypatch):
    """Provide a 32-byte KEK for the duration of one test."""
    raw = os.urandom(32)
    monkeypatch.setenv(KEK_ENV_VAR, base64.b64encode(raw).decode())
    return raw


def test_encrypted_round_trip(tmp_path, kek_set) -> None:
    s = SecretStore(data_root=tmp_path)
    s.write("/agents/phantom/connectors/abc/api_key", "sk_live_xyz")
    assert s.read("/agents/phantom/connectors/abc/api_key") == "sk_live_xyz"


def test_encrypted_file_is_NOT_plaintext_on_disk(tmp_path, kek_set) -> None:
    """The on-disk bytes must not contain the plaintext value
    anywhere — that's the whole point of the encryption layer."""
    s = SecretStore(data_root=tmp_path)
    secret_value = "very-secret-token-91823"
    s.write("/agents/phantom/connectors/abc/api_key", secret_value)
    on_disk = (
        tmp_path / "secrets" / "agents" / "phantom"
        / "connectors" / "abc" / "api_key"
    ).read_bytes()
    assert secret_value.encode("utf-8") not in on_disk
    # The base64-decoded blob must start with our envelope header.
    assert base64.b64decode(on_disk).startswith(ENVELOPE_HEADER)


def test_each_encrypt_uses_a_fresh_nonce(tmp_path, kek_set) -> None:
    """Same plaintext written twice should produce DIFFERENT
    ciphertext — random nonces. Otherwise pattern analysis on the
    on-disk blob could distinguish "same secret as before" from
    "new secret"."""
    s = SecretStore(data_root=tmp_path)
    s.write("/p1", "same-value")
    blob_a = (tmp_path / "secrets" / "p1").read_bytes()
    s.write("/p1", "same-value")
    blob_b = (tmp_path / "secrets" / "p1").read_bytes()
    assert blob_a != blob_b


def test_wrong_kek_fails_decrypt(tmp_path, monkeypatch) -> None:
    """Encrypt with one KEK; attempt to read with a different KEK;
    expect a clear SecretStoreError, NEVER bogus plaintext."""
    monkeypatch.setenv(KEK_ENV_VAR, base64.b64encode(os.urandom(32)).decode())
    s1 = SecretStore(data_root=tmp_path)
    s1.write("/p", "value")

    # Switch KEKs and re-open.
    monkeypatch.setenv(KEK_ENV_VAR, base64.b64encode(os.urandom(32)).decode())
    s2 = SecretStore(data_root=tmp_path)
    with pytest.raises(SecretStoreError, match="tag"):
        s2.read("/p")


def test_wrong_kek_is_NOT_secret_not_found_error(tmp_path, monkeypatch) -> None:
    """A wrong-KEK decrypt failure must raise the
    BASE SecretStoreError, never the SecretNotFoundError subclass — a
    caller distinguishing "never existed" from "exists but undecryptable"
    (e.g. auth_store's boot-time seed check) must see this as the
    latter, or a KEK rotation silently looks identical to a fresh
    install and a real credential gets silently overwritten."""
    monkeypatch.setenv(KEK_ENV_VAR, base64.b64encode(os.urandom(32)).decode())
    s1 = SecretStore(data_root=tmp_path)
    s1.write("/p", "value")

    monkeypatch.setenv(KEK_ENV_VAR, base64.b64encode(os.urandom(32)).decode())
    s2 = SecretStore(data_root=tmp_path)
    try:
        s2.read("/p")
        pytest.fail("expected SecretStoreError")
    except SecretNotFoundError:
        pytest.fail(
            "wrong-KEK decrypt failure must NOT raise SecretNotFoundError "
            "— that's indistinguishable from a genuinely fresh secret"
        )
    except SecretStoreError:
        pass  # expected — the base class, not the "not found" subclass


def test_missing_secret_raises_secret_not_found_error(tmp_path, kek_set) -> None:
    """A path with no file on disk must raise the specific
    SecretNotFoundError subclass — callers (e.g. the boot-time admin
    seed check) depend on catching exactly this case and nothing
    broader."""
    s = SecretStore(data_root=tmp_path)
    with pytest.raises(SecretNotFoundError):
        s.read("/never/written")


def test_tampered_ciphertext_fails_decrypt(tmp_path, kek_set) -> None:
    """Flipping a byte INSIDE the AES-GCM ciphertext must trigger
    tag verification failure, not silent garbage out.

    Subtlety: the on-disk format is

        base64( "v1\\x00" + nonce(12) + ct + tag(16) )

    so tampering the file as raw bytes (e.g. ``blob[-1] ^= 0x01``)
    flips a byte of the *base64 wrapper*, not the underlying
    envelope. When that flip turns the base64 into invalid chars,
    ``SecretStore._is_envelope`` returns False and ``read()`` falls
    into the legacy-plaintext migration path (decodes the tampered
    bytes as UTF-8). That path silently returns garbage instead of
    raising — defeating the test entirely. (That's a real
    SecretStore smell worth a separate hardening PR; here we just
    write a test that exercises what its name promises.)

    Correct probe: base64-decode the file, flip a byte in the
    ciphertext region (after the 3-byte envelope header + 12-byte
    nonce), re-encode, write back. That keeps the envelope detector
    happy and forces the AES-GCM tag check to run on tampered bytes.

    Fresh ``s2`` is used for the read because ``s.write()`` populates
    SecretStore's in-memory cache; reading via ``s`` would short-
    circuit disk entirely.
    """
    s = SecretStore(data_root=tmp_path)
    s.write("/p", "value")
    target = tmp_path / "secrets" / "p"

    # Decode → tamper inside the ciphertext region → re-encode.
    encoded = target.read_bytes()
    decoded = bytearray(base64.b64decode(encoded, validate=True))
    # ENVELOPE_HEADER is 3 bytes ("v1\x00"); nonce is 12. Flip a byte
    # at offset 16 (first byte of the ciphertext, before the tag).
    assert len(decoded) > 16, "envelope shorter than expected — test setup bug"
    decoded[16] ^= 0x01
    target.write_bytes(base64.b64encode(bytes(decoded)))

    s2 = SecretStore(data_root=tmp_path)
    with pytest.raises(SecretStoreError):
        s2.read("/p")


# ─── Migration: plaintext → encrypted ─────────────────────────────


def test_legacy_plaintext_file_migrates_on_first_read(tmp_path, kek_set) -> None:
    """Operator upgrades a deploy that has plaintext secrets:
       1. They set PHANTOM_SECRET_KEK + restart.
       2. The next read of each secret detects the legacy file,
          re-writes it as encrypted, and returns the same value.
       3. Subsequent reads see the encrypted form."""
    # Simulate a legacy file by writing plaintext directly.
    secrets_dir = tmp_path / "secrets" / "agents" / "phantom"
    secrets_dir.mkdir(parents=True, exist_ok=True)
    legacy_file = secrets_dir / "legacy_token"
    legacy_file.write_text("legacy-plaintext-value", encoding="utf-8")

    s = SecretStore(data_root=tmp_path)
    # First read: detects plaintext + migrates.
    assert s.read("/agents/phantom/legacy_token") == "legacy-plaintext-value"

    # On-disk file is now base64'd ciphertext, no longer plaintext.
    on_disk = legacy_file.read_bytes()
    assert b"legacy-plaintext-value" not in on_disk
    assert base64.b64decode(on_disk).startswith(ENVELOPE_HEADER)

    # Second read still returns the original value.
    assert s.read("/agents/phantom/legacy_token") == "legacy-plaintext-value"


def test_encrypted_file_with_kek_unset_refuses_to_decrypt(
    tmp_path, monkeypatch
) -> None:
    """Operator removes the KEK env var without realizing the secrets
    are already encrypted. Don't return garbage — fail fast.

    The SecretStore refuses to construct without a KEK
    unless the escape-hatch env var is set; this test sets the escape
    hatch to reach the read-with-no-KEK code path (which is the
    interesting failure mode being verified)."""
    monkeypatch.setenv(KEK_ENV_VAR, base64.b64encode(os.urandom(32)).decode())
    s1 = SecretStore(data_root=tmp_path)
    s1.write("/p", "value")

    monkeypatch.delenv(KEK_ENV_VAR, raising=False)
    monkeypatch.setenv("PHANTOM_SECRET_KEK_ALLOW_PLAINTEXT", "1")
    s2 = SecretStore(data_root=tmp_path)
    with pytest.raises(SecretStoreError, match="encrypted but"):
        s2.read("/p")


# ─── Audit + lifecycle ────────────────────────────────────────────


def test_delete_removes_encrypted_file(tmp_path, kek_set) -> None:
    s = SecretStore(data_root=tmp_path)
    s.write("/p", "value")
    target = tmp_path / "secrets" / "p"
    assert target.is_file()
    assert s.delete("/p") is True
    assert not target.is_file()


def test_path_traversal_rejected(tmp_path, kek_set) -> None:
    s = SecretStore(data_root=tmp_path)
    with pytest.raises(SecretStoreError):
        s.read("/agents/../../../etc/passwd")
    with pytest.raises(SecretStoreError):
        s.write("/foo/../bar", "value")


def test_constructor_with_invalid_kek_raises(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv(KEK_ENV_VAR, "this is not 32 bytes")
    with pytest.raises(SecretStoreError):
        SecretStore(data_root=tmp_path)
