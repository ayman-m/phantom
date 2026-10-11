"""cortex-docs connector: the Cortex public documentation as MCP tools.

The documentation lives on GitBook (cortex-docs.paloaltonetworks.com); `gitbook.py` holds the mechanics (page Markdown,
`?ask=` answers with sources, per-book sitemaps). This file is the tool surface. Tool names auto-namespace as
`cortex-docs/<bare_name>`; `connector.yaml`'s `runtimeMapping.functionPrefix=cortex_` strips the prefix at dispatch.

Every tool returns a dict with an `ok` boolean: a docs-site failure is a returned `{"ok": false, "error": ...}`, never an
exception, so one transient blip does not take the connector down.

Tool catalog
  cortex_search         ask the docs a question; the answer plus its source pages
  cortex_suggest        pages whose address matches what the operator has typed so far
  cortex_xql_lookup     a focused answer for one XQL stage or function
  cortex_fetch_topic    the Markdown of one docs page
  cortex_fetch_toc      the pages of one book
  cortex_deep_research  several linked questions, one brief with citations
"""
from __future__ import annotations

import re
import time
from typing import Any, Optional

from . import gitbook


RESEARCH_BUDGET_SECONDS = 75


def _err(message: str, **extra: Any) -> dict:
    return {"ok": False, "error": message, **extra}


def cortex_search(query: str, product: Optional[str] = None, per_page: int = 20, page: int = 1) -> dict:
    """Ask the Palo Alto Networks Cortex documentation a question.

    Args:
        query:    A question or topic in plain words, for example "How do I send logs to XSIAM from Cribl?".
        product:  Optional scope: agentix, xdr, xsiam, xsoar, xql, cloud, dspm, cspm, ciem, xpanse. When omitted the
                  product is read from the question (XSIAM when none is named).
        per_page: At most this many source pages are returned in `hits` (1-100, default 20).
        page:     Accepted for compatibility; the docs site answers a question, it does not paginate.

    Returns {ok, query, product, book, answer, hits: [{title, reader_url}], follow_ups: [question], total_hits}.
    `answer` is the docs' own answer and `hits` are the pages it came from; call cortex_fetch_topic(url) for the full text
    of a page. If the answer does not cover what you need, ask a follow-up question from `follow_ups`."""
    if not (query or "").strip():
        return _err("query is required")
    try:
        found = gitbook.ask(query, product)
    except gitbook.DocsError as exc:
        return _err(str(exc))
    hits = found["hits"][:max(1, min(int(per_page or 20), 100))]
    return {"ok": True, "query": query, "product": found["product"], "book": found["book"], "answer": found["answer"],
            "hits": hits, "follow_ups": found["follow_ups"], "total_hits": len(found["hits"])}


def cortex_suggest(input_text: str, product: Optional[str] = None) -> dict:
    """Pages whose address contains every word typed so far, the way a search box completes while you type.

    Args:
        input_text: Partial search text, for example "ingest cribl".
        product:    Optional product scope (same vocabulary as cortex_search).

    Returns {ok, suggestions: [title], pages: [{title, reader_url}]}."""
    try:
        pages = gitbook.suggest(input_text, product)
    except gitbook.DocsError as exc:
        return _err(str(exc))
    return {"ok": True, "suggestions": [p["title"] for p in pages], "pages": pages}


_NOISE = re.compile(r"^(cortex query language|xql|stage|function|the)\s+", re.I)


def _clean_term(term: str) -> str:
    text = (term or "").strip().strip("`'\"")
    for _ in range(3):
        text = _NOISE.sub("", text)
    return re.sub(r"\s*(stage|function)$", "", text, flags=re.I).strip()


def cortex_xql_lookup(term: str, kind: str = "auto", product: Optional[str] = None, per_page: int = 8,
                      suggest: bool = False) -> dict:
    """What one XQL stage or function does, with its syntax and examples.

    Args:
        term:     The stage or function name, for example dedup, comp, arrayindexof, json_extract_scalar. A leading "stage",
                  "function" or "XQL" is ignored.
        kind:     "auto" (default), "stage" or "function".
        product:  Product scope; defaults to xql (the XSIAM/XDR language reference).
        per_page: At most this many source pages are listed.
        suggest:  Also return pages whose address matches the term.

    Returns {ok, found, term, title, publication, reader_url, summary_content, hits, scope_note, suggestions?}. When the
    docs have no answer, {ok: true, found: false}."""
    clean = _clean_term(term)
    if not clean:
        return _err("term is required, for example 'dedup' or 'arrayindexof'")
    what = {"stage": "the XQL stage", "function": "the XQL function"}.get((kind or "auto").lower(), "the XQL stage or function")
    question = f"In Cortex Query Language XQL, what does {what} {clean} do? Give its syntax, arguments and examples."
    try:
        found = gitbook.ask(question, product or "xql", goal="write a correct XQL query")
        pages = gitbook.suggest(clean, product or "xql", limit=per_page) if suggest else None
    except gitbook.DocsError as exc:
        return _err(str(exc), found=False)
    answer = found["answer"].strip()
    top = found["hits"][0] if found["hits"] else {}
    out = {"ok": True, "found": bool(answer), "term": clean, "title": top.get("title"), "publication": found["book"],
           "reader_url": top.get("reader_url"), "summary_content": answer, "hits": found["hits"][:max(1, per_page)],
           "scope_note": "XQL reference as answered by the Cortex documentation for " + found["book"]}
    if pages is not None:
        out["suggestions"] = pages
    return out


