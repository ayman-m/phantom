"""EmbedderRuntime: which embedder memory + KB search use, decided from the
CURRENT provider store and re-decided whenever a Vertex provider is saved.

Why this exists. The embedder used to be chosen once, in main.py, at boot. A
fresh install boots with no Vertex provider (the operator adds one afterwards
on /providers), so the stub (TextHashEmbedder) was chosen and stayed in place
until the container restarted: memory and knowledge entries kept getting
`texthash-v1-768d` and `health_status` kept reporting `embedder_mode: stub`
long after Vertex was configured.

Now the provider routes call `refresh()` after a Vertex instance is created,
updated or deleted. `refresh()` rebuilds the VertexEmbedder from the stores as
they are now and swaps it into the memory store and the knowledge base. The
mode `health_status` reports is read from here, not from an env var stamped at
boot.

Policy kept from vertex_embedder.py: Vertex is authoritative once alive. A
refresh only ever upgrades (stub -> vertex) or replaces a Vertex embedder with
a freshly-built one; it never demotes to the stub. Deleting the Vertex provider
leaves the running embedder on its last credentials until the next restart,
which then boots as stub; `warning()` says so while no Vertex provider exists.

A new embedder is installed only after it has answered one real embed() call
(`_probe`). Building it needs nothing more than a project id and some
service-account JSON, so without the probe a wrong or revoked key flipped the
mode to vertex, the background KB re-index then failed five times in a row and
tripped the loader's circuit breaker, and the KB stayed on stub vectors. A
failed probe keeps whatever embedder is live (the stub, or the previous Vertex
one) and records `last_error`, which `warning()` and `health_status` surface.
The probe runs on a worker thread with a deadline; callers on the event loop
(the /providers routes, the boot path) hand `refresh()` / `select_initial()` to
a thread themselves.

The KB is re-indexed after every successful install while it still holds
documents another embedder produced, or while the last bundled load did not
finish, not only on the stub -> vertex flip.
"""

from __future__ import annotations

import logging
import os
import re
import threading
from typing import Any, Callable

from usecase.provider_store import is_own_secret_ref

logger = logging.getLogger("Phantom MCP")

VERTEX_PROVIDER_ID = "vertex"

MODE_STUB = "stub"
MODE_VERTEX = "vertex"

# One real embed() call proves the credentials before a Vertex embedder is
# installed. Bounded so a black-holed network cannot hold up boot (the
# entrypoint's readiness window is 60 s) or a /providers save.
PROBE_TEXT = "phantom embedder probe"
PROBE_TIMEOUT_S = 20.0

_MAX_ERROR_CHARS = 300
_REDACTED = "[redacted]"
_SECRET_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]*-----.*?(?:-----END [A-Z ]*-----|$)", re.DOTALL),
    re.compile(
        r"""(?ix)(["']?(?:private_key(?:_id)?|client_secret|access_token|refresh_token|
        id_token|api_key|assertion|serviceAccountJson)["']?\s*[:=]\s*)(?:"[^"]*"|'[^']*'|\S+)"""
    ),
    re.compile(r"(?i)\bauthorization\b\s*[:=]\s*(?:bearer\s+)?\S+"),
    re.compile(r"(?i)\bbearer\s+\S+"),
    re.compile(r"\bya29\.[\w.\-]+"),
    re.compile(r"\beyJ[\w\-]{4,}\.[\w\-]{4,}(?:\.[\w\-]{4,})?"),
    re.compile(r"\bAIza[\w\-]{20,}"),
)


def redact_secrets(text: str, literals: tuple[str, ...] = ()) -> str:
    """Strip key material from an error message before it is stored or shown.

    Removes PEM blocks, key/token fields, bearer tokens and JWTs by pattern,
    plus every literal secret value the provider was built from, then caps the
    length. The message is surfaced on /providers and in health_status.
    """
    out = text
    for lit in sorted({l for l in literals if isinstance(l, str) and len(l) >= 6}, key=len, reverse=True):
        out = out.replace(lit, _REDACTED)
    for pat in _SECRET_PATTERNS:
        if pat.groups:
            out = pat.sub(lambda m: m.group(1) + _REDACTED, out)
        else:
            out = pat.sub(_REDACTED, out)
    out = " ".join(out.split())
    if len(out) > _MAX_ERROR_CHARS:
        out = out[:_MAX_ERROR_CHARS] + "..."
    return out


