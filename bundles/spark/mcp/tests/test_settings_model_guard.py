"""A per-session model preference never mutates a global setting.

`/model <name>` stores a preference on the chat session. The global default
model (`defaultModel`, a canonical "provider/model" ref) is operator-only: the agent's `settings_update` and
`settings_reset` tools refuse it, while the REST surface keeps working and the
other settings stay writable by the agent.

Regression: on a v1.0.2 install the agent answered "What model are you?" by
calling `settings_update` and wrote `defaultModel` (audit `settings_changed`,
updated_by `agent`). The key was `geminiModel` then; it is `defaultModel` now and
the agent is refused the same way.
"""
from __future__ import annotations

import asyncio

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from usecase import settings_store as settings_module
from usecase.builtin_components import self_mod_tools
from usecase.settings_store import (
    SqliteSettingsStore,
    is_agent_protected_setting,
    set_settings_store,
)

DEFAULTS = {
    "defaultModel": "vertex/gemini-3.1-pro-preview",
    "defaultLogFormat": "JSON",
    "coverageReportFormat": "json",
}


@pytest.fixture
def store(tmp_path):
    s = SqliteSettingsStore(
        defaults=DEFAULTS, overridable=list(DEFAULTS), data_root=tmp_path,
    )
    set_settings_store(s)
    yield s
    set_settings_store(None)


def _run(coro):
    return asyncio.run(coro)


# ─── predicate ───────────────────────────────────────────────────


@pytest.mark.parametrize("key", ["defaultModel", "fallbackModel", "defaultmodel", "geminiModel"])
def test_model_selection_keys_are_protected(key):
    assert is_agent_protected_setting(key)


@pytest.mark.parametrize(
    "key", ["defaultLogFormat", "coverageReportFormat", "setupUiUser", "", None, 3],
)
def test_other_keys_are_not_protected(key):
    assert not is_agent_protected_setting(key)


def test_manifest_model_key_is_protected():
    """Every manifest-overridable model key stays covered if the manifest grows."""
    import yaml
    from pathlib import Path

    manifest = yaml.safe_load(
        (Path(__file__).resolve().parents[2] / "manifest.yaml").read_text(encoding="utf-8")
    )
    overridable = manifest["settings"]["overridable"]
    assert "defaultModel" in overridable
    for key in overridable:
        if "model" in key.lower():
            assert is_agent_protected_setting(key), key


# ─── settings_update ─────────────────────────────────────────────


def test_agent_cannot_set_default_model(store):
    out = _run(self_mod_tools.settings_update({"defaultModel": "vertex/gemini-2.5-pro"}))
    assert out["applied"] == []
    assert [r["key"] for r in out["rejected"]] == ["defaultModel"]
    assert "operator-only" in out["rejected"][0]["reason"]
    assert store.get("defaultModel") == DEFAULTS["defaultModel"]
    assert not store.is_overridden("defaultModel")


def test_agent_cannot_clear_default_model_override(store):
    store.set("defaultModel", "vertex/gemini-2.5-flash", actor="operator")
    out = _run(self_mod_tools.settings_update(clear=["defaultModel"]))
    assert out["cleared"] == []
    assert [r["key"] for r in out["rejected"]] == ["defaultModel"]
    assert store.get("defaultModel") == "vertex/gemini-2.5-flash"


def test_mixed_call_applies_the_other_keys_and_rejects_the_model_key(store):
    out = _run(self_mod_tools.settings_update(
        {"defaultModel": "vertex/gemini-2.5-pro", "defaultLogFormat": "CEF"},
    ))
    assert out["applied"] == ["defaultLogFormat"]
    assert [r["key"] for r in out["rejected"]] == ["defaultModel"]
    assert store.get("defaultLogFormat") == "CEF"
    assert store.get("defaultModel") == DEFAULTS["defaultModel"]


def test_other_settings_still_work_for_the_agent(store):
    out = _run(self_mod_tools.settings_update({"coverageReportFormat": "markdown"}))
    assert out["applied"] == ["coverageReportFormat"]
    assert out["rejected"] == []
    assert store.get("coverageReportFormat") == "markdown"
    assert store.overrides()[0].updated_by == "agent"
    out = _run(self_mod_tools.settings_update(clear=["coverageReportFormat"]))
    assert out["cleared"] == ["coverageReportFormat"]


def test_refused_call_leaves_no_override_row(store):
    _run(self_mod_tools.settings_update({"defaultModel": "vertex/gemini-2.5-pro"}))
    assert store.overrides() == []


# ─── settings_reset ──────────────────────────────────────────────


def test_reset_all_leaves_the_model_override_alone(store):
    store.set("defaultModel", "vertex/gemini-2.5-flash", actor="operator")
    store.set("defaultLogFormat", "CEF", actor="operator")
    out = _run(self_mod_tools.settings_reset())
    assert out["cleared"] == ["defaultLogFormat"]
    assert [r["key"] for r in out["rejected"]] == ["defaultModel"]
    assert store.get("defaultModel") == "vertex/gemini-2.5-flash"
    assert store.get("defaultLogFormat") == DEFAULTS["defaultLogFormat"]


def test_reset_naming_the_model_key_is_refused(store):
    store.set("defaultModel", "vertex/gemini-2.5-flash", actor="operator")
    out = _run(self_mod_tools.settings_reset(["defaultModel"]))
    assert out["cleared"] == []
    assert [r["key"] for r in out["rejected"]] == ["defaultModel"]
    assert store.get("defaultModel") == "vertex/gemini-2.5-flash"


# ─── batch dispatch reaches the same guard ───────────────────────


def test_batch_dispatch_table_uses_the_guarded_functions(store):
    self_mod_tools._populate_batchable_tools()
    table = self_mod_tools._BATCHABLE_TOOLS
    assert table["settings_update"] is self_mod_tools.settings_update
    assert table["settings_reset"] is self_mod_tools.settings_reset


# ─── the operator's REST surface is unaffected ───────────────────


def test_rest_put_can_still_set_the_model(store):
    from api.settings import register_settings_routes
    from config.config import config as _config

    _config.mcp_token = "t"

    class _Mcp:
        def __init__(self):
            self.routes = []

        def custom_route(self, path, methods=None, **_):
            def deco(fn):
                from starlette.routing import Route
                self.routes.append(Route(path, fn, methods=methods))
                return fn
            return deco

    mcp = _Mcp()
    register_settings_routes(mcp, store)
    client = TestClient(Starlette(routes=mcp.routes))
    r = client.put(
        "/api/v1/settings",
        json={"updates": {"defaultModel": "vertex/gemini-2.5-pro"}, "actor": "operator"},
        headers={"Authorization": "Bearer t"},
    )
    assert r.status_code == 200, r.text
    assert store.get("defaultModel") == "vertex/gemini-2.5-pro"
    assert store.overrides()[0].updated_by == "operator"


def test_module_exports_the_protected_set():
    assert "defaultModel" in settings_module.AGENT_PROTECTED_SETTINGS
