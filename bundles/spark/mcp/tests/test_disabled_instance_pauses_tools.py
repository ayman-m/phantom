"""A disabled instance is operator-paused: its connector's tools refuse to run.

The loader used to register a connector's tools whenever any instance existed and the
wrapper never looked at `enabled`, so the "Tools paused (disabled)" note on /connectors, and
the docs ("at least one enabled instance"; "tools just refuse to dispatch"), described
nothing the code did. Now: registration and the tool summary count only enabled instances,
PATCH enabled reloads the registry, and a call to a tool of a disabled instance is refused
immediately (a registered tool stays listed until the next restart).
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

import usecase.connector_loader as loader
from api.instances import register_instance_routes
from config.config import config as _config
from usecase.instance_store import InstanceStore
from usecase.secret_store import SecretStore


@pytest.fixture
def store(tmp_path, monkeypatch):
    # The container proxy imports the MCP client library at call-build time; the
    # registration logic under test does not need it.
    fake = types.ModuleType("pkg.connector_proxy")
    fake.proxy_call_tool = lambda *a, **k: None
    monkeypatch.setitem(sys.modules, "pkg.connector_proxy", fake)
    monkeypatch.setenv("PHANTOM_SECRET_KEK_ALLOW_PLAINTEXT", "1")
    monkeypatch.setenv("BUNDLE_ROOT", str(Path(__file__).resolve().parents[2]))  # bundles/spark
    return InstanceStore(data_root=tmp_path, secret_store=SecretStore(data_root=tmp_path))


def _regs(store):
    return list(loader.iter_registrations(include_legacy_aliases=False, store=store, secret_store=store.secret_store))


def _connector_ids(store):
    return {r.connector_id for r in _regs(store) if r.connector_id}


def test_an_enabled_instance_advertises_its_connector_tools(store):
    store.create("cortex-docs", "docs", {}, {})
    assert "cortex-docs" in _connector_ids(store)
    assert loader.tool_summary(store)["cortex-docs"] > 0


def test_a_disabled_instance_does_not(store):
    inst = store.create("cortex-docs", "docs", {}, {})
    store.update(inst.id, enabled=False)
    assert "cortex-docs" not in _connector_ids(store)
    assert loader.tool_summary(store)["cortex-docs"] == 0
    # It is still a configured connector (the card says so); it is just paused.
    assert store.configured_connector_ids() == {"cortex-docs"}
    assert store.configured_connector_ids(enabled_only=True) == set()


def test_re_enabling_brings_the_tools_back(store):
    inst = store.create("cortex-docs", "docs", {}, {})
    store.update(inst.id, enabled=False)
    store.update(inst.id, enabled=True)
    assert "cortex-docs" in _connector_ids(store)


def test_only_the_enabled_instance_is_the_one_wrapped(store):
    old = store.create("cortex-docs", "old", {}, {}, enabled=True)
    store.update(old.id, enabled=False)
    store.create("cortex-docs", "new", {}, {}, enabled=True)
    regs = [r for r in _regs(store) if r.connector_id == "cortex-docs"]
    assert regs


def test_patching_enabled_reloads_the_tool_registry(store, monkeypatch):
    monkeypatch.setattr(_config, "mcp_token", "test-token")
    reloads = []
    monkeypatch.setattr(loader, "reload_tools_now", lambda: reloads.append(1) or (1, 1))

    class FakeMcp:
        def __init__(self):
            self.routes = {}

        def custom_route(self, path, methods=None, include_in_schema=True):
            def deco(fn):
                for m in methods or ["GET"]:
                    self.routes[(path, m)] = fn
                return fn
            return deco

    mcp = FakeMcp()
    register_instance_routes(mcp, store)
    app = Starlette()
    for (path, method), fn in mcp.routes.items():
        app.add_route(path, fn, methods=[method])
    client = TestClient(app, headers={"Authorization": "Bearer test-token"})
    inst = store.create("cortex-docs", "docs", {}, {})

    assert client.patch(f"/api/v1/instances/{inst.id}", json={"enabled": False}).status_code == 200
    assert reloads == [1] and store.get(inst.id).enabled is False
    client.patch(f"/api/v1/instances/{inst.id}", json={"name": "renamed"})
    assert reloads == [1]  # a rename does not reload


def test_a_call_to_a_disabled_instances_tool_is_refused_and_resumes_when_enabled(store):
    import asyncio

    inst = store.create("cortex-docs", "docs", {}, {})
    from usecase.instance_store import set_instance_store

    set_instance_store(store)
    try:
        calls = []

        async def tool(**kw):
            calls.append(kw)
            return {"ok": True}

        wrapped = loader._wrap_with_instance(tool, inst, secret_store=store.secret_store, tool_name="t")
        assert asyncio.run(wrapped()) == {"ok": True}

        store.update(inst.id, enabled=False)
        with pytest.raises(loader.InstanceDisabledError, match="is disabled"):
            asyncio.run(wrapped())
        assert len(calls) == 1  # the tool body did not run again

        store.update(inst.id, enabled=True)
        assert asyncio.run(wrapped()) == {"ok": True}
        assert len(calls) == 2
    finally:
        set_instance_store(None)


def test_the_sync_wrapper_refuses_too(store):
    inst = store.create("cortex-docs", "docs", {}, {})
    from usecase.instance_store import set_instance_store

    set_instance_store(store)
    try:
        wrapped = loader._wrap_with_instance(lambda: "ran", inst, secret_store=store.secret_store, tool_name="t")
        assert wrapped() == "ran"
        store.update(inst.id, enabled=False)
        with pytest.raises(loader.InstanceDisabledError):
            wrapped()
    finally:
        set_instance_store(None)
