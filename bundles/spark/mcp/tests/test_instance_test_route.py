"""POST /api/v1/instances/{id}/test: Test Connection for every bundle connector.

The route answers `probe_implemented: true` for all nine bundle connectors, passes the
instance's container_url to the probe, writes connector_state after a persisted test and
does not after a dry run, and says plainly that an uploaded connector has no built-in test.
"""
from __future__ import annotations

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

import api.instances as instances_api
from api.instances import register_instance_routes
from config.config import config as _config
from usecase.connector_probes import PROBE_IMPLEMENTED, ProbeResult
from usecase.connector_state import SqliteConnectorStateStore, set_connector_state_store
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
    state = SqliteConnectorStateStore(data_root=data)
    set_connector_state_store(state)
    store = InstanceStore(data_root=data, secret_store=SecretStore(data_root=data))
    mcp = _FakeMcp()
    register_instance_routes(mcp, store)
    app = Starlette()
    for (path, method), fn in mcp.routes.items():
        app.add_route(path, fn, methods=[method])

    calls = []
    outcome = {"result": ProbeResult(True, None, False, "it works")}

    async def fake_probe(connector_id, **kwargs):
        calls.append((connector_id, kwargs))
        return outcome["result"]

    monkeypatch.setattr(instances_api, "run_probe", fake_probe)

    class World:
        pass

    w = World()
    w.store, w.state, w.calls, w.outcome = store, state, calls, outcome
    w.client = TestClient(app, headers={"Authorization": "Bearer test-token"})
    yield w
    set_connector_state_store(None)


def _instance(world, connector_id, name="one", container_url="http://phantom-connector-x:9000"):
    inst = world.store.create(connector_id, name, {"k": "v"}, {})
    if container_url:
        world.store.set_container_url(inst.id, container_url)
    return inst


@pytest.mark.parametrize("connector_id", sorted(PROBE_IMPLEMENTED))
def test_every_bundle_connector_reports_probe_implemented_and_writes_state(world, connector_id):
    inst = _instance(world, connector_id)
    assert world.state.get(connector_id) is None

    body = world.client.post(f"/api/v1/instances/{inst.id}/test").json()

    assert body["probe_implemented"] is True
    assert body["ok"] is True and body["message"] == "it works" and body["dry_run"] is False
    assert body["connector_state"]["state"] == "connected"
    assert world.state.get(connector_id).state == "connected"
    cid, kwargs = world.calls[0]
    assert cid == connector_id
    assert kwargs["container_url"] == "http://phantom-connector-x:9000" and kwargs["check_container"] is True
    assert kwargs["config"] == {"k": "v"}


def test_a_failed_probe_writes_failed_and_an_auth_failure_writes_needs_auth(world):
    inst = _instance(world, "xsiam")
    world.outcome["result"] = ProbeResult(False, "HTTP 500 from x", False)
    body = world.client.post(f"/api/v1/instances/{inst.id}/test").json()
    assert body["ok"] is False and body["error"] == "HTTP 500 from x"
    assert world.state.get("xsiam").state == "failed"

    world.outcome["result"] = ProbeResult(False, "HTTP 401 from x", True)
    body = world.client.post(f"/api/v1/instances/{inst.id}/test").json()
    assert body["is_auth_error"] is True
    assert world.state.get("xsiam").state == "needs-auth"

    world.outcome["result"] = ProbeResult(True, None, False, "fine")
    world.client.post(f"/api/v1/instances/{inst.id}/test")
    assert world.state.get("xsiam").state == "connected"


def test_a_dry_run_does_not_write_connector_state(world):
    inst = _instance(world, "web")
    body = world.client.post(f"/api/v1/instances/{inst.id}/test", json={"config": {"cdp_url": "http://x:9222"}}).json()
    assert body["dry_run"] is True and body["probe_implemented"] is True
    assert world.state.get("web") is None
    assert world.calls[0][1]["config"] == {"cdp_url": "http://x:9222"}

    body = world.client.post(f"/api/v1/instances/{inst.id}/test", json={"config": {}, "dry_run": False}).json()
    assert body["dry_run"] is False
    assert world.state.get("web").state == "connected"


def test_an_uploaded_connector_has_no_built_in_test_and_nothing_is_written(world):
    inst = _instance(world, "acme-uploaded")
    body = world.client.post(f"/api/v1/instances/{inst.id}/test").json()
    assert body["probe_implemented"] is False
    assert body["message"] == "This connector has no built-in test."
    assert "ok" not in body
    assert world.calls == [] and world.state.get("acme-uploaded") is None


def test_the_instance_row_carries_the_last_probe_error(world):
    inst = _instance(world, "xlog")
    world.outcome["result"] = ProbeResult(False, "cannot connect to x", False)
    world.client.post(f"/api/v1/instances/{inst.id}/test")
    row = world.client.get(f"/api/v1/instances/{inst.id}").json()
    row = row.get("instance", row)
    assert row["state"] == "failed" and row["last_error"] == "cannot connect to x"


def test_an_unknown_instance_is_404(world):
    assert world.client.post("/api/v1/instances/nope/test").status_code == 404
