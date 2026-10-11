"""SqliteMemoryStore — bundle-local implementation of the spec's
`memory` capability (spec.md §6.10 row "memory").

Per spec §6.10, `memory` has two backend impls:

  - **Standalone**: `SqliteMemoryStore` — local sqlite at
                    `<data_root>/memory.db` with embeddings as BLOBs
                    and brute-force cosine similarity search.
  - **Platform**:   `PgvectorMemoryStore` — shared per-tenant Postgres
                    with the pgvector extension for ANN search.

This module is the standalone variant. The agent's `memory_store(key,
value)` and `memory_search(query, limit)` built-in tools call into it.

# Why a brute-force scan is fine here

With the operator-scale workloads Phantom targets (a SOC analyst's
day-to-day notes, target hostnames, recent IOCs), memory tables will
sit in the low thousands of rows. Even with 768-dim float32 vectors,
that's ~3 MB scanned per search — well under 100ms on any modern
disk. Adding a vector index (annoy / hnswlib / faiss) is a real
optimization but premature for this scale. The Postgres backend gets
pgvector for free; standalone stays simple.

# Embedder protocol

The constructor takes an `Embedder` object satisfying:

    class Embedder:
        dims: int
        def embed(self, text: str) -> list[float]: ...

`TextHashEmbedder` (deterministic, 768-dim, no network)
is the default. A future `VertexEmbedder` will call out to the
configured Google provider — same interface, drop-in. The embedder
choice is held by the store (set at construction); rotating embedders
requires re-embedding all existing memory rows, which would be a
migration step.

# Schema

    memories(
      id           TEXT PRIMARY KEY,    -- uuid4
      key          TEXT NOT NULL,        -- caller-supplied label
      value        TEXT NOT NULL,        -- the recallable content
      scope        TEXT NOT NULL,        -- "agent" | "session:<id>" | ...
      created_at   TEXT NOT NULL,
      updated_at   TEXT NOT NULL,
      ttl_seconds  INTEGER,              -- nullable; null = no TTL
      embedding    BLOB NOT NULL,        -- packed float32, length = dims
      meta_json    TEXT NOT NULL,
      UNIQUE(key, scope)                  -- (key, scope) is the natural id;
                                          -- writing the same (key, scope)
                                          -- updates in place
    );
    CREATE INDEX idx_memories_scope ON memories(scope);
    CREATE INDEX idx_memories_updated ON memories(updated_at);
"""

from __future__ import annotations

import calendar
import hashlib
import json
import logging
import math
import os
import re
import sqlite3
import struct
import threading
import time
from datetime import datetime
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from usecase.audit_log import AUDIT_SENSITIVE_KEY_SUBSTRINGS

logger = logging.getLogger("Phantom MCP")

DEFAULT_DATA_ROOT = Path("/app/data")
DEFAULT_EMBED_DIMS = 768  # matches manifest.memory.embeddingDims

# ─── Provenance ──────────────────────────────────────────────────
# A memory's meta.source distinguishes "an operator stated this" from
# "the agent concluded this itself" — see store()'s meta handling and
# search()'s scoring loop. A wrong self-concluded verdict that gets
# recalled and repeated without re-investigation is how one mistake
# becomes permanent (the failure this section exists to prevent). The
# multiplier is intentionally modest: it should let a well-matching
# operator statement win a close call against a self-conclusion on the
# same topic, not override relevance entirely.
_OPERATOR_SOURCE_TRUST_MULTIPLIER = 1.3

# ─── TTL enforcement ───────────────────────────────────────────────
# AND this into every read path so an expired row is invisible the
# INSTANT it expires, not merely until the next reap sweep.
# _reap_expired() runs ONLY at store construction (see __init__), so on
# a stable install a memory past its TTL would otherwise keep being
# returned by get/get_by_id/list_all/search — and therefore keep being
# injected into prompts — for as long as the container stayed up. The
# sweep is space-reclamation + an audit trail, not correctness;
# correctness lives here. updated_at is written as
# "%Y-%m-%dT%H:%M:%SZ" (see _now_iso) — substr(...,1,19) drops the
# trailing Z so SQLite's datetime() parses it directly.
_NOT_EXPIRED_SQL = (
    "(ttl_seconds IS NULL OR datetime(substr(updated_at,1,19)) "
    ">= datetime('now','-' || ttl_seconds || ' seconds'))"
)


def _like_prefix_pattern(prefix: str) -> str:
    """Escape a caller-supplied scope prefix for safe use in a SQL LIKE
    clause. scope is a hierarchical string ("session:<uuid>") — a bare
    equality filter can only ever match a LEAF value, never the family:
    the UI's "session" tab sends scope="session" while every real row is
    scope="session:<id>", so an exact-match filter would always return
    zero rows for a value that genuinely has data. LIKE needs its own escaping (independent of the
    DB-API placeholder, which only protects against SQL injection, not
    against a literal %/_ in the prefix being treated as a wildcard)."""
    escaped = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return escaped + "%"

