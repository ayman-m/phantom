"""ContextAssembler — bundle-local implementation of the spec's
`context` capability (spec.md §6.10 row "context").

Per spec §6.10 + the manifest's:

    context:
      strategy: "hybrid"
      budgetTokens: 24000

The assembler produces, for each turn of the agent's loop, a bounded
slice of context that fits the model's prompt window. "hybrid" means
it pulls from BOTH ordered sources (recent session messages) AND
unordered semantic sources (memory hits matching the query). KB hits
are packed the same way, from a different store.

# Why an explicit assembler

The naive approach is "shove the whole session history into the
prompt and hope it fits". For Phantom that doesn't work: a SOC
operator's session can run hundreds of messages over a multi-hour
incident response. The assembler bounds the prompt size while still
surfacing the most relevant history+memory for the current question.

# Algorithm

  1. Embed the query (free if we already have it, but we don't here —
     the embedder is in MemoryStore so we delegate to its search).
  2. Pull the last N messages from the session (recency window).
     N is tuned so the session prelude consumes ~30% of the budget.
  3. Run a top-K memory search against the query, scoped to the
     session and to "agent" (cross-session). Take results above
     `min_score`.
  4. Estimate token usage of each candidate snippet using a chars/4
     heuristic (close enough for budgeting; real tokenization depends
     on the active model).
  5. Greedily pack results into the budget, preserving:
       - all of the recency window (it's hard to reason about a
         conversation without the most recent turns)
       - then memory hits in score order
       - then drop overflow.

# Output shape

    {
      "session_id": str,
      "query": str,
      "messages": [{role, content, ts}, ...],   # chronological
      "memories": [{key, value, score}, ...],    # by score desc
      "estimated_tokens": int,
      "budget_tokens": int,
      "truncated": bool,                          # true if overflow dropped
    }

This is what the agent's turn-driver sends to the LLM as the
"context" portion of the prompt. The system prompt + skills are
glued on by the runtime separately.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("Phantom MCP")

# A character-per-token heuristic. Real tokenizers vary by model
# (GPT/Claude/Gemini all differ slightly), but ~4 chars/token holds
# within ±20% across English prose. Within budget headroom, this is
# fine; for tighter accuracy we'd plug in a per-model tokenizer.
CHARS_PER_TOKEN = 4

DEFAULT_RECENT_N = 12
DEFAULT_MEMORY_K = 5
DEFAULT_KB_K = 3
DEFAULT_MEMORY_MIN_SCORE = 0.05
DEFAULT_KB_MIN_SCORE = 0.05
RECENCY_BUDGET_FRACTION = 0.35


@dataclass(frozen=True)
class AssembledContext:
    session_id: str | None
    query: str
    messages: list[dict[str, Any]]
    memories: list[dict[str, Any]]
    knowledge: list[dict[str, Any]]
    estimated_tokens: int
    budget_tokens: int
    truncated: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "query": self.query,
            "messages": self.messages,
            "memories": self.memories,
            "knowledge": self.knowledge,
            "estimated_tokens": self.estimated_tokens,
            "budget_tokens": self.budget_tokens,
            "truncated": self.truncated,
        }


def estimate_tokens(text: str) -> int:
    """Cheap token-count heuristic. See module docstring."""
    if not text:
        return 0
    return max(1, len(text) // CHARS_PER_TOKEN)


class ContextAssembler:
    """Assembles per-turn context from session + memory stores.

    The assembler doesn't own state — it reads from the SessionStore
    and MemoryStore singletons set by `main.py`. Constructed with the
    bundle's manifest config (budget_tokens, strategy) so unit tests
    can vary the budget without touching globals.
    """

    def __init__(
        self,
        *,
        budget_tokens: int = 24000,
        strategy: str = "hybrid",
        recent_n: int = DEFAULT_RECENT_N,
        memory_k: int = DEFAULT_MEMORY_K,
        kb_k: int = DEFAULT_KB_K,
        memory_min_score: float = DEFAULT_MEMORY_MIN_SCORE,
        kb_min_score: float = DEFAULT_KB_MIN_SCORE,
    ) -> None:
        self._budget_tokens = max(1024, budget_tokens)
        self._strategy = strategy
        self._recent_n = recent_n
        self._memory_k = memory_k
        self._kb_k = kb_k
        self._memory_min_score = memory_min_score
        self._kb_min_score = kb_min_score
        logger.info(
            "ContextAssembler ready: strategy=%s budget_tokens=%d "
            "recent_n=%d memory_k=%d kb_k=%d",
            strategy, self._budget_tokens, recent_n, memory_k, kb_k,
        )

    @property
    def budget_tokens(self) -> int:
        return self._budget_tokens

    @property
    def strategy(self) -> str:
        return self._strategy

    def assemble(
        self,
        *,
        query: str,
        session_id: str | None = None,
    ) -> AssembledContext:
        """Build an AssembledContext for the current turn.

        `session_id` is optional — when None (e.g. the very first user
        message), the recency window is empty and only memory hits
        contribute.
        """
        from usecase.audit_log import ACTION_CONTEXT_ASSEMBLED, record_event
        from usecase.kb_store import knowledge_base as _knowledge_base
        from usecase.memory_store import memory_store as _memory_store
        from usecase.session_store import session_store as _session_store

        sessions = _session_store()
        memories = _memory_store()
        kb = _knowledge_base()

        # Recency window — last N messages, chronological.
        recency: list[dict[str, Any]] = []
        recency_tokens = 0
        recency_budget = int(self._budget_tokens * RECENCY_BUDGET_FRACTION)
        if session_id and sessions is not None:
            msgs = sessions.get_recent_messages(session_id, limit=self._recent_n)
            for m in msgs:
                t = estimate_tokens(m.content)
                if recency_tokens + t > recency_budget:
                    # Stop early — recency budget hit. Older messages
                    # get dropped silently; their summary may live in
                    # memory if the agent stored it.
                    break
                recency.append({
                    "role": m.role,
                    "content": m.content,
                    "ts": m.ts,
                })
                recency_tokens += t

        # Memory hits — top K, then filter by score, then pack into
        # the remainder of the budget in score order.
        remaining = max(0, self._budget_tokens - recency_tokens)
        mem_results: list[dict[str, Any]] = []
        mem_tokens = 0
        truncated = False
        if memories is not None and self._strategy in {"hybrid", "memory_only"}:
            # Search BOTH the agent-scope (cross-session) and this
            # session's scope. Agent-scope wins ties because it
            # represents stable knowledge, not in-conversation context.
            scopes_to_search: list[str | None] = ["agent"]
            if session_id:
                scopes_to_search.append(f"session:{session_id}")

            seen: set[str] = set()
            all_hits: list[tuple[Any, float]] = []
            for sc in scopes_to_search:
                hits = memories.search(
                    query,
                    limit=self._memory_k,
                    scope=sc,
                    min_score=self._memory_min_score,
                )
                for mem, score in hits:
                    if mem.id in seen:
                        continue
                    seen.add(mem.id)
                    all_hits.append((mem, score))
            all_hits.sort(key=lambda x: x[1], reverse=True)

            for mem, score in all_hits[: self._memory_k]:
                t = estimate_tokens(mem.value) + estimate_tokens(mem.key)
                if mem_tokens + t > remaining:
                    truncated = True
                    break
                mem_results.append({
                    "key": mem.key,
                    "value": mem.value,
                    "scope": mem.scope,
                    "score": round(score, 4),
                })
                mem_tokens += t

        # KB hits round out the hybrid context. KB content
        # is the bundle's stable knowledge (ATT&CK references, SOC
        # playbooks); typically more relevant for "how do I…" queries
        # than memory hits which are conversation-context. Pack them
        # into whatever budget remains after recency + memory.
        kb_results: list[dict[str, Any]] = []
        kb_tokens = 0
        remaining_after_mem = max(0, self._budget_tokens - recency_tokens - mem_tokens)
        if kb is not None and self._strategy in {"hybrid", "kb_only"} and not truncated:
            try:
                hits = kb.search(
                    query, limit=self._kb_k, min_score=self._kb_min_score,
                )
            except Exception as exc:
                logger.warning("ContextAssembler: KB search failed (%s)", exc)
                hits = []
            for doc, score in hits:
                t = estimate_tokens(doc.content) + estimate_tokens(doc.title or "")
                if kb_tokens + t > remaining_after_mem:
                    truncated = True
                    break
                kb_results.append({
                    "kb_name": doc.kb_name,
                    "doc_id": doc.doc_id,
                    "title": doc.title,
                    "category": doc.category,
                    "content": doc.content,
                    "score": round(score, 4),
                })
                kb_tokens += t

        total_tokens = recency_tokens + mem_tokens + kb_tokens

        record_event(
            ACTION_CONTEXT_ASSEMBLED,
            target=f"session:{session_id}" if session_id else "context:_anon_",
            status="success",
            metadata={
                "session_id": session_id,
                "query_chars": len(query),
                "messages_included": len(recency),
                "memories_included": len(mem_results),
                "knowledge_included": len(kb_results),
                "estimated_tokens": total_tokens,
                "budget_tokens": self._budget_tokens,
                "truncated": truncated,
            },
        )
        return AssembledContext(
            session_id=session_id,
            query=query,
            messages=recency,
            memories=mem_results,
            knowledge=kb_results,
            estimated_tokens=total_tokens,
            budget_tokens=self._budget_tokens,
            truncated=truncated,
        )


# ─────────────────────────────────────────────────────────────────
# Module-level singleton accessor
# ─────────────────────────────────────────────────────────────────

_assembler: ContextAssembler | None = None


def set_context_assembler(a: ContextAssembler | None) -> None:
    global _assembler
    _assembler = a


def context_assembler() -> ContextAssembler | None:
    return _assembler
