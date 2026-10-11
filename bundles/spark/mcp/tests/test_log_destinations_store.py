"""Tests for LogDestinationStore.

Coverage:
  - schema init on a fresh tmp_path
  - create() persists row + writes secrets to SecretStore at the right path
  - get() by id OR name
  - list_all() with optional type_id + enabled_only filters
  - update() with "***" sentinel preserves secret slot
  - update() with empty string deletes secret slot
  - delete() cascades secret cleanup
  - set_default() clears default flag on siblings of same type
  - record_probe() updates probe columns + bumps consecutive_failures
  - merged_config() resolves secrets to plaintext (server-side only)
  - UNIQUE(name) raises ValueError, not IntegrityError
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.usecase.log_destinations_store import (
    LogDestinationStore,
    reset_store_for_tests,
)
from src.usecase.secret_store import (
    SecretStore,
    log_destination_prefix,
    log_destination_secret_path,
)
from src.usecase.destination_types_loader import reset_loader_for_tests


@pytest.fixture(autouse=True)
def _reset(monkeypatch: pytest.MonkeyPatch) -> None:
    # SecretStore refuses to boot without KEK; tests don't care about
    # at-rest encryption so allow the plaintext fallback.
    monkeypatch.setenv("PHANTOM_SECRET_KEK_ALLOW_PLAINTEXT", "1")
    reset_store_for_tests()
    reset_loader_for_tests()
    yield
    reset_store_for_tests()
    reset_loader_for_tests()


@pytest.fixture
def store(tmp_path: Path) -> LogDestinationStore:
    secret = SecretStore(data_root=tmp_path)
    return LogDestinationStore(data_root=tmp_path, secret_store=secret)


# ─── Create + get ──────────────────────────────────────────────────


def test_create_syslog_destination(store: LogDestinationStore) -> None:
    dest = store.create(
        name="local-syslog",
        type_id="syslog",
        config={
            "host": "127.0.0.1", "port": "5514",
            "protocol": "udp", "framing": "rfc5424", "facility": "local0",
        },
        secrets={},
    )
    assert dest.id
    assert dest.name == "local-syslog"
    assert dest.type_id == "syslog"
    assert dest.config["host"] == "127.0.0.1"
    assert dest.secret_refs == {}
    assert dest.enabled is True


def test_create_webhook_with_bearer_secret(
    store: LogDestinationStore, tmp_path: Path,
) -> None:
    dest = store.create(
        name="my-webhook",
        type_id="webhook",
        config={
            "url": "https://example.com/hook",
            "auth_type": "bearer",
            "method": "POST",
        },
        secrets={"bearer_token": "shhh-secret-token"},
    )
    # bearer_token persisted to SecretStore at the conventional path
    assert dest.secret_refs == {
        "bearer_token": log_destination_secret_path(dest.id, "bearer_token"),
    }
    # config does NOT carry the secret
    assert "bearer_token" not in dest.config
    # Resolve via merged_config (server-side only)
    merged = store.merged_config(dest.id)
    assert merged is not None
    assert merged["bearer_token"] == "shhh-secret-token"


def test_create_rejects_unknown_type(store: LogDestinationStore) -> None:
    with pytest.raises(ValueError, match="unknown destination type"):
        store.create(name="x", type_id="nonexistent", config={}, secrets={})


def test_create_rejects_empty_name(store: LogDestinationStore) -> None:
    with pytest.raises(ValueError, match="name is required"):
        store.create(name="", type_id="syslog", config={}, secrets={})


def test_create_rejects_duplicate_name(store: LogDestinationStore) -> None:
    store.create(
        name="dup", type_id="syslog",
        config={"host": "x", "port": "514", "protocol": "udp"},
    )
    with pytest.raises(ValueError, match="already exists"):
        store.create(
            name="dup", type_id="webhook",
            config={"url": "https://example.com"},
        )


def test_get_by_id_and_by_name(store: LogDestinationStore) -> None:
    dest = store.create(
        name="findme", type_id="syslog",
        config={"host": "127.0.0.1", "port": "514", "protocol": "udp"},
    )
    assert store.get(dest.id) is not None
    assert store.get("findme") is not None
    assert store.get("not-a-real-id") is None


# ─── List ──────────────────────────────────────────────────────────


def test_list_all_with_type_filter(store: LogDestinationStore) -> None:
    store.create(
        name="s1", type_id="syslog",
        config={"host": "h1", "port": "514", "protocol": "udp"},
    )
    store.create(
        name="s2", type_id="syslog",
        config={"host": "h2", "port": "514", "protocol": "tcp"},
    )
    store.create(
        name="w1", type_id="webhook",
        config={"url": "https://example.com", "auth_type": "none"},
    )

    syslogs = store.list_all(type_id="syslog")
    assert len(syslogs) == 2
    assert all(d.type_id == "syslog" for d in syslogs)

    webhooks = store.list_all(type_id="webhook")
    assert len(webhooks) == 1
    assert webhooks[0].name == "w1"


def test_list_all_enabled_only(store: LogDestinationStore) -> None:
    d1 = store.create(
        name="enabled-one", type_id="syslog",
        config={"host": "h", "port": "514", "protocol": "udp"},
        enabled=True,
    )
    d2 = store.create(
        name="disabled-one", type_id="syslog",
        config={"host": "h", "port": "514", "protocol": "udp"},
        enabled=False,
    )
    enabled = store.list_all(enabled_only=True)
    assert {d.id for d in enabled} == {d1.id}


# ─── Update ────────────────────────────────────────────────────────


def test_update_with_triple_star_preserves_secret(
    store: LogDestinationStore,
) -> None:
    dest = store.create(
        name="rot", type_id="webhook",
        config={
            "url": "https://example.com",
            "auth_type": "bearer",
        },
        secrets={"bearer_token": "original"},
    )
    # Update config but pass *** for the secret
    updated = store.update(
        dest.id,
        config={"url": "https://updated.example.com", "auth_type": "bearer"},
        secrets={"bearer_token": "***"},
    )
    assert updated is not None
    assert updated.config["url"] == "https://updated.example.com"
    merged = store.merged_config(dest.id)
    assert merged is not None
    assert merged["bearer_token"] == "original"  # preserved


def test_update_with_real_value_rotates_secret(
    store: LogDestinationStore,
) -> None:
    dest = store.create(
        name="rot2", type_id="webhook",
        config={"url": "https://example.com", "auth_type": "bearer"},
        secrets={"bearer_token": "original"},
    )
    store.update(dest.id, secrets={"bearer_token": "rotated-value"})
    merged = store.merged_config(dest.id)
    assert merged is not None
    assert merged["bearer_token"] == "rotated-value"


def test_update_with_empty_value_deletes_secret(
    store: LogDestinationStore,
) -> None:
    dest = store.create(
        name="del", type_id="webhook",
        config={"url": "https://example.com", "auth_type": "bearer"},
        secrets={"bearer_token": "to-be-deleted"},
    )
    store.update(dest.id, secrets={"bearer_token": ""})
    updated = store.get(dest.id)
    assert updated is not None
    assert "bearer_token" not in updated.secret_refs


# ─── Delete + cascade ──────────────────────────────────────────────


def test_delete_cascades_secret_cleanup(store: LogDestinationStore) -> None:
    dest = store.create(
        name="bye", type_id="webhook",
        config={"url": "https://example.com", "auth_type": "bearer"},
        secrets={"bearer_token": "boom"},
    )
    secret_path = log_destination_secret_path(dest.id, "bearer_token")
    assert store._secret_store.has(secret_path)

    assert store.delete(dest.id) is True
    assert store.get(dest.id) is None
    assert not store._secret_store.has(secret_path)


def test_delete_returns_false_for_missing(store: LogDestinationStore) -> None:
    assert store.delete("never-existed") is False


# ─── Default ───────────────────────────────────────────────────────


def test_set_default_clears_siblings(store: LogDestinationStore) -> None:
    d1 = store.create(
        name="a", type_id="syslog",
        config={"host": "h", "port": "514", "protocol": "udp"},
        is_default=True,
    )
    d2 = store.create(
        name="b", type_id="syslog",
        config={"host": "h2", "port": "514", "protocol": "udp"},
    )
    # d1 created with is_default=True
    assert store.get(d1.id).is_default is True
    assert store.get(d2.id).is_default is False

    # Promote d2 → d1 must become non-default
    store.set_default(d2.id)
    assert store.get(d1.id).is_default is False
    assert store.get(d2.id).is_default is True


def test_set_default_does_not_cross_types(
    store: LogDestinationStore,
) -> None:
    """Default-of-type is scoped per type_id; promoting a webhook
    doesn't clear a syslog's default."""
    syslog = store.create(
        name="def-sys", type_id="syslog",
        config={"host": "h", "port": "514", "protocol": "udp"},
        is_default=True,
    )
    webhook = store.create(
        name="def-web", type_id="webhook",
        config={"url": "https://example.com", "auth_type": "none"},
    )
    store.set_default(webhook.id)
    assert store.get(syslog.id).is_default is True  # unchanged
    assert store.get(webhook.id).is_default is True


# ─── Probe outcomes ────────────────────────────────────────────────


# ─── WEBHOOK_ENDPOINT migration ────────────────────────────────────


def test_migrate_webhook_endpoint_creates_xsiam_default(
    store: LogDestinationStore, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """First-boot migration: env vars → XSIAM Default destination."""
    from src.usecase.log_destinations_store import (
        migrate_webhook_endpoint_to_destination,
    )

    monkeypatch.setenv("WEBHOOK_ENDPOINT", "https://migrated.xdr/v1/logs")
    monkeypatch.setenv("WEBHOOK_KEY", "migrated-secret-key")

    result = migrate_webhook_endpoint_to_destination(store)
    assert result is not None
    assert result.name == "XSIAM Default"
    assert result.type_id == "xsiam_http"
    assert result.is_default is True
    assert result.config["url"] == "https://migrated.xdr/v1/logs"
    # auth_key MUST be in secret_refs, NOT config
    assert "auth_key" in result.secret_refs
    assert "auth_key" not in result.config
    # Migration resolves to plaintext via merged_config
    merged = store.merged_config(result.id)
    assert merged is not None
    assert merged["auth_key"] == "migrated-secret-key"


def test_migrate_webhook_endpoint_idempotent(
    store: LogDestinationStore, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If any xsiam_http destination already exists, migration is a no-op."""
    from src.usecase.log_destinations_store import (
        migrate_webhook_endpoint_to_destination,
    )

    monkeypatch.setenv("WEBHOOK_ENDPOINT", "https://migrated.xdr/v1/logs")
    monkeypatch.setenv("WEBHOOK_KEY", "migrated-key")

    # First call creates it
    first = migrate_webhook_endpoint_to_destination(store)
    assert first is not None
    # Second call is a no-op
    second = migrate_webhook_endpoint_to_destination(store)
    assert second is None
    # Still only one xsiam_http row
    rows = store.list_all(type_id="xsiam_http")
    assert len(rows) == 1


def test_migrate_webhook_endpoint_skips_when_env_empty(
    store: LogDestinationStore, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No env vars → migration returns None, no row created."""
    from src.usecase.log_destinations_store import (
        migrate_webhook_endpoint_to_destination,
    )

    monkeypatch.delenv("WEBHOOK_ENDPOINT", raising=False)
    monkeypatch.delenv("WEBHOOK_KEY", raising=False)

    result = migrate_webhook_endpoint_to_destination(store)
    assert result is None
    assert store.list_all(type_id="xsiam_http") == []


def test_record_probe_ok_resets_consecutive_failures(
    store: LogDestinationStore,
) -> None:
    dest = store.create(
        name="p1", type_id="syslog",
        config={"host": "h", "port": "514", "protocol": "udp"},
    )
    store.record_probe(dest.id, ok=False, error="conn refused")
    store.record_probe(dest.id, ok=False, error="conn refused")
    after_failures = store.get(dest.id)
    assert after_failures.consecutive_failures == 2

    store.record_probe(dest.id, ok=True, error=None, latency_ms=12)
    final = store.get(dest.id)
    assert final.last_probe_ok is True
    assert final.consecutive_failures == 0
    assert final.last_probe_error is None