def cortex_fetch_topic(url: str, max_chars: int = 12000) -> dict:
    """The Markdown of one documentation page.

    Args:
        url:       The page address, as returned in a `hits[].reader_url` (a path such as /cortex-xsiam/... also works).
                   Only pages on the Cortex docs site can be fetched.
        max_chars: Cut the content at this many characters (default 12000); `truncated` says when it was cut.

    Returns {ok, title, reader_url, content, truncated, total_chars}."""
    try:
        page = gitbook.fetch(url, max(500, int(max_chars or 12000)))
    except gitbook.DocsError as exc:
        return _err(str(exc))
    return {"ok": True, **page}


def cortex_fetch_toc(book: str, max_items: int = 300) -> dict:
    """The pages of one documentation book, in site order, with their depth.

    Args:
        book:      A product (xsiam, xdr, xsoar, agentix, cloud, xpanse), a book slug (cortex-xsiam) or any page URL of the book.
        max_items: Cut the list after this many pages (default 300; XSIAM has over 2,000).

    Returns {ok, book, total_pages, items: [{title, reader_url, depth}], truncated}."""
    try:
        return {"ok": True, **gitbook.toc(book, max(1, min(int(max_items or 300), 2000)))}
    except gitbook.DocsError as exc:
        return _err(str(exc))


def cortex_deep_research(request: str, max_sections: int = 3, hits_per_section: int = 4, enable_gap_check: bool = False,
                         model: Optional[str] = None) -> dict:
    """Research a topic across several linked questions and return one brief with citations.

    It asks the docs the request, then the follow-up questions the docs suggest (up to `max_sections` questions in all),
    and collects every answer and source page. A question nobody asked before takes about 30 seconds, so it stops
    starting new questions after 75 seconds and returns what it has (`partial: true`). Use it for a deliverable (a
    briefing, a comparison); for one fact use cortex_search.

    Args:
        request:          What to research, for example "How XSIAM ingests data from Cribl, and what each source needs".
        max_sections:     At most this many questions are asked (1-12, default 3; a new question takes about 30 seconds).
        hits_per_section: At most this many sources are kept per section (default 4).
        enable_gap_check: Accepted for compatibility; the docs site already searches the whole book per question.
        model:            Accepted for compatibility; no model is used, the docs site writes the answers.

    Returns {ok, brief: {request, sections: [{question, answer, sources}], citations: [{title, reader_url}], coverage, stats}}."""
    if not (request or "").strip():
        return _err("request is required")
    limit = max(1, min(int(max_sections or 3), 12))
    deadline = time.monotonic() + RESEARCH_BUDGET_SECONDS
    keep = max(1, min(int(hits_per_section or 4), 20))
    questions, sections, citations, seen = [request.strip()], [], {}, set()
    try:
        while questions and len(sections) < limit:
            q = questions.pop(0)
            if q in seen:
                continue
            if sections and time.monotonic() > deadline:
                return {"ok": True, "partial": True, "warning": "stopped at the time budget; call again with a narrower request for more",
                        "brief": _brief(request, sections, citations)}
            seen.add(q)
            found = gitbook.ask(q, None, goal=request.strip())
            sections.append({"question": q, "answer": found["answer"], "sources": found["hits"][:keep]})
            for hit in found["hits"]:
                citations.setdefault(hit["reader_url"], hit)
            questions += [f for f in found["follow_ups"] if f not in seen]
    except gitbook.DocsError as exc:
        if not sections:
            return _err(str(exc))
        return {"ok": True, "partial": True, "warning": str(exc), "brief": _brief(request, sections, citations)}
    return {"ok": True, "brief": _brief(request, sections, citations)}


def _brief(request: str, sections: list, citations: dict) -> dict:
    return {"request": request, "sections": sections, "citations": list(citations.values()),
            "coverage": {"sections": len(sections), "answered": sum(1 for s in sections if s["answer"])},
            "stats": {"requests": len(sections), "citations": len(citations)}}


__all__ = [
    "cortex_search",
    "cortex_suggest",
    "cortex_xql_lookup",
    "cortex_fetch_topic",
    "cortex_fetch_toc",
    "cortex_deep_research",
]
