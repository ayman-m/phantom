"""providers_list / providers_get show the agent no provider setting it does not need.

Vertex's project id and region are values (the agent answers "is Vertex
configured?" from them). Everything else a provider stores (an OpenAI
organization or project id, a gateway base URL) is reported only as set or not,
because the agent has no use for the value and an id or an internal gateway host
should not land in a chat transcript. Keys never appear in either tool.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from usecase.builtin_components.self_mod_tools import providers_get, providers_list
from usecase.provider_store import ProviderStore, set_provider_store
from usecase.secret_store import SecretStore

ORG = "org-AcmeSecretOrg123"
PROJ = "proj_AcmeSecretProj456"
GATEWAY = "https://llm-gateway.corp.internal.example/v1"
KEY = "sk-live-NOT-A-REAL-KEY-0123456789"


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("PHANTOM_SECRET_KEK_ALLOW_PLAINTEXT", "1")
    s = ProviderStore(data_root=tmp_path, secret_store=SecretStore(data_root=tmp_path))
    set_provider_store(s)
    yield s
    set_provider_store(None)


def _seed(store):
    openai = store.create(
        "openai", "primary-openai",
        {"organization": ORG, "project": PROJ, "base_url": GATEWAY}, {"api_key": KEY},
    )
    bare = store.create("anthropic", "primary-anthropic", {"base_url": ""}, {"api_key": KEY})
    vertex = store.create(
        "vertex", "primary-vertex", {"project_id": "lab-project", "region": "us-central1"},
        {"serviceAccountJson": '{"type": "service_account"}'},
    )
    return openai, bare, vertex


def test_list_reports_only_whether_openai_settings_are_set(store):
    _seed(store)
    rows = {r["provider_id"]: r for r in providers_list()["providers"]}
    openai = rows["openai"]
    assert openai["config"] == {}
    assert openai["config_set"] == {"organization": True, "project": True, "base_url": True}
    assert rows["anthropic"]["config_set"] == {"base_url": False}, "an empty value is not set"


def test_vertex_keeps_project_and_region_as_values(store):
    _seed(store)
    vertex = {r["provider_id"]: r for r in providers_list()["providers"]}["vertex"]
    assert vertex["config"] == {"project_id": "lab-project", "region": "us-central1"}
    assert vertex["config_set"] == {}


def test_get_applies_the_same_redaction(store):
    openai, _, vertex = _seed(store)
    got = providers_get(openai.id)["provider"]
    assert got["config"] == {} and got["config_set"]["organization"] is True
    assert providers_get(vertex.id)["provider"]["config"]["project_id"] == "lab-project"


def test_no_setting_value_or_key_reaches_either_tool(store):
    openai, bare, vertex = _seed(store)
    blob = json.dumps(
        [providers_list(), providers_list("openai")] + [providers_get(i.id) for i in (openai, bare, vertex)]
    )
    for secret in (ORG, PROJ, GATEWAY, "llm-gateway.corp.internal", KEY):
        assert secret not in blob, secret


def test_a_setting_a_later_provider_adds_is_hidden_by_default(store):
    inst = store.create("openai", "x", {"new_internal_setting": "internal-value"}, {"api_key": KEY})
    got = providers_get(inst.id)["provider"]
    assert got["config"] == {}
    assert got["config_set"] == {"new_internal_setting": True}
    assert "internal-value" not in json.dumps(got)


def test_the_docstrings_tell_the_agent_what_it_gets(store):
    for fn in (providers_list, providers_get):
        assert "config_set" in (fn.__doc__ or "")
