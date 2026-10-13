"""PATCH /api/v1/instances/{id} restarts the instance's connector container when needed.

A per-instance container reads its config and secrets once, at start, so a saved
change reaches it only through a restart through phantom-updater. The restart
happens when config or a secret really changed (or a disabled instance is
enabled), not for a tools-only, rename-only or no-op PATCH, and not while the
instance is disabled. A restart that fails or hangs never fails or blocks the
save: the response says what happened.
"""
from __future__ import annotations

import asyncio

import httpx
import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

import api.instances as instances_api
from api.instances import register_instance_routes
from config.config import config as _config
from usecase.instance_store import InstanceStore
from usecase.secret_store import SecretStore


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
def world(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("DATA_ROOT", str(data))
    monkeypatch.setenv("PHANTOM_SECRET_KEK_ALLOW_PLAINTEXT", "1")
    monkeypatch.setattr(_config, "mcp_token", "test-token")
    store = InstanceStore(data_root=data, secret_store=SecretStore(data_root=data))
    mcp = _FakeMcp()
    register_instance_routes(mcp, store)
    app = Starlette()
    for (path, method), fn in mcp.routes.items():
        app.add_route(path, fn, methods=[method])

    calls = []
    outcome = {"result": {"ok": True, "status": "restarted"}, "delay": 0.0}

    async def fake_restart(connector_id, container_instance_name, instance_id, image_ref=None):
        calls.append((connector_id, container_instance_name, instance_id, image_ref))
        if outcome["delay"]:
            await asyncio.sleep(outcome["delay"])
        return outcome["result"]

    monkeypatch.setattr(instances_api, "_updater_restart", fake_restart)
    monkeypatch.setattr(instances_api, "RESTART_WAIT_S", 0.2)
    # reload_tools_now needs the agent's tool registry; it is not under test.
    import usecase.connector_loader as loader
    monkeypatch.setattr(loader, "reload_tools_now", lambda: None, raising=False)

    class World:
        pass

    w = World()
    w.store, w.calls, w.outcome = store, calls, outcome
    w.client = TestClient(app, headers={"Authorization": "Bearer test-token"})
    return w


def _instance(world, name="Lab Sender", config=None, secrets=None, container_url="http://phantom-connector-http-sender-Lab_Sender:9000"):
    inst = world.store.create("http-sender", name, config or {"collectorUrl": "https://a.example/logs/v1/event"}, secrets or {"collectorKey": "k1"})
    if container_url:
        world.store.set_container_url(inst.id, container_url)
    return inst


def _patch(world, inst, body):
    return world.client.patch(f"/api/v1/instances/{inst.id}", json=body)


def test_a_config_change_restarts_the_container_and_says_so(world):
    inst = _instance(world)
    r = _patch(world, inst, {"config": {"collectorUrl": "https://a.example/logs/v1/event", "criblUrl": "https://b.example/logs/v1/integrated/cribl/data"}})
    assert r.status_code == 200
    assert r.json()["restart"] == {"ok": True, "status": "restarted"}
    assert world.calls == [("http-sender", "Lab_Sender", inst.id, None)]
    assert world.store.get(inst.id).config["criblUrl"].startswith("https://b.example")


def test_a_rotated_secret_restarts_and_an_untouched_one_does_not(world):
    inst = _instance(world)
    r = _patch(world, inst, {"secrets": {"collectorKey": "***"}})
    assert "restart" not in r.json() and world.calls == []
    r = _patch(world, inst, {"secrets": {"collectorKey": "rotated", "criblToken": "t1"}})
    assert r.json()["restart"]["ok"] is True and len(world.calls) == 1


def test_a_save_that_changes_nothing_does_not_restart(world):
    inst = _instance(world)
    same = {"collectorUrl": "https://a.example/logs/v1/event"}
    r = _patch(world, inst, {"name": "Lab Sender", "config": same, "secrets": {"collectorKey": "***"}})
    assert r.status_code == 200 and "restart" not in r.json()
    assert world.calls == []


def test_tools_only_and_rename_only_patches_do_not_restart(world):
    inst = _instance(world)
    r = _patch(world, inst, {"disabled_tools": ["send_events"]})
    assert r.status_code == 200 and "restart" not in r.json()
    r = _patch(world, inst, {"name": "Renamed"})
    assert r.status_code == 200 and "restart" not in r.json()
    assert world.calls == []


def test_a_disabled_instance_is_not_restarted_by_a_config_change(world):
    inst = _instance(world)
    _patch(world, inst, {"enabled": False})
    r = _patch(world, inst, {"config": {"collectorUrl": "https://c.example/logs/v1/event"}})
    assert r.status_code == 200 and "restart" not in r.json()
    assert world.calls == []


def test_disabling_does_not_restart_and_enabling_does(world):
    inst = _instance(world)
    r = _patch(world, inst, {"enabled": False})
    assert "restart" not in r.json() and world.calls == []
    r = _patch(world, inst, {"enabled": True})
    assert r.json()["restart"]["ok"] is True and len(world.calls) == 1


def test_a_rename_with_a_config_change_restarts_the_container_it_has(world):
    inst = _instance(world, container_url="http://phantom-connector-http-sender-Old_Name:9000")
    _patch(world, inst, {"name": "New Name", "config": {"collectorUrl": "https://d.example/logs/v1/event"}})
    assert world.calls[0][1] == "Old_Name", "the container keeps the name it was started with"


def test_an_instance_without_a_container_url_uses_the_slug_of_its_name(world):
    inst = _instance(world, name="My Sender!", container_url=None)
    _patch(world, inst, {"config": {"collectorUrl": "https://e.example/logs/v1/event"}})
    assert world.calls[0][1] == "My_Sender"


def test_a_failed_restart_still_saves_and_reports_the_failure(world):
    world.outcome["result"] = {"ok": False, "status": "failed", "error": "phantom-updater could not be reached"}
    inst = _instance(world)
    r = _patch(world, inst, {"config": {"collectorUrl": "https://f.example/logs/v1/event"}})
    assert r.status_code == 200
    assert r.json()["restart"] == {"ok": False, "status": "failed", "error": "phantom-updater could not be reached"}
    assert world.store.get(inst.id).config["collectorUrl"] == "https://f.example/logs/v1/event"


def test_a_slow_restart_does_not_hold_the_save(world):
    world.outcome["delay"] = 1.0
    inst = _instance(world)
    r = _patch(world, inst, {"config": {"collectorUrl": "https://g.example/logs/v1/event"}})
    assert r.status_code == 200
    assert r.json()["restart"] == {"ok": True, "status": "in_progress"}


class _Audit:
    def __init__(self):
        self.rows = []

    def record(self, action, **kw):
        self.rows.append((action, kw))


@pytest.fixture
def audit(monkeypatch):
    a = _Audit()
    monkeypatch.setattr(instances_api, "audit_log", lambda: a)
    return a


def _restart_rows(audit):
    return [kw for action, kw in audit.rows if action == "instance_restart"]


def test_a_restart_that_finishes_in_time_is_audited_once(world, audit):
    inst = _instance(world)
    _patch(world, inst, {"config": {"collectorUrl": "https://h.example/logs/v1/event"}})
    rows = _restart_rows(audit)
    assert len(rows) == 1
    assert rows[0]["status"] == "success" and rows[0]["metadata"]["outcome"] == "restarted"
    assert rows[0]["target"] == f"instance:{inst.id}"


# A restart that outlives the wait answers in_progress; its failure arrives later and must still reach the audit log.
def test_the_final_outcome_is_audited_when_the_background_task_ends(monkeypatch, audit):
    results = {"ok": False, "status": "failed", "error": "phantom-updater timed out"}

    async def slow_fail(*args, **kwargs):
        await asyncio.sleep(0.05)
        return results

    monkeypatch.setattr(instances_api, "_updater_restart", slow_fail)
    monkeypatch.setattr(instances_api, "RESTART_WAIT_S", 0.01)

    async def run():
        answer = await instances_api._restart_and_wait("http-sender", "Lab_Sender", "iid-9", None)
        assert answer == {"ok": True, "status": "in_progress"}
        assert _restart_rows(audit) == []
        await asyncio.sleep(0.2)

    asyncio.run(run())
    rows = _restart_rows(audit)
    assert len(rows) == 1
    assert rows[0]["status"] == "failure"
    assert rows[0]["metadata"]["outcome"] == "failed"
    assert rows[0]["metadata"]["error"] == "phantom-updater timed out"
    assert rows[0]["metadata"]["instance_id"] == "iid-9"


# ── the updater call itself ──────────────────────────────────────────────────

_REAL_CLIENT = httpx.AsyncClient


def _updater_world(monkeypatch, handler):
    monkeypatch.setenv("PHANTOM_UPDATER_URL", "http://updater.example:8090/")
    monkeypatch.setenv("MCP_TOKEN", "tok")
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: _REAL_CLIENT(transport=httpx.MockTransport(handler), **kw))


