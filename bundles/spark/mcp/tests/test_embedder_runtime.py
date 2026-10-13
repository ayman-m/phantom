"""The embedder follows the provider store; it is not frozen at boot.

A fresh install boots with no Vertex provider (the operator adds one later on
/providers), so the stub embedder was chosen once and stayed in place:
health_status kept reporting `embedder_mode: stub` and new memory/knowledge
entries kept the `texthash-v1-768d` model id after Vertex was configured.
EmbedderRuntime re-decides from the current provider store whenever a Vertex
provider is created or updated through /api/v1/providers.
"""
from __future__ import annotations

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from api.providers import register_provider_routes
from config.config import config as _config
from usecase import embedder_runtime as er
from usecase.builtin_components.self_mod_tools import health_status
from usecase.embedder_runtime import EmbedderRuntime
from usecase.kb_store import SqliteKnowledgeBase
from usecase.memory_store import SqliteMemoryStore, TextHashEmbedder
from usecase.provider_store import ProviderStore
from usecase.secret_store import SecretStore
from usecase.vertex_embedder import VertexEmbedder, get_embedder, set_embedder

DIMS = 768
VERTEX_BODY = {
    "provider_id": "vertex",
    "name": "primary-vertex",
    "config": {"project_id": "proj-1", "region": "us-central1"},
    "secrets": {"serviceAccountJson": '{"type": "service_account"}'},
}


class _FakeMcp:
    def __init__(self):
        self.routes = {}

    def custom_route(self, path, methods=None, include_in_schema=True):
        def deco(fn):
            for m in methods or ["GET"]:
                self.routes[(path, m)] = fn
            return fn

        return deco


class FakeVertexProvider:
    """Stands in for providers.vertex.src.provider.Provider (no network)."""

    fail = False
    # A key that builds a provider fine but is rejected by Vertex on the first
    # embed() call (the realistic wrong/revoked service-account case).
    embed_error: str | None = None
    embed_on_loop: list[bool] = []

    def __init__(self, config, secrets):
        if FakeVertexProvider.fail:
            raise ValueError("vertex provider: secrets.serviceAccountJson is required")
        self.config, self.secrets = config, secrets

    def embed(self, model_id, text):
        import asyncio

        try:
            asyncio.get_running_loop()
            FakeVertexProvider.embed_on_loop.append(True)
        except RuntimeError:
            FakeVertexProvider.embed_on_loop.append(False)
        if FakeVertexProvider.embed_error:
            raise RuntimeError(FakeVertexProvider.embed_error)
        return [0.25] * DIMS


class World:
    def __init__(self, tmp_path, monkeypatch, *, embed_provider="google"):
        data = tmp_path / "data"
        data.mkdir()
        monkeypatch.setenv("DATA_ROOT", str(data))
        monkeypatch.setenv("PHANTOM_SECRET_KEK_ALLOW_PLAINTEXT", "1")
        # Recorded here so the runtime's own env write is undone at teardown.
        monkeypatch.setenv("PHANTOM_EMBEDDER_MODE", "unknown")
        monkeypatch.setattr(_config, "mcp_token", "test-token")
        FakeVertexProvider.fail = False
        FakeVertexProvider.embed_error = None
        FakeVertexProvider.embed_on_loop = []
        self.secrets = SecretStore(data_root=data)
        self.providers = ProviderStore(data_root=data, secret_store=self.secrets)
        self.runtime = EmbedderRuntime(
            provider_store=self.providers,
            secret_store=self.secrets,
            embed_provider_id=embed_provider,
            embed_model="text-embedding-004",
            embed_dims=DIMS,
            fallback_embedder=TextHashEmbedder(dims=DIMS),
            provider_class=FakeVertexProvider,
        )
        er.set_embedder_runtime(self.runtime)
        self.memory = SqliteMemoryStore(
            data_root=tmp_path / "mem", embedder=self.runtime.select_initial()
        )
        self.kb = SqliteKnowledgeBase(data_root=tmp_path / "kb", embedder=self.memory.embedder)
        self.runtime.attach(self.memory, self.kb)
        mcp = _FakeMcp()
        register_provider_routes(mcp, self.providers)
        app = Starlette()
        for (path, method), fn in mcp.routes.items():
            app.add_route(path, fn, methods=[method])
        self.client = TestClient(app, headers={"Authorization": "Bearer test-token"})


