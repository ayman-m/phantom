---
name: cortex_kb_search
displayName: Cortex KB Search (cortex-docs.paloaltonetworks.com)
category: foundation
description: 'Answer questions about Palo Alto Networks Cortex products (XDR, XSIAM, XSOAR, AgentiX, Cortex Cloud, Xpanse, XQL) from the official public documentation via the cortex-docs connector, with citations. Use this skill when the operator asks ANY Cortex product question: a feature, a configuration, troubleshooting, an API endpoint, XQL syntax. The workflow: (1) split a multi-topic request into one question per topic, (2) cortex-docs/search with a plain-words question and a product scope (it returns the docs'' own answer, the source pages and follow-up questions), (3) cortex-docs/fetch_topic on a source page when the answer needs more detail, (4) answer per topic and cite the pages. Two related skills hold the lookup tables: cortex_kb_search_patterns for question shaping by intent and fallbacks, and cortex_kb_api_reference for how the documentation site works (load only when needed).'
icon: menu_book
source: platform
loadingMode: on-demand
locked: false
attack: []
---

# Skill: Cortex KB Search

## Category

foundation

## Purpose

Answer questions about Palo Alto Networks Cortex products from the official public documentation at `cortex-docs.paloaltonetworks.com`, and say which pages the answer came from. The documentation site answers questions itself: you ask it a question in plain words and it returns an answer, the pages it drew on and follow-up questions. Your job is to ask well, check the answer against the source pages when it matters, and never state something the tools did not return.

## Available tools

| Tool | Use |
|---|---|
| `cortex-docs/search` | Ask a question. Returns `answer`, `hits` (source pages with `reader_url`) and `follow_ups`. |
| `cortex-docs/suggest` | Pages whose address contains the words typed so far; use it to find the exact title of a feature. |
| `cortex-docs/fetch_topic` | The Markdown of one page (`url` from a hit's `reader_url`). |
| `cortex-docs/fetch_toc` | The pages of one book, in site order (XSIAM has over 2,000; prefer search). |
| `cortex-docs/xql_lookup` | One XQL stage or function: what it does, syntax, examples. |
| `cortex-docs/deep_research` | Several linked questions in one brief with citations, for a deliverable (slow). |

A question nobody asked before takes about 30 seconds to answer; a repeat comes back at once. Do not retry a slow call.

## Workflow

### Step 0 — One question per topic

If the operator asks about two things, make two searches and answer both. Do not merge two topics into one question; the answer will cover one and skim the other.

```
# Single topic: one search
cortex-docs/search(query="How do I send logs to XSIAM from Cribl?", product="xsiam")

# Two topics: two searches
cortex-docs/search(query="What does the XDR agent prevention profile control?", product="xdr")
cortex-docs/search(query="How are XSIAM alerts grouped into cases?", product="xsiam")
```

### Step 1 — Ask in plain words, with a product

Write the question the way you would ask a colleague, naming the feature with Palo Alto's own words ("Broker VM", "correlation rule", "data model rule", "Cribl integration"), not the operator's shorthand. Pass `product` whenever the area is known (see the table below); when omitted it is read from the question and defaults to XSIAM.

Keep the question short and plain. Backticks, parentheses and other punctuation are replaced with spaces before the question is sent.

If you are unsure of the feature's exact name, call `cortex-docs/suggest(input_text="broker vm azure")` first and use the title it returns.

### Step 2 — Read the answer, then the sources

`answer` is the docs' own answer. Use it as the base of your reply. When the question needs detail the answer skipped (exact field names, every step of a procedure, a table), fetch the page:

```
cortex-docs/fetch_topic(url="<hits[0].reader_url>")
cortex-docs/fetch_topic(url="<hits[0].reader_url>", max_chars=30000)
```

`truncated: true` means the page was cut at `max_chars`. If the answer is weak or off-topic, ask one of the `follow_ups`, or ask again with different words. Do not ask the same question twice.

### Step 3 — Answer, per topic

Lead with the answer to the question that was asked. Keep to what the answer and pages say. If they disagree, or the docs do not cover it, say so plainly instead of filling the gap.

### Step 4 — Cite

End with the pages you used, as titles with their `reader_url`:

```
Sources:
- Ingest data from Cribl (https://cortex-docs.paloaltonetworks.com/cortex-xsiam/.../ingest-data-from-cribl)
```

## Product Scope Reference

| `product` key | Book |
|---|---|
| `xsiam`, `xql` | Cortex XSIAM (`cortex-xsiam`) |
| `xdr` | Cortex XDR 5.x (`cortex-xdr-5.x`) |
| `xsoar` | Cortex XSOAR 8 SaaS (`cortex-xsoar-8-saas`) |
| `agentix` | Cortex AgentiX (`cortex-agentix`) |
| `cloud`, `cspm`, `dspm`, `ciem` | Cortex Cloud posture management (`cortex-cloud-posture-management`) |
| `xpanse` | Cortex Xpanse (`cortex-xpanse`) |

Other books exist (release notes, API references, older XDR versions, agent guides). Pass a page URL to `fetch_topic` or a book slug to `fetch_toc` to reach them.

## Constraints

- The documentation is public: no credential is involved, and only `cortex-docs.paloaltonetworks.com` pages can be fetched.
- Do not invent documentation that the tools did not return. If a call fails, say that the docs could not be reached and answer only from what you already have, marked as unsourced.
- If results are weak, state the uncertainty and still give the best evidence-backed answer; do not ask the operator to rephrase.
- For multi-topic requests, finish all searches before you answer.

## Cross-references

- **Related Phantom skills**: `cortex_xql_query_authoring` (pairs this skill with the XQL example knowledge base for query authoring); `cortex_kb_search_patterns` (question shaping by intent, fallbacks); `cortex_kb_api_reference` (how the documentation site works).
- **Connector**: `cortex-docs`, see `bundles/spark/connectors/cortex-docs/`.