def test_the_updater_call_uses_the_restart_endpoint_with_the_bearer_token(monkeypatch):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"status": "started"})

    _updater_world(monkeypatch, handler)
    out = asyncio.run(instances_api._updater_restart("http-sender", "Lab_Sender", "iid-1", "ghcr.io/example/x:1"))
    assert out == {"ok": True, "status": "restarted"}
    req = seen[0]
    assert req.method == "POST"
    assert str(req.url) == "http://updater.example:8090/api/v1/connectors/http-sender/instances/Lab_Sender/restart"
    assert req.headers["authorization"] == "Bearer tok"
    import json
    assert json.loads(req.content) == {"instance_id": "iid-1", "image_ref": "ghcr.io/example/x:1"}


def test_the_updater_call_reports_an_http_error_and_an_unreachable_updater(monkeypatch):
    _updater_world(monkeypatch, lambda r: httpx.Response(502, json={"detail": "image pull failed"}))
    out = asyncio.run(instances_api._updater_restart("http-sender", "Lab_Sender", "iid-1"))
    assert out["ok"] is False and "502" in out["error"] and "image pull failed" in out["error"]

    def boom(request):
        raise httpx.ConnectError("refused")

    _updater_world(monkeypatch, boom)
    out = asyncio.run(instances_api._updater_restart("http-sender", "Lab_Sender", "iid-1"))
    assert out == {"ok": False, "status": "failed", "error": "phantom-updater could not be reached"}

    def slow(request):
        raise httpx.ReadTimeout("slow")

    _updater_world(monkeypatch, slow)
    out = asyncio.run(instances_api._updater_restart("http-sender", "Lab_Sender", "iid-1"))
    assert out["error"] == "phantom-updater timed out"
