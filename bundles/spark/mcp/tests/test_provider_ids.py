"""Provider instances are model providers the agent has an adapter for.

`POST /api/v1/providers` accepts `vertex`, `anthropic` and `openai` and refuses
any other `provider_id` (an instance nothing would read). The agent reads a
provider's credentials from the store on every model call, so no provider write
asks for a restart. The Anthropic provider is declared in the bundle as an
optional provider with one config field and one secret, and adding it
registered no new agent tool.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml
from starlette.applications import Starlette
from starlette.testclient import TestClient

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from api.providers import MODEL_PROVIDER_IDS, _instance_to_dict, register_provider_routes
from config.config import config as _config
from usecase.provider_store import ForeignSecretRefError, ProviderStore
from usecase.secret_store import SecretStore, provider_secret_path

_BUNDLE = Path(__file__).resolve().parents[2]
_TOKEN = {"Authorization": "Bearer test-token"}


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
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("PHANTOM_SECRET_KEK_ALLOW_PLAINTEXT", "1")
    monkeypatch.setattr(_config, "mcp_token", "test-token")
    store = ProviderStore(data_root=tmp_path, secret_store=SecretStore(data_root=tmp_path))
    mcp = _FakeMcp()
    register_provider_routes(mcp, store)
    app = Starlette()
    for (path, method), fn in mcp.routes.items():
        app.add_route(path, fn, methods=[method])

    class World:
        pass

    w = World()
    w.store = store
    w.client = TestClient(app, headers=_TOKEN)
    return w


def _body(provider_id, name="primary", config=None, secrets=None):
    return {
        "provider_id": provider_id,
        "name": name,
        "config": config or {},
        "secrets": secrets or {"api_key": "k"},
    }


def test_the_allowed_set_is_the_three_model_providers():
    assert MODEL_PROVIDER_IDS == ("vertex", "anthropic", "openai")


@pytest.mark.parametrize("provider_id", ["anthropic", "openai"])
def test_create_accepts_the_api_key_providers_without_a_restart(world, provider_id):
    r = world.client.post("/api/v1/providers", json=_body(provider_id, config={"base_url": "https://gw.example.com"}))
    assert r.status_code == 201
    assert r.json()["requires_mcp_restart"] is False
    assert r.json()["instance"]["provider_id"] == provider_id
    assert r.json()["instance"]["secrets"] == {"api_key": "***"}, "secrets stay redacted on the wire"


def test_create_accepts_vertex_without_a_restart(world):
    r = world.client.post(
        "/api/v1/providers",
        json=_body("vertex", config={"project_id": "p"}, secrets={"serviceAccountJson": "{}"}),
    )
    assert r.status_code == 201
    assert r.json()["requires_mcp_restart"] is False


@pytest.mark.parametrize("provider_id", ["azure", "Anthropic", "", None, 7])
def test_create_refuses_an_unknown_provider_id(world, provider_id):
    r = world.client.post("/api/v1/providers", json=_body(provider_id))
    assert r.status_code == 400
    assert world.store.list_all() == []
    if provider_id and isinstance(provider_id, str):
        assert "expected one of vertex, anthropic, openai" in r.json()["error"]


def test_update_cannot_change_the_provider_id(world):
    pid = world.client.post("/api/v1/providers", json=_body("anthropic")).json()["instance"]["id"]
    r = world.client.put(f"/api/v1/providers/{pid}", json={"provider_id": "openai"})
    assert r.status_code == 400
    assert world.store.get(pid).provider_id == "anthropic"


def test_update_still_edits_config_and_the_stored_key_survives_the_sentinel(world):
    pid = world.client.post("/api/v1/providers", json=_body("anthropic", secrets={"api_key": "real-key"})).json()["instance"]["id"]
    r = world.client.put(
        f"/api/v1/providers/{pid}",
        json={"config": {"base_url": "https://gw.example.com"}, "secrets": {"api_key": "***"}},
    )
    assert r.status_code == 200
    # The cleartext read is loopback-only over HTTP, so resolve it the way that route does.
    detail = _instance_to_dict(world.store.get(pid), redact_secrets=False, secret_store=world.store._secret_store)
    assert detail["config"] == {"base_url": "https://gw.example.com"}
    assert detail["secrets"]["api_key"] == "real-key"


def test_update_refuses_an_instance_of_an_unknown_provider(world):
    legacy = world.store.create("legacy-provider", "x", {}, {"api_key": "k"})
    r = world.client.put(f"/api/v1/providers/{legacy.id}", json={"config": {"a": 1}})
    assert r.status_code == 400


def test_delete_asks_for_no_restart(world):
    pid = world.client.post("/api/v1/providers", json=_body("openai")).json()["instance"]["id"]
    r = world.client.delete(f"/api/v1/providers/{pid}")
    assert r.status_code == 200
    assert r.json()["requires_mcp_restart"] is False


def test_the_anthropic_provider_declares_config_and_a_secret_only():
    spec = yaml.safe_load((_BUNDLE / "providers" / "anthropic" / "provider.yaml").read_text())
    assert spec["id"] == "anthropic"
    assert set(spec) == {"id", "version", "description", "configSchema", "secretSlots"}
    props = spec["configSchema"]["properties"]
    assert set(props) == {"base_url"}
    assert props["base_url"]["default"] == "https://api.anthropic.com"
    assert "required" not in spec["configSchema"], "the base URL is optional"
    slots = spec["secretSlots"]
    assert [(s["name"], s["required"]) for s in slots] == [("api_key", True)]


def test_the_manifest_declares_anthropic_as_an_optional_provider():
    manifest = yaml.safe_load((_BUNDLE / "manifest.yaml").read_text())
    declared = {p["id"]: p for p in manifest["providers"]}
    # v1.0.5: no provider is required on its own. A Claude-only or OpenAI-only
    # install has no Vertex provider and must not be reported as incomplete.
    assert declared["vertex"]["required"] is False
    assert declared["anthropic"]["required"] is False
    assert declared["anthropic"]["path"] == "./providers/anthropic/"
    assert (_BUNDLE / declared["anthropic"]["path"] / "provider.yaml").is_file()


def test_the_openai_provider_declares_config_and_a_secret_only():
    spec = yaml.safe_load((_BUNDLE / "providers" / "openai" / "provider.yaml").read_text())
    assert spec["id"] == "openai"
    assert set(spec) == {"id", "version", "description", "configSchema", "secretSlots"}
    props = spec["configSchema"]["properties"]
    assert set(props) == {"base_url", "organization", "project"}
    assert props["base_url"]["default"] == "https://api.openai.com/v1"
    assert "required" not in spec["configSchema"], "every config field is optional"
    slots = spec["secretSlots"]
    assert [(s["name"], s["required"]) for s in slots] == [("api_key", True)]


def test_the_manifest_declares_openai_as_an_optional_provider():
    manifest = yaml.safe_load((_BUNDLE / "manifest.yaml").read_text())
    declared = {p["id"]: p for p in manifest["providers"]}
    assert declared["openai"]["required"] is False
    assert declared["openai"]["path"] == "./providers/openai/"
    assert (_BUNDLE / declared["openai"]["path"] / "provider.yaml").is_file()


# ─── Secret values that point at another secret ──────────────────────────────
# A value starting with "/" is stored as a SecretStore path reference and later
# resolved to plaintext. Accepting one from a writer would let a typed API key
# of "/ui/auth/admin/password_hash" be sent to the provider's base URL as the
# bearer token.

_FOREIGN = "/ui/auth/admin/password_hash"


def _seed_foreign_secret(world):
    world.store._secret_store.write(_FOREIGN, "the-admin-hash")


@pytest.mark.parametrize("provider_id,slot", [("anthropic", "api_key"), ("openai", "api_key"), ("vertex", "serviceAccountJson")])
def test_create_refuses_a_secret_that_is_a_path_reference(world, provider_id, slot):
    _seed_foreign_secret(world)
    r = world.client.post("/api/v1/providers", json=_body(provider_id, secrets={slot: _FOREIGN}))
    assert r.status_code == 400
    assert "path reference" in r.json()["error"]
    assert world.store.list_all() == []


def test_update_refuses_a_secret_that_is_a_path_reference(world):
    _seed_foreign_secret(world)
    pid = world.client.post("/api/v1/providers", json=_body("openai", secrets={"api_key": "real-key"})).json()["instance"]["id"]
    r = world.client.put(
        f"/api/v1/providers/{pid}",
        json={"config": {"base_url": "https://attacker.example.com"}, "secrets": {"api_key": _FOREIGN}},
    )
    assert r.status_code == 400
    after = world.store.get(pid)
    assert after.config == {}, "a refused write must not change the config either"
    detail = _instance_to_dict(after, redact_secrets=False, secret_store=world.store._secret_store)
    assert detail["secrets"]["api_key"] == "real-key"


def test_update_refuses_another_instances_secret_path(world):
    a = world.client.post("/api/v1/providers", json=_body("openai", name="a", secrets={"api_key": "key-a"})).json()["instance"]["id"]
    b = world.client.post("/api/v1/providers", json=_body("openai", name="b", secrets={"api_key": "key-b"})).json()["instance"]["id"]
    other = provider_secret_path(a, "api_key")
    assert world.client.put(f"/api/v1/providers/{b}", json={"secrets": {"api_key": other}}).status_code == 400
    # The same instance's own path under a different slot is not its slot's path.
    assert world.client.put(f"/api/v1/providers/{b}", json={"secrets": {"other_slot": provider_secret_path(b, "api_key")}}).status_code == 400


def test_update_accepts_the_slots_own_path_and_a_plain_key(world):
    pid = world.client.post("/api/v1/providers", json=_body("openai", secrets={"api_key": "key-1"})).json()["instance"]["id"]
    own = provider_secret_path(pid, "api_key")
    assert world.client.put(f"/api/v1/providers/{pid}", json={"secrets": {"api_key": own}}).status_code == 200
    assert world.client.put(f"/api/v1/providers/{pid}", json={"secrets": {"api_key": "key-2"}}).status_code == 200
    detail = _instance_to_dict(world.store.get(pid), redact_secrets=False, secret_store=world.store._secret_store)
    assert detail["secrets"]["api_key"] == "key-2"


def test_the_store_itself_refuses_a_path_reference_and_a_slot_with_a_slash(world):
    _seed_foreign_secret(world)
    with pytest.raises(ForeignSecretRefError):
        world.store.create("openai", "x", {}, {"api_key": _FOREIGN})
    with pytest.raises(ForeignSecretRefError):
        world.store.create("openai", "x", {}, {"../../ui/auth/admin/password_hash": "v"})
    pid = world.client.post("/api/v1/providers", json=_body("openai", secrets={"api_key": "k"})).json()["instance"]["id"]
    with pytest.raises(ForeignSecretRefError):
        world.store.update(pid, secrets={"api_key": _FOREIGN})


def test_a_row_stored_with_a_foreign_reference_is_never_resolved(world):
    """Rows written before the check existed must not leak the target secret."""
    _seed_foreign_secret(world)
    inst = world.store.create("openai", "legacy", {}, {"api_key": "k"})
    # Simulate the old behaviour: point the stored ref at another secret.
    import json as _json
    with world.store._conn() as c:
        c.execute("UPDATE provider_instances SET secrets_json = ? WHERE id = ?", (_json.dumps({"api_key": _FOREIGN}), inst.id))
    stored = world.store.get(inst.id)
    detail = _instance_to_dict(stored, redact_secrets=False, secret_store=world.store._secret_store)
    assert detail["secrets"]["api_key"] == ""
    assert stored.merged_config(world.store._secret_store)["api_key"] == ""
