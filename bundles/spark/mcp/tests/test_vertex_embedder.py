"""Tests for VertexEmbedder — wrapper around the bundle's Vertex provider
with LRU cache and fail-fast error semantics. Provider is mocked
end-to-end; we do not exercise google-auth or httpx here.

CONTRACT (post-tightening): per-call demotion to TextHashEmbedder is
DISABLED. The `fallback` kwarg is accepted for back-compat but
ignored. On Vertex error / malformed response / dim mismatch, embed()
RAISES so the search endpoint surfaces a 5xx — operators must see the
problem rather than get garbage hash-similarity scores. The boot-time
TextHash path in main.py is used only before Vertex is set up;
once VertexEmbedder is alive, it stays alive or it raises."""

from __future__ import annotations

from typing import Any

import pytest

from src.usecase.vertex_embedder import (
    DEFAULT_DIMS,
    DEFAULT_MODEL,
    VertexEmbedder,
)


class _StubProvider:
    """Provider that returns a deterministic 768-dim vector seeded from
    text length. Used as the "happy path" upstream."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def embed(self, model_id: str, text: str) -> list[float]:
        self.calls.append((model_id, text))
        # Plain deterministic shape: cycle (len(text) mod 7) into a 768-vec.
        v = [0.0] * DEFAULT_DIMS
        v[len(text) % DEFAULT_DIMS] = 1.0
        return v


class _BoomProvider:
    def embed(self, model_id: str, text: str) -> list[float]:
        raise RuntimeError("vertex network down")


class _BadShapeProvider:
    def embed(self, model_id: str, text: str) -> list[float]:
        return ["nope", "this", "is", "wrong"]  # type: ignore[return-value]


class _StubFallback:
    dims = DEFAULT_DIMS

    def __init__(self) -> None:
        self.calls: list[str] = []

    def embed(self, text: str) -> list[float]:
        self.calls.append(text)
        return [0.5] * DEFAULT_DIMS


def test_constructor_requires_provider() -> None:
    with pytest.raises(ValueError):
        VertexEmbedder(provider=None)


def test_embed_round_trip_via_provider() -> None:
    p = _StubProvider()
    e = VertexEmbedder(provider=p)
    v = e.embed("hello world")
    assert len(v) == DEFAULT_DIMS
    assert p.calls == [(DEFAULT_MODEL, "hello world")]
    assert e.upstream_calls == 1
    assert e.cache_hits == 0


def test_cache_hits_avoid_upstream() -> None:
    p = _StubProvider()
    e = VertexEmbedder(provider=p)
    e.embed("hello")
    e.embed("hello")
    e.embed("hello")
    # Second + third are cache hits — only one upstream call.
    assert p.calls == [(DEFAULT_MODEL, "hello")]
    assert e.upstream_calls == 1
    assert e.cache_hits == 2


def test_cache_lru_evicts_oldest() -> None:
    p = _StubProvider()
    e = VertexEmbedder(provider=p, cache_size=3)
    for s in ["a", "b", "c", "d"]:    # 4 items into a 3-slot cache
        e.embed(s)
    # "a" should be evicted; re-embedding it triggers another upstream.
    e.embed("a")
    # 4 unique embeddings + 1 re-embed of "a" = 5 upstream calls.
    assert e.upstream_calls == 5


def test_upstream_failure_raises_even_with_fallback_kwarg() -> None:
    """Per the new contract, the `fallback` kwarg is accepted for
    back-compat but IGNORED — Vertex errors propagate so the search
    endpoint can return a 5xx. This is the operator-policy change
    motivated by 'no per-call demotion to hash stub: SOC tooling
    can't afford silently-wrong scores'.
    """
    fb = _StubFallback()
    e = VertexEmbedder(provider=_BoomProvider(), fallback=fb)
    with pytest.raises(RuntimeError, match="vertex network down"):
        e.embed("anything")
    # Fallback is never invoked.
    assert fb.calls == []
    assert e.fallback_calls == 0
    # error_count tracks the failure for /api/v1/metrics.
    assert e.error_count == 1


def test_no_fallback_propagates_failure() -> None:
    """Same contract whether or not a fallback is supplied — the kwarg
    is decorative now."""
    e = VertexEmbedder(provider=_BoomProvider(), fallback=None)
    with pytest.raises(RuntimeError):
        e.embed("anything")


def test_malformed_provider_response_raises() -> None:
    """If the provider returns a non-list-of-float, we cannot serve
    that as an embedding — raise rather than try to coerce or fall
    back. Operators see this as a 5xx and investigate."""
    e = VertexEmbedder(provider=_BadShapeProvider(), fallback=_StubFallback())
    with pytest.raises(RuntimeError, match="malformed embedding"):
        e.embed("x")


def test_dim_mismatch_raises() -> None:
    """Earlier the embedder passed mis-dimensioned vectors through with
    a warning. That's wrong — the SqliteKnowledgeBase index is built
    on a fixed dim count, so cosine similarity against a 1024-dim
    query with 768-dim stored rows produces meaningless scores. Hard
    error is the correct response; operator must re-embed the index
    or fix the manifest declaration."""

    class _OddDims:
        def embed(self, model_id, text):
            return [0.1] * 1024

    e = VertexEmbedder(provider=_OddDims(), fallback=_StubFallback())
    with pytest.raises(RuntimeError, match="1024 dims"):
        e.embed("hi")


def test_fallback_kwarg_logged_but_ignored(caplog) -> None:
    """Constructing with a fallback emits an info log (helps operators
    spot stale call sites) but the embedder doesn't actually use it."""
    import logging
    caplog.set_level(logging.INFO, logger="Phantom MCP")
    fb = _StubFallback()
    VertexEmbedder(provider=_StubProvider(), fallback=fb)
    assert any(
        "fallback" in r.message.lower() and "ignored" in r.message.lower()
        for r in caplog.records
    ), "expected info log noting fallback kwarg is ignored"


