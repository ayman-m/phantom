"""verify_key endpoint — validates a phantom_ak_* key, returns scopes.

Exercises the HTTP glue (MCP_TOKEN gate via require_bearer → store.verify →
JSON). The store + verify logic are covered by test_api_keys.py; this test
covers the new endpoint wiring the Next.js middleware calls.
"""
from __future__ import annotations

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from config.config import config as _config
from api.ui_auth import register_ui_auth_routes
from usecase.api_keys import SqliteApiKeyStore, set_api_key_store


class _FakeMcp:
    """Mimics FastMCP.custom_route(path, methods=, include_in_schema=)."""

    def __init__(self):
        self.routes = {}

    def custom_route(self, path, methods=None, include_in_schema=True):
        def deco(fn):
            for m in (methods or ["GET"]):
                self.routes[(path, m)] = fn
            return fn

        return deco


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(_config, "mcp_token", "test-mcp-token")
    store = SqliteApiKeyStore(data_root=tmp_path)
    set_api_key_store(store)
    mcp = _FakeMcp()
    register_ui_auth_routes(mcp)
    app = Starlette()
    for (path, method), fn in mcp.routes.items():
        app.add_route(path, fn, methods=[method])
    yield TestClient(app), store
    set_api_key_store(None)


def test_verify_key_valid(client):
    c, store = client
    created = store.create(label="t", scopes=["agent:*"], actor="ayman")
    r = c.post(
        "/api/v1/ui/auth/verify_key",
        json={"api_key": created.plaintext},
        headers={"Authorization": "Bearer test-mcp-token"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["valid"] is True
    assert body["scopes"] == ["agent:*"]
    assert body["key_id"] == created.record.id
    assert body["label"] == "t"


def test_verify_key_unknown(client):
    c, _ = client
    r = c.post(
        "/api/v1/ui/auth/verify_key",
        json={"api_key": "phantom_ak_deadbeef_" + "0" * 32},
        headers={"Authorization": "Bearer test-mcp-token"},
    )
    assert r.status_code == 200
    assert r.json()["valid"] is False


def test_verify_key_requires_mcp_token(client):
    c, _ = client
    r = c.post("/api/v1/ui/auth/verify_key", json={"api_key": "x"})
    assert r.status_code in (401, 403)