@pytest.fixture
def world(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    yield w
    er.set_embedder_runtime(None)
    set_embedder(None)


def test_boot_without_a_vertex_provider_is_stub_and_points_at_providers(world):
    assert world.runtime.mode == "stub"
    assert world.memory.store(key="k", value="v").embedding_model == "texthash-v1-768d"
    h = health_status()
    # v1.0.5: no Vertex provider is the normal state of a Claude-only or
    # OpenAI-only install (embeddings are Vertex-only), so it is reported but
    # does not make the install unhealthy. See the fault tests below.
    assert h["embedder_mode"] == "stub" and h["ok"] is True
    assert "/providers" in h["embedder_warning"]
    assert "/setup" not in h["embedder_warning"]
    assert "Chat does not depend on it" in h["embedder_warning"]
    assert world.runtime.is_fault() is False


def test_an_install_without_vertex_stays_healthy_after_other_providers_are_saved(world):
    """Claude-only / OpenAI-only: chat runs on another provider, the embedder
    stays on the stub on purpose, and nothing about that is a fault."""
    for provider_id in ("anthropic", "openai"):
        r = world.client.post(
            "/api/v1/providers",
            json={"provider_id": provider_id, "name": f"primary-{provider_id}", "config": {}, "secrets": {"api_key": "key-for-tests"}},
        )
        assert r.status_code == 201, r.text
    assert world.runtime.mode == "stub"
    h = health_status()
    assert h["ok"] is True and h["embedder_mode"] == "stub"
    assert "embedder_warning" in h, "the limit is still reported"


def test_a_vertex_provider_that_cannot_start_is_still_a_fault(world):
    FakeVertexProvider.fail = True
    world.client.post("/api/v1/providers", json=VERTEX_BODY)
    assert world.runtime.is_fault() is True
    assert health_status()["ok"] is False


def test_saving_a_vertex_provider_moves_memory_and_kb_off_the_stub_without_a_restart(world):
    activated = []
    world.runtime.on_vertex_activated = lambda: activated.append(1)

    r = world.client.post("/api/v1/providers", json=VERTEX_BODY)

    assert r.status_code == 201
    assert r.json()["embedder_mode"] == "vertex"
    assert r.json()["requires_mcp_restart"] is False
    assert world.runtime.mode == "vertex"
    assert isinstance(world.memory.embedder, VertexEmbedder)
    assert world.kb.embedder is world.memory.embedder
    assert get_embedder() is world.memory.embedder
    assert world.memory.store(key="k2", value="v2").embedding_model == "text-embedding-004"
    h = health_status()
    assert h["embedder_mode"] == "vertex" and h["embedder_model"] == "text-embedding-004"
    assert "embedder_warning" not in h
    assert activated == [1], "the KB re-index hook fires once, on the stub -> vertex flip"


def test_a_vertex_provider_that_will_not_initialise_keeps_the_stub_and_says_why(world):
    FakeVertexProvider.fail = True

    r = world.client.post("/api/v1/providers", json=VERTEX_BODY)

    assert r.status_code == 201, "the provider write itself still succeeds"
    assert world.runtime.mode == "stub"
    warning = health_status()["embedder_warning"]
    assert "could not start" in warning and "serviceAccountJson" in warning
    assert "/providers" in warning

    FakeVertexProvider.fail = False
    pid = r.json()["instance"]["id"]
    assert world.client.put(f"/api/v1/providers/{pid}", json={"config": {"region": "us-east1"}}).status_code == 200
    assert world.runtime.mode == "vertex" and world.runtime.last_error is None


def test_updating_the_vertex_provider_rebuilds_the_embedder_without_a_second_reindex(world):
    activated = []
    world.runtime.on_vertex_activated = lambda: activated.append(1)
    pid = world.client.post("/api/v1/providers", json=VERTEX_BODY).json()["instance"]["id"]
    first = world.memory.embedder

    world.client.put(f"/api/v1/providers/{pid}", json={"config": {"project_id": "proj-2"}})

    assert world.memory.embedder is not first
    assert world.memory.embedder.model_id == first.model_id
    assert activated == [1]


def test_deleting_the_vertex_provider_never_demotes_the_running_embedder(world):
    pid = world.client.post("/api/v1/providers", json=VERTEX_BODY).json()["instance"]["id"]

    assert world.client.delete(f"/api/v1/providers/{pid}").status_code == 200

    assert world.runtime.mode == "vertex"
    assert isinstance(world.memory.embedder, VertexEmbedder)
    warning = world.runtime.warning()
    assert warning and "removed" in warning and "/providers" in warning
    assert health_status()["ok"] is False


def test_delete_response_reports_the_embedder_mode_like_create_and_update(world):
    pid = world.client.post("/api/v1/providers", json=VERTEX_BODY).json()["instance"]["id"]

    r = world.client.delete(f"/api/v1/providers/{pid}")

    assert r.status_code == 200
    body = r.json()
    assert body["deleted"] is True and body["id"] == pid
    # The running embedder is never demoted by a delete (see the test above).
    assert body["embedder_mode"] == "vertex"


def test_deleting_a_non_vertex_provider_reports_no_embedder_mode(world):
    pid = world.client.post(
        "/api/v1/providers",
        json={"provider_id": "anthropic", "name": "a", "config": {}, "secrets": {"api_key": "x"}},
    ).json()["instance"]["id"]
    r = world.client.delete(f"/api/v1/providers/{pid}")
    assert r.status_code == 200 and "embedder_mode" not in r.json()


def test_other_providers_do_not_touch_the_embedder(world):
    r = world.client.post(
        "/api/v1/providers",
        json={"provider_id": "anthropic", "name": "a", "config": {}, "secrets": {"api_key": "x"}},
    )
    assert r.status_code == 201
    assert "embedder_mode" not in r.json() and r.json()["requires_mcp_restart"] is False
    assert world.runtime.mode == "stub"


def test_vertex_already_configured_at_boot_starts_live(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    w.providers.create("vertex", "primary-vertex", VERTEX_BODY["config"], VERTEX_BODY["secrets"])
    rt = EmbedderRuntime(
        provider_store=w.providers, secret_store=w.secrets, embed_provider_id="google",
        embed_model="text-embedding-004", embed_dims=DIMS,
        fallback_embedder=TextHashEmbedder(dims=DIMS), provider_class=FakeVertexProvider,
    )
    assert isinstance(rt.select_initial(), VertexEmbedder) and rt.mode == "vertex"
    er.set_embedder_runtime(None)
    set_embedder(None)


def test_a_bundle_without_an_embedding_provider_stays_stub_and_says_so(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch, embed_provider="")
    w.providers.create("vertex", "primary-vertex", VERTEX_BODY["config"], VERTEX_BODY["secrets"])
    assert w.runtime.refresh("test") == "stub"
    assert "embeddingProvider" in w.runtime.warning()
    # A bundle that declares no embedding provider is a configuration fault.
    assert w.runtime.is_fault() is True
    assert health_status()["ok"] is False
    er.set_embedder_runtime(None)
    set_embedder(None)


def test_swapping_the_kb_embedder_re_embeds_hash_unchanged_documents(tmp_path):
    """The re-index after the flip works because upsert() compares the model id too."""
    kb = SqliteKnowledgeBase(data_root=tmp_path, embedder=TextHashEmbedder(dims=DIMS))
    doc = dict(kb_name="k", doc_id="d", title="t", category="c", content="body", source_path="p", source_hash="h", metadata={})
    assert kb.upsert(**doc)[1] == "insert"
    assert kb.upsert(**doc)[1] == "unchanged"

    class Vertexish:
        model_id, dims = "text-embedding-004", DIMS

        def embed(self, text):
            return [0.25] * DIMS

    kb.set_embedder(Vertexish())
    d, action = kb.upsert(**doc)
    assert action == "update" and d.embedding_model == "text-embedding-004"


# ─── A key Vertex rejects must not flip the mode ─────────────────────────────

BAD_KEY_ERROR = "invalid_grant: Invalid JWT Signature (HTTP 401)"


def _doc(i):
    return dict(
        kb_name="k", doc_id=f"d{i}", title=f"t{i}", category="c",
        content=f"body number {i}", source_path=f"p{i}", source_hash=f"h{i}", metadata={},
    )


def _kb_models(kb):
    import sqlite3

    with sqlite3.connect(kb.db_path) as c:
        return {r[0]: r[1] for r in c.execute("SELECT doc_id, embedding_model FROM kb_documents")}


def _reindex_from(kb, docs):
    """Stand-in for the bundled-KB loader: upsert() skips docs the live embedder already produced."""
    def run():
        for d in docs:
            kb.upsert(**d)
    return run


def test_a_rejected_key_keeps_the_stub_and_never_fires_the_reindex(world):
    activated = []
    world.runtime.on_vertex_activated = lambda: activated.append(1)
    FakeVertexProvider.embed_error = BAD_KEY_ERROR

    r = world.client.post("/api/v1/providers", json=VERTEX_BODY)

    assert r.status_code == 201
    assert r.json()["embedder_mode"] == "stub"
    assert world.runtime.mode == "stub"
    assert not isinstance(world.memory.embedder, VertexEmbedder)
    assert world.memory.store(key="k", value="v").embedding_model == "texthash-v1-768d"
    assert activated == []
    warning = health_status()["embedder_warning"]
    assert warning.startswith("Vertex embedder could not start:")
    assert "invalid_grant" in warning and "check /providers" in warning
    assert health_status()["ok"] is False


def test_bad_key_then_fixed_key_moves_the_kb_off_the_stub_vectors(world):
    docs = [_doc(i) for i in range(3)]
    for d in docs:
        world.kb.upsert(**d)  # embedded by the stub, as on a fresh install
    assert set(_kb_models(world.kb).values()) == {"texthash-v1-768d"}
    world.runtime.on_vertex_activated = _reindex_from(world.kb, docs)

    FakeVertexProvider.embed_error = BAD_KEY_ERROR
    pid = world.client.post("/api/v1/providers", json=VERTEX_BODY).json()["instance"]["id"]
    assert world.runtime.mode == "stub"
    assert set(_kb_models(world.kb).values()) == {"texthash-v1-768d"}

    FakeVertexProvider.embed_error = None
    r = world.client.put(f"/api/v1/providers/{pid}", json={"secrets": {"serviceAccountJson": '{"fixed": 1}'}})

    assert r.status_code == 200 and r.json()["embedder_mode"] == "vertex"
    assert world.runtime.last_error is None
    assert set(_kb_models(world.kb).values()) == {"text-embedding-004"}
    assert [d.doc_id for d, _ in world.kb.search("body number 1", limit=5, min_score=-1.0)]
    assert "embedder_warning" not in health_status()


def test_reindex_fires_on_every_install_while_the_kb_still_has_stale_documents(world):
    """The old hook fired only on the stub -> vertex flip, so a KB left on stub
    vectors (breaker tripped, or a load that never finished) stayed there."""
    fired = []
    world.runtime.on_vertex_activated = lambda: fired.append(1)
    pid = world.client.post("/api/v1/providers", json=VERTEX_BODY).json()["instance"]["id"]
    assert fired == [1]  # the flip (empty KB)

    world.client.put(f"/api/v1/providers/{pid}", json={"config": {"region": "us-east1"}})
    assert fired == [1], "nothing stale: no second re-index"

    world.kb.upsert(**_doc(9))
    import sqlite3

    with sqlite3.connect(world.kb.db_path) as c:
        c.execute("UPDATE kb_documents SET embedding_model = 'texthash-v1-768d'")
    world.client.put(f"/api/v1/providers/{pid}", json={"config": {"region": "us-west1"}})
    assert fired == [1, 1], "stale stub-embedded document: re-index again"


def test_an_incomplete_bundled_load_also_triggers_the_reindex(world):
    fired = []
    world.runtime.on_vertex_activated = lambda: fired.append(1)
    incomplete = {"v": False}
    world.runtime.kb_load_incomplete = lambda: incomplete["v"]
    pid = world.client.post("/api/v1/providers", json=VERTEX_BODY).json()["instance"]["id"]
    assert fired == [1]
    world.client.put(f"/api/v1/providers/{pid}", json={"config": {"region": "us-east1"}})
    assert fired == [1]
    incomplete["v"] = True  # the loader's breaker aborted partway
    world.client.put(f"/api/v1/providers/{pid}", json={"config": {"region": "us-west1"}})
    assert fired == [1, 1]


def test_a_rejected_replacement_key_keeps_the_live_vertex_embedder_and_says_so(world):
    pid = world.client.post("/api/v1/providers", json=VERTEX_BODY).json()["instance"]["id"]
    live = world.memory.embedder
    assert world.runtime.mode == "vertex"

    FakeVertexProvider.embed_error = BAD_KEY_ERROR
    r = world.client.put(f"/api/v1/providers/{pid}", json={"secrets": {"serviceAccountJson": '{"bad": 1}'}})

    assert r.status_code == 200 and r.json()["embedder_mode"] == "vertex"
    assert world.memory.embedder is live and world.kb.embedder is live
    warning = world.runtime.warning()
    assert warning and "could not start" in warning and "invalid_grant" in warning
    assert "check /providers" in warning
    assert health_status()["ok"] is False


def test_last_error_never_carries_key_material(world):
    pem_dashes = "-----"
    key = f"{pem_dashes}BEGIN PRIVATE KEY{pem_dashes}\nMIIEvQIBADANBgkq\n{pem_dashes}END PRIVATE KEY{pem_dashes}\n"
    # Token-shaped fixtures are assembled at run time so secret scanners do not flag the source.
    oauth_token = "ya29." + "a0AfH6SMBx"
    FakeVertexProvider.embed_error = (
        f"auth failed for {{'private_key': '{key}', 'private_key_id': 'abc123def456'}} "
        f"Authorization: Bearer {oauth_token}-secret-token eyJhbGciOi.eyJpc3MiOiJ4.c2lnbmF0dXJl "
        'and the stored value {"type": "service_account"}'
    )
    world.client.post("/api/v1/providers", json=VERTEX_BODY)

    err = world.runtime.last_error
    assert err and "auth failed" in err
    for leaked in ("MIIEvQIBADANBgkq", "BEGIN PRIVATE KEY", oauth_token, "eyJhbGciOi", "abc123def456", '{"type": "service_account"}'):
        assert leaked not in err
        assert leaked not in health_status()["embedder_warning"]


def test_the_routes_refresh_the_embedder_off_the_event_loop(world, monkeypatch):
    """refresh() probes with a network call; it must not run on the loop that serves every request."""
    import asyncio

    from api import providers as providers_api

    real = providers_api._refresh_embedder
    seen = []

    def spy(provider_id, reason):
        try:
            asyncio.get_running_loop()
            seen.append(True)
        except RuntimeError:
            seen.append(False)
        return real(provider_id, reason)

    monkeypatch.setattr(providers_api, "_refresh_embedder", spy)
    pid = world.client.post("/api/v1/providers", json=VERTEX_BODY).json()["instance"]["id"]
    world.client.put(f"/api/v1/providers/{pid}", json={"config": {"region": "us-east1"}})
    world.client.delete(f"/api/v1/providers/{pid}")
    assert seen == [False, False, False]


def test_boot_with_a_rejected_key_starts_on_the_stub(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    w.providers.create("vertex", "primary-vertex", VERTEX_BODY["config"], VERTEX_BODY["secrets"])
    FakeVertexProvider.embed_error = BAD_KEY_ERROR
    rt = EmbedderRuntime(
        provider_store=w.providers, secret_store=w.secrets, embed_provider_id="google",
        embed_model="text-embedding-004", embed_dims=DIMS,
        fallback_embedder=TextHashEmbedder(dims=DIMS), provider_class=FakeVertexProvider,
    )
    assert isinstance(rt.select_initial(), TextHashEmbedder) and rt.mode == "stub"
    assert "invalid_grant" in rt.warning()
    er.set_embedder_runtime(None)
    set_embedder(None)


def test_a_hung_probe_times_out_instead_of_blocking(tmp_path, monkeypatch):
    import threading

    w = World(tmp_path, monkeypatch)
    w.providers.create("vertex", "primary-vertex", VERTEX_BODY["config"], VERTEX_BODY["secrets"])
    release = threading.Event()

    class Hangs(FakeVertexProvider):
        def embed(self, model_id, text):
            release.wait(5)
            return [0.0] * DIMS

    monkeypatch.setattr(er, "PROBE_TIMEOUT_S", 0.2)
    rt = EmbedderRuntime(
        provider_store=w.providers, secret_store=w.secrets, embed_provider_id="google",
        embed_model="text-embedding-004", embed_dims=DIMS,
        fallback_embedder=TextHashEmbedder(dims=DIMS), provider_class=Hangs,
    )
    try:
        assert rt.select_initial() is not None and rt.mode == "stub"
        assert "timed out" in rt.last_error
    finally:
        release.set()
        er.set_embedder_runtime(None)
        set_embedder(None)


def test_concurrent_upserts_of_the_same_new_document_do_not_collide(tmp_path):
    """The boot load and a re-index can race on one (kb_name, doc_id): both see
    no row, both embed, both INSERT. The second used to die on UNIQUE and count
    as an embed failure toward the loader's circuit breaker."""
    import threading

    barrier = threading.Barrier(2, timeout=5)

    class Slow:
        model_id, dims = "texthash-v1-768d", DIMS

        def embed(self, text):
            barrier.wait()  # both threads have passed the "no existing row" check
            return [0.1] * DIMS

    kb = SqliteKnowledgeBase(data_root=tmp_path, embedder=Slow())
    errors, actions = [], []

    def go():
        try:
            actions.append(kb.upsert(**_doc(1))[1])
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=go) for _ in range(2)]
    [t.start() for t in threads]
    [t.join(10) for t in threads]

    assert errors == []
    assert sorted(actions) == ["insert", "update"]
    assert len(_kb_models(kb)) == 1


def test_count_stale_embeddings_counts_other_models_and_null(tmp_path):
    import sqlite3

    kb = SqliteKnowledgeBase(data_root=tmp_path, embedder=TextHashEmbedder(dims=DIMS))
    for i in range(3):
        kb.upsert(**_doc(i))
    assert kb.count_stale_embeddings("texthash-v1-768d") == 0
    assert kb.count_stale_embeddings("text-embedding-004") == 3
    with sqlite3.connect(kb.db_path) as c:
        c.execute("UPDATE kb_documents SET embedding_model = NULL WHERE doc_id = 'd0'")
    assert kb.count_stale_embeddings("texthash-v1-768d") == 1
