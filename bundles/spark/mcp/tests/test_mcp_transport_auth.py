"""The JSON-RPC tool endpoint is authenticated, and API keys stay inside their scopes.

Regression: `MCP_PATH` (the FastMCP transport on the published port 8080) had no
authentication at all, so anyone who could reach the port could list and call
every agent tool; and the REST routes accepted ANY valid API key whatever its
scopes (an `audit:read` key could read instances and create jobs).
"""
from __future__ import annotations

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from api.auth import API_KEY_ROUTE_SCOPES, api_key_allows, require_bearer
from api.mcp_auth import McpTransportAuthMiddleware, authorize_transport
from config.config import config as _config
from usecase.api_keys import SqliteApiKeyStore, set_api_key_store
from usecase.audit_log import get_current_approval_bypass

MCP_PATH = "/api/v1/stream/mcp"
TOKEN = "test-mcp-token"


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(_config, "mcp_token", TOKEN)
    s = SqliteApiKeyStore(data_root=tmp_path)
    set_api_key_store(s)
    yield s
    set_api_key_store(None)


def _key(store, *scopes):
    return store.create(label="t", scopes=list(scopes), actor="test").plaintext


# ---- the JSON-RPC endpoint ---------------------------------------------------

@pytest.fixture
def transport(store):
    seen = {}

    async def endpoint(request: Request):
        seen["bypass"] = get_current_approval_bypass()
        seen["principal"] = request.scope.get("state", {}).get("mcp_principal")
        return JSONResponse({"ok": True})

    async def other(request: Request):
        return JSONResponse({"other": True})

    app = Starlette(routes=[
        Route(MCP_PATH, endpoint, methods=["GET", "POST", "DELETE"]),
        Route(MCP_PATH + "/sub", endpoint, methods=["POST"]),
        Route("/ping/", other, methods=["GET"]),
    ])
    app.add_middleware(McpTransportAuthMiddleware, path=MCP_PATH)
    return TestClient(app), seen, store


def test_no_credential_is_refused(transport):
    c, _, _ = transport
    r = c.post(MCP_PATH, json={})
    assert r.status_code == 401 and r.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize("header", ["Bearer nope", "Bearer ", "Basic abc", TOKEN, "Bearer phantom_ak_aaaaaaaa_" + "b" * 43])
def test_wrong_or_malformed_credentials_are_refused(transport, header):
    c, _, _ = transport
    assert c.post(MCP_PATH, json={}, headers={"Authorization": header}).status_code == 401


def test_the_agent_token_is_accepted_on_every_method_and_subpath(transport):
    c, seen, _ = transport
    h = {"Authorization": f"Bearer {TOKEN}"}
    assert c.post(MCP_PATH, json={}, headers=h).status_code == 200
    assert seen["principal"] == "mcp_token"
    assert c.get(MCP_PATH, headers=h).status_code == 200
    assert c.delete(MCP_PATH, headers=h).status_code == 200
    assert c.post(MCP_PATH + "/sub", json={}, headers=h).status_code == 200


def test_every_method_and_subpath_needs_a_credential(transport):
    c, _, _ = transport
    assert c.get(MCP_PATH).status_code == 401
    assert c.delete(MCP_PATH).status_code == 401
    assert c.post(MCP_PATH + "/sub", json={}).status_code == 401
    assert c.post(MCP_PATH + "/", json={}).status_code in (401, 307)


def test_a_key_needs_the_tools_call_scope(transport):
    c, seen, store = transport
    ok = {"Authorization": "Bearer " + _key(store, "tools:call")}
    assert c.post(MCP_PATH, json={}, headers=ok).status_code == 200
    assert seen["principal"].startswith("api_key:")
    star = {"Authorization": "Bearer " + _key(store, "*")}
    assert c.post(MCP_PATH, json={}, headers=star).status_code == 200
    for scopes in (["audit:read"], ["agent:*"], ["agent:read", "agent:write"], ["settings:write"]):
        h = {"Authorization": "Bearer " + _key(store, *scopes)}
        assert c.post(MCP_PATH, json={}, headers=h).status_code == 403, scopes