def test_stats_shape() -> None:
    p = _StubProvider()
    e = VertexEmbedder(provider=p)
    e.embed("a")
    e.embed("a")    # cache hit
    s = e.stats()
    assert s["upstream_calls"] == 1
    assert s["cache_hits"] == 1
    assert s["fallback_calls"] == 0
    assert s["cache_size"] == 1
    assert s["error_count"] == 0


def test_error_count_increments_on_each_failure() -> None:
    """error_count is the operator-visible health signal. Counts every
    failure path: provider raise, malformed response, dim mismatch."""
    e = VertexEmbedder(provider=_BoomProvider())
    for q in ("a", "b", "c"):
        with pytest.raises(RuntimeError):
            e.embed(q)
    assert e.error_count == 3
    assert e.stats()["error_count"] == 3


def test_text_must_be_string() -> None:
    e = VertexEmbedder(provider=_StubProvider())
    with pytest.raises(TypeError):
        e.embed(1234)  # type: ignore[arg-type]


# ─────────────────────────────────────────────────────────────────
# Credential refresh — the provider is built once at boot, so a key the operator replaces
# later (30-day service-account keys expire) must be picked up without a container restart.
# ─────────────────────────────────────────────────────────────────


class _ExpiredKeyProvider:
    def embed(self, model_id: str, text: str) -> list[float]:
        raise RuntimeError("('invalid_grant: Invalid JWT Signature.', {'error': 'invalid_grant'})")


def test_auth_failure_rebuilds_provider_and_retries_once() -> None:
    fresh = _StubProvider()
    builds: list[int] = []

    def factory() -> Any:
        builds.append(1)
        return fresh

    emb = VertexEmbedder(provider=_ExpiredKeyProvider(), provider_factory=factory)
    vec = emb.embed("okta tor signin")
    assert len(vec) == DEFAULT_DIMS
    assert builds == [1]
    assert fresh.calls == [(DEFAULT_MODEL, "okta tor signin")]
    assert emb.stats()["credential_refreshes"] == 1
    # The refreshed provider stays in use; no second rebuild for the next call.
    emb.embed("another text")
    assert builds == [1]


def test_auth_failure_after_refresh_still_raises() -> None:
    emb = VertexEmbedder(provider=_ExpiredKeyProvider(), provider_factory=lambda: _ExpiredKeyProvider())
    with pytest.raises(RuntimeError, match="invalid_grant"):
        emb.embed("text")
    assert emb.stats()["credential_refreshes"] == 1
    assert emb.stats()["error_count"] == 1


def test_non_auth_failure_does_not_rebuild_provider() -> None:
    builds: list[int] = []
    emb = VertexEmbedder(provider=_BoomProvider(), provider_factory=lambda: builds.append(1) or _StubProvider())
    with pytest.raises(RuntimeError, match="network down"):
        emb.embed("text")
    assert builds == []
    assert emb.stats()["credential_refreshes"] == 0


def test_no_factory_keeps_raising_on_auth_failure() -> None:
    emb = VertexEmbedder(provider=_ExpiredKeyProvider())
    with pytest.raises(RuntimeError, match="invalid_grant"):
        emb.embed("text")
