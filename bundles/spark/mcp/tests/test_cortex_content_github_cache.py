"""Cache-behavior tests for cortex-content/_github_client.py.

Scope: only the file-backed TTL cache layer (the `_cache_*` methods).
These tests intentionally skip urllib mocking — the HTTP layer is
better exercised live against the real GitHub API, since mocking
urllib.request requires intrusive monkeypatching that bears little
resemblance to the real failure modes (redirects, transient 502s,
content-encoding handling).

What the cache does that's worth defending with tests:
  - SHA256-hashed cache keys (path-traversal-safe regardless of how
    exotic the request key looks)
  - TTL via filesystem mtime — `_cache_read` returns None for entries
    older than `cache_ttl_seconds`
  - cache_ttl_seconds <= 0 disables the cache entirely
  - Corrupted cache JSON is treated as a miss (graceful), not an
    exception that crashes the request path

# Path resolution

Same synthetic-package import as test_cortex_content_index_kb.py to
sidestep the connector-src vs MCP-src namespace collision. See that
file for the full rationale.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any
from unittest import mock

import pytest


def _resolve_connector_src() -> Path:
    here = Path(__file__).resolve().parent
    candidates = [
        here.parent.parent / "connectors" / "cortex-content" / "src",
        Path("/app/bundle/connectors/cortex-content/src"),
    ]
    for c in candidates:
        if c.is_dir():
            return c
    raise ImportError(
        f"cortex-content/src not found in any of: {[str(c) for c in candidates]}"
    )


def _load_github_client_module() -> Any:
    """Synthetic package load — same pattern as the index_kb test.
    The GitHub client doesn't have relative imports, so we could
    load it directly, but using the synthetic-package path keeps
    both connector test files consistent and avoids reintroducing
    the src/ namespace collision."""
    import importlib.util

    src = _resolve_connector_src()
    pkg_name = "_cortex_test_pkg"  # same name as index_kb test → shared
    pkg = sys.modules.get(pkg_name)
    if pkg is None:
        spec_pkg = importlib.util.spec_from_loader(pkg_name, loader=None)
        pkg = importlib.util.module_from_spec(spec_pkg)
        pkg.__path__ = [str(src)]
        sys.modules[pkg_name] = pkg

    full = f"{pkg_name}._github_client"
    if full not in sys.modules:
        spec_gh = importlib.util.spec_from_file_location(
            full, src / "_github_client.py",
        )
        gh = importlib.util.module_from_spec(spec_gh)
        sys.modules[full] = gh
        spec_gh.loader.exec_module(gh)
    return sys.modules[full]


_gh_mod = _load_github_client_module()
GitHubClient = _gh_mod.GitHubClient


@pytest.fixture
def client(tmp_path):
    """A GitHubClient pointed at a tmp cache root. Default TTL is
    high (1h) so tests that don't care about expiry get a deterministic
    no-expiry environment."""
    return GitHubClient(
        owner="demisto",
        repo="content",
        branch="master",
        cache_root=tmp_path / "cache",
        cache_ttl_seconds=3600,
    )


# ─── Round-trip + isolation ─────────────────────────────────────────


def test_write_then_read_returns_payload(client):
    """Basic round-trip: write a payload, read it back, get the
    same object shape."""
    client._cache_write("api:list_dir:Packs:master", [{"name": "F5APM", "type": "dir"}])
    out = client._cache_read("api:list_dir:Packs:master")
    assert out == [{"name": "F5APM", "type": "dir"}]


def test_read_with_no_cached_entry_returns_none(client):
    """A key that was never written returns None — distinguishable
    from a key that was written with payload=None (though we don't
    test the latter because the connector never writes None)."""
    assert client._cache_read("never:written:key") is None


def test_distinct_keys_produce_distinct_cache_paths(client):
    """SHA256 hashing means different keys hash to different paths
    deterministically. No collision on common variants."""
    p1 = client._cache_path("api:list_dir:Packs:master")
    p2 = client._cache_path("api:list_dir:Packs/F5APM:master")
    p3 = client._cache_path("api:list_dir:Packs:dev")
    assert p1 != p2
    assert p1 != p3
    assert p2 != p3


def test_same_key_produces_same_cache_path(client):
    """Cache path is deterministic for repeat reads of the same key."""
    assert client._cache_path("k") == client._cache_path("k")


# ─── TTL behavior ───────────────────────────────────────────────────


def test_expired_entry_returns_none(client, tmp_path):
    """Mtime older than cache_ttl_seconds → read returns None.
    Operators rely on this for "stale-by-default after 24h" semantics
    so a long-running container doesn't serve a year-old pack
    listing from cache."""
    key = "api:list_dir:Packs:master"
    client._cache_write(key, ["fresh content"])
    # Backdate the file's mtime to before the TTL window.
    path = client._cache_path(key)
    old = time.time() - (client.cache_ttl_seconds + 10)
    os.utime(str(path), (old, old))
    # Read should miss now.
    assert client._cache_read(key) is None


def test_zero_ttl_disables_cache(tmp_path):
    """cache_ttl_seconds=0 → reads always miss, writes always no-op.
    Used during development against a freshly-updated mirror where
    operators want the connector to bypass cache."""
    c = GitHubClient(
        cache_root=tmp_path / "cache",
        cache_ttl_seconds=0,
    )
    c._cache_write("k", "v")
    assert c._cache_read("k") is None


def test_negative_ttl_treated_as_zero(tmp_path):
    """Defensive: the constructor clamps cache_ttl_seconds at 0 so a
    negative value (operator typo) doesn't produce undefined behavior."""
    c = GitHubClient(
        cache_root=tmp_path / "cache",
        cache_ttl_seconds=-50,
    )
    assert c.cache_ttl_seconds == 0
    c._cache_write("k", "v")
    assert c._cache_read("k") is None


