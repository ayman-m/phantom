"""VertexEmbedder — calls Vertex AI's text-embedding-004 model (or a
compatible alternative) for memory + KB embedding.

Wires the bundle's `vertex` provider (bundles/spark/providers/vertex)
into the Embedder protocol that SqliteMemoryStore + SqliteKnowledgeBase
consume. The provider already knows how to authenticate to Vertex
(service-account JWT → access token); this wrapper adapts the async
Provider.embed() signature into the sync Embedder protocol with one
defensive layer on top:

  **LRU cache**: in-memory, keyed on text → vector. A single search
  may re-embed the same query against multiple KBs/scopes; caching
  avoids paying the round-trip more than once per process lifetime
  per query. Cache is per-instance and memory-only.

# What this DOESN'T do anymore (and why)

Earlier versions silently demoted a failing Vertex call to a local
TextHashEmbedder so the agent stayed responsive during outages. That
was the wrong tradeoff for SOC tooling: a search that returns
*wrong-but-plausible* hash-similarity scores is worse than a search
that returns a 5xx — operators may trust the bad scores and act on
them. Per the operator policy "Vertex is authoritative; no local ML
substitution", the per-call fallback was removed. A Vertex outage
now surfaces as a clear error to the caller (HTTP 5xx in the search
endpoint, exception in tool calls). The boot-time TextHash path in
main.py is unchanged — it still kicks in when Vertex isn't yet
configured, so the agent UI loads and the operator can complete
setup. But once VertexEmbedder is alive, it stays alive or it
raises. No mid-life demotion.

# Choosing between Vertex and TextHash at boot

main.py constructs a VertexEmbedder when:
  * The bundle declares manifest.memory.embeddingProvider == "google"
  * A `vertex` provider instance has been materialized in the
    ProviderStore (i.e. the operator filled out vertexProjectId +
    vertexServiceAccountJson at setup)

Otherwise it boots with TextHashEmbedder (a deterministic SHA-256-
based stub — *not* a local ML model; near-zero compute) and emits
a stark WARN-level log so the operator knows search quality is
degraded until Vertex creds are submitted.
"""

from __future__ import annotations

import logging
import threading
from collections import OrderedDict
from typing import Any, Callable

logger = logging.getLogger("Phantom MCP")

# Default model + dims per spec (manifest.memory.embeddingModel == "text-embedding-004").
DEFAULT_MODEL = "text-embedding-004"
DEFAULT_DIMS = 768
DEFAULT_CACHE_SIZE = 1024


_AUTH_ERROR_MARKERS = ("invalid_grant", "invalid jwt", "unauthenticated", "unauthorized", "permission_denied", "401", "403")


def _is_auth_error(exc: BaseException) -> bool:
    """True when the failure looks like a rejected credential rather than a quota, network or model error."""
    text = str(exc).lower()
    return any(m in text for m in _AUTH_ERROR_MARKERS)


