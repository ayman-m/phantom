"""Task 3 — proxy_call_tool resolves logdest:<id> before forwarding.

Mocks the MCP-over-HTTP dispatch (streamablehttp_client + ClientSession)
with async fakes that capture the arguments actually forwarded to the
connector, so we can assert the destination reference was rewritten
MCP-side (and the xsiam_http secret injected) before the call left.
"""
from __future__ import annotations

import asyncio

import pytest

from pkg import connector_proxy
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


class _Result:
    isError = False
    content: list = []


class _FakeSession:
    def __init__(self, capture):
        self._capture = capture

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def initialize(self):
        return None

    async def call_tool(self, name, arguments=None):
        self._capture["name"] = name
        self._capture["args"] = arguments
        return _Result()


class _FakeTransport:
    async def __aenter__(self):
        return (None, None, None)

    async def __aexit__(self, *a):
        return False


def _install_fakes(monkeypatch, capture):
    monkeypatch.setattr(connector_proxy, "streamablehttp_client",
                        lambda url: _FakeTransport())
    monkeypatch.setattr(connector_proxy, "ClientSession",
                        lambda read, write: _FakeSession(capture))


def test_proxy_resolves_syslog_ref(store, monkeypatch):
    d = store.create(name="b", type_id="syslog",
                     config={"host": "10.0.0.8", "port": "514", "protocol": "udp"},
                     secrets={})
    cap: dict = {}
    _install_fakes(monkeypatch, cap)
    asyncio.run(connector_proxy.proxy_call_tool(
        "http://x:9000", "phantom_create_data_worker",
        {"destination": f"logdest:{d.id}", "type": "CEF"}))
    assert cap["args"]["destination"] == "udp:10.0.0.8:514"


def test_proxy_injects_xsiam_http_secret(store, monkeypatch):
    d = store.create(name="c", type_id="xsiam_http",
                     config={"url": "https://x/logs", "source": "tag"},
                     secrets={"auth_key": "SECRET"})
    cap: dict = {}
    _install_fakes(monkeypatch, cap)
    asyncio.run(connector_proxy.proxy_call_tool(
        "http://x:9000", "phantom_create_data_worker",
        {"destination": f"logdest:{d.id}"}))
    assert cap["args"]["destination"] == "XSIAM_WEBHOOK"
    assert cap["args"]["webhook_url"] == "https://x/logs"
    assert cap["args"]["webhook_key"] == "SECRET"


def test_proxy_passthrough_non_reference(store, monkeypatch):
    cap: dict = {}
    _install_fakes(monkeypatch, cap)
    asyncio.run(connector_proxy.proxy_call_tool(
        "http://x:9000", "some_other_tool",
        {"destination": "udp:1.2.3.4:514"}))
    assert cap["args"]["destination"] == "udp:1.2.3.4:514"