def test_a_revoked_key_is_refused(transport):
    c, _, store = transport
    created = store.create(label="t", scopes=["tools:call"], actor="test")
    store.revoke(created.record.id, actor="test")
    assert c.post(MCP_PATH, json={}, headers={"Authorization": "Bearer " + created.plaintext}).status_code == 401


def test_other_paths_are_not_this_middlewares_business(transport):
    c, _, _ = transport
    assert c.get("/ping/").status_code == 200


def test_approval_bypass_is_honoured_only_for_the_agent_token(transport):
    c, seen, store = transport
    b = {"X-Phantom-Approval-Bypass": "1"}
    c.post(MCP_PATH, json={}, headers={"Authorization": f"Bearer {TOKEN}", **b})
    assert seen["bypass"] is True
    c.post(MCP_PATH, json={}, headers={"Authorization": f"Bearer {TOKEN}"})
    assert seen["bypass"] is False
    c.post(MCP_PATH, json={}, headers={"Authorization": "Bearer " + _key(store, "tools:call", "*"), **b})
    assert seen["bypass"] is False
    assert get_current_approval_bypass() is False   # nothing leaks past the request


def test_a_server_without_a_token_refuses_everything(monkeypatch):
    monkeypatch.setattr(_config, "mcp_token", "")
    assert authorize_transport("Bearer anything")[1] == 503


# ---- REST: an API key reaches only what its scopes name ------------------------

def _rest(store, key, method, path):
    async def handler(request: Request):
        denied = require_bearer(request)
        return denied or JSONResponse({"ok": True})
    app = Starlette(routes=[Route(path, handler, methods=[method])])
    c = TestClient(app)
    return c.request(method, path, headers={"Authorization": "Bearer " + key}).status_code


@pytest.mark.parametrize("scopes,method,path,allowed", [
    (["audit:read"], "GET", "/api/v1/audit", True),
    (["audit:read"], "GET", "/api/v1/audit/summary", True),
    (["audit:read"], "GET", "/api/v1/audit/stream", True),
    (["audit:read"], "POST", "/api/v1/audit", False),            # writing audit rows needs the token
    (["audit:read"], "GET", "/api/v1/jobs", False),
    (["audit:read"], "POST", "/api/v1/jobs", False),
    (["audit:read"], "GET", "/api/v1/instances", False),
    (["audit:read"], "GET", "/api/v1/providers", False),
    (["audit:read"], "GET", "/api/v1/settings", False),
    (["settings:read"], "GET", "/api/v1/settings", True),
    (["settings:read"], "PUT", "/api/v1/settings", False),
    (["settings:write"], "PUT", "/api/v1/settings", True),
    (["approvals:resolve"], "POST", "/api/v1/approvals/abc/resolve", True),
    (["approvals:resolve"], "GET", "/api/v1/approvals", False),
    (["*"], "GET", "/api/v1/audit", True),
    (["*"], "PUT", "/api/v1/settings", True),
    (["*"], "GET", "/api/v1/jobs", False),                         # * is not "the whole MCP port"
    (["*"], "GET", "/api/v1/instances", False),
    (["*"], "POST", "/api/v1/api_keys", False),
    (["agent:*"], "GET", "/api/v1/audit", False),                  # agent:* is an agent-API scope
    (["tools:call"], "GET", "/api/v1/jobs", False),
])
def test_api_key_scope_table(store, scopes, method, path, allowed):
    assert api_key_allows(scopes, method, path) is allowed
    status = _rest(store, _key(store, *scopes), method, path)
    assert (status == 200) is allowed, (scopes, method, path, status)


def test_the_agent_token_is_unrestricted_on_rest(store):
    for method, path in (("GET", "/api/v1/jobs"), ("POST", "/api/v1/jobs"), ("GET", "/api/v1/instances")):
        assert _rest(store, TOKEN, method, path) == 200


def test_the_scope_table_matches_the_documented_scopes():
    documented = {"audit:read", "settings:read", "settings:write", "approvals:resolve"}
    assert {scope for _, _, scope in API_KEY_ROUTE_SCOPES} == documented
