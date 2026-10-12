"""The marketplace catalogue carries what an uploaded connector's card needs.

/connectors draws bundle cards from its own curated list, so an uploaded
connector has to bring its image, config schema, secret slots and tool list in
`GET /api/v1/marketplace` (origin 'user' only), and the page's Delete button
relies on `DELETE /api/v1/marketplace/{id}`. Uses a throwaway bundle, data root
and stores, like test_user_connectors.py.
"""
from __future__ import annotations

import pytest
import yaml
from starlette.applications import Starlette
from starlette.testclient import TestClient

from api.marketplace import register_marketplace_routes
from config.config import config as _config
from usecase.instance_store import InstanceStore
from usecase.marketplace_store import MarketplaceStore


def _spec(cid: str, **extra) -> dict:
    spec = {
        "id": cid,
        "version": "0.2.0",
        "description": f"{cid} test connector",
        "displayName": cid.title(),
        "source": {"language": "python", "entrypoint": "src.connector"},
        "runtimeMapping": {"style": "container", "functionPrefix": ""},
        "configSchema": {
            "type": "object",
            "required": ["baseUrl"],
            "properties": {"baseUrl": {"type": "string", "description": "Where it lives."}},
        },
        "secretSlots": [{"name": "apiKey", "description": "Key.", "required": True}],
        "spec": {"tools": [{"name": "echo", "method": "POST /echo", "description": "Echo.", "args": []}]},
    }
    spec.update(extra)
    return spec


@pytest.fixture
def world(tmp_path, monkeypatch):
    bundle = tmp_path / "bundle"
    (bundle / "connectors" / "alpha").mkdir(parents=True)
    (bundle / "connectors" / "alpha" / "connector.yaml").write_text(yaml.safe_dump(_spec("alpha")))
    (bundle / "manifest.yaml").write_text(
        yaml.safe_dump({"toolConnectors": [{"id": "alpha", "path": "./connectors/alpha/"}]})
    )
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("BUNDLE_ROOT", str(bundle))
    monkeypatch.setenv("DATA_ROOT", str(data))
    monkeypatch.setattr(_config, "mcp_token", "test-token")
    return data


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
def api(world):
    mcp = _FakeMcp()
    register_marketplace_routes(mcp, MarketplaceStore(data_root=world), InstanceStore(data_root=world))
    app = Starlette()
    for (path, method), fn in mcp.routes.items():
        app.add_route(path, fn, methods=[method])
    return TestClient(app, headers={"Authorization": "Bearer test-token"})


def _upload(world, cid: str, spec: dict | None = None) -> None:
    target = world / "user_connectors" / cid
    target.mkdir(parents=True)
    (target / "connector.yaml").write_text(yaml.safe_dump(spec or _spec(cid, image="ghcr.io/example/beta:1.0")))


def _rows(api):
    return {r["id"]: r for r in api.get("/api/v1/marketplace").json()["connectors"]}


def test_user_entry_carries_detail_and_bundle_entry_does_not(world, api):
    _upload(world, "beta")
    rows = _rows(api)
    assert "detail" not in rows["alpha"] and rows["alpha"]["origin"] == "bundle"
    detail = rows["beta"]["detail"]
    assert rows["beta"]["origin"] == "user"
    assert detail["image"] == "ghcr.io/example/beta:1.0"
    assert detail["language"] == "python"
    assert detail["config_schema"]["required"] == ["baseUrl"]
    assert [s["name"] for s in detail["secret_slots"]] == ["apiKey"]
    assert [t["name"] for t in detail["tools"]] == ["echo"]


def test_malformed_detail_fields_degrade_to_empty(world, api):
    _upload(world, "beta", _spec("beta", image=7, configSchema="x", secretSlots="y", spec={"tools": "z"}))
    detail = _rows(api)["beta"]["detail"]
    assert detail == {"image": "", "language": "python", "config_schema": {}, "secret_slots": [], "tools": []}


def test_delete_removes_an_uploaded_connector_and_refuses_a_bundle_one(world, api):
    _upload(world, "beta")
    assert api.delete("/api/v1/marketplace/alpha").status_code == 403
    assert api.delete("/api/v1/marketplace/beta").status_code == 200
    assert "beta" not in _rows(api)
    assert not (world / "user_connectors" / "beta").exists()
    assert api.delete("/api/v1/marketplace/beta").status_code == 404


def test_delete_is_refused_while_an_instance_exists(world, api):
    _upload(world, "beta")
    InstanceStore(data_root=world).create("beta", "beta-inst", {"baseUrl": "http://x"}, {})
    r = api.delete("/api/v1/marketplace/beta")
    assert r.status_code == 409 and r.json()["code"] == "has_instances"
    assert "beta" in _rows(api)


# ── upload: ids that are fixed UI route names ───────────────────────────

def _post_upload(api, spec: dict):
    body = yaml.safe_dump(spec)
    return api.post(
        "/api/v1/marketplace/upload",
        files={"connector_yaml": ("connector.yaml", body, "application/x-yaml")},
    )


@pytest.mark.parametrize("cid", ["install", "installed", "upload"])
def test_upload_refuses_an_id_that_is_a_fixed_route_name(world, api, cid):
    r = _post_upload(api, _spec(cid, image="ghcr.io/example/x:1.0"))
    assert r.status_code == 400
    assert r.json()["code"] == "id_reserved"
    assert cid in r.json()["error"] and "reserved" in r.json()["error"]
    assert not (world / "user_connectors" / cid).exists()
    assert cid not in _rows(api)


def test_upload_still_accepts_an_ordinary_id_and_it_can_be_deleted(world, api):
    r = _post_upload(api, _spec("beta", image="ghcr.io/example/beta:1.0"))
    assert r.status_code == 201
    assert api.delete("/api/v1/marketplace/beta").status_code == 200


def test_reserved_ids_match_the_fixed_ui_marketplace_routes():
    """Every fixed route directly under app/api/agent/marketplace/ shadows the
    dynamic [connectorId] route, so its name must be a reserved upload id."""
    from pathlib import Path

    from api.marketplace import _RESERVED_CONNECTOR_IDS

    root = Path(__file__).resolve().parents[4] / "mcp" / "agent" / "app" / "api" / "agent" / "marketplace"
    if not root.is_dir():
        pytest.skip("the agent UI tree is not part of this checkout")
    fixed = {
        d.name for d in root.iterdir()
        if d.is_dir() and not d.name.startswith("[") and (d / "route.ts").is_file()
    }
    assert fixed == set(_RESERVED_CONNECTOR_IDS)
