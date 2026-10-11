"""Tests for resolve_worker_args — Task 2 of the store-driven
log-destination resolution arc.

Same module-identity discipline as the create-tool test: import the store
via `usecase.*` (the path the resolver itself imports) and monkeypatch its
`_store` singleton.
"""
from __future__ import annotations

import pytest

from usecase.log_destination_resolver import resolve_worker_args
from usecase import log_destinations_store as lds
from usecase.destination_types_loader import reset_loader_for_tests
from usecase.secret_store import SecretStore


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("PHANTOM_SECRET_KEK_ALLOW_PLAINTEXT", "1")
    lds.reset_store_for_tests()
    reset_loader_for_tests()
    secret = SecretStore(data_root=tmp_path)
    s = lds.LogDestinationStore(data_root=tmp_path, secret_store=secret)
    monkeypatch.setattr(lds, "_store", s)
    yield s
    lds.reset_store_for_tests()
    reset_loader_for_tests()


def test_syslog_ref_resolves_to_address(store):
    d = store.create(name="b", type_id="syslog",
                     config={"host": "10.0.0.8", "port": "514", "protocol": "udp"},
                     secrets={})
    out = resolve_worker_args({"destination": f"logdest:{d.id}", "type": "CEF"})
    assert out["destination"] == "udp:10.0.0.8:514"
    assert "webhook_url" not in out


def test_xsiam_http_ref_injects_url_and_secret(store):
    d = store.create(name="c", type_id="xsiam_http",
                     config={"url": "https://x/logs", "source": "tag"},
                     secrets={"auth_key": "SUPERSECRET"})
    out = resolve_worker_args({"destination": f"logdest:{d.id}"})
    assert out["destination"] == "XSIAM_WEBHOOK"
    assert out["webhook_url"] == "https://x/logs"
    assert out["webhook_key"] == "SUPERSECRET"


def test_non_reference_passthrough(store):
    out = resolve_worker_args({"destination": "udp:1.2.3.4:514"})
    assert out["destination"] == "udp:1.2.3.4:514"
    out2 = resolve_worker_args({"destination": "XSIAM_WEBHOOK"})
    assert out2["destination"] == "XSIAM_WEBHOOK"


def test_unknown_id_raises(store):
    with pytest.raises(ValueError):
        resolve_worker_args({"destination": "logdest:does-not-exist"})
