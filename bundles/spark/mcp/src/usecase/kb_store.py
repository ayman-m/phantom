"""SqliteKnowledgeBase — bundle-local implementation of the spec's
`knowledge` capability (spec.md §6.10 row "knowledge").

Per spec §6.10, `knowledge` has two backend impls:

  - **Standalone**: `SqliteKnowledgeBase` — local sqlite at
                    `<data_root>/kb.db`, brute-force cosine search.
  - **Platform**:   `OpenSearchKnowledgeBase` — shared per-tenant
                    OpenSearch cluster with proper inverted index +
                    pgvector for ANN.

This module is the standalone variant. It's structurally a sibling of
`SqliteMemoryStore`: same Embedder protocol, same brute-force scan,
same row-by-row JSON-encoded metadata. The differences shape the API:

  - **Multi-KB**: a single store hosts multiple kb_name namespaces
    (manifest.knowledge.bundled[].name).
  - **Doc-id is external**: rows are keyed by (kb_name, doc_id) where
    doc_id comes from the document's frontmatter `id` field, NOT a
    uuid4 — KB contents have stable external identity (T1078, PH-SOC-001),
    unlike memories which are anonymous KV pairs.
  - **Read-only at the agent surface**: `manifest.kbWrites: []` means
    there's no `knowledge_store` tool. The store has `upsert()` and
    `delete()` for the boot-time loader to use, but the agent path
    only ever calls `search()` and `get_doc()`.
  - **Hash-based change detection**: `source_hash` lets the loader
    skip re-embedding unchanged files between boots.

# Schema

    kb_documents(
      id            TEXT PRIMARY KEY,    -- uuid4 (internal)
      kb_name       TEXT NOT NULL,        -- "phantom-soc"
      doc_id        TEXT NOT NULL,        -- frontmatter.id, e.g. "PH-SOC-001"
      title         TEXT,
      category      TEXT,                 -- frontmatter.category (indexed)
      content       TEXT NOT NULL,        -- searchable body (post-frontmatter)
      metadata_json TEXT NOT NULL,        -- frontmatter as JSON
      source_path   TEXT,                 -- relative path from bundle/kbs/
      source_hash   TEXT NOT NULL,        -- SHA-256 of the on-disk file
      embedding     BLOB NOT NULL,        -- packed float32, length = dims
      loaded_at     TEXT NOT NULL,
      UNIQUE(kb_name, doc_id)
    );
    CREATE INDEX idx_kb_kb_name ON kb_documents(kb_name);
    CREATE INDEX idx_kb_category ON kb_documents(kb_name, category);
"""

from __future__ import annotations

import json
import logging
import math
import os
import sqlite3
import struct
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from usecase.memory_store import Embedder, TextHashEmbedder

logger = logging.getLogger("Phantom MCP")

DEFAULT_DATA_ROOT = Path("/app/data")


@dataclass(frozen=True)
class KbDocument:
    id: str
    kb_name: str
    doc_id: str
    title: str | None
    category: str | None
    content: str
    metadata: dict[str, Any]
    source_path: str | None
    source_hash: str
    loaded_at: str
    # Which embedder produced `embedding`. None for pre-migration rows.
    # search() uses this to avoid cosine-comparing a stale vector
    # against a live query from a different embedder.
    embedding_model: str | None = None

    def to_dict(
        self, *, score: float | None = None, include_content: bool = True
    ) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": self.id,
            "kb_name": self.kb_name,
            "doc_id": self.doc_id,
            "title": self.title,
            "category": self.category,
            "metadata": self.metadata,
            "source_path": self.source_path,
            "loaded_at": self.loaded_at,
            "embedding_model": self.embedding_model,
        }
        if include_content:
            out["content"] = self.content
        if score is not None:
            out["score"] = score
        return out


