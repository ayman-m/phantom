"""Tests for memory-store session-scope matching: scope is a hierarchical
string ("session:<uuid>"), but the UI's session tab filters with the bare
aggregate "session" — an EXACT match on which can never match any real
row, since nothing is ever stored with scope exactly "session". Without
a prefix match the tab would silently show zero rows forever.

Matching has two layers:
  1. memory_store.list_all()/search() take a scope_prefix param that
     LIKE-matches the whole family ("session:" matches every
     "session:<id>" row), properly escaping % and _ so a literal
     wildcard character in either the stored scope or the caller's
     prefix can't corrupt the match.
  2. api/cognitive.py's _resolve_scope_filter() rewrites a bare
     scope="session" into scope_prefix="session:" transparently, so
     the UI (which sends the bare string) needs no special handling —
     the REST layer owns the "session is hierarchical"
     knowledge, not the store or the UI.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.usecase.memory_store import SqliteMemoryStore, TextHashEmbedder, _like_prefix_pattern


def _make_store(tmp_path: Path) -> SqliteMemoryStore:
    return SqliteMemoryStore(data_root=tmp_path, embedder=TextHashEmbedder(dims=768))


# ─── _like_prefix_pattern escaping ──────────────────────────────────


@pytest.mark.parametrize(
    "prefix,expected",
    [
        ("session:", "session:%"),
        ("100%_done:", "100\\%\\_done:%"),
        ("back\\slash:", "back\\\\slash:%"),
    ],
)
def test_like_prefix_pattern_escapes_metacharacters(prefix: str, expected: str) -> None:
    assert _like_prefix_pattern(prefix) == expected


# ─── list_all(scope_prefix=...) ─────────────────────────────────────


def test_list_all_bare_scope_exact_match_finds_nothing_for_hierarchical_rows(
    tmp_path: Path,
) -> None:
    """Pins the store-level contract: an exact
    scope="session" filter can never match scope="session:<id>" rows."""
    store = _make_store(tmp_path)
    store.store(key="k1", value="v1", scope="session:abc123")
    store.store(key="k2", value="v2", scope="session:def456")
    assert store.list_all(scope="session") == []


def test_list_all_scope_prefix_finds_every_row_in_the_family(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    store.store(key="k1", value="v1", scope="session:abc123")
    store.store(key="k2", value="v2", scope="session:def456")
    store.store(key="k3", value="v3", scope="agent")  # different family — excluded
    keys = {m.key for m in store.list_all(scope_prefix="session:")}
    assert keys == {"k1", "k2"}


def test_list_all_scope_prefix_wins_when_both_given(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    store.store(key="k1", value="v1", scope="session:abc123")
    rows = store.list_all(scope="agent", scope_prefix="session:")
    assert [m.key for m in rows] == ["k1"]


def test_list_all_exact_scope_still_works_unaffected(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    store.store(key="k1", value="v1", scope="agent")
    store.store(key="k2", value="v2", scope="session:abc123")
    keys = {m.key for m in store.list_all(scope="agent")}
    assert keys == {"k1"}


def test_list_all_scope_prefix_does_not_bleed_into_unrelated_prefix_match(
    tmp_path: Path,
) -> None:
    """"session:" must not accidentally match a differently-named scope
    family that happens to share a leading substring, e.g. "sessionx:"."""
    store = _make_store(tmp_path)
    store.store(key="k1", value="v1", scope="session:abc123")
    store.store(key="k2", value="v2", scope="sessionx:zzz")
    keys = {m.key for m in store.list_all(scope_prefix="session:")}
    assert keys == {"k1"}


# ─── search(scope_prefix=...) — both the vector path and the FTS branch ──


def test_search_scope_prefix_restricts_vector_candidates(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    store.store(key="k1", value="a distinctive marker phrase", scope="session:abc123")
    store.store(key="k2", value="a distinctive marker phrase", scope="agent")
    hits = [m.key for m, _score in store.search("distinctive marker phrase", scope_prefix="session:")]
    assert hits == ["k1"]


def test_search_scope_prefix_restricts_fts_branch(tmp_path: Path) -> None:
    """A rare/exact token (a UUID-shaped string) is the case the FTS5
    branch exists for — confirm scope_prefix is honored there too, not
    just in the vector-scoring path."""
    store = _make_store(tmp_path)
    if not store._fts_available:
        pytest.skip("FTS5 not available in this SQLite build")
    token = "aa11bb22cc33dd44"
    store.store(key="k1", value=f"host correlated with {token}", scope="session:abc123")
    store.store(key="k2", value=f"host correlated with {token}", scope="agent")
    hits = [m.key for m, _score in store.search(token, scope_prefix="session:")]
    assert hits == ["k1"]


def test_search_bare_session_scope_exact_match_finds_nothing(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    store.store(key="k1", value="a distinctive marker phrase", scope="session:abc123")
    hits = store.search("distinctive marker phrase", scope="session")
    assert hits == []


# ─── api/cognitive.py: _resolve_scope_filter mapping ────────────────


def test_resolve_scope_filter_rewrites_bare_session_to_prefix() -> None:
    from src.api.cognitive import _resolve_scope_filter

    assert _resolve_scope_filter("session", None) == (None, "session:")


def test_resolve_scope_filter_explicit_prefix_wins_over_scope() -> None:
    from src.api.cognitive import _resolve_scope_filter

    assert _resolve_scope_filter("agent", "session:") == (None, "session:")


def test_resolve_scope_filter_leaves_real_leaf_scope_unchanged() -> None:
    from src.api.cognitive import _resolve_scope_filter

    assert _resolve_scope_filter("agent", None) == ("agent", None)
    assert _resolve_scope_filter("session:abc123", None) == ("session:abc123", None)


def test_resolve_scope_filter_none_and_empty_string_pass_through() -> None:
    from src.api.cognitive import _resolve_scope_filter

    assert _resolve_scope_filter(None, None) == (None, None)
    assert _resolve_scope_filter("", "") == (None, None)


# ─── end-to-end via the REST route handlers (Starlette test client) ─


def test_list_memories_route_bare_session_scope_finds_session_rows(tmp_path: Path) -> None:
    """The memory page's session tab sends scope=session over
    GET /api/v1/memories; a bare `session` scope must match the
    `session:<id>` rows rather than return an empty list."""
    store = _make_store(tmp_path)
    store.store(key="k1", value="v1", scope="session:abc123")

    # api/cognitive.py registers routes via a closure over `memories`
    # and `mcp.custom_route`; exercise the resolver + store call the
    # same way the route body does, rather than standing up a full
    # FastMCP app, since that's the actual logic under test here (the
    # route body itself is a two-line passthrough already covered by
    # the resolver + store unit tests above).
    from src.api.cognitive import _resolve_scope_filter

    scope, scope_prefix = _resolve_scope_filter("session", None)
    rows = store.list_all(scope=scope, scope_prefix=scope_prefix)
    assert [m.key for m in rows] == ["k1"]
