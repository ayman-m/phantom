"""Google Cloud Vertex AI provider — minimal class wrapper for the
embedded MCP runtime.

Per spark-agents spec v1.2 §7.6, the runtime imports this module's
`Provider` class, instantiates it once per configured provider
instance, and uses it to:

  - `list_models()` → enumerate the available model catalog (defaults
    to the static spec.models[] from provider.yaml)
  - `chat(model_id, messages, **kwargs)` → run a chat completion
  - `embed(model_id, text)` → generate embeddings

For Phantom's first cut, this class is a thin contract holder. The
agent's actual Gemini calls still happen in the Next.js layer using
`@google-cloud/aiplatform` against the same project_id + service
account JSON the operator supplies at setup. Wiring those Next.js
calls through this Provider class is a follow-up — the contract
exists so future code paths (e.g. server-side embedding for memory)
can use the same pattern.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger("Phantom MCP")


class Provider:
    """Vertex AI provider — operates against one configured instance.

    Per the v1.2 spec, the runtime instantiates this class once per
    provider instance, passing the resolved config + secrets dict.
    """

    # Region used for text-embedding-* :predict calls when the
    # configured `region` is "global" (which is valid for Gemini-3
    # chat but NOT for embedding's regional predict endpoint).
    # us-central1 is the canonical availability region for
    # text-embedding-004 and serves projects regardless of where
    # they're billed.
    EMBEDDING_FALLBACK_REGION = "us-central1"

    def __init__(self, config: dict[str, Any], secrets: dict[str, Any]) -> None:
        self._project_id = config.get("project_id")
        self._region = config.get("region", "us-central1")
        self._service_account_json = secrets.get("serviceAccountJson") or secrets.get(
            "service_account_json"
        )
        if not self._project_id:
            raise ValueError("vertex provider: config.project_id is required")
        if not self._service_account_json:
            raise ValueError(
                "vertex provider: secrets.serviceAccountJson is required"
            )
        # Validate service account JSON is parseable. Don't crash on
        # bad SA JSON at module import time; defer to first real call
        # so misconfigured providers boot but fail loudly when used.
        try:
            sa = json.loads(self._service_account_json)
            if sa.get("type") != "service_account":
                logger.warning(
                    "vertex provider: serviceAccountJson type is %r, expected 'service_account'",
                    sa.get("type"),
                )
        except (json.JSONDecodeError, TypeError) as exc:
            logger.warning(
                "vertex provider: serviceAccountJson is not valid JSON: %s", exc
            )

        logger.info(
            "Vertex provider initialized for project %s in %s",
            self._project_id, self._region,
        )

    def list_models(self) -> list[dict[str, Any]]:
        """Return the static model catalog from provider.yaml.

        Override this when the connector/provider's actual API supports
        runtime catalog enumeration — for Vertex, the model list is
        relatively stable, so the static block in provider.yaml is the
        primary source of truth. The runtime reads provider.yaml's
        `spec.models` directly when this method isn't overridden, so
        bundles can rely on the static declaration.
        """
        # The runtime reads spec.models from provider.yaml; this is a
        # placeholder that signals "use the static catalog."
        return []

    async def chat(self, model_id: str, messages: list[dict[str, Any]], **kwargs: Any) -> dict[str, Any]:
        """Phase-4 placeholder. Actual Gemini calls happen in the
        Next.js layer today using @google-cloud/aiplatform. When the
        embedded MCP needs to call Gemini server-side (e.g. for tool
        argument inference), this method becomes the dispatch point.
        """
        raise NotImplementedError(
            "vertex Provider.chat() is not wired in this phase. The Next.js "
            "agent calls Vertex directly via @google-cloud/aiplatform; this "
            "class exists as a contract for future server-side use."
        )

    def embed(self, model_id: str, text: str) -> list[float]:
        """Run a synchronous text-embedding-004 (or compatible) call
        against Vertex AI's REST predict endpoint.

        Why sync (not async): the Embedder protocol the memory + KB
        stores expect is sync, and embedding is a single request/
        response — there's nothing to stream. Caller-side concurrency
        is fine via thread pools if needed.

        Path:
          POST https://{REGION}-aiplatform.googleapis.com/v1/
            projects/{PROJECT}/locations/{REGION}/publishers/google/
            models/{MODEL}:predict
          Authorization: Bearer <oauth2-access-token>
          { "instances": [{"content": "<text>"}] }
        Response:
          { "predictions": [{"embeddings": {"values": [...]}}] }
        """
        if not isinstance(text, str):
            raise TypeError("text must be a string")
        if not text.strip():
            # Vertex rejects empty content with a 400; return zero vector
            # so callers don't need to special-case empty strings.
            return [0.0] * self._embedding_dims_for(model_id)

        # Vertex's `:predict` endpoint for text-embedding-* is REGIONAL.
        # `global-aiplatform.googleapis.com` does NOT exist — only
        # specific regions host the embedding endpoint. The chat route
        # uses region="global" for Gemini-3 (which DOES have a global
        # endpoint via aiplatform.googleapis.com without a region
        # prefix), so deploys often pick "global" in the provider
        # config. For embeds, we substitute a regional endpoint that's
        # known to host text-embedding-004. us-central1 is the canonical
        # availability region and serves any global project.
        #
        # Without this, every embed call hit `global-aiplatform.
        # googleapis.com` which is a non-existent hostname. The DNS
        # might resolve (Google's wildcard) to a Google web frontend,
        # which returns the *HTML 404 page* (not a JSON API error)
        # we observed in the boot logs — and SqliteMemoryStore +
        # SqliteKnowledgeBase silently fell back to TextHashEmbedder
        # for every write/search, defeating semantic memory entirely.
        embed_region = self._region
        if embed_region == "global" or not embed_region:
            embed_region = self.EMBEDDING_FALLBACK_REGION

        access_token = self._get_access_token()
        url = (
            f"https://{embed_region}-aiplatform.googleapis.com/v1/projects/"
            f"{self._project_id}/locations/{embed_region}/publishers/google/"
            f"models/{model_id}:predict"
        )
        body = {"instances": [{"content": text}]}
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }
        # httpx.Client used in a `with` block so the connection pool is
        # cleaned up after each call. Embedding cadence is low enough
        # that long-lived pooling isn't a perf concern; correctness +
        # leak-free shutdown matter more.
        import httpx
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(url, json=body, headers=headers)
        if resp.status_code != 200:
            raise RuntimeError(
                f"vertex embed: {resp.status_code} {resp.text[:300]}"
            )
        data = resp.json()
        try:
            values = data["predictions"][0]["embeddings"]["values"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(
                f"vertex embed: unexpected response shape — {exc}: {data!r}"
            )
        return [float(v) for v in values]

    # ─────────────────────────────────────────────────────────────
    # Auth + utilities
    # ─────────────────────────────────────────────────────────────

    @staticmethod
    def _embedding_dims_for(model_id: str) -> int:
        """Default dim per model. Today text-embedding-004 → 768; gecko
        → 768 as well. Future models with different dims would extend
        this table."""
        return 768

    def _get_access_token(self) -> str:
        """Return a fresh OAuth2 bearer for the Vertex AI scope.
        Cached on the instance until 60s before expiry — google-auth's
        Credentials.refresh() handles the renewal."""
        creds = self._creds()
        # google-auth's Credentials caches the token internally; calling
        # refresh() here is what fetches a new one when expired.
        if not creds.valid:
            from google.auth.transport.requests import Request
            creds.refresh(Request())
        return creds.token

    def _creds(self):
        """Build google.oauth2 service-account credentials from the
        operator-supplied JSON. Cached on the instance after first build."""
        if getattr(self, "_creds_cache", None) is not None:
            return self._creds_cache
        try:
            from google.oauth2 import service_account
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "google-auth is not installed. Add `google-auth` to the MCP "
                "image's requirements.txt to enable real Vertex embeddings."
            ) from exc
        sa_dict = json.loads(self._service_account_json)
        creds = service_account.Credentials.from_service_account_info(
            sa_dict,
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )
        self._creds_cache = creds
        return creds
