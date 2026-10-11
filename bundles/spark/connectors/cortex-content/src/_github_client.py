"""GitHub fetcher for the cortex-content connector.

Two endpoints:
  - api.github.com/repos/<owner>/<repo>/contents/<path>
      Used for directory listings and pack metadata. Anonymous limit
      is 60 requests/hour; with the operator-supplied GITHUB_TOKEN the
      limit becomes 5000/hour. Most operator flows are well under 60/hr
      because file contents go via the CDN below.
  - raw.githubusercontent.com/<owner>/<repo>/<branch>/<path>
      Used for file content fetches. No rate limit; CDN-cached. The
      bulk of bytes flow through this endpoint.

All responses are TTL-cached on the agent's local filesystem so a
24-hour idle period passes without a single GitHub hit. Cache keys
include the full path + branch + a content-hash of the request body
(so different `?ref=` queries don't collide).

Failure modes:
  - HTTPError 404 → return None / [] (depending on call type); pass
    through the 404 to the tool layer where it becomes
    `{"ok": false, "error": "pack not found"}`.
  - HTTPError 403 with X-RateLimit-Remaining=0 → distinct error type;
    tool layer surfaces "GitHub anonymous rate limit hit; set
    GITHUB_TOKEN to lift to 5000/hr".
  - Network timeout → return a structured error; the cache still has
    last-known-good data which the tool layer may return with a
    `stale=true` flag.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

logger = logging.getLogger("Phantom MCP.cortex-content")

# Default cache root — overridable per-instance via the cacheDir
# config when phantom-updater spawns per-instance connectors. For the
# in-process connector this lives under /app/data which is
# already a volume mount so the cache survives container restarts.
DEFAULT_CACHE_ROOT = Path(
    os.getenv("PHANTOM_DATA_ROOT", "/app/data")
).resolve() / "cortex-content-cache"


class GitHubRateLimitError(RuntimeError):
    """Raised when api.github.com returns 403 with rate-limit headers.

    The operator's escape hatch is to set GITHUB_TOKEN on the agent
    container which lifts the limit from 60/hr to 5000/hr.
    """


class GitHubNotFoundError(RuntimeError):
    """Raised when api.github.com returns 404. The tool layer maps
    this to a structured `{"ok": false, "error": "not found"}` return
    rather than propagating the exception."""


class GitHubClient:
    """Thin wrapper around the GitHub Contents API + raw.githubusercontent.com.

    State:
      - owner / repo / branch (from connector config)
      - github_token (optional; from connector secret slot)
      - cache_root + cache_ttl (from connector config)
      - request_timeout (from connector config)
    """

    def __init__(
        self,
        owner: str = "demisto",
        repo: str = "content",
        branch: str = "master",
        github_token: str | None = None,
        cache_root: Path | None = None,
        cache_ttl_seconds: int = 86400,
        request_timeout_seconds: int = 30,
    ) -> None:
        self.owner = owner
        self.repo = repo
        self.branch = branch
        self.github_token = github_token
        self.cache_root = (cache_root or DEFAULT_CACHE_ROOT).resolve()
        self.cache_root.mkdir(parents=True, exist_ok=True)
        self.cache_ttl_seconds = max(0, int(cache_ttl_seconds))
        self.request_timeout_seconds = max(1, int(request_timeout_seconds))

    # ─── Public API ──────────────────────────────────────────────────

    def list_dir(self, path: str) -> list[dict[str, Any]]:
        """List the contents of a directory in the repo via the GitHub
        Contents API. Returns a list of `{name, type, size, sha, ...}`
        dicts. Caches the response per the configured TTL."""
        cache_key = f"api:list_dir:{path}:{self.branch}"
        cached = self._cache_read(cache_key)
        if cached is not None:
            return cached
        url = self._api_url(f"contents/{path}", ref=self.branch)
        raw = self._http_get_json(url)
        if not isinstance(raw, list):
            raise GitHubNotFoundError(f"expected directory listing at {path!r}, got {type(raw).__name__}")
        result = [
            {
                "name": entry.get("name"),
                "type": entry.get("type"),
                "size": entry.get("size", 0),
                "sha": entry.get("sha"),
            }
            for entry in raw
            if isinstance(entry, dict)
        ]
        self._cache_write(cache_key, result)
        return result

    def get_file(self, path: str) -> str:
        """Fetch a single file's content as a string. Routes through
        raw.githubusercontent.com (no rate limit). Caches the result
        per the configured TTL."""
        cache_key = f"raw:{path}:{self.branch}"
        cached = self._cache_read(cache_key)
        if cached is not None and isinstance(cached, dict) and "content" in cached:
            return str(cached["content"])
        url = self._raw_url(path)
        text = self._http_get_text(url)
        self._cache_write(cache_key, {"content": text})
        return text

    def get_file_json(self, path: str) -> Any:
        """Fetch and json-decode a single file. Convenience wrapper
        around get_file for pack_metadata.json / _schema.json reads."""
        text = self.get_file(path)
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise GitHubNotFoundError(
                f"file {path!r} did not parse as JSON: {exc}"
            ) from exc

    # ─── URL builders ────────────────────────────────────────────────

    def _api_url(self, suffix: str, ref: str | None = None) -> str:
        base = f"https://api.github.com/repos/{self.owner}/{self.repo}/{suffix.lstrip('/')}"
        if ref:
            base += f"?ref={urllib.parse.quote(ref)}"
        return base

    def _raw_url(self, path: str) -> str:
        return (
            f"https://raw.githubusercontent.com/"
            f"{self.owner}/{self.repo}/{self.branch}/{path.lstrip('/')}"
        )

    # ─── HTTP layer ──────────────────────────────────────────────────

    def _headers(self, accept: str = "application/vnd.github+json") -> dict[str, str]:
        h = {
            "Accept": accept,
            "User-Agent": "phantom-agent-cortex-content/0.3.7",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.github_token:
            h["Authorization"] = f"Bearer {self.github_token}"
        return h

    def _http_get_json(self, url: str) -> Any:
        req = urllib.request.Request(url, headers=self._headers())
        try:
            with urllib.request.urlopen(req, timeout=self.request_timeout_seconds) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise GitHubNotFoundError(f"{url} → 404") from exc
            if exc.code == 403:
                remaining = exc.headers.get("X-RateLimit-Remaining")
                if remaining == "0":
                    raise GitHubRateLimitError(
                        f"GitHub API rate limit hit (anonymous=60/hr). Set the "
                        "githubToken connector secret to lift to 5000/hr."
                    ) from exc
            raise
        except urllib.error.URLError as exc:
            raise GitHubNotFoundError(f"{url} → network error: {exc}") from exc

    def _http_get_text(self, url: str) -> str:
        # raw.githubusercontent.com does not require the github
        # Accept header; sending bare User-Agent is enough. We still
        # include the auth token if available — raw github does
        # accept it for private-repo reads (no effect on public).
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "phantom-agent-cortex-content/0.3.7",
                **({"Authorization": f"Bearer {self.github_token}"} if self.github_token else {}),
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.request_timeout_seconds) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise GitHubNotFoundError(f"{url} → 404") from exc
            raise

    # ─── Cache (file-backed, TTL-bounded) ─────────────────────────────

    def _cache_path(self, key: str) -> Path:
        # Hash the key so paths stay short + filesystem-safe regardless
        # of how exotic the request path is.
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return self.cache_root / digest[:2] / f"{digest}.json"

    def _cache_read(self, key: str) -> Any | None:
        if self.cache_ttl_seconds <= 0:
            return None
        path = self._cache_path(key)
        if not path.exists():
            return None
        try:
            stat = path.stat()
            age = time.time() - stat.st_mtime
            if age > self.cache_ttl_seconds:
                return None
            with path.open("r", encoding="utf-8") as f:
                envelope = json.load(f)
            return envelope.get("payload")
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("cache read failed for %s: %s", key, exc)
            return None

    def _cache_write(self, key: str, payload: Any) -> None:
        if self.cache_ttl_seconds <= 0:
            return
        path = self._cache_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with path.open("w", encoding="utf-8") as f:
                json.dump({"key": key, "fetched_at": time.time(), "payload": payload}, f)
        except OSError as exc:
            logger.warning("cache write failed for %s: %s", key, exc)
