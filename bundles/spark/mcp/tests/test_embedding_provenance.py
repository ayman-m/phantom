"""Tests for embedding provenance — validating that a stored vector
and a live query vector came from the same embedding model before
trusting a cosine comparison between them.

Phantom silently switches between TextHashEmbedder (a SHA-256 stub,
not semantic) and VertexEmbedder (real semantic embeddings) depending
on whether a Vertex provider is materialized. Both are 768-dim, so
the existing dims check at store()/search() time cannot catch a swap
— cosine "succeeds" but compares vectors from two unrelated spaces,
producing a plausible-looking score that means nothing. This mixing
produces no error and no visible symptom, just quietly wrong
retrieval (the failure mode this section targets).

Covers both stores that carry the same structure:
  - memory_store.py: model_id on the Embedder protocol, persisted
    embedding_model per row, search() skipping (or FTS-keeping with a
    zeroed cosine) cross-model rows, a cumulative mismatch counter.
  - kb_store.py: the same, PLUS upsert()'s "unchanged" fast-path, which
    must not key off source_hash alone: completing /setup with Vertex
    creds touches no file on disk, so a hash-only check would leave
    every pre-existing KB doc silently stuck on its old TextHash vector
    forever.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from usecase.memory_store import SqliteMemoryStore, TextHashEmbedder
from usecase.kb_store import SqliteKnowledgeBase


class _FakeEmbedder:
    """Same hashing algorithm as TextHashEmbedder (so dims/vectors are
    self-consistent and won't raise on pack/unpack), but a distinct,
    caller-chosen model_id — isolates the tests below to the model_id
    filtering logic itself, independent of what makes two real models'
    vector spaces actually incomparable (that property is assumed,
    not what's under test here)."""

    def __init__(self, model_id: str, dims: int = 768) -> None:
        self.model_id = model_id
        self.dims = dims
        self._inner = TextHashEmbedder(dims=dims)

    def embed(self, text: str) -> list[float]:
        return self._inner.embed(text)


def _make_store(tmp_path: Path, embedder=None) -> SqliteMemoryStore:
    return SqliteMemoryStore(data_root=tmp_path, embedder=embedder or TextHashEmbedder(dims=768))


def _make_kb(tmp_path: Path, embedder=None) -> SqliteKnowledgeBase:
    return SqliteKnowledgeBase(data_root=tmp_path, embedder=embedder or TextHashEmbedder(dims=768))


# ─── model_id on the Embedder protocol ───────────────────────────────


def test_texthash_embedder_model_id_encodes_dims() -> None:
    assert TextHashEmbedder(dims=768).model_id == "texthash-v1-768d"
    assert TextHashEmbedder(dims=384).model_id == "texthash-v1-384d"


def test_texthash_and_a_same_dims_fake_never_collide_model_id() -> None:
    # The whole point: two embedders can share dims (both 768) while
    # having distinct model_id — dims alone can't distinguish them.
    a = TextHashEmbedder(dims=768)
    b = _FakeEmbedder("vertex:text-embedding-004", dims=768)
    assert a.dims == b.dims
    assert a.model_id != b.model_id


# ─── memory_store.py: persistence ────────────────────────────────────


def test_store_persists_embedding_model(tmp_path: Path) -> None:
    embedder = _FakeEmbedder("vertex:text-embedding-004")
    store = _make_store(tmp_path, embedder)
    m = store.store(key="k1", value="v1", scope="agent")
    assert m.embedding_model == "vertex:text-embedding-004"
    fetched = store.get(key="k1", scope="agent")
    assert fetched.embedding_model == "vertex:text-embedding-004"


def test_store_re_stores_with_the_now_live_embedder_model_id(tmp_path: Path) -> None:
    """Simulates a boot-to-boot embedder swap (e.g. Vertex creds
    submitted after running on the TextHash stub): re-storing the
    same key updates embedding_model to whatever's live NOW, not
    whatever it was originally."""
    store = _make_store(tmp_path, _FakeEmbedder("texthash-v1-768d"))
    store.store(key="k1", value="v1", scope="agent")
    store._embedder = _FakeEmbedder("vertex:text-embedding-004")
    m = store.store(key="k1", value="v1 updated", scope="agent")
    assert m.embedding_model == "vertex:text-embedding-004"
    assert store.get(key="k1", scope="agent").embedding_model == "vertex:text-embedding-004"


# ─── memory_store.py: search() cross-model handling ──────────────────


def test_search_excludes_mismatched_row_with_no_fts_justification(tmp_path: Path) -> None:
    store = _make_store(tmp_path, _FakeEmbedder("texthash-v1-768d"))
    # Deliberately shares no tokens with the query below, so FTS5
    # can't promote it — isolates the model_id skip from the
    # FTS-keeps-it-anyway branch (covered separately).
    store.store(key="stale", value="unrelated content zzqqxx", scope="agent")
    # Simulate the live process now running a different embedder —
    # the stale row's stored vector + embedding_model are untouched.
    store._embedder = _FakeEmbedder("vertex:text-embedding-004")
    store.store(key="fresh", value="a distinctive marker phrase", scope="agent")
    hits = [m.key for m, _score in store.search("distinctive marker phrase", scope="agent", min_score=0.0)]
    assert "fresh" in hits
    assert "stale" not in hits


def test_search_keeps_mismatched_row_when_fts_promoted_but_zeroes_its_score(
    tmp_path: Path,
) -> None:
    """The other half of the same branch: a mismatched row that DOES
    share the query's exact text is FTS-promoted, so it's kept (the
    keyword match is independently valid evidence) but its cosine is
    forced to 0.0 rather than trusted."""
    store = _make_store(tmp_path, _FakeEmbedder("texthash-v1-768d"))
    if not store._fts_available:
        pytest.skip("FTS5 not available in this SQLite build")
    store.store(key="stale-but-fts-matched", value="a distinctive marker phrase", scope="agent")
    store._embedder = _FakeEmbedder("vertex:text-embedding-004")
    hits = dict(
        (m.key, s) for m, s in store.search("distinctive marker phrase", scope="agent")
    )
    assert "stale-but-fts-matched" in hits
    assert hits["stale-but-fts-matched"] == 0.0


def test_search_matching_model_id_is_unaffected(tmp_path: Path) -> None:
    embedder = _FakeEmbedder("vertex:text-embedding-004")
    store = _make_store(tmp_path, embedder)
    store.store(key="k1", value="a distinctive marker phrase", scope="agent")
    hits = [m.key for m, _score in store.search("distinctive marker phrase", scope="agent")]
    assert "k1" in hits


def test_search_null_embedding_model_pre_migration_row_treated_as_mismatch(
    tmp_path: Path,
) -> None:
    """A legacy row written before provenance was recorded
    (embedding_model IS NULL in the DB) must be treated as unknown provenance, not assumed-safe —
    it degrades exactly like a genuine mismatch, not like a match."""
    import sqlite3

    store = _make_store(tmp_path, _FakeEmbedder("vertex:text-embedding-004"))
    # No shared tokens with the query — same rationale as the sibling
    # test above: isolates the null-model skip from FTS promotion.
    m = store.store(key="old", value="unrelated content zzqqxx", scope="agent")
    with sqlite3.connect(str(store._db_path)) as c:
        c.execute("UPDATE memories SET embedding_model = NULL WHERE id = ?", (m.id,))
    hits = [mem.key for mem, _score in store.search("distinctive marker phrase", scope="agent")]
    assert "old" not in hits


def test_search_increments_cumulative_mismatch_counter(tmp_path: Path) -> None:
    store = _make_store(tmp_path, _FakeEmbedder("texthash-v1-768d"))
    store.store(key="stale", value="a distinctive marker phrase", scope="agent")
    store._embedder = _FakeEmbedder("vertex:text-embedding-004")
    assert store.embedding_model_mismatches == 0
    store.search("distinctive marker phrase", scope="agent")
    assert store.embedding_model_mismatches == 1
    store.search("distinctive marker phrase", scope="agent")
    assert store.embedding_model_mismatches == 2


def test_search_audit_event_carries_mismatch_count(tmp_path: Path) -> None:
    import json
    import sqlite3

    from usecase.audit_log import ACTION_MEMORY_SEARCHED, SqliteAuditLog, set_audit_log

    log = SqliteAuditLog(data_root=tmp_path / "audit")
    set_audit_log(log)
    try:
        store = _make_store(tmp_path, _FakeEmbedder("texthash-v1-768d"))
        store.store(key="stale", value="a distinctive marker phrase", scope="agent")
        store._embedder = _FakeEmbedder("vertex:text-embedding-004")
        store.search("distinctive marker phrase", scope="agent")
        with sqlite3.connect(str(log._db_path)) as c:
            c.row_factory = sqlite3.Row
            row = c.execute(
                "SELECT metadata_json FROM audit_events WHERE action = ? "
                "ORDER BY rowid DESC LIMIT 1",
                (ACTION_MEMORY_SEARCHED,),
            ).fetchone()
        assert json.loads(row["metadata_json"])["embedding_model_mismatches"] == 1
    finally:
        set_audit_log(None)


# ─── kb_store.py: the actual corruption site ─────────────────────────


def test_kb_upsert_unchanged_fast_path_requires_matching_embedder(tmp_path: Path) -> None:
    """The corruption this guards against: completing /setup with
    Vertex creds touches no file on disk, so every pre-existing doc's
    source_hash still matches — the OLD fast path would return
    "unchanged" and never re-embed, silently stranding every
    pre-existing doc on its stale vector forever."""
    kb = _make_kb(tmp_path, _FakeEmbedder("texthash-v1-768d"))
    doc, action = kb.upsert(
        kb_name="test", doc_id="d1", content="some content",
        source_hash="samehash",
    )
    assert action == "insert"
    assert doc.embedding_model == "texthash-v1-768d"

    # Same content (same hash) but the live embedder changed —
    # must re-embed, not report "unchanged".
    kb._embedder = _FakeEmbedder("vertex:text-embedding-004")
    doc2, action2 = kb.upsert(
        kb_name="test", doc_id="d1", content="some content",
        source_hash="samehash",
    )
    assert action2 == "update"
    assert doc2.embedding_model == "vertex:text-embedding-004"


def test_kb_upsert_genuinely_unchanged_still_skips_re_embed(tmp_path: Path) -> None:
    """Negative control — the provenance check must not turn every
    upsert into a forced re-embed. Same hash AND same embedder => still "unchanged"."""
    embedder = _FakeEmbedder("vertex:text-embedding-004")
    kb = _make_kb(tmp_path, embedder)
    kb.upsert(kb_name="test", doc_id="d1", content="c", source_hash="h1")
    _doc, action = kb.upsert(kb_name="test", doc_id="d1", content="c", source_hash="h1")
    assert action == "unchanged"


def test_kb_search_excludes_null_embedding_model_doc(tmp_path: Path) -> None:
    """Same null-is-not-safe rule as memory_store — a condition of the
    form `row_model is not None and row_model != live_id` would let a
    NULL row_model short-circuit past the check entirely and get
    silently trusted."""
    import sqlite3

    kb = _make_kb(tmp_path, _FakeEmbedder("vertex:text-embedding-004"))
    doc, _action = kb.upsert(
        kb_name="test", doc_id="old",
        content="a distinctive marker phrase", source_hash="h1",
    )
    with sqlite3.connect(str(kb._db_path)) as c:
        c.execute("UPDATE kb_documents SET embedding_model = NULL WHERE id = ?", (doc.id,))
    hits = [d.doc_id for d, _score in kb.search("distinctive marker phrase")]
    assert "old" not in hits


def test_kb_search_excludes_mismatched_doc(tmp_path: Path) -> None:
    kb = _make_kb(tmp_path, _FakeEmbedder("texthash-v1-768d"))
    kb.upsert(
        kb_name="test", doc_id="stale",
        content="a distinctive marker phrase", source_hash="h1",
    )
    kb._embedder = _FakeEmbedder("vertex:text-embedding-004")
    kb.upsert(
        kb_name="test", doc_id="fresh",
        content="a distinctive marker phrase", source_hash="h2",
    )
    hits = [d.doc_id for d, _score in kb.search("distinctive marker phrase")]
    assert "fresh" in hits
    assert "stale" not in hits
    assert kb.embedding_model_mismatches == 1
