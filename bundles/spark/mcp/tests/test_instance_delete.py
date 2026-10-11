"""DELETE /api/v1/instances/{id} must say what happened to the connector container.

Ignoring a failed phantom-updater stop and answering {"deleted": true} would leave an
uploaded connector's container (the updater answers 400) running with nothing in the
response or the UI to say so. The response reports the container outcome instead.
"""
from __future__ import annotations

import httpx
import pytest
import yaml
from starlette.applications import Starlette
from starlette.testclient import TestClient

from api.instances import register_instance_routes
from config.config import config as _config
from usecase.instance_store import InstanceStore


class _FakeMcp:
    def __init__(self):
        self.routes = {}

    def custom_route(self, path, methods=None, include_in_schema=True):
        def deco(fn):
            for m in methods or ["GET"]:
                self.routes[(path, m)] = fn
            return fn

        return deco


def _spec(cid: str, style: str) -> dict:
    return {
        "id": cid, "version": "0.1.0", "description": f"{cid} test connector",
        "source": {"language": "python", "entrypoint": "src.connector"},
        "runtimeMapping": {"style": style, "functionPrefix": ""},
        "configSchema": {"type": "object"}, "secretSlots": [],
        "spec": {"tools": []},
    }


class FakeUpdater:
    """Stands in for httpx.AsyncClient. `outcome` is a (status, json) pair or an Exception."""
    outcome: object = (200, {"status": "stopped"})
    calls: list = []

    def __init__(self, *a, **kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, headers=None, json=None):
        FakeUpdater.calls.append(url)
        if isinstance(FakeUpdater.outcome, Exception):
            raise FakeUpdater.outcome
        status, body = FakeUpdater.outcome
        return httpx.Response(status, json=body, request=httpx.Request("POST", url))


@pytest.fixture
def world(tmp_path, monkeypatch):
    bundle, data = tmp_path / "bundle", tmp_path / "data"
    for cid, style in (("sender", "container"), ("inproc", "module")):
        (bundle / "connectors" / cid).mkdir(parents=True)
        (bundle / "connectors" / cid / "connector.yaml").write_text(yaml.safe_dump(_spec(cid, style)))
    data.mkdir()
    monkeypatch.setenv("BUNDLE_ROOT", str(bundle))
    monkeypatch.setenv("DATA_ROOT", str(data))
    monkeypatch.setattr(_config, "mcp_token", "test-token")
    monkeypatch.setattr(httpx, "AsyncClient", FakeUpdater)
    FakeUpdater.calls, FakeUpdater.outcome = [], (200, {"status": "stopped"})

    store = InstanceStore(data_root=data)
    mcp = _FakeMcp()
    register_instance_routes(mcp, store)
    app = Starlette()
    for (path, method), fn in mcp.routes.items():
        app.add_route(path, fn, methods=[method])
    return store, TestClient(app, headers={"Authorization": "Bearer test-token"})


def delete(world, connector_id="sender"):
    store, client = world
    inst = store.create(connector_id, "ds-1", {}, {})
    return inst, client.delete(f"/api/v1/instances/{inst.id}")


def test_delete_reports_a_stopped_container(world):
    inst, r = delete(world)
    assert r.status_code == 200
    assert r.json()["container_stop"] == "stopped" and r.json()["deleted"] is True
    assert world[0].get(inst.id) is None
    assert FakeUpdater.calls == ["http://phantom-updater:8090/api/v1/connectors/sender/instances/ds-1/stop"]


def test_delete_reports_when_nothing_was_running(world):
    FakeUpdater.outcome = (200, {"status": "not_running"})
    _, r = delete(world)
    assert r.json()["container_stop"] == "not_running"


def test_delete_reports_a_failed_stop_but_still_deletes_the_row(world, caplog):
    FakeUpdater.outcome = (400, {"detail": "refused"})
    inst, r = delete(world)
    assert r.status_code == 200 and r.json()["deleted"] is True
    assert r.json()["container_stop"] == "failed", "a failed stop must not be reported as success"
    assert world[0].get(inst.id) is None
    assert "could not be stopped" in caplog.text


def test_delete_reports_an_unreachable_updater_as_failed(world):
    FakeUpdater.outcome = httpx.ConnectError("updater down")
    _, r = delete(world)
    assert r.json()["container_stop"] == "failed"


def test_delete_of_a_connector_without_a_container_does_not_call_the_updater(world):
    _, r = delete(world, "inproc")
    assert r.status_code == 200 and r.json()["container_stop"] is None
    assert FakeUpdater.calls == []