# ─── Write-time secret redaction ──────────────────────────────────
# Redact BEFORE embed/persist — a secret redacted after the fact has
# already been embedded (and, with VertexEmbedder active, transmitted
# to Google's embedding API) and written to the FTS index. There is no
# way to un-ring that bell, so this must run first in store(), not as
# a cleanup pass.
_BEARER_RE = re.compile(r"\bBearer\s+[A-Za-z0-9\-_.~+/]{8,}=*", re.IGNORECASE)
_PROVIDER_KEY_RE = re.compile(
    r"\b(?:sk|ghp|gho|ghu|ghs|ghr|xox[abpr])-[A-Za-z0-9\-_]{10,}\b"
)
_SECRET_KV_RE = re.compile(
    r"(?i)\b(" + "|".join(re.escape(s) for s in AUDIT_SENSITIVE_KEY_SUBSTRINGS)
    + r")\s*[=:]\s*(['\"]?)([^\s'\",;]{4,})\2"
)
_CONN_STRING_PASSWORD_RE = re.compile(
    r"(?i)(://[^:/?#\s]+:)([^@/?#\s]+)(@)"
)
# Long opaque token catch-all. Digit-guarded: a bare 20+ char alnum run
# is common for perfectly innocent snake_case identifiers (e.g. a
# manifest constant name) — require at least one digit so we don't
# redact ordinary words while still catching hex/base64-shaped secrets.
_LONG_TOKEN_RE = re.compile(r"\b(?=[A-Za-z0-9+/_-]*\d)[A-Za-z0-9+/_-]{24,}={0,2}\b")

# ─── Write-time directive filter ──────────────────────────────────
# Refuse to store a value that reads as a standing instruction TO THE
# AGENT rather than an observation ABOUT something. Anchored on the
# sentence-initial DIRECTIVE form deliberately: "never"/"always" appear
# constantly in genuine SOC findings ("never seen this hash before",
# "this rule always fires at 09:00"), so a bare-keyword filter would
# reject real findings and get disabled — which protects nothing. Only
# the imperative-addressed-to-the-agent form is blocked.
_INSTRUCTION_RE = re.compile(
    r"(?:^|[.!?]\s+|\n)\s*"
    r"(?:ignore (?:all )?(?:previous|prior|above|earlier)"
    r"|disregard the \w+"
    r"|from now on"
    r"|you (?:must|should|will|are to)"
    r"|(?:always|never) (?:allow|approve|deny|treat|mark|assume|trust|skip|ask)"
    r"|system:)",
    re.IGNORECASE,
)


class Embedder(Protocol):
    """Minimal interface the memory store needs from any embedding backend."""

    dims: int
    # A stable id for the producing model — NOT just dims. TextHash
    # and Vertex are both 768-dim, so the dims check alone cannot
    # catch a stub/real embedder swap; model_id is what lets a stored
    # vector be validated against the live embedder before it's
    # trusted. See _row_embedder_mismatch() below.
    model_id: str

    def embed(self, text: str) -> list[float]: ...


class TextHashEmbedder:
    """Deterministic stub embedder for v1.

    NOT a real semantic embedder — produces a vector from token-level
    SHA-256 hashes. Useful properties:
      - Deterministic: same text → same vector, every time.
      - Locality: shared substrings produce overlapping non-zero dims,
        so cosine distance does discriminate "similar" texts at coarse
        granularity (it won't distinguish synonyms, but it does pick up
        shared keywords).
      - Zero deps: no model files, no network, no GPU.

    This lets the memory_store/search tools work end-to-end.
    A real `VertexEmbedder` (which calls
    google.cloud.aiplatform.TextEmbeddingModel) is a drop-in
    replacement — just instantiate it instead and the store behavior
    is unchanged.
    """

    def __init__(self, dims: int = DEFAULT_EMBED_DIMS) -> None:
        self.dims = dims
        # Deliberately encodes dims so a stub vector can never
        # coincidentally match a real embedder's model_id at the same
        # dims — TextHash and Vertex are both 768-dim.
        self.model_id = f"texthash-v1-{dims}d"

    def embed(self, text: str) -> list[float]:
        if not isinstance(text, str):
            raise TypeError("text must be a string")
        # Tokenize crudely (lowercase, split on non-alphanumerics).
        tokens: list[str] = []
        cur: list[str] = []
        for ch in text.lower():
            if ch.isalnum():
                cur.append(ch)
            elif cur:
                tokens.append("".join(cur))
                cur = []
        if cur:
            tokens.append("".join(cur))

        if not tokens:
            return [0.0] * self.dims

        vec = [0.0] * self.dims
        for tok in tokens:
            digest = hashlib.sha256(tok.encode("utf-8")).digest()
            # Spread the digest across dims by 4-byte groups → unsigned
            # int → bucket. Each token contributes to ~8 dims with the
            # SAME magnitude, making the scoring stable.
            for i in range(0, len(digest), 4):
                bucket = int.from_bytes(digest[i:i + 4], "big") % self.dims
                vec[bucket] += 1.0

        # L2-normalize so cosine similarity is just a dot product.
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]


