"""Tests for SqliteApiKeyStore — operator-minted API keys for external
integrations (token format, hash storage, revocation, audit emission)."""

from __future__ import annotations

from typing import Any

import pytest

from src.usecase.api_keys import (
    API_KEY_PREFIX,
    ID_LEN,
    SECRET_LEN,
    SqliteApiKeyStore,
)


@pytest.fixture
def store(tmp_path) -> SqliteApiKeyStore:
    return SqliteApiKeyStore(data_root=tmp_path)


def test_create_returns_plaintext_with_correct_format(store: SqliteApiKeyStore) -> None:
    created = store.create(label="siem-poller", scopes=["audit:read"], actor="ayman")
    assert created.plaintext.startswith(API_KEY_PREFIX)
    body = created.plaintext[len(API_KEY_PREFIX):]
    key_id, secret = body.split("_", 1)
    assert len(key_id) == ID_LEN
    assert len(secret) == SECRET_LEN
    assert created.record.id == key_id
    assert created.record.scopes == ["audit:read"]
    assert created.record.label == "siem-poller"
    assert created.record.created_by == "ayman"
    assert created.record.revoked_at is None


def test_verify_accepts_active_key(store: SqliteApiKeyStore) -> None:
    created = store.create(label="x", scopes=["audit:read"])
    row = store.verify(created.plaintext)
    assert row is not None
    assert row.id == created.record.id
    assert row.last_used_at is not None  # bumped on verify


def test_verify_rejects_unknown_id(store: SqliteApiKeyStore) -> None:
    fake = f"{API_KEY_PREFIX}{'a' * ID_LEN}_{'b' * SECRET_LEN}"
    assert store.verify(fake) is None


def test_verify_rejects_wrong_secret(store: SqliteApiKeyStore) -> None:
    created = store.create(label="x")
    body = created.plaintext[len(API_KEY_PREFIX):]
    key_id, _ = body.split("_", 1)
    bad = f"{API_KEY_PREFIX}{key_id}_{'b' * SECRET_LEN}"
    assert store.verify(bad) is None


def test_verify_rejects_malformed_token(store: SqliteApiKeyStore) -> None:
    assert store.verify("totally-not-an-api-key") is None
    assert store.verify("") is None
    assert store.verify(API_KEY_PREFIX + "no-underscore") is None
    # Wrong lengths
    assert store.verify(f"{API_KEY_PREFIX}aa_{'b' * SECRET_LEN}") is None
    assert store.verify(f"{API_KEY_PREFIX}{'a' * ID_LEN}_short") is None


def test_revoke_blocks_subsequent_verify(store: SqliteApiKeyStore) -> None:
    created = store.create(label="x")
    assert store.verify(created.plaintext) is not None
    revoked = store.revoke(created.record.id, actor="ayman")
    assert revoked is True
    assert store.verify(created.plaintext) is None


def test_revoke_is_idempotent(store: SqliteApiKeyStore) -> None:
    created = store.create(label="x")
    assert store.revoke(created.record.id) is True
    # Second revoke returns False (no-op).
    assert store.revoke(created.record.id) is False


def test_revoke_unknown_id_returns_false(store: SqliteApiKeyStore) -> None:
    assert store.revoke("ffffffff") is False


def test_list_orders_by_creation(store: SqliteApiKeyStore) -> None:
    a = store.create(label="a")
    b = store.create(label="b")
    listed = store.list()
    # Newest first.
    assert listed[0].id == b.record.id
    assert listed[1].id == a.record.id


def test_default_scope_is_admin_wildcard(store: SqliteApiKeyStore) -> None:
    created = store.create(label="no-scopes-given")
    assert created.record.scopes == ["*"]


def test_audit_records_create_and_revoke(tmp_path) -> None:
    class _SpyAudit:
        def __init__(self) -> None:
            self.events: list[dict[str, Any]] = []

        def record(
            self, action: str, *, target: str | None = None,
            status: str | None = None, actor: str | None = None,
            duration_ms: int | None = None, metadata: dict[str, Any] | None = None,
        ) -> str:
            self.events.append(
                {"action": action, "target": target, "actor": actor, "metadata": metadata}
            )
            return "row-id"

    spy = _SpyAudit()
    s = SqliteApiKeyStore(data_root=tmp_path, audit_log=spy)
    created = s.create(label="x", scopes=["audit:read"], actor="ayman")
    s.revoke(created.record.id, actor="ayman")

    actions = [e["action"] for e in spy.events]
    assert actions == ["api_key_created", "api_key_revoked"]
    targets = [e["target"] for e in spy.events]
    assert all(t and t.startswith("api_key:") for t in targets)
    assert spy.events[0]["metadata"]["scopes"] == ["audit:read"]


def test_label_required(store: SqliteApiKeyStore) -> None:
    with pytest.raises(ValueError):
        store.create(label="")


def test_secret_persistence_round_trip(tmp_path) -> None:
    """Reopen the store and confirm verify() still works — proves the
    hash actually persists rather than living in memory."""
    s1 = SqliteApiKeyStore(data_root=tmp_path)
    created = s1.create(label="persist-test")
    plaintext = created.plaintext

    s2 = SqliteApiKeyStore(data_root=tmp_path)
    row = s2.verify(plaintext)
    assert row is not None
    assert row.id == created.record.id