class EmbedderRuntime:
    def __init__(
        self,
        *,
        provider_store: Any,
        secret_store: Any,
        embed_provider_id: str,
        embed_model: str,
        embed_dims: int,
        fallback_embedder: Any,
        provider_class: Callable[..., Any] | None = None,
    ) -> None:
        self._provider_store = provider_store
        self._secret_store = secret_store
        self._embed_provider_id = embed_provider_id
        self._embed_model = embed_model
        self._embed_dims = embed_dims
        self._fallback = fallback_embedder
        # Injectable so tests need not import the bundle's Vertex provider.
        self._provider_class = provider_class
        self._lock = threading.RLock()
        self.mode = MODE_STUB
        # Why the last attempt to start the Vertex embedder failed (None when
        # it has not failed or the latest attempt worked).
        self.last_error: str | None = None
        self._embedder: Any = fallback_embedder
        self._memory_store: Any = None
        self._kb: Any = None
        # Called (once, from the refresh thread) when the mode flips from stub
        # to vertex. main.py uses it to re-index the bundled knowledge base:
        # its documents were embedded by the stub and are skipped by search
        # until they are re-embedded.
        self.on_vertex_activated: Callable[[], None] | None = None
        # True while the last bundled-KB load did not finish (the loader's
        # circuit breaker aborted it). main.py wires it; a successful embedder
        # install then re-runs the load even if no stored document is stale.
        self.kb_load_incomplete: Callable[[], bool] | None = None
        # Secret values the Vertex provider was last built from, so an error
        # that echoes one back is redacted before it is stored or shown.
        self._secret_literals: tuple[str, ...] = ()

    # ─── Provider lookup ──────────────────────────────────────────

    def _vertex_instances(self) -> list[Any]:
        return [
            p for p in self._provider_store.list_all()
            if p.provider_id == VERTEX_PROVIDER_ID
        ]

    def build_vertex_provider(self) -> Any:
        """Build the Vertex provider from the stores as they are NOW.

        Also the VertexEmbedder's own credential-refresh path
        (`provider_factory`), so a key the operator replaces later is picked
        up without a restart.
        """
        current = self._vertex_instances()
        if not current:
            raise RuntimeError("no Vertex provider is configured")
        inst = current[0]
        provider_class = self._provider_class
        if provider_class is None:
            from providers.vertex.src.provider import Provider as provider_class
        # Resolve secret-store paths to literal values for the provider
        # __init__. Keep config + secrets split to match its two-arg
        # constructor.
        resolved: dict[str, Any] = {}
        for slot, ref in inst.secret_refs.items():
            if isinstance(ref, str) and ref.startswith("/") and self._secret_store:
                if not is_own_secret_ref(inst.id, slot, ref):
                    # Not this slot's own path: never follow it into another secret.
                    logger.warning("vertex secret for %s is a foreign reference; not resolving it", slot)
                    resolved[slot] = ""
                    continue
                try:
                    resolved[slot] = self._secret_store.read(ref)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("vertex secret resolve failed for %s: %s", slot, exc)
                    resolved[slot] = ""
            else:
                resolved[slot] = ref
        self._secret_literals = tuple(v for v in resolved.values() if isinstance(v, str))
        return provider_class(config=dict(inst.config), secrets=resolved)

    def _new_vertex_embedder(self) -> Any:
        from usecase.vertex_embedder import VertexEmbedder

        # `fallback=` is deliberately not passed: VertexEmbedder ignores it
        # and raises on a per-call failure.
        return VertexEmbedder(
            provider=self.build_vertex_provider(),
            model_id=self._embed_model,
            dims=self._embed_dims,
            provider_factory=self.build_vertex_provider,
        )

    def _probe(self, embedder: Any) -> None:
        """Prove the credentials with one real embed() call, with a deadline.

        Runs on a daemon thread so a hung connection costs at most
        PROBE_TIMEOUT_S; the abandoned thread ends when its own HTTP timeout
        does. Raises whatever the call raised, or TimeoutError.
        """
        box: dict[str, BaseException | list[float]] = {}

        def run() -> None:
            try:
                box["vec"] = embedder.embed(PROBE_TEXT)
            except BaseException as exc:  # noqa: BLE001
                box["err"] = exc

        t = threading.Thread(target=run, name="embedder-probe", daemon=True)
        t.start()
        t.join(PROBE_TIMEOUT_S)
        if t.is_alive():
            raise TimeoutError(f"probe embed() call timed out after {PROBE_TIMEOUT_S:g}s")
        if "err" in box:
            raise box["err"]  # type: ignore[misc]

    def _kb_needs_reindex(self) -> bool:
        """True when the KB holds documents the live embedder did not produce,
        or the last bundled load did not finish."""
        try:
            if self.kb_load_incomplete is not None and self.kb_load_incomplete():
                return True
            counter = getattr(self._kb, "count_stale_embeddings", None)
            if counter is None:
                return False
            return counter(getattr(self._embedder, "model_id", "")) > 0
        except Exception:  # noqa: BLE001
            logger.exception("could not tell whether the knowledge base needs a re-index")
            return False

    # ─── Selection ────────────────────────────────────────────────

    def select_initial(self) -> Any:
        """Boot-time choice. Returns the embedder to construct the stores with."""
        with self._lock:
            self._reevaluate(boot=True)
            return self._embedder

    def attach(self, memory_store: Any, kb: Any) -> None:
        """Register the stores a later refresh() swaps the embedder into."""
        with self._lock:
            self._memory_store = memory_store
            self._kb = kb

    def refresh(self, reason: str = "provider saved") -> str:
        """Re-decide the embedder from the current provider store. Returns the mode.

        Blocks while the new embedder is probed (up to PROBE_TIMEOUT_S): call it
        from a worker thread when on the event loop.
        """
        with self._lock:
            before = self.mode
            installed = self._reevaluate(boot=False, reason=reason)
            flipped = installed and before != MODE_VERTEX and self.mode == MODE_VERTEX
        # Outside the lock: the callback may take long (it re-embeds the KB).
        # Re-index on the flip, and after any other successful install while
        # the KB still holds documents this embedder did not produce.
        if installed and self.on_vertex_activated is not None and (
            flipped or self._kb_needs_reindex()
        ):
            try:
                self.on_vertex_activated()
            except Exception:  # noqa: BLE001
                logger.exception("embedder activation callback failed")
        return self.mode

    def _reevaluate(self, *, boot: bool, reason: str = "boot") -> bool:
        """Apply the current provider store. Returns True when a new Vertex
        embedder was installed."""
        if self._embed_provider_id != "google":
            # No embedding provider declared in the manifest: bundle author
            # probably forgot. Stay on the stub.
            if boot:
                logger.warning(
                    "Embedder=TextHash (DEGRADED). manifest.memory.embeddingProvider "
                    "not set to google, so the bundle declares no embedding model. "
                    "Set manifest.memory.embeddingProvider=google + embeddingModel="
                    "text-embedding-004 to enable Vertex.",
                )
            self._publish()
            return False
        if not self._vertex_instances():
            if self.mode == MODE_VERTEX:
                logger.warning(
                    "Vertex provider removed (%s). The running embedder keeps its last "
                    "credentials until the MCP restarts; after a restart it falls back "
                    "to the stub until a Vertex provider is saved on /providers.",
                    reason,
                )
            else:
                logger.warning(
                    "Embedder=TextHash (DEGRADED). No Vertex provider is configured. "
                    "Memory + KB search returns hash-similarity scores, NOT semantic "
                    "matches. Add Vertex on /providers; it takes effect immediately.",
                )
            self.last_error = None
            self._publish()
            return False
        try:
            embedder = self._new_vertex_embedder()
            self._probe(embedder)
        except Exception as exc:  # noqa: BLE001
            # A Vertex provider exists but would not initialise or its key was
            # rejected: closer to a config bug than a transient outage, so log
            # at ERROR. Keep whatever embedder is live (stub at boot, or the
            # previous Vertex one). Never let key material reach the log, the
            # health report or /providers.
            reason_text = redact_secrets(f"{type(exc).__name__}: {exc}", self._secret_literals)
            self.last_error = reason_text
            logger.error(
                "Embedder stays %s (%s). Could not start the Vertex embedder: %s. "
                "Check the Vertex provider's project, region and service-account "
                "JSON on /providers.",
                self.mode, reason, reason_text,
            )
            self._publish()
            return False
        self.last_error = None
        self._embedder = embedder
        self.mode = MODE_VERTEX
        if self._memory_store is not None:
            self._memory_store.set_embedder(embedder)
        if self._kb is not None:
            self._kb.set_embedder(embedder)
        self._publish()
        logger.info(
            "Embedder=Vertex (model=%s, dims=%d) (%s): authoritative; no per-call "
            "demotion to TextHash. Failures will raise.",
            self._embed_model, self._embed_dims, reason,
        )
        return True

    def _publish(self) -> None:
        """Mirror the decision to the process-wide accessors."""
        from usecase.vertex_embedder import VertexEmbedder, set_embedder

        set_embedder(self._embedder if isinstance(self._embedder, VertexEmbedder) else None)
        # Kept for out-of-process readers that only have the env (a docker exec
        # shell); in-process readers use `mode` directly.
        os.environ["PHANTOM_EMBEDDER_MODE"] = self.mode

    # ─── Reporting ────────────────────────────────────────────────

    @property
    def embedder_model_id(self) -> str:
        return str(getattr(self._embedder, "model_id", "unknown"))

    def warning(self) -> str | None:
        """What the operator must do to leave stub mode, or None when live."""
        if self.mode == MODE_VERTEX:
            try:
                provider_present = bool(self._vertex_instances())
            except Exception:  # noqa: BLE001
                provider_present = True
            if not provider_present:
                return (
                    "The Vertex provider was removed. Embedding still works on the "
                    "credentials it had, but after the next restart search falls back "
                    "to the stub. Add the Vertex provider again on /providers."
                )
            if self.last_error:
                return (
                    f"Vertex embedder could not start: {self.last_error}, check "
                    "/providers. Embedding continues on the previous credentials "
                    "until they stop working; no restart is needed after fixing it."
                )
            return None
        if self._embed_provider_id != "google":
            return (
                "The bundle declares no embedding provider (manifest "
                "memory.embeddingProvider), so semantic search uses hash-similarity "
                "instead of real embeddings."
            )
        if self.last_error:
            return (
                f"Vertex embedder could not start: {self.last_error}, check "
                "/providers (project, region and service-account JSON). Search stays on "
                "hash-similarity until it is fixed; no restart is needed."
            )
        return (
            "Embedder is in stub mode: semantic search returns hash-similarity, not "
            "real embeddings, because no Vertex provider is configured. Add one on "
            "/providers (Google Vertex AI); it takes effect as soon as it is saved, "
            "no restart. Chat does not depend on it."
        )

    def is_fault(self) -> bool:
        """True when `warning()` describes something broken, False when it only
        describes the normal state of an install without Vertex.

        Embeddings are Vertex-only, so an install that runs its chat on Claude
        or OpenAI alone has no Vertex provider and stays on the stub on
        purpose. That is a limit worth telling the operator about, not a fault,
        and `health_status` must not report the install as unhealthy for it.
        Still a fault: a Vertex embedder that is configured but cannot start
        (`last_error`), a Vertex provider removed while its embedder is still
        running on the old credentials (it degrades at the next restart), and a
        bundle that declares no embedding provider.
        """
        if self.warning() is None:
            return False
        if self._embed_provider_id != "google":
            return True
        if self.last_error:
            return True
        return self.mode == MODE_VERTEX


_runtime: EmbedderRuntime | None = None


def set_embedder_runtime(rt: EmbedderRuntime | None) -> None:
    global _runtime
    _runtime = rt


def embedder_runtime() -> EmbedderRuntime | None:
    return _runtime
