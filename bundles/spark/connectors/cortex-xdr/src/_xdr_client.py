"""Cortex XDR API HTTP client — minimal, async, stateless.

Mirrors the XSIAM connector's _papi_client.py auth/header pattern
(both products use the same /public_api/v1/... family with
Authorization + x-xdr-auth-id headers) but trimmed to just what the
tool surface needs: POST a JSON body, get a JSON response,
surface 401/403/5xx as distinct exception types so the connector
wrapper can map them to operator-actionable error envelopes.

No retry logic in this layer — the connector wrapper handles
transient retries at the tool level if needed. No global state —
each tool invocation builds its own client from the resolved
instance config.
"""
from __future__ import annotations

import json
import logging
from typing import Optional

import httpx


logger = logging.getLogger(__name__)


class XDRError(Exception):
    """Base for Cortex XDR API errors."""


class XDRAuthError(XDRError):
    """401/403 — bad api_key or api_id."""


class XDRRateLimitError(XDRError):
    """429 — per-tenant rate limit. Caller can retry after a delay."""


class XDRServerError(XDRError):
    """5xx — upstream XDR side. Caller can retry."""


class XDRRequestError(XDRError):
    """4xx other than 401/403/429 — caller's request shape is bad."""


class XDRResponseError(XDRError):
    """200 OK but body isn't valid JSON or has unexpected shape."""


class Fetcher:
    """Stateless Cortex XDR API client.

    Usage:
        f = Fetcher(api_url, api_key, api_id)
        result = await f.post("/incidents/get_incidents", {"request_data": {...}})
    """

    def __init__(self, api_url: str, api_key: str, api_id: str):
        # Normalize url: strip trailing /, ensure /public_api/v1 suffix.
        url = api_url.rstrip("/")
        if "/public_api" not in url:
            url = f"{url}/public_api/v1"
        elif not url.endswith("/public_api/v1"):
            url = url.split("/public_api")[0].rstrip("/") + "/public_api/v1"
        self.url = url
        self.api_key = api_key
        self.api_id = str(api_id)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": self.api_key,
            "x-xdr-auth-id": self.api_id,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def post(
        self,
        path: str,
        body: Optional[dict] = None,
        *,
        timeout_seconds: float = 30.0,
    ) -> dict:
        """POST to `{url}{path}` with the auth headers. Returns parsed JSON.

        Raises one of the XDRError subclasses on non-2xx responses.
        """
        # Ensure path starts with /
        if not path.startswith("/"):
            path = "/" + path
        # Don't double the /public_api/v1 prefix if caller included it
        if path.startswith("/public_api/v1"):
            path = path[len("/public_api/v1") :]
            if not path.startswith("/"):
                path = "/" + path

        full_url = f"{self.url}{path}"
        timeout = httpx.Timeout(timeout_seconds, connect=10.0)

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                r = await client.post(full_url, headers=self._headers(), json=body or {})
        except httpx.HTTPError as exc:
            raise XDRError(f"network error talking to XDR: {type(exc).__name__}: {exc}") from exc

        if r.status_code == 200:
            try:
                return r.json()
            except json.JSONDecodeError as exc:
                raise XDRResponseError(
                    f"non-JSON 200 from {path}: {r.text[:200]}"
                ) from exc

        if r.status_code in (401, 403):
            raise XDRAuthError(
                f"HTTP {r.status_code} from {path} (auth failed — check api_key + api_id)"
            )
        if r.status_code == 429:
            raise XDRRateLimitError(
                f"HTTP 429 from {path} (per-tenant rate limit)"
            )
        if r.status_code >= 500:
            raise XDRServerError(
                f"HTTP {r.status_code} from {path}: {r.text[:200]}"
            )
        # Other 4xx
        raise XDRRequestError(
            f"HTTP {r.status_code} from {path}: {r.text[:200]}"
        )

    async def get_bytes(
        self,
        url: str,
        *,
        timeout_seconds: float = 60.0,
    ) -> bytes:
        """GET raw bytes from an XDR-issued download URL.

        Used by xdr_download_file when XDR returns a one-shot file URL
        from a prior retrieval action. The URL is fully-qualified and
        already includes the auth context (signed token in the path);
        we still send the bearer headers to be safe (XDR ignores them
        when the URL is pre-signed).
        """
        timeout = httpx.Timeout(timeout_seconds, connect=10.0)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                r = await client.get(url, headers=self._headers())
        except httpx.HTTPError as exc:
            raise XDRError(f"network error fetching {url[:80]}: {exc}") from exc

        if r.status_code == 200:
            return r.content
        if r.status_code in (401, 403):
            raise XDRAuthError(
                f"HTTP {r.status_code} downloading file (auth failed or URL expired)"
            )
        if r.status_code == 404:
            raise XDRRequestError(
                f"HTTP 404 from {url[:80]} (file_link may have expired)"
            )
        raise XDRRequestError(
            f"HTTP {r.status_code} downloading file: {r.text[:200]}"
        )
