"""HTTP surface the /organization page uses: list, add, switch, edit, fork, export, history."""
from __future__ import annotations

from pathlib import Path

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from api.organizations import register_organization_routes
from config.config import config as _config
from usecase import organization_model as om
from usecase.organization_store import SqliteOrganizationStore

from tests.organization_fixtures import _small_org

BUNDLE = Path(__file__).resolve().parents[2]


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
    monkeypatch.setenv("BUNDLE_ROOT", str(BUNDLE))
    om.load_schema.cache_clear()
    monkeypatch.setattr(_config, "mcp_token", "test-token")
    store = SqliteOrganizationStore(data_root=tmp_path)
    mcp = _FakeMcp()
    register_organization_routes(mcp, store)
    app = Starlette()
    # fixed paths before {org_id} ones, as the registration order does in the real server
    for (path, method), fn in sorted(mcp.routes.items(), key=lambda kv: "{" in kv[0][0]):
        app.add_route(path, fn, methods=[method])
    return store, TestClient(app, headers={"Authorization": "Bearer test-token"})


def test_requires_bearer(world):
    _, api = world
    r = TestClient(api.app).get("/api/v1/organizations")
    assert r.status_code in (401, 403)


def test_list_and_active(world):
    _, api = world
    body = api.get("/api/v1/organizations").json()
    assert body["active_id"] == "phantom-lab" and body["organizations"][0]["people"] == 50
    active = api.get("/api/v1/organizations/active").json()
    assert active["id"] == "phantom-lab" and active["document"]["domain"]["dns"] == "phantom.lab"


def test_add_from_text_then_switch_and_switch_back(world):
    _, api = world
    r = api.post("/api/v1/organizations", json={"text": om.to_yaml(_small_org()), "format": "yaml"})
    assert r.status_code == 201 and r.json()["id"] == "acme"
    assert api.post("/api/v1/organizations/acme/activate").json()["active"] is True
    assert api.get("/api/v1/organizations/active").json()["id"] == "acme"
    api.post("/api/v1/organizations/phantom-lab/activate")
    ids = {o["id"] for o in api.get("/api/v1/organizations").json()["organizations"]}
    assert ids == {"phantom-lab", "acme"}  # switching removes nothing


def test_add_duplicate_is_409_and_invalid_is_400(world):
    _, api = world
    api.post("/api/v1/organizations", json={"document": _small_org()})
    assert api.post("/api/v1/organizations", json={"document": _small_org()}).status_code == 409
    bad = _small_org("bad")
    bad["hosts"][0]["ip"] = "10.99.9.9"
    r = api.post("/api/v1/organizations", json={"document": bad})
    assert r.status_code == 400 and r.json()["errors"]
    assert api.post("/api/v1/organizations", json={}).status_code == 400


def test_validate_endpoint(world):
    _, api = world
    ok = api.post("/api/v1/organizations/validate", json={"document": _small_org()}).json()
    assert ok["valid"] is True
    bad = _small_org()
    bad["people"][0]["manager"] = "ghost"
    out = api.post("/api/v1/organizations/validate", json={"document": bad}).json()
    assert out["valid"] is False and any("manager" in e for e in out["errors"])
    assert api.post("/api/v1/organizations/validate", json={"text": "- not an object"}).json()["valid"] is False


def test_bundled_put_is_refused_and_fork_then_edit_works(world):
    _, api = world
    doc = api.get("/api/v1/organizations/phantom-lab").json()["document"]
    r = api.put("/api/v1/organizations/phantom-lab", json={"document": doc})
    assert r.status_code == 409 and r.json()["code"] == "bundled_read_only"
    fork = api.post("/api/v1/organizations/phantom-lab/fork", json={}).json()
    assert fork["id"] == "phantom-lab-custom"
    fork["document"]["description"] = "edited"
    r = api.put(f"/api/v1/organizations/{fork['id']}", json={"document": fork["document"], "note": "n"})
    assert r.status_code == 200 and r.json()["version"] == 2


def test_changes_endpoint_forks_the_bundled_org_and_reports_notes(world):
    _, api = world
    r = api.post("/api/v1/organizations/phantom-lab/changes", json={"changes": {"upsert": {"people": [
        {"given_name": "Amira", "family_name": "Alfarsi", "title": "Analyst", "department": "Finance"}]}}})
    body = r.json()
    assert r.status_code == 200 and body["forked_from"] == "phantom-lab" and body["id"] == "phantom-lab-custom"
    assert body["people"] == 51 and any("PHWS-051" in n for n in body["notes"])
    assert api.get("/api/v1/organizations/active").json()["id"] == "phantom-lab-custom"
    assert api.post("/api/v1/organizations/phantom-lab/changes", json={"changes": {"remove": {"people": ["ghost"]}}}
                    ).status_code == 400


def test_delete_rules(world):
    _, api = world
    api.post("/api/v1/organizations", json={"document": _small_org(), "activate": True})
    assert api.delete("/api/v1/organizations/acme").status_code == 409
    assert api.delete("/api/v1/organizations/phantom-lab").status_code == 409
    api.post("/api/v1/organizations/phantom-lab/activate")
    assert api.delete("/api/v1/organizations/acme").status_code == 200
    assert api.get("/api/v1/organizations/acme").status_code == 404


def test_export_section_and_cortex_setup(world):
    _, api = world
    ex = api.get("/api/v1/organizations/phantom-lab/export").json()
    assert ex["format"] == "yaml" and "phantom.lab" in ex["text"]
    assert api.get("/api/v1/organizations/phantom-lab/export?format=json").json()["format"] == "json"
    sec = api.get("/api/v1/organizations/phantom-lab/section", params={"name": "people", "filter": "flag=vip"}).json()
    assert sec["total"] == 2
    assert api.get("/api/v1/organizations/phantom-lab/section?name=nope").status_code == 400
    cx = api.get("/api/v1/organizations/phantom-lab/cortex-setup").json()
    assert "10.20.0.0/16" in cx["internal_ranges"] and cx["domain_suffixes"] == ["phantom.lab"]


def test_history_and_restore(world):
    store, api = world
    api.post("/api/v1/organizations", json={"document": _small_org()})
    doc = api.get("/api/v1/organizations/acme").json()["document"]
    doc["description"] = "v2"
    api.put("/api/v1/organizations/acme", json={"document": doc})
    versions = api.get("/api/v1/organizations/acme/history").json()["versions"]
    assert len(versions) == 1
    r = api.post("/api/v1/organizations/acme/restore", json={"seq": versions[0]["seq"]})
    assert r.status_code == 200 and "description" not in r.json()["document"]
    assert api.post("/api/v1/organizations/acme/restore", json={}).status_code == 400