@dataclass(frozen=True)
class Memory:
    id: str
    key: str
    value: str
    scope: str
    created_at: str
    updated_at: str
    ttl_seconds: int | None
    meta: dict[str, Any]
    # Which embedder produced `embedding` — None for rows written
    # before this field existed. search() uses this to detect a
    # stored vector that no longer matches the live embedder (e.g.
    # after switching from the TextHash stub to Vertex) rather than
    # cosine-comparing across incompatible vector spaces.
    embedding_model: str | None = None

    def to_dict(self, *, score: float | None = None) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": self.id,
            "key": self.key,
            "value": self.value,
            "scope": self.scope,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "ttl_seconds": self.ttl_seconds,
            "meta": self.meta,
            "embedding_model": self.embedding_model,
        }
        if score is not None:
            out["score"] = score
        return out


class SqliteMemoryStore:
    """Sqlite-backed semantic memory at ``<data_root>/memory.db``.

    Search is brute-force cosine similarity over all rows in the
    selected scope; see module docstring for why that's fine at this
    scale.
    """

    def __init__(
        self,
        data_root: Path | None = None,
        embedder: Embedder | None = None,
    ) -> None:
        self._data_root = (data_root or self._resolve_data_root()).resolve()
        self._data_root.mkdir(parents=True, exist_ok=True)
        self._db_path = self._data_root / "memory.db"
        self._embedder = embedder or TextHashEmbedder()
        self._lock = threading.Lock()
        # Cumulative, process-lifetime count of search() hits whose
        # stored embedding_model didn't match the live embedder (e.g.
        # a row embedded by TextHash before Vertex creds were
        # submitted). Surfaced next to embedder_mode on health_status()
        # — see search()'s scoring loop for where this increments.
        self.embedding_model_mismatches = 0
        self._init_schema()
        n_expired = self._reap_expired()
        if n_expired:
            logger.info(
                "MemoryStore: reaped %d expired row(s) at boot", n_expired
            )
        logger.info(
            "SqliteMemoryStore at %s (embedder=%s, dims=%d)",
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
                CREATE TABLE IF NOT EXISTS memories (
                    id           TEXT PRIMARY KEY,
                    key          TEXT NOT NULL,
                    value        TEXT NOT NULL,
                    scope        TEXT NOT NULL,
                    created_at   TEXT NOT NULL,
                    updated_at   TEXT NOT NULL,
                    ttl_seconds  INTEGER,
                    embedding    BLOB NOT NULL,
                    meta_json    TEXT NOT NULL,
                    UNIQUE(key, scope)
                )
                """
            )
            # Migration for existing memories.db's that pre-date the
            # embedding_model column (same PRAGMA-introspection pattern
            # audit_log.py uses for its `trigger` column). Existing
            # rows get embedding_model=NULL, which search() treats as
            # "unknown provenance" — same conservative handling as a
            # genuine cross-model mismatch, not silently trusted.
            cols = {
                r["name"]
                for r in c.execute("PRAGMA table_info(memories)").fetchall()
            }
            if "embedding_model" not in cols:
                c.execute("ALTER TABLE memories ADD COLUMN embedding_model TEXT")
            c.execute(
                "CREATE INDEX IF NOT EXISTS idx_memories_scope "
                "ON memories(scope)"
            )
            c.execute(
                "CREATE INDEX IF NOT EXISTS idx_memories_updated "
                "ON memories(updated_at)"
            )

            # ── FTS5 hybrid index ─────────────────────────────
            #
            # Catches exact-keyword queries (UUIDs, hostnames, IP
            # addresses, vendor names) that the embedder misses
            # because the tokens have no semantic meaning to it. We
            # use a CONTENTLESS FTS5 table — manually synced from
            # store() / delete() — instead of `content='memories'`
            # because:
            #
            #   - Our primary key is TEXT not INTEGER, so the rowid
            #     mapping FTS expects (`content_rowid='rowid'`)
            #     would point at SQLite's implicit rowid which is
            #     unstable across VACUUM. Contentless avoids that
            #     class of sync bug entirely.
            #   - Storage cost is small (we duplicate key+value
            #     text into the FTS index) but search latency drops
            #     from O(n) full-text scan to O(log n) prefix lookup.
            #
            # Tokenizer: porter (English stemming) + unicode61 (case
            # folding + punctuation handling). Same defaults sqlite3's
            # docs recommend for general English text.
            try:
                c.execute(
                    """
                    CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts
                    USING fts5(
                        id UNINDEXED,
                        key,
                        value,
                        scope UNINDEXED,
                        tokenize='porter unicode61'
                    )
                    """
                )
                self._fts_available = True
            except sqlite3.OperationalError as exc:
                # FTS5 not compiled into this sqlite3 build (rare on
                # macOS Homebrew Pythons, common on stripped-down
                # Linux containers). Continue without it — vector-only
                # search degrades gracefully.
                logger.warning(
                    "memory_store: FTS5 unavailable (%s) — falling back "
                    "to vector-only search",
                    exc,
                )
                self._fts_available = False
                return

            # Backfill: if FTS is empty but memories has rows
            # (upgrade from pre-FTS deploy), populate from existing.
            existing_count = c.execute(
                "SELECT COUNT(*) FROM memories_fts"
            ).fetchone()[0]
            mem_count = c.execute(
                "SELECT COUNT(*) FROM memories"
            ).fetchone()[0]
            if existing_count == 0 and mem_count > 0:
                logger.info(
                    "memory_store: backfilling FTS5 index from "
                    "%d existing memories",
                    mem_count,
                )
                c.execute(
                    "INSERT INTO memories_fts (id, key, value, scope) "
                    "SELECT id, key, value, scope FROM memories"
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
    def _fts_safe_query(query: str) -> str:
        """Sanitize an operator-typed query for FTS5 MATCH.

        FTS5 has its own little query DSL — `*` is prefix match, `:` is
        column scope, `"..."` is phrase, AND/OR/NEAR are operators. Most
        operator queries are bare keyword strings ("firewall destination",
        "10.10.0.5"), but pathological inputs (`*` alone, `:` mid-token,
        unmatched quotes) cause SQLite to error.

        Rather than parse the operator's intent, we conservatively quote
        each whitespace-separated token as a phrase, dropping ones that
        contain only special chars. Result: search behaves like AND-of-
        phrases, which matches operator expectation for "did we see
        this IP" / "what did we test against vendor X."

        Examples:
          "firewall destination"     → '"firewall" "destination"'
          "10.10.0.5"                → '"10.10.0.5"'
          "  *  "                    → '' (caller falls back to vector-only)
          'tech_stack:firewall'      → '"tech_stack" "firewall"'  (the `:`
                                       acts as a delimiter — operator
                                       likely typed the canonical key
                                       name, both halves are useful
                                       tokens for FTS).
        """
        if not query:
            return ""
        # Split on whitespace AND FTS-tokenizer-delimiters. Dots
        # are explicitly delimiters: porter+unicode61 splits "10.0.0.1"
        # into ["10", "0", "0", "1"] when indexing, so we must split
        # the query the same way to match. We keep `_` and `-` since
        # the default tokenizer treats them as letters.
        tokens: list[str] = []
        current: list[str] = []
        for ch in query:
            if ch.isalnum() or ch in "_-":
                current.append(ch)
            else:
                if current:
                    tokens.append("".join(current))
                    current = []
        if current:
            tokens.append("".join(current))
        usable = [t for t in tokens if any(c.isalnum() for c in t)]
        if not usable:
            return ""
        quoted = [f'"{t}"' for t in usable]
        return " ".join(quoted)

    @staticmethod
    def _cosine(a: list[float], b: list[float]) -> float:
        # Embedder returns L2-normalized vectors; cosine == dot product.
        # Defense-in-depth: re-normalize one factor in case a future
        # embedder doesn't pre-normalize.
        norm_b = math.sqrt(sum(x * x for x in b)) or 1.0
        return sum(x * y for x, y in zip(a, b)) / norm_b

    # ─── Write-time safety (redaction + directive filter) ──────
    # Both run inside store() itself — the single choke point every
    # write path (the memory_store MCP tool, POST /api/v1/memories,
    # plugin seed application) already funnels through.

    @staticmethod
    def _scrub_free_text(text: str) -> str:
        """Regex-scrub secret-shaped substrings from free text."""
        text = _BEARER_RE.sub("Bearer ***", text)
        text = _PROVIDER_KEY_RE.sub("***", text)
        text = _CONN_STRING_PASSWORD_RE.sub(r"\1***\3", text)
        text = _SECRET_KV_RE.sub(lambda m: f"{m.group(1)}=***", text)
        text = _LONG_TOKEN_RE.sub("***", text)
        return text

    @classmethod
    def _redact_structural(cls, obj: Any) -> Any:
        """Recursively mask values whose key hints at a secret."""
        if isinstance(obj, dict):
            out: dict[Any, Any] = {}
            for k, v in obj.items():
                if isinstance(k, str) and any(
                    s in k.lower() for s in AUDIT_SENSITIVE_KEY_SUBSTRINGS
                ):
                    out[k] = "***" if isinstance(v, str) else v
                else:
                    out[k] = cls._redact_structural(v)
            return out
        if isinstance(obj, list):
            return [cls._redact_structural(v) for v in obj]
        if isinstance(obj, str):
            return cls._scrub_free_text(obj)
        return obj

    @classmethod
    def _redact_value(cls, value: str) -> str:
        """Redact a memory value before it is embedded or persisted.

        Two-tier: if the value parses as a JSON object/array, mask by
        KEY NAME structurally (catches e.g. {"api_key": "..."} even
        though "api_key" alone doesn't read as a secret VALUE to a
        free-text regex); otherwise fall back to free-text scrubbing.
        """
        stripped = value.strip()
        if stripped[:1] in ("{", "["):
            try:
                parsed = json.loads(stripped)
            except (json.JSONDecodeError, ValueError):
                parsed = None
            if isinstance(parsed, (dict, list)):
                return json.dumps(cls._redact_structural(parsed))
        return cls._scrub_free_text(value)

    @staticmethod
    def _reject_if_directive(label: str, text: str) -> None:
        """Refuse a key/value that reads as an instruction TO the agent
        rather than an observation ABOUT something. See _INSTRUCTION_RE
        for why this is anchored on the directive form specifically."""
        if _INSTRUCTION_RE.search(text):
            raise ValueError(
                f"memory {label} reads as a directive to the agent, not an "
                "observation, and was refused. If this is a genuine finding "
                "quoting an attacker's text, paraphrase it in your own words "
                "instead of storing it verbatim."
            )

    # ─── CRUD ──────────────────────────────────────────────────

    def store(
        self,
        *,
        key: str,
        value: str,
        scope: str = "agent",
        ttl_seconds: int | None = None,
        meta: dict[str, Any] | None = None,
    ) -> Memory:
        """Insert or update a memory row keyed by (key, scope).

        Re-stores update value/meta/ttl AND re-embed (since the value
        text may have changed). Idempotent: re-storing identical
        content is fine, just bumps `updated_at`.
        """
        if not key or not isinstance(key, str):
            raise ValueError("key must be a non-empty string")
        if not isinstance(value, str):
            raise ValueError("value must be a string")
        self._reject_if_directive("key", key)
        self._reject_if_directive("value", value)
        value = self._redact_value(value)
        scope = scope or "agent"
        now = self._now_iso()
        embedding = self._embedder.embed(value)
        if len(embedding) != self._embedder.dims:
            raise RuntimeError(
                f"embedder returned {len(embedding)} dims; expected {self._embedder.dims}"
            )
        embedding_blob = self._pack(embedding)
        meta_dict = dict(meta or {})
        with self._lock, self._conn() as c:
            existing = c.execute(
                "SELECT id, created_at FROM memories WHERE key = ? AND scope = ?",
                (key, scope),
            ).fetchone()
            if existing:
                mid = existing["id"]
                created_at = existing["created_at"]
                c.execute(
                    "UPDATE memories SET value = ?, updated_at = ?, "
                    "ttl_seconds = ?, embedding = ?, meta_json = ?, "
                    "embedding_model = ? WHERE id = ?",
                    (value, now, ttl_seconds, embedding_blob,
                     json.dumps(meta_dict), self._embedder.model_id, mid),
                )
                # Keep FTS5 in sync. Contentless table, so
                # we can't rely on triggers; manual delete-then-insert
                # is the FTS5-recommended pattern for re-indexing a row.
                if self._fts_available:
                    c.execute(
                        "DELETE FROM memories_fts WHERE id = ?", (mid,)
                    )
                    c.execute(
                        "INSERT INTO memories_fts (id, key, value, scope) "
                        "VALUES (?, ?, ?, ?)",
                        (mid, key, value, scope),
                    )
                action = "update"
            else:
                mid = str(uuid.uuid4())
                created_at = now
                c.execute(
                    "INSERT INTO memories "
                    "(id, key, value, scope, created_at, updated_at, "
                    " ttl_seconds, embedding, meta_json, embedding_model) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (mid, key, value, scope, now, now, ttl_seconds,
                     embedding_blob, json.dumps(meta_dict), self._embedder.model_id),
                )
                if self._fts_available:
                    c.execute(
                        "INSERT INTO memories_fts (id, key, value, scope) "
                        "VALUES (?, ?, ?, ?)",
                        (mid, key, value, scope),
                    )
                action = "insert"

        # Audit (writes are higher-value forensic events than reads).
        from usecase.audit_log import ACTION_MEMORY_STORED, record_event
        record_event(
            ACTION_MEMORY_STORED,
            target=f"memory:{mid}",
            status="success",
            metadata={
                "memory_id": mid,
                "key": key,
                "scope": scope,
                "value_chars": len(value),
                "ttl_seconds": ttl_seconds,
                "action": action,
            },
        )
        return Memory(
            id=mid, key=key, value=value, scope=scope,
            created_at=created_at, updated_at=now,
            ttl_seconds=ttl_seconds, meta=meta_dict,
            embedding_model=self._embedder.model_id,
        )

    def get(self, *, key: str, scope: str = "agent") -> Memory | None:
        with self._lock, self._conn() as c:
            row = c.execute(
                f"SELECT * FROM memories WHERE key = ? AND scope = ? "
                f"AND {_NOT_EXPIRED_SQL}",
                (key, scope),
            ).fetchone()
        return self._row_to_memory(row) if row else None

    def get_by_id(self, memory_id: str) -> Memory | None:
        with self._lock, self._conn() as c:
            row = c.execute(
                f"SELECT * FROM memories WHERE id = ? AND {_NOT_EXPIRED_SQL}",
                (memory_id,),
            ).fetchone()
        return self._row_to_memory(row) if row else None

    def list_all(
        self,
        *,
        scope: str | None = None,
        scope_prefix: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Memory]:
        """List memories, optionally filtered by scope.

        `scope` is an exact-match filter (e.g. "agent"). `scope_prefix`
        matches the whole hierarchical family (e.g. "session:" matches
        every "session:<id>" row) — pass this, not `scope`, when the
        caller means "all session-scoped memory" rather than one exact
        scope string. If both are given, `scope_prefix` wins.
        """
        clauses, params = [_NOT_EXPIRED_SQL], []
        if scope_prefix is not None:
            clauses.append("scope LIKE ? ESCAPE '\\'")
            params.append(_like_prefix_pattern(scope_prefix))
        elif scope is not None:
            clauses.append("scope = ?")
            params.append(scope)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params.extend([max(1, min(limit, 500)), max(0, offset)])
        with self._lock, self._conn() as c:
            rows = c.execute(
                f"SELECT * FROM memories {where} "
                "ORDER BY updated_at DESC LIMIT ? OFFSET ?",
                params,
            ).fetchall()
        return [self._row_to_memory(r) for r in rows]

    def delete(self, *, key: str, scope: str = "agent") -> bool:
        with self._lock, self._conn() as c:
            row = c.execute(
                "SELECT id FROM memories WHERE key = ? AND scope = ?",
                (key, scope),
            ).fetchone()
            if row is None:
                return False
            mid = row["id"]
            c.execute("DELETE FROM memories WHERE id = ?", (mid,))
            if self._fts_available:
                c.execute("DELETE FROM memories_fts WHERE id = ?", (mid,))
        from usecase.audit_log import ACTION_MEMORY_DELETED, record_event
        record_event(
            ACTION_MEMORY_DELETED,
            target=f"memory:{mid}",
            status="success",
            metadata={"memory_id": mid, "key": key, "scope": scope},
        )
        return True

    # ─── Search ────────────────────────────────────────────────

    def search(
        self,
        query: str,
        *,
        limit: int = 5,
        scope: str | None = None,
        scope_prefix: str | None = None,
        min_score: float = 0.0,
        mmr_lambda: float = 0.7,
        temporal_decay_lambda: float = 0.01,
        mode: str | None = None,
    ) -> list[tuple[Memory, float]]:
        """Top-K hybrid-relevance memory search.

        Pipeline:
          1. Score every row by cosine similarity to the query embedding.
          2. Apply temporal decay: score *= exp(-age_days × λ_decay).
             Default λ=0.01 → half-life ~70 days. Recent memories outrank
             older ones at equal cosine, but old-and-very-relevant still
             wins over new-but-tangential.
          3. Greedy MMR rerank for diversity. λ_mmr=0.7 means
             70% relevance / 30% diversity. Avoids the near-duplicate
             dilution problem (5 entries that all say roughly the same
             thing crowd out useful info further down).
          4. Slice to `limit`.

        Returns (Memory, score) tuples sorted by their MMR-adjusted
        score. Score is post-decay-and-MMR; for raw cosine, set
        mmr_lambda=1.0 and temporal_decay_lambda=0.0.

        Args:
          query: Free-form text to match against. Embedded once.
          limit: Max results returned. Soft-capped at 100.
          scope: Restrict to this scope; None searches all scopes.
          min_score: Threshold on cosine (BEFORE decay+MMR) — filters
            out clearly-unrelated rows before the more expensive
            ranking steps.
          mmr_lambda: Diversity weighting. 1.0 = pure relevance (no
            diversification), 0.0 = pure diversity (max-cover-style),
            0.7 default (relevance-favoring).
          temporal_decay_lambda: Recency weighting per day of age.
            0.01 default (half-life ~70 days), 0.0 disables.
          mode: Audit discriminator distinguishing WHO triggered this
            search — "active" (an explicit memory_search tool call or
            operator REST call, default when omitted) vs. "passive"
            (the memory-inject hook's automatic per-turn injection,
            which produces no tool_call row of its own). Purely for
            the emitted audit event; has no effect on results.

        Notes:
          - When `scope` is None, search ALL scopes (useful for the
            agent's "what do I know about X" query).
          - When `scope` is set, restrict to that scope. Common cases:
            "agent" (cross-session memory), "session:<id>" (this
            conversation only).
        """
        if not isinstance(query, str) or not query.strip():
            return []
        query_vec = self._embedder.embed(query)
        clauses, params = [_NOT_EXPIRED_SQL], []
        if scope_prefix is not None:
            clauses.append("scope LIKE ? ESCAPE '\\'")
            params.append(_like_prefix_pattern(scope_prefix))
        elif scope is not None:
            clauses.append("scope = ?")
            params.append(scope)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""

        # Hybrid candidate gathering. The vector query
        # below scans all rows (n is small for SOC ops; brute-force is
        # fine). FTS5 contributes its own top-K candidates on top — for
        # exact-token queries (UUIDs, hostnames, IP addresses) the
        # embedder misses, the FTS branch surfaces them.
        #
        # We don't hard-merge scores here; instead, we union the
        # candidate sets by id (vector ∪ FTS), then let the cosine +
        # decay scoring + MMR rerank below produce the final order.
        # The FTS contribution is "guarantee these rows make the
        # candidate pool"; ranking is still embedder-driven.
        fts_promoted_ids: set[str] = set()
        fts_query = self._fts_safe_query(query) if self._fts_available else ""
        if fts_query:
            try:
                fts_clauses = ["memories_fts MATCH ?"]
                fts_params = [fts_query]
                if scope_prefix is not None:
                    fts_clauses.append("scope LIKE ? ESCAPE '\\'")
                    fts_params.append(_like_prefix_pattern(scope_prefix))
                elif scope is not None:
                    fts_clauses.append("scope = ?")
                    fts_params.append(scope)
                fts_where = " AND ".join(fts_clauses)
                with self._lock, self._conn() as c:
                    fts_rows = c.execute(
                        f"SELECT id FROM memories_fts WHERE {fts_where} "
                        f"ORDER BY bm25(memories_fts) LIMIT ?",
                        [*fts_params, max(1, min(limit * 3, 50))],
                    ).fetchall()
                fts_promoted_ids = {r["id"] for r in fts_rows}
            except sqlite3.OperationalError as exc:
                # Bad MATCH syntax (rare after sanitization) → log +
                # degrade to vector-only. Empty-query case skipped
                # before the try.
                logger.warning("memory_store: FTS5 query failed (%s)", exc)

        with self._lock, self._conn() as c:
            rows = c.execute(
                f"SELECT * FROM memories {where}", params
            ).fetchall()

        # ── Cosine + temporal-decay scoring ────────────────────
        # Hold the embedding vector alongside score for the MMR pass
        # below. Stripped before return.
        now_epoch = time.time()
        scored: list[tuple[Memory, float, list[float]]] = []
        dims = self._embedder.dims
        mismatch_count_this_call = 0
        for row in rows:
            try:
                vec = self._unpack(row["embedding"], dims)
            except struct.error:
                continue
            is_fts_match = row["id"] in fts_promoted_ids
            # A row's embedding_model can differ from the LIVE
            # embedder's — most commonly a row written by the
            # TextHash stub before Vertex creds were submitted, still
            # sitting in the index after the switch. dims alone can't
            # catch this: TextHash and Vertex are both 768-dim, so the
            # cosine math "succeeds" but compares vectors from two
            # unrelated spaces, producing a plausible-looking score
            # that means nothing. Per the embedder's own no-silent-
            # degradation policy (see vertex_embedder.py's module
            # docstring), don't serve that as if it were real
            # relevance. A row with no recorded embedding_model (pre-
            # migration data) is treated as unknown, not assumed-safe.
            row_model = row["embedding_model"]
            mismatched = row_model != self._embedder.model_id
            if mismatched:
                self.embedding_model_mismatches += 1
                mismatch_count_this_call += 1
                if not is_fts_match:
                    # No independent (text-match) justification to
                    # keep it — the only signal we have is the
                    # meaningless cross-model cosine. Drop it.
                    continue
                # FTS-promoted: the keyword match is still valid
                # evidence (it's text-based, not vector-based), so
                # keep the row but don't trust its cosine number.
                cosine = 0.0
            else:
                cosine = self._cosine(query_vec, vec)
            # FTS-promoted rows skip the min_score gate.
            # An exact-keyword match (e.g., a UUID or IP) can have very
            # low cosine because the embedder doesn't model bare
            # identifiers, but the operator obviously wants it back.
            if cosine < min_score and not is_fts_match:
                continue
            mem = self._row_to_memory(row)
            # Temporal decay on `updated_at`. We use updated_at
            # not created_at: a stored memory that's been re-confirmed
            # (re-stored) effectively resets its decay clock, which
            # matches operator intuition ("the operator just told me
            # this again — it's still current").
            decay_factor = 1.0
            if temporal_decay_lambda > 0.0 and mem.updated_at:
                try:
                    # updated_at is ISO-8601 with `Z` or `+00:00` suffix.
                    iso = mem.updated_at.replace("Z", "+00:00")
                    updated_epoch = datetime.fromisoformat(iso).timestamp()
                    age_days = max(0.0, (now_epoch - updated_epoch) / 86400.0)
                    decay_factor = math.exp(-age_days * temporal_decay_lambda)
                except (ValueError, AttributeError):
                    # Bad timestamp — keep the default 1.0 factor.
                    pass
            # An operator stated this directly; the agent concluded it
            # itself and may be wrong. Weight operator-sourced rows
            # higher so a well-matching self-conclusion doesn't outrank
            # a slightly-less-well-matching operator statement on the
            # same topic. See _reject_if_directive's neighbor section
            # below for the write-time half of this (meta.source is
            # stamped server-side, never caller-chosen).
            if mem.meta.get("source") == "operator":
                decay_factor *= _OPERATOR_SOURCE_TRUST_MULTIPLIER
            adjusted_score = cosine * decay_factor
            scored.append((mem, adjusted_score, vec))

        # Sort by adjusted score (relevance + recency) and trim to a
        # candidate pool larger than `limit` so MMR has room to pick
        # diverse winners. 3× limit is the standard heuristic.
        scored.sort(key=lambda x: x[1], reverse=True)
        candidate_pool_size = max(1, min(limit * 3, 100))
        candidates = scored[:candidate_pool_size]

        # ── MMR rerank ─────────────────────────────────────────
        final = self._apply_mmr(
            candidates, limit=limit, mmr_lambda=mmr_lambda,
        )

        from usecase.audit_log import ACTION_MEMORY_SEARCHED, record_event
        record_event(
            ACTION_MEMORY_SEARCHED,
            target="memory:_search_",
            status="success",
            metadata={
                "query_chars": len(query),
                # Bounded preview, not the full query: the passive
                # (hook) path produces no separate tool_call row, so
                # without this the query text is unrecoverable from
                # the audit log at all — query_chars alone is a
                # length, not enough to answer "why did the agent
                # bring up X?". Bounded to keep audit.db from growing
                # unboundedly on long turns.
                "query_preview": query[:200],
                "scope": scope,
                "limit": limit,
                "result_count": len(final),
                "top_score": final[0][1] if final else None,
                "mmr_lambda": mmr_lambda,
                "temporal_decay_lambda": temporal_decay_lambda,
                "mode": mode or "active",
                "embedding_model_mismatches": mismatch_count_this_call,
            },
        )
        return final

    @staticmethod
    def _apply_mmr(
        candidates: list[tuple[Memory, float, list[float]]],
        *,
        limit: int,
        mmr_lambda: float = 0.7,
    ) -> list[tuple[Memory, float]]:
        """Greedy MMR (Maximal Marginal Relevance) selection.

        At each step, pick the candidate that maximizes:
            λ × relevance_score - (1 - λ) × max_similarity_to_already_picked

        First pick is pure relevance (nothing to diversify against yet).
        Subsequent picks balance new-information vs already-known.

        Returns (Memory, score) tuples — vectors stripped — in
        selection order.

        Edge cases:
          - mmr_lambda >= 1.0 → degenerate to pure relevance (no
            diversity penalty); fast-path returns the slice as-is.
          - <= 1 candidate → pass through unchanged.
        """
        if mmr_lambda >= 1.0 or len(candidates) <= 1:
            return [(m, s) for m, s, _ in candidates[:limit]]

        remaining = list(candidates)
        selected: list[tuple[Memory, float, list[float]]] = []
        target = max(1, min(limit, len(remaining)))

        while remaining and len(selected) < target:
            best_idx = 0
            best_mmr = float("-inf")
            for i, (_mem, score, vec) in enumerate(remaining):
                if not selected:
                    # First pick: pure relevance — diversity term is 0.
                    mmr_score = mmr_lambda * score
                else:
                    max_sim_to_picked = max(
                        SqliteMemoryStore._cosine(vec, sel_vec)
                        for _, _, sel_vec in selected
                    )
                    mmr_score = (
                        mmr_lambda * score
                        - (1.0 - mmr_lambda) * max_sim_to_picked
                    )
                if mmr_score > best_mmr:
                    best_mmr = mmr_score
                    best_idx = i
            selected.append(remaining.pop(best_idx))

        return [(m, s) for m, s, _ in selected]

    # ─── TTL reaper ────────────────────────────────────────────

    def _reap_expired(self) -> int:
        """Delete memory rows whose TTL has passed.

        TTL is interpreted as seconds since `updated_at`. This is now
        space-reclamation + an audit trail, NOT correctness — every
        read path (get/get_by_id/list_all/search) already excludes
        expired rows via _NOT_EXPIRED_SQL, so an expired-but-unreaped
        row is invisible long before this ever runs. Run at boot and
        on the periodic sweep (see main.py).
        """
        now_epoch = time.time()
        deleted = 0
        deleted_ids: list[str] = []
        with self._lock, self._conn() as c:
            rows = c.execute(
                "SELECT id, updated_at, ttl_seconds FROM memories "
                "WHERE ttl_seconds IS NOT NULL"
            ).fetchall()
            to_delete: list[str] = []
            for r in rows:
                ttl = r["ttl_seconds"]
                if ttl is None:
                    continue
                # Parse updated_at (assume ISO8601 UTC seconds-precision).
                try:
                    upd = time.strptime(r["updated_at"], "%Y-%m-%dT%H:%M:%SZ")
                    # calendar.timegm treats the struct_time as pure UTC
                    # fields with NO timezone/DST adjustment — the
                    # correct inverse of strptime on a 'Z'-suffixed
                    # string. time.mktime(upd) - time.timezone (the
                    # prior form) instead interprets `upd` as LOCAL
                    # time and subtracts a DST-naive constant offset,
                    # which is off by one hour for any updated_at that
                    # falls within a DST period on a DST-observing
                    # host — latent on UTC-run containers, live under
                    # pytest on a DST-zone dev machine.
                    upd_epoch = calendar.timegm(upd)
                except ValueError:
                    continue
                if upd_epoch + ttl < now_epoch:
                    to_delete.append(r["id"])
            for mid in to_delete:
                c.execute("DELETE FROM memories WHERE id = ?", (mid,))
                if self._fts_available:
                    c.execute("DELETE FROM memories_fts WHERE id = ?", (mid,))
                deleted += 1
                deleted_ids.append(mid)
        if deleted_ids:
            from usecase.audit_log import ACTION_MEMORY_DELETED, record_event
            for mid in deleted_ids:
                record_event(
                    ACTION_MEMORY_DELETED,
                    target=f"memory:{mid}",
                    status="success",
                    metadata={"memory_id": mid, "trigger": "ttl_reaper"},
                )
        return deleted

    # ─── Mappers ───────────────────────────────────────────────

    @staticmethod
    def _row_to_memory(row: sqlite3.Row) -> Memory:
        return Memory(
            id=row["id"],
            key=row["key"],
            value=row["value"],
            scope=row["scope"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            ttl_seconds=row["ttl_seconds"],
            meta=json.loads(row["meta_json"]),
            embedding_model=row["embedding_model"],
        )


# ─────────────────────────────────────────────────────────────────
# Module-level singleton accessor — wired by main.py
# ─────────────────────────────────────────────────────────────────

_memory_store: SqliteMemoryStore | None = None


def set_memory_store(store: SqliteMemoryStore | None) -> None:
    global _memory_store
    _memory_store = store


def memory_store() -> SqliteMemoryStore | None:
    return _memory_store
