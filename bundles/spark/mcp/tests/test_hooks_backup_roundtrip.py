"""The MCP half of the hooks backup/restore contract.

The backup route (mcp/agent/app/api/agent/backup/route.ts) reads
`GET /api/v1/hooks` and the restore route writes each hook back with
`POST /api/v1/hooks`. These tests drive the real routes over a real
SqliteHookStore to prove the store accepts exactly what a backup produces:

  create -> list (the backup) -> delete -> POST each listed hook -> same hooks

including a disabled hook, a builtin hook whose secret-ref value was stripped
(the shape restore writes when a hook lost values), and a re-POST of an id that
already exists (restore skips that case without force; with force it relies on
the store's upsert keeping created_at).

The agent-side pure logic (what to strip, what to skip) is covered by
mcp/agent/scripts/test-hooks-backup.mjs.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from api.hooks import register_hook_routes
from config.config import config as _config
from usecase.audit_log import SqliteAuditLog
from usecase.hook_store import SqliteHookStore

AUTH = {"Authorization": "Bearer test-mcp-token"}


class _FakeMcp:
    def __init__(self):
        self.routes = {}

    def custom_route(self, path, methods=None, include_in_schema=True):
        def deco(fn):
            for m in methods or ["GET"]:
                self.routes[(path, m)] = fn
            return fn

        return deco


@pytest.fixture
def client(monkeypatch, tmp_path: Path) -> TestClient:
    monkeypatch.setattr(_config, "mcp_token", "test-mcp-token")
    store = SqliteHookStore(data_root=tmp_path)
    audit = SqliteAuditLog(data_root=tmp_path)
    mcp = _FakeMcp()
    register_hook_routes(mcp, store, audit)
    app = Starlette()
    for (path, method), fn in mcp.routes.items():
        app.add_route(path, fn, methods=[method])
    return TestClient(app)


def _post(client: TestClient, hook: dict):
    return client.post("/api/v1/hooks", json=hook, headers=AUTH)


def _list(client: TestClient) -> list[dict]:
    r = client.get("/api/v1/hooks", headers=AUTH)
    assert r.status_code == 200, r.text
    return r.json()["hooks"]


def _delete_all(client: TestClient) -> None:
    for h in _list(client):
        assert client.delete(f"/api/v1/hooks/{h['id']}", headers=AUTH).status_code == 200


HOOKS = [
    {
        "id": "hook-block-prod",
        "name": "Block prod",
        "event": "PreToolUse",
        "priority": 50,
        "enabled": True,
        "matcher": {"toolGlob": "caldera_*"},
        "transport": {"type": "command", "command": "/opt/policy.sh",
                      "env": {"POLICY_TOKEN": "secret:POLICY_TOKEN"}},
        "timeoutMs": 3000,
        "failurePolicy": "block",
        "createdAt": "2026-10-10T08:00:00Z",
    },
    {
        "id": "hook-notify",
        "name": "Notify",
        "event": "RunEnd",
        "priority": 100,
        "enabled": False,
        "transport": {"type": "http", "url": "https://hooks.example/notify",
                      "headers": {"X-Ref": "secret:NOTIFY"}},
        "createdAt": "2026-10-10T09:00:00Z",
    },
]


def _without_times(hook: dict) -> dict:
    return {k: v for k, v in hook.items() if k not in ("updatedAt",)}


def test_backup_listing_contains_disabled_hooks_and_full_definitions(client):
    for h in HOOKS:
        assert _post(client, h).status_code == 201
    listed = {h["id"]: h for h in _list(client)}
    assert set(listed) == {"hook-block-prod", "hook-notify"}
    assert listed["hook-notify"]["enabled"] is False
    assert listed["hook-block-prod"]["transport"]["env"] == {"POLICY_TOKEN": "secret:POLICY_TOKEN"}
    assert listed["hook-block-prod"]["matcher"] == {"toolGlob": "caldera_*"}
    assert listed["hook-block-prod"]["failurePolicy"] == "block"


def test_create_backup_delete_restore_brings_the_hooks_back(client):
    for h in HOOKS:
        assert _post(client, h).status_code == 201
    backup = _list(client)  # what GET /api/agent/backup writes to hooks.json

    _delete_all(client)
    assert _list(client) == []

    for h in backup:  # what POST /api/agent/restore does for each hook
        assert _post(client, h).status_code == 201

    restored = {h["id"]: _without_times(h) for h in _list(client)}
    assert restored == {h["id"]: _without_times(h) for h in backup}
    # created_at survives the round trip (the backup carries it)
    assert restored["hook-block-prod"]["createdAt"] == "2026-10-10T08:00:00Z"
    assert restored["hook-notify"]["enabled"] is False


def test_a_hook_that_lost_its_secret_value_is_accepted_when_written_disabled(client):
    """The shape restore POSTs after stripping: no auth header value, enabled False."""
    stripped = {
        "id": "hook-slack",
        "name": "Slack approval",
        "event": "PreToolUse",
        "enabled": False,
        "transport": {"type": "builtin", "name": "slack-approval",
                      "config": {"webhookUrl": "https://r.example/p", "authHeaderName": "X-Auth"}},
        "failurePolicy": "block",
    }
    assert _post(client, stripped).status_code == 201
    got = client.get("/api/v1/hooks/hook-slack", headers=AUTH).json()["hook"]
    assert got["enabled"] is False
    assert "authHeaderValue" not in got["transport"]["config"]


def test_posting_an_existing_id_replaces_it_and_keeps_created_at(client):
    """Force restore over an existing id: the store upserts, created_at stays."""
    assert _post(client, HOOKS[0]).status_code == 201
    changed = {**HOOKS[0], "name": "Renamed", "createdAt": "2030-01-01T00:00:00Z"}
    assert _post(client, changed).status_code == 201
    hooks = _list(client)
    assert len(hooks) == 1
    assert hooks[0]["name"] == "Renamed"
    assert hooks[0]["createdAt"] == "2026-10-10T08:00:00Z"


def test_a_restore_body_for_an_unknown_event_is_refused(client):
    bad = {**HOOKS[0], "id": "x", "event": "NoSuchEvent"}
    assert _post(client, bad).status_code == 400
    assert _list(client) == []