class VertexEmbedder:
    """Embedder backed by the bundle's Vertex provider with cache + fallback."""

    def __init__(
        self,
        provider: Any,
        model_id: str = DEFAULT_MODEL,
        dims: int = DEFAULT_DIMS,
        cache_size: int = DEFAULT_CACHE_SIZE,
        fallback: Any | None = None,  # accepted for back-compat; ignored
        provider_factory: Callable[[], Any] | None = None,
    ) -> None:
        if provider is None:
            raise ValueError("VertexEmbedder needs a provider instance")
        self._provider = provider
        # Rebuilds the provider from the CURRENT provider + secret stores. The provider object is
        # built once at boot with the key that existed then, so without this a key the operator
        # replaces later (the 30-day service-account keys expire) keeps failing with invalid_grant
        # until the container restarts. embed() calls it once on an authentication failure.
        self._provider_factory = provider_factory
        self.credential_refreshes = 0
        self._model_id = model_id
        # Public alias — the Embedder protocol (memory_store.py,
        # kb_store.py) reads model_id to validate a stored vector
        # against the live embedder before trusting it. dims alone
        # can't catch a TextHash<->Vertex swap since both are 768-dim.
        self.model_id = model_id
        self.dims = dims
        self._cache: OrderedDict[str, list[float]] = OrderedDict()
        self._cache_size = cache_size
        self._lock = threading.Lock()
        # Counters surface in /api/v1/metrics for the observability pillar.
        # `fallback_calls` retained as a metric for parity with the
        # boot-time TextHash mode, but at runtime the VertexEmbedder
        # itself never falls back — failures raise.
        self.upstream_calls = 0
        self.fallback_calls = 0
        self.cache_hits = 0
        self.error_count = 0
        if fallback is not None:
            logger.info(
                "VertexEmbedder: 'fallback' kwarg is accepted but ignored — "
                "per-call demotion to TextHashEmbedder is disabled. "
                "Vertex errors now raise.",
            )

    def embed(self, text: str) -> list[float]:
        if not isinstance(text, str):
            raise TypeError("text must be a string")

        cache_key = text
        with self._lock:
            if cache_key in self._cache:
                # Move-to-front for LRU.
                self._cache.move_to_end(cache_key)
                self.cache_hits += 1
                return self._cache[cache_key]

        # Authoritative path: Vertex or bust. We do NOT demote to a
        # hash stub on failure — see the module docstring for why.
        try:
            try:
                vec = self._provider.embed(self._model_id, text)
            except Exception as first:
                if not (self._provider_factory and _is_auth_error(first)):
                    raise
                # Authentication failed: the stored credential may have been replaced since boot.
                # Re-resolve it once and retry; a second failure is a real failure and raises.
                self._provider = self._provider_factory()
                self.credential_refreshes += 1
                logger.warning("VertexEmbedder: credential refreshed after %s", type(first).__name__)
                vec = self._provider.embed(self._model_id, text)
            self.upstream_calls += 1
        except Exception as exc:
            self.error_count += 1
            logger.error(
                "VertexEmbedder upstream failed (%s). Raising — operators "
                "see this as a 5xx from the search endpoint, which is the "
                "intended signal that the embedder needs attention. Text "
                "prefix: %r",
                exc, text[:60],
            )
            raise

        if not isinstance(vec, list) or not all(isinstance(v, (int, float)) for v in vec):
            self.error_count += 1
            raise RuntimeError(
                f"vertex provider returned malformed embedding "
                f"(type={type(vec).__name__}); cannot proceed",
            )

        if len(vec) != self.dims:
            # Vertex's text-embedding-004 always returns 768; if a future
            # model returns different dims, we surface that as an error
            # rather than serve mis-dimensioned vectors that would make
            # cosine similarity meaningless across the existing index.
            self.error_count += 1
            raise RuntimeError(
                f"vertex returned {len(vec)} dims; this embedder is "
                f"configured for {self.dims}. Re-embed the index or fix the "
                f"manifest.memory.embeddingDims declaration.",
            )

        with self._lock:
            self._cache[cache_key] = vec
            self._cache.move_to_end(cache_key)
            while len(self._cache) > self._cache_size:
                self._cache.popitem(last=False)
        return vec

    def stats(self) -> dict[str, int]:
        return {
            "upstream_calls": self.upstream_calls,
            "fallback_calls": self.fallback_calls,  # always 0 post-tightening
            "cache_hits": self.cache_hits,
            "cache_size": len(self._cache),
            "error_count": self.error_count,
            "credential_refreshes": self.credential_refreshes,
        }


# ─────────────────────────────────────────────────────────────────
# Module-level singleton accessor — wired by main.py at boot.
#
# Same pattern as memory_store/kb_store: the metrics endpoint and any
# /api/v1/health-style probes look up the active embedder via
# get_embedder() instead of being passed it through every route.
# Returns None when the boot path chose TextHashEmbedder (no Vertex
# stats to expose) or when called before main.py has wired things.
# ─────────────────────────────────────────────────────────────────

_embedder: VertexEmbedder | None = None


def set_embedder(e: VertexEmbedder | None) -> None:
    global _embedder
    _embedder = e


def get_embedder() -> VertexEmbedder | None:
    return _embedder
