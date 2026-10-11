"""Boot-time admin-credential seeding.

seed_admin_defaults_if_empty() must seed on a genuine first boot, no-op
on every later boot, and must NEVER silently
overwrite an existing admin credential just because the current
PHANTOM_SECRET_KEK can't decrypt it. A KEK mismatch means "fail loud",
not "treat as empty and reseed".
"""
from __future__ import annotations

import base64
import os

import pytest

from usecase.auth_store import AuthStore
from usecase.secret_store import KEK_ENV_VAR, SecretStore, SecretStoreError
from usecase.ui_auth import UiAuthStore


def _store(tmp_path, sessions_name="sessions.db") -> AuthStore:
    secret_store = SecretStore(data_root=tmp_path)
    return AuthStore(secret_store, sessions_db_path=tmp_path / sessions_name)


@pytest.fixture
def kek(monkeypatch):
    """Set a fresh 32-byte KEK and return it, so a test can later swap
    to a different one to simulate a regenerated .env."""
    raw = os.urandom(32)
    monkeypatch.setenv(KEK_ENV_VAR, base64.b64encode(raw).decode())
    return raw


def test_seed_fires_on_genuine_first_boot(tmp_path, kek) -> None:
    store = _store(tmp_path)
    seeded = store.seed_admin_defaults_if_empty("admin", "FirstBootPW1")
    assert seeded is True
    assert store.verify_password("admin", "FirstBootPW1") is True


def test_seed_is_noop_on_later_boot_same_kek(tmp_path, kek) -> None:
    store = _store(tmp_path)
    store.seed_admin_defaults_if_empty("admin", "FirstBootPW1")

    # Simulate a later boot: fresh AuthStore instance, SAME kek (as a
    # real installer re-run guarantees via its "reuse existing secrets"
    # branch), a DIFFERENT default password sitting in the new .env.
    store2 = _store(tmp_path)
    seeded_again = store2.seed_admin_defaults_if_empty("admin", "DifferentPW2")
    assert seeded_again is False
    assert store2.verify_password("admin", "FirstBootPW1") is True
    assert store2.verify_password("admin", "DifferentPW2") is False


def test_seed_fails_loud_on_kek_mismatch_instead_of_overwriting(
    tmp_path, monkeypatch
) -> None:
    """A KEK mismatch must not make has_password() report False, which
    would let the seeder silently overwrite the real admin hash with one
    derived from whatever default password happens to be in the current
    environment — no error, no warning, normal 'seeded' return value.
    The decrypt failure must propagate so the caller (entrypoint.sh)
    fails the boot loudly instead of destroying the operator's real
    credential."""
    monkeypatch.setenv(KEK_ENV_VAR, base64.b64encode(os.urandom(32)).decode())
    store = _store(tmp_path)
    store.seed_admin_defaults_if_empty("admin", "OriginalPW1")
    assert store.verify_password("admin", "OriginalPW1") is True

    # Simulate .env being regenerated between installer attempts while
    # the SecretStore volume survived: a DIFFERENT KEK, fresh AuthStore.
    monkeypatch.setenv(KEK_ENV_VAR, base64.b64encode(os.urandom(32)).decode())
    store2 = _store(tmp_path, sessions_name="sessions2.db")
    with pytest.raises(SecretStoreError):
        store2.seed_admin_defaults_if_empty("admin", "NewDefaultPW2")


def test_original_credential_survives_a_kek_mismatch_attempt(
    tmp_path, monkeypatch
) -> None:
    """Companion to the test above, isolating the "data survives"
    assertion with an explicit KEK instead of reaching into internals."""
    original_kek = os.urandom(32)
    monkeypatch.setenv(KEK_ENV_VAR, base64.b64encode(original_kek).decode())
    store = _store(tmp_path)
    store.seed_admin_defaults_if_empty("admin", "OriginalPW1")

    wrong_kek = os.urandom(32)
    monkeypatch.setenv(KEK_ENV_VAR, base64.b64encode(wrong_kek).decode())
    store2 = _store(tmp_path, sessions_name="sessions2.db")
    with pytest.raises(SecretStoreError):
        store2.seed_admin_defaults_if_empty("admin", "NewDefaultPW2")

    # Switch back to the ORIGINAL kek and confirm the original password
    # still verifies — nothing was overwritten by the failed attempt.
    monkeypatch.setenv(KEK_ENV_VAR, base64.b64encode(original_kek).decode())
    store3 = _store(tmp_path, sessions_name="sessions3.db")
    assert store3.verify_password("admin", "OriginalPW1") is True


def test_has_password_true_for_undecryptable_hash(tmp_path, monkeypatch) -> None:
    """UiAuthStore.has_password() must RAISE (not return False) when a
    hash exists but can't be decrypted with the current KEK — False is
    reserved for genuine absence. The seeder depends on this exact
    distinction: seed_admin_defaults_if_empty() only reseeds when
    has_password() == False."""
    monkeypatch.setenv(KEK_ENV_VAR, base64.b64encode(os.urandom(32)).decode())
    store1 = SecretStore(data_root=tmp_path)
    UiAuthStore(store1).set_password("admin", "OriginalPW1")

    monkeypatch.setenv(KEK_ENV_VAR, base64.b64encode(os.urandom(32)).decode())
    store2 = SecretStore(data_root=tmp_path)
    auth2 = UiAuthStore(store2)
    with pytest.raises(SecretStoreError):
        auth2.has_password("admin")


def test_has_password_false_for_genuine_absence(tmp_path, kek) -> None:
    store = SecretStore(data_root=tmp_path)
    assert UiAuthStore(store).has_password("admin") is False
