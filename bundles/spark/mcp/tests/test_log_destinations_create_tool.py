"""Tests for the log_destinations_create MCP tool (secretless syslog).

Store-driven log-destination resolution arc — Task 1.

The tool calls get_log_destination_store() (the module singleton), so the
fixture monkeypatches the SAME module the tool imports (`usecase.*`, NOT
`src.usecase.*` — they're distinct module objects under the test PYTHONPATH;
mixing them would leave the tool reading a different singleton).
"""
from __future__ import annotations

import pytest

from usecase.builtin_components import self_mod_tools
from usecase import log_destinations_store as lds
from usecase.destination_types_loader import reset_loader_for_tests
from usecase.secret_store import SecretStore


@pytest.fixture(autouse=True)
def _fresh_store(tmp_path, monkeypatch):
    monkeypatch.setenv("PHANTOM_SECRET_KEK_ALLOW_PLAINTEXT", "1")
    lds.reset_store_for_tests()
    reset_loader_for_tests()
    secret = SecretStore(data_root=tmp_path)
    store = lds.LogDestinationStore(data_root=tmp_path, secret_store=secret)
    monkeypatch.setattr(lds, "_store", store)
    yield
    lds.reset_store_for_tests()
    reset_loader_for_tests()


def test_create_secretless_syslog_first_is_default():
    out = self_mod_tools.log_destinations_create(
        name="probe-syslog", host="10.1.1.1", port=514, protocol="udp")
    assert out["type_id"] == "syslog"
    assert out["config"]["host"] == "10.1.1.1"
    assert out["config"]["port"] == "514"
    assert out["config"]["protocol"] == "udp"
    assert out["is_default"] is True            # first syslog → default
    assert out["secrets"] == {}                 # no secret slot


def test_second_syslog_not_default():
    self_mod_tools.log_destinations_create(name="first", host="a", port=514)
    out = self_mod_tools.log_destinations_create(name="second", host="b", port=514)
    assert out["is_default"] is False


def test_create_rejects_non_udp_tcp_protocol():
    out = self_mod_tools.log_destinations_create(
        name="bad", host="h", port=514, protocol="tls")
    assert "error" in out
    assert "protocol" in out["error"].lower()
