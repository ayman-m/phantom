"""User-uploaded connectors are first-class.

A connector uploaded through the marketplace lives at
`<DATA_ROOT>/user_connectors/<id>/connector.yaml`. These tests pin that the same
catalog answers "which connectors exist?" for tool registration, the tool summary,
and the connector routes, using a throwaway bundle, data root and instance store.
"""
from __future__ import annotations

import pytest
import yaml
from starlette.applications import Starlette
from starlette.testclient import TestClient

from api.connectors import register_connector_routes
from config.config import config as _config
from usecase import connector_catalog
from usecase.connector_loader import iter_registrations, tool_summary
from usecase.connector_state import SqliteConnectorStateStore
from usecase.instance_store import InstanceStore


def _spec(cid: str, tools: list[str], *, prefix: str = "", style: str = "container") -> dict:
    return {
        "id": cid,
        "version": "0.1.0",
        "description": f"{cid} test connector",
        "source": {"language": "python", "entrypoint": "src.connector"},
        "runtimeMapping": {"style": style, "functionPrefix": prefix},
        "configSchema": {"type": "object"},
        "secretSlots": [],
        "spec": {"tools": [{"name": t, "description": f"{t} tool", "args": []} for t in tools]},
    }


@pytest.fixture
def world(tmp_path, monkeypatch):
    """A bundle with one bundle connector (`alpha`), an empty data root, an instance store."""
    bundle = tmp_path / "bundle"
    (bundle / "connectors" / "alpha").mkdir(parents=True)
    (bundle / "connectors" / "alpha" / "connector.yaml").write_text(
        yaml.safe_dump(_spec("alpha", ["ping"], prefix="alpha_"))
    )
    (bundle / "manifest.yaml").write_text(
        yaml.safe_dump({"toolConnectors": [{"id": "alpha", "path": "./connectors/alpha/"}]})
    )
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("BUNDLE_ROOT", str(bundle))
    monkeypatch.setenv("DATA_ROOT", str(data))
    return {"data": data, "store": InstanceStore(data_root=data)}


def upload(world, cid: str, spec: dict | None = None, *, dirname: str | None = None) -> None:
    """Place a connector.yaml where the marketplace upload route puts it."""
    target = world["data"] / "user_connectors" / (dirname or cid)
    target.mkdir(parents=True)
    (target / "connector.yaml").write_text(yaml.safe_dump(spec or _spec(cid, ["echo", "send"], prefix="phantom_")))


def instance(world, cid: str, **kw):
    return world["store"].create(cid, f"{cid}-inst", {"containerUrl": "http://x:9000"}, {}, **kw)


def registrations(world, **kw):
    regs = list(iter_registrations(store=world["store"], secret_store=object(), **kw))
    return [r for r in regs if r.connector_id is not None]  # drop runtime built-ins


# ── catalog ─────────────────────────────────────────────────────────────

def test_effective_connectors_lists_bundle_then_user(world):
    upload(world, "beta")
    refs = connector_catalog.effective_connectors()
    assert [(r.id, r.origin) for r in refs] == [("alpha", "bundle"), ("beta", "user")]
    assert connector_catalog.find_connector("beta").yaml_path.is_file()
    assert connector_catalog.find_connector("nope") is None


def test_bundle_id_wins_a_collision_and_bad_ids_are_ignored(world):
    upload(world, "alpha", dirname="impostor")  # same id as the bundle connector
    upload(world, "Bad_Id", dirname="weird")  # violates the id rule
    (world["data"] / "user_connectors" / "empty").mkdir()  # no connector.yaml
    assert [(r.id, r.origin) for r in connector_catalog.effective_connectors()] == [("alpha", "bundle")]


# ── tool registration ───────────────────────────────────────────────────

def test_user_connector_with_an_instance_registers_namespaced_tools(world):
    upload(world, "beta")
    instance(world, "beta")
    by_name = {r.namespaced_name: r for r in registrations(world)}
    assert {"beta.echo", "beta.send"} <= by_name.keys()
    assert by_name["beta.echo"].connector_id == "beta"