class SqliteKnowledgeBase:
    """Multi-KB sqlite-backed knowledge store at ``<data_root>/kb.db``.

    Constructed once at boot; the `KbLoader` populates it from the
    bundle's `manifest.knowledge.bundled[]` directories. After load,
    the store is effectively read-only at the agent surface — only
    the loader writes (idempotent upserts).
    """

    def __init__(
        self,
        data_root: Path | None = None,
        embedder: Embedder | None = None,
    ) -> None:
        self._data_root = (data_root or self._resolve_data_root()).resolve()
        self._data_root.mkdir(parents=True, exist_ok=True)
        self._db_path = self._data_root / "kb.db"
        self._embedder = embedder or TextHashEmbedder()
        self._lock = threading.Lock()
        # Cumulative, process-lifetime count of search() hits skipped
        # for a cross-model embedding_model mismatch — see search()
        # and the note on memory_store's identical counter.
        self.embedding_model_mismatches = 0
        self._init_schema()
        logger.info(
            "SqliteKnowledgeBase at %s (embedder=%s, dims=%d)",
            self._db_path, type(self._embedder).__name__, self._embedder.dims,
        )

    @staticmethod
    def _resolve_data_root() -> Path:
        raw = os.getenv("DATA_ROOT", str(DEFAULT_DATA_ROOT))
        return Path(raw)

    @property
    def db_path(self) -> Path:
        return self._db_path

    @property
    def embedder(self) -> Embedder:
        return self._embedder

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self._db_path, isolation_level=None, check_same_thread=False)
        c.row_factory = sqlite3.Row
        return c

    def _init_schema(self) -> None:
        with self._lock, self._conn() as c:
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS kb_documents (
                    id            TEXT PRIMARY KEY,
                    kb_name       TEXT NOT NULL,
                    doc_id        TEXT NOT NULL,
                    title         TEXT,
                    category      TEXT,
                    content       TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    source_path   TEXT,
                    source_hash   TEXT NOT NULL,
                    embedding     BLOB NOT NULL,
                    loaded_at     TEXT NOT NULL,
                    UNIQUE(kb_name, doc_id)
                )
                """
            )
            # Migration for existing kb.db's that pre-date the
            # embedding_model column (same PRAGMA-introspection
            # pattern audit_log.py uses for its `trigger` column).
            cols = {
                r["name"]
                for r in c.execute("PRAGMA table_info(kb_documents)").fetchall()
            }
            if "embedding_model" not in cols:
                c.execute("ALTER TABLE kb_documents ADD COLUMN embedding_model TEXT")
            c.execute(
                "CREATE INDEX IF NOT EXISTS idx_kb_kb_name "
                "ON kb_documents(kb_name)"
            )
            c.execute(
                "CREATE INDEX IF NOT EXISTS idx_kb_category "
                "ON kb_documents(kb_name, category)"
            )

    @staticmethod
    def _now_iso() -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    @staticmethod
    def _pack(vec: list[float]) -> bytes:
        return struct.pack(f"{len(vec)}f", *vec)

    @staticmethod
    def _unpack(blob: bytes, dims: int) -> list[float]:
        return list(struct.unpack(f"{dims}f", blob))

    @staticmethod
    def _cosine(a: list[float], b: list[float]) -> float:
        norm_b = math.sqrt(sum(x * x for x in b)) or 1.0
        return sum(x * y for x, y in zip(a, b)) / norm_b

    # ─── Loader-facing CRUD ────────────────────────────────────

    def upsert(
        self,
        *,
        kb_name: str,
        doc_id: str,
        content: str,
        title: str | None = None,
        category: str | None = None,
        metadata: dict[str, Any] | None = None,
        source_path: str | None = None,
        source_hash: str,
    ) -> tuple[KbDocument, str]:
        """Insert or update a document. Returns (doc, action) where
        action is "insert" | "update" | "unchanged".

        "unchanged" means the source_hash matched — we skipped the
        embed step entirely. That's the v1 change-detection win: most
        boots re-load the same docs, and re-embedding is the slow
        part (especially with a future network embedder).
        """
        if not kb_name or not doc_id:
            raise ValueError("kb_name and doc_id are required")
        meta_dict = dict(metadata or {})
        with self._lock, self._conn() as c:
            existing = c.execute(
                "SELECT * FROM kb_documents WHERE kb_name = ? AND doc_id = ?",
                (kb_name, doc_id),
            ).fetchone()
            # "Unchanged" requires BOTH the content hash AND the
            # producing embedder to match. A content-only check
            # would miss this corruption case: completing /setup with Vertex creds for the
            # first time doesn't touch any file on disk, so every
            # pre-existing doc's source_hash still matches and this
            # fast path would keep serving its OLD TextHash vector
            # forever, silently, while every other doc (and every
            # query) goes semantic. Same-dims (both 768) means no
            # existing check catches it — only the model id does.
            if (
                existing
                and existing["source_hash"] == source_hash
                and existing["embedding_model"] == self._embedder.model_id
            ):
                # Nothing to do — content AND embedder both unchanged.
                return self._row_to_doc(existing), "unchanged"

        # Re-embed when content changed, the doc is new, or the live
        # embedder no longer matches what produced the stored vector.
        embedding = self._embedder.embed(content)
        if len(embedding) != self._embedder.dims:
            raise RuntimeError(
                f"embedder returned {len(embedding)} dims; expected {self._embedder.dims}"
            )
        embedding_blob = self._pack(embedding)
        now = self._now_iso()

        with self._lock, self._conn() as c:
            if existing:
                doc_uuid = existing["id"]
                c.execute(
                    "UPDATE kb_documents SET title = ?, category = ?, "
                    "content = ?, metadata_json = ?, source_path = ?, "
                    "source_hash = ?, embedding = ?, loaded_at = ?, "
                    "embedding_model = ? WHERE id = ?",
                    (title, category, content, json.dumps(meta_dict),
                     source_path, source_hash, embedding_blob, now,
                     self._embedder.model_id, doc_uuid),
                )
                action = "update"
            else:
                doc_uuid = str(uuid.uuid4())
                c.execute(
                    "INSERT INTO kb_documents "
                    "(id, kb_name, doc_id, title, category, content, "
                    " metadata_json, source_path, source_hash, "
                    " embedding, loaded_at, embedding_model) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (doc_uuid, kb_name, doc_id, title, category, content,
                     json.dumps(meta_dict), source_path, source_hash,
                     embedding_blob, now, self._embedder.model_id),
                )
                action = "insert"

        from usecase.audit_log import ACTION_KB_DOC_INDEXED, record_event
        record_event(
            ACTION_KB_DOC_INDEXED,
            target=f"kb:{kb_name}:doc:{doc_id}",
            status="success",
            metadata={
                "kb_name": kb_name,
                "doc_id": doc_id,
                "action": action,
                "content_chars": len(content),
                "source_path": source_path,
            },
        )
        return KbDocument(
            id=doc_uuid, kb_name=kb_name, doc_id=doc_id,
            title=title, category=category, content=content,
            metadata=meta_dict, source_path=source_path,
            source_hash=source_hash, loaded_at=now,
            embedding_model=self._embedder.model_id,
        ), action

    def remove(self, kb_name: str, doc_id: str) -> bool:
        with self._lock, self._conn() as c:
            cur = c.execute(
                "DELETE FROM kb_documents WHERE kb_name = ? AND doc_id = ?",
                (kb_name, doc_id),
            )
        if cur.rowcount > 0:
            from usecase.audit_log import ACTION_KB_DOC_REMOVED, record_event
            record_event(
                ACTION_KB_DOC_REMOVED,
                target=f"kb:{kb_name}:doc:{doc_id}",
                status="success",
                metadata={"kb_name": kb_name, "doc_id": doc_id},
            )
            return True
        return False

    def list_kb_names(self) -> list[str]:
        with self._lock, self._conn() as c:
            rows = c.execute(
                "SELECT DISTINCT kb_name FROM kb_documents ORDER BY kb_name"
            ).fetchall()
        return [r[0] for r in rows]

    def kb_doc_ids(self, kb_name: str) -> set[str]:
        """Return the set of doc_ids currently in `kb_name` — used by the
        loader to detect docs that vanished from disk."""
        with self._lock, self._conn() as c:
            rows = c.execute(
                "SELECT doc_id FROM kb_documents WHERE kb_name = ?",
                (kb_name,),
            ).fetchall()
        return {r[0] for r in rows}

    # ─── Read API ──────────────────────────────────────────────

    def get_doc(self, kb_name: str, doc_id: str) -> KbDocument | None:
        with self._lock, self._conn() as c:
            row = c.execute(
                "SELECT * FROM kb_documents WHERE kb_name = ? AND doc_id = ?",
                (kb_name, doc_id),
            ).fetchone()
        if row is None:
            return None
        from usecase.audit_log import ACTION_KB_DOC_READ, record_event
        record_event(
            ACTION_KB_DOC_READ,
            target=f"kb:{kb_name}:doc:{doc_id}",
            status="success",
            metadata={"kb_name": kb_name, "doc_id": doc_id},
        )
        return self._row_to_doc(row)

    def list_docs(
        self,
        kb_name: str,
        *,
        category: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[KbDocument]:
        # The limit cap is 2000: a lower cap silently truncates large
        # KBs (the xql-examples KB has hundreds of entries). 2000 is a
        # balanced max — enough to return the full set in one
        # call for any KB that's reasonable to operate on, while still
        # bounding payload size on misbehaving callers.
        clauses, params = ["kb_name = ?"], [kb_name]
        if category:
            clauses.append("category = ?")
            params.append(category)
        params.extend([max(1, min(limit, 2000)), max(0, offset)])
        with self._lock, self._conn() as c:
            rows = c.execute(
                f"SELECT * FROM kb_documents WHERE {' AND '.join(clauses)} "
                "ORDER BY doc_id LIMIT ? OFFSET ?",
                params,
            ).fetchall()
        return [self._row_to_doc(r) for r in rows]

    def count_docs(
        self,
        kb_name: str,
        *,
        category: str | None = None,
    ) -> int:
        """Total-count helper for paginated responses.

        Callers of list_docs() need to know whether there are more rows
        beyond the returned slice. Returning just `len(docs)` (the slice
        size) silently hides the true total — operators see a truncated page
        and don't know what they're missing. This helper feeds the
        `total_count` field in the API response.
        """
        clauses, params = ["kb_name = ?"], [kb_name]
        if category:
            clauses.append("category = ?")
            params.append(category)
        with self._lock, self._conn() as c:
            row = c.execute(
                f"SELECT COUNT(*) AS n FROM kb_documents WHERE {' AND '.join(clauses)}",
                params,
            ).fetchone()
        return int(row["n"]) if row else 0

    def kb_summary(self) -> dict[str, dict[str, Any]]:
        """Per-KB summary used by /api/v1/kbs and the boot log."""
        with self._lock, self._conn() as c:
            rows = c.execute(
                "SELECT kb_name, COUNT(*) AS n, MAX(loaded_at) AS latest "
                "FROM kb_documents GROUP BY kb_name"
            ).fetchall()
        return {
            r["kb_name"]: {"doc_count": int(r["n"]), "latest_loaded_at": r["latest"]}
            for r in rows
        }

    def search(
        self,
        query: str,
        *,
        kb_name: str | None = None,
        category: str | None = None,
        limit: int = 5,
        min_score: float = 0.0,
    ) -> list[tuple[KbDocument, float]]:
        """Cosine similarity search across one or all KBs.

        Audit: every search records ACTION_KB_SEARCHED with the
        kb_name + result count + top score, like memory_searched.
        For SOC forensics, "what did the agent look up in the KB?"
        is one of the most useful questions.
        """
        if not isinstance(query, str) or not query.strip():
            return []
        query_vec = self._embedder.embed(query)
        clauses, params = [], []
        if kb_name:
            clauses.append("kb_name = ?")
            params.append(kb_name)
        if category:
            clauses.append("category = ?")
            params.append(category)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        with self._lock, self._conn() as c:
            rows = c.execute(
                f"SELECT * FROM kb_documents {where}", params
            ).fetchall()

        scored: list[tuple[KbDocument, float]] = []
        dims = self._embedder.dims
        mismatch_count = 0
        for row in rows:
            try:
                vec = self._unpack(row["embedding"], dims)
            except struct.error:
                continue
            # A doc's embedding_model can lag the live embedder (see
            # upsert()'s fast-path) — most commonly right after
            # /setup adds Vertex creds, before the loader's next boot
            # re-indexes every bundled doc. Same-dims (TextHash and
            # Vertex are both 768) means cosine "succeeds" but compares
            # unrelated vector spaces. Unlike memory_store.search(),
            # there's no FTS layer here to independently justify
            # keeping the row, so a mismatch is a straight skip. A
            # NULL embedding_model (pre-migration doc) counts as a
            # mismatch too — unknown provenance, not assumed-safe.
            row_model = row["embedding_model"]
            if row_model != self._embedder.model_id:
                mismatch_count += 1
                self.embedding_model_mismatches += 1
                continue
            score = self._cosine(query_vec, vec)
            if score < min_score:
                continue
            scored.append((self._row_to_doc(row), score))

        scored.sort(key=lambda x: x[1], reverse=True)
        scored = scored[: max(1, min(limit, 100))]

        from usecase.audit_log import ACTION_KB_SEARCHED, record_event
        record_event(
            ACTION_KB_SEARCHED,
            target=f"kb:{kb_name or '_all_'}",
            status="success",
            metadata={
                "kb_name": kb_name,
                "category": category,
                "query_chars": len(query),
                "limit": limit,
                "result_count": len(scored),
                "top_score": scored[0][1] if scored else None,
                "embedding_model_mismatches": mismatch_count,
            },
        )
        return scored

    # ─── Mappers ───────────────────────────────────────────────

    @staticmethod
    def _row_to_doc(row: sqlite3.Row) -> KbDocument:
        return KbDocument(
            id=row["id"],
            kb_name=row["kb_name"],
            doc_id=row["doc_id"],
            title=row["title"],
            category=row["category"],
            content=row["content"],
            metadata=json.loads(row["metadata_json"]),
            source_path=row["source_path"],
            source_hash=row["source_hash"],
            loaded_at=row["loaded_at"],
            embedding_model=row["embedding_model"],
        )


# ─────────────────────────────────────────────────────────────────
# Module-level singleton accessor — wired by main.py
# ─────────────────────────────────────────────────────────────────

_kb: SqliteKnowledgeBase | None = None


def set_knowledge_base(kb: SqliteKnowledgeBase | None) -> None:
    global _kb
    _kb = kb


def knowledge_base() -> SqliteKnowledgeBase | None:
    return _kb
