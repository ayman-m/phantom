"""Images and releases are public: the updater never sends credentials and
every GHCR package it names carries the `-oss` suffix."""

import asyncio
import os
import sys

os.environ.setdefault("MCP_TOKEN", "test-mcp-token")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src import main as updater_main  # noqa: E402


class _Resp:
    def __init__(self, *, json_body=None, text=""):
        self._json, self.text = json_body, text

    def raise_for_status(self):
        pass

    def json(self):
        return self._json


def _fake_client(calls, resp):
    class _Client:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, headers=None):
            calls.append((url, dict(headers or {})))
            return resp

    return _Client


def test_latest_release_lookup_is_anonymous(monkeypatch):
    calls = []
    monkeypatch.setattr(
        updater_main.httpx, "AsyncClient",
        _fake_client(calls, _Resp(json_body={"tag_name": "v1.2.3"})),
    )
    assert asyncio.run(updater_main._latest_release_version()) == "1.2.3"
    url, headers = calls[0]
    assert url == f"https://api.github.com/repos/{updater_main.OWNER}/phantom/releases/latest"
    assert not any(k.lower() == "authorization" for k in headers)


def test_release_manifest_fetch_is_anonymous(monkeypatch):
    calls = []
    monkeypatch.setattr(
        updater_main.httpx, "AsyncClient",
        _fake_client(calls, _Resp(text="PHANTOM_VERSION=1.2.3\n")),
    )
    asyncio.run(updater_main._fetch_release_manifest("1.2.3"))
    _, headers = calls[0]
    assert not any(k.lower() == "authorization" for k in headers)


def test_managed_service_packages_carry_the_oss_suffix():
    packages = {pkg for pkg, _ in updater_main.MANAGED_SERVICES.values()}
    assert packages == {"phantom-xlog-oss", "phantom-caldera-oss", "phantom-agent-oss"}


def test_connector_image_ref_uses_the_oss_package(monkeypatch):
    digest = "sha256:" + "a" * 64
    monkeypatch.setattr(updater_main, "_running_phantom_version", lambda: "1.0.0")
    monkeypatch.setattr(updater_main, "_connector_digest", lambda cid: digest)
    assert updater_main._connector_image_ref("cortex-xdr") == (
        f"{updater_main.REGISTRY}/{updater_main.OWNER}/phantom-connector-cortex-xdr-oss@{digest}"
    )
    monkeypatch.setattr(updater_main, "_connector_digest", lambda cid: None)
    assert updater_main._connector_image_ref("cortex-xdr").endswith("/phantom-connector-cortex-xdr-oss:1.0.0")


def test_no_registry_credentials_are_read():
    assert not hasattr(updater_main, "REGISTRY_TOKEN")
    assert not hasattr(updater_main, "REGISTRY_USER")
    assert not hasattr(updater_main, "_docker_login")
