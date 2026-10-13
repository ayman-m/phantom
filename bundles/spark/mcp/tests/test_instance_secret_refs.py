"""A connector-instance secret that is a path to another secret is refused.

A value starting with "/" was stored verbatim as a SecretStore reference and later
resolved to plaintext, so a typed secret of /ui/auth/admin/password_hash would be handed
to the connector (and sent wherever its config points) as that credential. The store
accepts a "/" value only when it is exactly this instance's own path for that slot, and
the API answers 400 for anything else (POST and PATCH). The same rule as providers.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
import yaml
from starlette.applications import Starlette
from starlette.testclient import TestClient

from api.instances import _instance_to_dict, register_instance_routes
from config.config import config as _config
from usecase.instance_store import InstanceStore
from usecase.secret_store import ForeignSecretRefError, SecretStore, connector_secret_path

_FOREIGN = "/ui/auth/admin/password_hash"


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
    bundle, data = tmp_path / "bundle", tmp_path / "data"
    (bundle / "connectors" / "demo").mkdir(parents=True)
    (bundle / "connectors" / "demo" / "connector.yaml").write_text(yaml.safe_dump({
        "id": "demo", "version": "0.1.0", "description": "demo connector",
        "source": {"language": "python", "entrypoint": "src.connector"},
        "runtimeMapping": {"style": "module", "functionPrefix": ""},
        "configSchema": {"type": "object"}, "secretSlots": [],
        "spec": {"tools": []},
    }))
    data.mkdir()
    monkeypatch.setenv("BUNDLE_ROOT", str(bundle))
    monkeypatch.setenv("DATA_ROOT", str(data))
    monkeypatch.setenv("PHANTOM_SECRET_KEK_ALLOW_PLAINTEXT", "1")
    monkeypatch.setattr(_config, "mcp_token", "test-token")
    secrets = SecretStore(data_root=data)
    secrets.write(_FOREIGN, "the-admin-hash")
    store = InstanceStore(data_root=data, secret_store=secrets)
    mcp = _FakeMcp()
    register_instance_routes(mcp, store)
    app = Starlette()
    for (path, method), fn in mcp.routes.items():
        app.add_route(path, fn, methods=[method])

    class World:
        pass

    w = World()
    w.store, w.secrets = store, secrets
    w.client = TestClient(app, headers={"Authorization": "Bearer test-token"})
    return w


def _post(world, secrets, name="one"):
    return world.client.post(
        "/api/v1/instances",
        json={"connector_id": "demo", "name": name, "config": {}, "secrets": secrets, "disabled_tools": []},
    )


def _resolved(world, inst_id):
    return _instance_to_dict(
        world.store.get(inst_id), redact_secrets=False, secret_store=world.secrets
    )["secrets"]


def test_post_refuses_a_secret_that_is_a_path_reference(world):
    r = _post(world, {"api_key": _FOREIGN})
    assert r.status_code == 400
    assert "path reference" in r.json()["error"]
    assert world.store.list_all() == []


def test_post_refuses_a_path_under_any_slot_and_a_slot_with_a_slash(world):
    assert _post(world, {"anything": "/agents/phantom/providers/x/api_key"}).status_code == 400
    assert _post(world, {"../../ui/auth/admin/password_hash": "v"}).status_code == 400
    assert world.store.list_all() == []


def test_post_still_stores_a_plain_secret_under_its_own_path(world):
    r = _post(world, {"api_key": "real-key"})
    assert r.status_code == 201
    iid = r.json()["instance"]["id"]
    assert world.store.get(iid).secret_refs == {"api_key": connector_secret_path(iid, "api_key")}
    assert _resolved(world, iid)["api_key"] == "real-key"


def test_patch_refuses_a_foreign_path_and_leaves_the_instance_untouched(world):
    iid = _post(world, {"api_key": "real-key"}).json()["instance"]["id"]
    r = world.client.patch(
        f"/api/v1/instances/{iid}",
        json={"config": {"base_url": "https://attacker.example.com"}, "secrets": {"api_key": _FOREIGN}},
    )
    assert r.status_code == 400
    assert "path reference" in r.json()["error"]
    assert world.store.get(iid).config == {}, "a refused write must not change the config either"
    assert _resolved(world, iid)["api_key"] == "real-key"


def test_patch_refuses_another_instances_path_and_the_wrong_slot(world):
    a = _post(world, {"api_key": "key-a"}, "a").json()["instance"]["id"]
    # one active instance per connector: create b disabled
    bid = world.store.create("demo", "b", {}, {"api_key": "key-b"}, enabled=False).id
    assert world.client.patch(f"/api/v1/instances/{bid}", json={"secrets": {"api_key": connector_secret_path(a, "api_key")}}).status_code == 400
    assert world.client.patch(f"/api/v1/instances/{bid}", json={"secrets": {"other": connector_secret_path(bid, "api_key")}}).status_code == 400


def test_patch_accepts_the_slots_own_path_the_sentinel_and_a_new_value(world):
    iid = _post(world, {"api_key": "key-1"}).json()["instance"]["id"]
    own = connector_secret_path(iid, "api_key")
    assert world.client.patch(f"/api/v1/instances/{iid}", json={"secrets": {"api_key": own}}).status_code == 200
    assert world.client.patch(f"/api/v1/instances/{iid}", json={"secrets": {"api_key": "***"}}).status_code == 200
    assert world.client.patch(f"/api/v1/instances/{iid}", json={"secrets": {"api_key": "key-2"}}).status_code == 200
    assert _resolved(world, iid)["api_key"] == "key-2"


def test_the_store_itself_refuses_a_path_reference(world):
    with pytest.raises(ForeignSecretRefError):
        world.store.create("demo", "x", {}, {"api_key": _FOREIGN})
    iid = _post(world, {"api_key": "k"}).json()["instance"]["id"]
    with pytest.raises(ForeignSecretRefError):
        world.store.update(iid, secrets={"api_key": _FOREIGN})


def test_the_store_refuses_a_path_reference_without_a_secret_store(tmp_path):
    store = InstanceStore(data_root=tmp_path)
    with pytest.raises(ForeignSecretRefError):
        store.create("demo", "x", {}, {"api_key": _FOREIGN})


def test_a_row_stored_with_a_foreign_reference_is_never_resolved(world):
    """Rows written before the check existed must not leak the target secret."""
    iid = _post(world, {"api_key": "k"}).json()["instance"]["id"]
    with world.store._conn() as c:
        c.execute("UPDATE instances SET secrets_json = ? WHERE id = ?", (json.dumps({"api_key": _FOREIGN}), iid))
    stored = world.store.get(iid)
    assert stored.merged_config(world.secrets)["api_key"] == ""
    assert stored.resolved_secrets(world.secrets)["api_key"] == ""
    assert _resolved(world, iid)["api_key"] == ""


def test_the_connector_runtime_reader_applies_the_same_rule(world):
    """The per-instance container reads instances.db itself; its rule must match."""
    path = Path(__file__).resolve().parents[4] / "phantom-connector-runtime" / "runtime" / "instance_store_client.py"
    spec = importlib.util.spec_from_file_location("runtime_instance_store_client", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)

    class Reader:
        def read(self, p):
            return world.secrets.read(p)

    iid = _post(world, {"api_key": "real-key"}).json()["instance"]["id"]
    # The runtime's own-path rule must be the same path the store writes.
    row = mod.InstanceRow(
        id=iid, connector_id="demo", name="one", config={}, created_at="", enabled=True,
        secret_refs={"api_key": connector_secret_path(iid, "api_key")},
    )
    assert mod.InstanceStoreReader.resolve_merged_config(None, row, Reader())["api_key"] == "real-key"
    foreign = mod.InstanceRow(
        id=iid, connector_id="demo", name="one", config={}, created_at="", enabled=True,
        secret_refs={"api_key": _FOREIGN},
    )
    assert mod.InstanceStoreReader.resolve_merged_config(None, foreign, Reader())["api_key"] == ""
