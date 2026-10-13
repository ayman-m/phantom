"""The bundle default personality: its shape, its single home, and the route
the personality page reads it from.

The personality page carries no copy of these defaults. It loads them from
GET /api/v1/personality/defaults to fill keys a stored blob lacks and for its
Reset Defaults button, so what this module pins is what both a fresh install
and a Reset Defaults click end up with.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from api.personality import register_personality_routes
from config.config import config as _config
from usecase.personality_store import (
    DEFAULT_PERSONALITY,
    SqlitePersonalityStore,
    default_personality,
)

AUTH = {"Authorization": "Bearer test-mcp-token"}


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
def store(tmp_path: Path) -> SqlitePersonalityStore:
    return SqlitePersonalityStore(data_root=tmp_path)


@pytest.fixture
def client(monkeypatch, store: SqlitePersonalityStore) -> TestClient:
    monkeypatch.setattr(_config, "mcp_token", "test-mcp-token")
    mcp = _FakeMcp()
    register_personality_routes(mcp, store)
    app = Starlette()
    for (path, method), fn in mcp.routes.items():
        app.add_route(path, fn, methods=[method])
    return TestClient(app)


def test_default_keys_are_exactly_the_two_something_reads() -> None:
    """Only personalityMd (system prompt) and actionPolicy (chat route) are
    read at runtime; a third default key would be a knob nothing reads."""
    assert set(DEFAULT_PERSONALITY) == {"personalityMd", "actionPolicy"}
    assert set(DEFAULT_PERSONALITY["actionPolicy"]) == {
        "localCategories",
        "externalCategories",
        "askWhenUnsure",
        "confirmLocalActions",
        "confirmExternalActions",
    }


def test_external_categories_include_the_sender_connectors() -> None:
    """The store seeds a fresh install, so it must classify the HTTP and WEC
    senders as acting on the SOC environment, as the chat route does."""
    external = DEFAULT_PERSONALITY["actionPolicy"]["externalCategories"]
    assert external == [
        "xlog",
        "caldera",
        "xsiam",
        "simulations",
        "http-sender",
        "wec-sender",
    ]


def test_default_personality_is_an_independent_copy() -> None:
    copy_a = default_personality()
    copy_a["actionPolicy"]["externalCategories"].append("mutated")
    copy_a["personalityMd"] = "changed"
    copy_b = default_personality()
    assert "mutated" not in copy_b["actionPolicy"]["externalCategories"]
    assert copy_b == DEFAULT_PERSONALITY
    assert "mutated" not in DEFAULT_PERSONALITY["actionPolicy"]["externalCategories"]


def test_fresh_store_seeds_and_resets_to_the_same_document(
    store: SqlitePersonalityStore,
) -> None:
    seeded = store.get()
    assert seeded is not None and seeded.blob == DEFAULT_PERSONALITY
    store.put({"personalityMd": "# Mine\n"}, actor="user:operator")
    reset = store.reset_to_default(actor="user:operator")
    assert reset.blob == DEFAULT_PERSONALITY


def test_defaults_route_serves_the_default_document(client: TestClient) -> None:
    r = client.get("/api/v1/personality/defaults", headers=AUTH)
    assert r.status_code == 200, r.text
    assert r.json() == {"personality": DEFAULT_PERSONALITY}


def test_defaults_route_ignores_the_stored_blob(
    client: TestClient, store: SqlitePersonalityStore
) -> None:
    store.put({"personalityMd": "# Mine\n"}, actor="user:operator")
    r = client.get("/api/v1/personality/defaults", headers=AUTH)
    assert r.json()["personality"]["personalityMd"] == DEFAULT_PERSONALITY["personalityMd"]


def test_defaults_route_requires_the_bearer(client: TestClient) -> None:
    assert client.get("/api/v1/personality/defaults").status_code in (401, 403)