# ─── Corruption + IO robustness ────────────────────────────────────


def test_corrupted_cache_file_treated_as_miss(client):
    """If the cache JSON is corrupt (truncated write, manual edit),
    read returns None instead of raising. The connector then hits
    the network like a cold cache."""
    key = "k"
    path = client._cache_path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not { valid json", encoding="utf-8")
    assert client._cache_read(key) is None


def test_cache_envelope_structure(client):
    """Cache file is a JSON envelope: {key, fetched_at, payload}. The
    envelope is the on-disk contract — operators inspecting the cache
    dir can grep for keys, and the connector's `payload` extraction
    is checked against this shape."""
    client._cache_write("api:list_dir:Packs:master", ["item"])
    path = client._cache_path("api:list_dir:Packs:master")
    with path.open("r", encoding="utf-8") as f:
        envelope = json.load(f)
    assert envelope["key"] == "api:list_dir:Packs:master"
    assert envelope["payload"] == ["item"]
    assert isinstance(envelope["fetched_at"], (int, float))


def test_cache_path_is_subdir_of_cache_root(client):
    """No path traversal — even an adversarial key never escapes the
    cache root. SHA256 keys can't produce '..' sequences."""
    p = client._cache_path("../../../../../etc/passwd")
    # The path must resolve to a child of cache_root.
    assert str(p).startswith(str(client.cache_root))


def test_cache_path_uses_sharded_subdir(client):
    """Per the implementation, the cache path is
    <root>/<digest[:2]>/<digest>.json. The 2-char shard prevents
    one big flat dir from getting too many entries (filesystem
    perf cliff on some FSes around ~10k entries). This test asserts
    the shard exists as a parent of the file."""
    p = client._cache_path("some_key")
    # Two parents: root/<shard>/file.json
    assert p.parent.parent == client.cache_root
    # The shard name is 2 chars.
    assert len(p.parent.name) == 2


# ─── Read-failure isolation ─────────────────────────────────────────


def test_read_failure_emits_warning_but_returns_none(client, caplog):
    """When the underlying file read raises (permission, IO error,
    etc.), the cache layer logs a warning and returns None instead
    of propagating. The connector then proceeds as if cold-cache."""
    import logging
    caplog.set_level(logging.WARNING, logger="Phantom MCP.cortex-content")

    key = "k"
    client._cache_write(key, "v")
    # Now patch open to raise OSError on read.
    path = client._cache_path(key)
    real_open = Path.open

    def _fail_open(self: Path, *a: Any, **kw: Any):
        if self == path and "r" in (a[0] if a else kw.get("mode", "r")):
            raise OSError("simulated permission error")
        return real_open(self, *a, **kw)

    with mock.patch.object(Path, "open", _fail_open):
        out = client._cache_read(key)
    assert out is None
    assert any("cache read failed" in r.message for r in caplog.records)