def test_user_connector_without_an_instance_advertises_nothing(world):
    upload(world, "beta")
    instance(world, "alpha")
    assert {r.connector_id for r in registrations(world)} == {"alpha"}


def test_user_connectors_get_no_legacy_aliases_but_bundle_ones_still_do(world):
    # functionPrefix "phantom_" is what xlog uses: an alias here would shadow built-in tools.
    upload(world, "beta")
    instance(world, "alpha")
    instance(world, "beta")
    by_name = {r.namespaced_name: r for r in registrations(world, include_legacy_aliases=True)}
    assert by_name["beta.echo"].legacy_name is None
    assert by_name["alpha.ping"].legacy_name == "alpha_ping"


def test_operator_disabled_tools_apply_to_user_connectors(world):
    upload(world, "beta")
    instance(world, "beta", disabled_tools=["send"])
    names = {r.namespaced_name for r in registrations(world)}
    assert "beta.echo" in names and "beta.send" not in names


def test_a_broken_upload_is_skipped_without_stopping_other_connectors(world, caplog):
    upload(world, "broken", _spec("broken", ["x"], style="module"))  # only `container` is valid
    upload(world, "beta")
    for cid in ("alpha", "broken", "beta"):
        instance(world, cid)
    names = {r.namespaced_name for r in registrations(world)}
    assert {"alpha.ping", "beta.echo"} <= names
    assert not any(n.startswith("broken.") for n in names)
    assert "broken" in caplog.text


def test_tool_summary_counts_user_connectors_only_when_configured(world):
    upload(world, "beta")
    assert tool_summary(store=world["store"])["beta"] == 0
    instance(world, "beta")
    assert tool_summary(store=world["store"])["beta"] == 2


# ── routes ──────────────────────────────────────────────────────────────

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
def api(world, monkeypatch):
    monkeypatch.setattr(_config, "mcp_token", "test-token")
    mcp = _FakeMcp()
    register_connector_routes(mcp, SqliteConnectorStateStore(data_root=world["data"]), world["store"], None)
    app = Starlette()
    for (path, method), fn in mcp.routes.items():
        app.add_route(path, fn, methods=[method])
    client = TestClient(app, headers={"Authorization": "Bearer test-token"})
    return client


def test_state_list_carries_origin_for_bundle_user_and_orphaned_rows(world, api):
    upload(world, "beta")
    instance(world, "beta")
    SqliteConnectorStateStore(data_root=world["data"]).upsert_pending("ghost")  # a state row nothing declares
    rows = {r["connector_id"]: r for r in api.get("/api/v1/connectors").json()["connectors"]}
    assert (rows["alpha"]["origin"], rows["alpha"]["in_manifest"]) == ("bundle", True)
    assert (rows["beta"]["origin"], rows["beta"]["in_manifest"], rows["beta"]["configured"]) == ("user", False, True)
    assert (rows["ghost"]["origin"], rows["ghost"]["in_manifest"]) == ("orphaned", False)


def test_get_connector_answers_for_a_user_connector_and_404s_for_unknown(world, api):
    upload(world, "beta")
    body = api.get("/api/v1/connectors/beta").json()["connector"]
    assert body["origin"] == "user" and body["state"] == "pending"
    assert api.get("/api/v1/connectors/nope").status_code == 404


def test_tools_panel_lists_user_connector_tools_with_disabled_state(world, api):
    upload(world, "beta")
    inst = instance(world, "beta", disabled_tools=["send"])
    r = api.get(f"/api/v1/connectors/beta/tools?instance_id={inst.id}")
    assert r.status_code == 200
    body = r.json()
    assert [t["name"] for t in body["tools"]] == ["echo", "send"]
    assert body["enabled"] == 1 and body["disabled"] == 1
    assert body["tools"][0]["namespaced"] == "beta.echo"


def test_tools_panel_404_names_both_places_it_looked(world, api):
    r = api.get("/api/v1/connectors/nope/tools")
    assert r.status_code == 404 and "uploaded" in r.json()["error"]
