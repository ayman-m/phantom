---
name: cortex_xql_query_authoring
displayName: Cortex XQL query authoring
category: foundation
description: 'Compose authoritative Cortex Query Language (XQL) queries by chaining the operator''s own example-query knowledge base with Palo Alto Networks''s public Cortex documentation. Workflow: (1) embedding-search the operator''s KB for ~5 similar example queries, (2) extract the XQL stages and functions used in those examples, (3) for each stage/function, hit cortex-docs/xql_lookup against the canonical Cortex docs, (4) assemble a focused doc-grounded context, (5) author the query. The cortex-docs connector wraps the Palo Alto Cortex public docs API (XDR / XSIAM / AgentiX / Cortex Cloud / XSOAR / Xpanse) with cortex_search, cortex_suggest, cortex_xql_lookup, cortex_fetch_topic, cortex_fetch_toc, and cortex_deep_research. Triggers when the operator wants to build, fix, or extend an XQL query and needs both an in-house example and authoritative syntax docs.'
icon: query_stats
source: platform
loadingMode: on-demand
locked: false
attack: []
---

# Skill: Cortex XQL query authoring

## Category

foundation

## Purpose

Bridge the operator's **internal query knowledge base** (past queries that worked, sometimes embedded for similarity search) with the **canonical Palo Alto Networks Cortex documentation** so the agent can author XQL queries that are both pattern-correct (matches what the org's queries already look like) and syntax-correct (matches what the docs say each stage and function actually does).

This skill exists because XQL query authoring failure modes split cleanly into two camps:

1. **Pattern drift** — the agent invents an idiom that doesn't match how the org's queries are usually written (wrong dataset names, wrong field aliases, missing org-specific lookups).
2. **Syntax drift** — the agent uses a stage/function that doesn't exist, has the wrong argument order, or has subtle behavioural differences across Cortex products (some functions on AgentiX behave differently than on XSIAM).

Embedding-search against the operator's KB fixes (1). The cortex-docs connector tools fix (2). The skill ties them together.

## Connector tools used

This skill drives the `cortex-docs` connector. The relevant tools:

| Tool | When to call |
|---|---|
| `cortex-docs/xql_lookup` | Primary lookup. Per stage/function name, returns the canonical doc topic with summary content, source citation, and reader URL. Default `product: xql` searches all XQL-capable products. |
| `cortex-docs/search` | Free-text search across all Cortex docs. Use when `xql_lookup` returns `found: false` or when the operator's question isn't a single stage/function (e.g. "how do I bin data into 5-minute buckets?"). |
| `cortex-docs/suggest` | Autocomplete for ambiguous partial terms. Useful when the operator writes "comp" — could be `comp` stage or a typo of `complete`. |
| `cortex-docs/fetch_topic` | Pull a page's full text given its `url` (a `reader_url` from a prior search hit or lookup). Use when the lookup answer is too brief. |
| `cortex-docs/fetch_toc` | Enumerate every topic in a publication. Rarely needed by this skill; useful when the operator wants to browse a topic family. |
| `cortex-docs/deep_research` | Heavyweight (1-3 min). Reserve for explicit multi-section deliverables ("write me a partner briefing on XSIAM alert triage"). DO NOT call from this skill's standard flow — too slow for query authoring. |

For full per-tool argument schema, see the cortex-docs connector page in `/connectors`.

## Standard authoring workflow

### Step 1 — Understand the operator's query intent

Before any tool call, restate the request to confirm scope:

- What's the dataset class? (`xdr_data`, `endpoint_data`, `incident_data`, `lookup table name`, etc.)
- What's the time window?
- What's the output shape — alert? table? aggregation? trend?
- What product context? (XDR? XSIAM? AgentiX? Cloud?)

If any of these is unclear, ask once, then proceed.

### Step 2 — Find ~5 similar examples in the operator's KB

Hit the operator's example-query knowledge base via the agent's existing `knowledge_search` tool family (NOT a cortex-docs tool — this is a separate KB). Aim for 5 hits, top similarity. Each hit is a previously-validated XQL query with metadata about what it did.

If the operator's KB has no relevant entries, skip directly to step 4 — the cortex-docs lookup alone is usable, just less idiomatic.

### Step 3 — Extract stages and functions from the examples

Parse each example query and pull out:

- **Stages** — `filter`, `comp`, `alter`, `sort`, `dedup`, `bin`, `arrayexpand`, `call`, `fields`, `config`, etc. (canonical list of XQL stages: see `cortex-docs/xql_lookup --kind stage --product xql` if you need the authoritative set)
- **Functions** — `arrayindexof`, `json_extract_scalar`, `to_timestamp`, `concat`, `lookup`, etc. Functions appear inside `alter` and `filter` clauses; identify them by `(`...`)` patterns following identifiers.
- **Datasets** — names appearing right after `dataset =` or piped from a lookup. Carry these through unchanged; the operator's KB is authoritative for naming.
- **Org-specific lookups** — `| call ...` references and named query inclusions. Carry through.

Deduplicate. You typically end up with 8-15 unique stages + functions across 5 examples.

### Step 4 — Look up each stage and function in Cortex docs

For each unique stage/function name from step 3, call `cortex-docs/xql_lookup`:

```
cortex-docs/xql_lookup(term="dedup", kind="stage", product="<product from step 1>")
cortex-docs/xql_lookup(term="arrayindexof", kind="function", product="xql")
```

Tactics:

- **Default `kind`** to `auto` only if you can't tell from context; the upstream's stage list (`alter`, `arrayexpand`, `bin`, `call`, `comp`, `config`, `dedup`, `fields`, `filter`, `sort`) gives correct inference for the canonical 10. Anything else is a function.
- **Narrow `product`** when the operator gave a product context. Default `xql` searches all products and is fine when no context is given, but `xsiam` / `xdr` / `agentix` / `cloud` returns more focused docs.
- **Run lookups in parallel** if your runtime supports it — the docs API tolerates concurrent reads, and 8-15 lookups serialised would noticeably stretch the response.

For each lookup, capture:

- `title` — the canonical name (often differs from the term you queried; e.g. `arrayindexof` → `Arrayindexof Function`)
- `summary_content` — the truncated docs body (≤2,200 chars)
- `source` — citation string for the response
- `reader_url` — let the operator click through to the full docs page if needed

If `cortex-docs/xql_lookup` returns `found: false`:

- Check `suggestions` for a typo correction (e.g. operator wrote `dedupe` → suggestion `dedup`)
- Fall back to `cortex-docs/search` with the bare term + product context
- If still nothing, note the gap in your response — don't invent syntax

### Step 5 — Author the query, citing per stage/function

Compose the XQL query using:

- The operator's KB examples as the **pattern prior** — match dataset names, field aliases, ordering conventions
- The cortex-docs lookups as the **syntax reference** — use exact stage/function syntax, argument order, and behavioral notes from the docs

Output shape:

````markdown
**Query:**

```xql
dataset = xdr_data
| filter event_type = "Login" and event_sub_type = "Success"
| alter ts_5m = bin(_time, 5m)
| comp count() as logins by user_name, ts_5m
| filter logins > 50
| sort desc logins
```

**Authored from:**

- 5 similar queries in the org KB (paths: ...).
- Cortex docs lookups for: `filter`, `alter`, `bin`, `comp`, `sort`.
  Source: cortex-docs.paloaltonetworks.com - Filter Stage (Cortex XSIAM Documentation), Alter Stage (Cortex XSIAM Documentation), bin Function (Cortex XSIAM Documentation), Comp Stage (Cortex XSIAM Documentation), Sort Stage (Cortex XSIAM Documentation).

**Notes:**

- `bin` function returns a bucket label per row; using `bin` as a tagging function inside `alter` rather than as a standalone stage matches the dominant pattern in the org KB.
- Counts > 50 in 5 minutes is the threshold the example queries used; tune via the `filter logins > N` clause.
````

Always cite the docs as `cortex-docs.paloaltonetworks.com - <Title> (<reader_url>)`, using the title and `reader_url` the connector returns.

### Step 6 — Offer to broaden if the result feels under-grounded

If only 0-1 examples came back from step 2, tell the operator and offer a `cortex-docs/deep_research` follow-up for the broader topic:

> "I had no similar queries in your KB to anchor this against, so the result is leaning on Cortex docs alone. Want me to also run a `deep_research` against `<topic>` to surface multi-topic context? It takes 1-3 minutes."

Reserve `deep_research` for explicit operator opt-in; don't fire it as part of the default flow.

## Failure handling

| Symptom | Likely cause | Fix |
|---|---|---|
| `cortex-docs/xql_lookup` returns `ok: false, error: "cortex-docs API call failed"` | Docs API unreachable (network blip, GitHub Actions runner egress, customer firewall) | Retry once. If still failing, tell the operator "Cortex docs are temporarily unreachable; falling back to operator-KB-only" and proceed with reduced confidence |
| `found: false` even with correct spelling | Term may be product-specific. Re-call with explicit `product` (e.g. `xsiam` instead of default `xql`) | Cortex publications occasionally hide a function under one product but not others |
| Only release-notes pages come back | The lookup ranking subtracts heavy points from release notes, so this is rare. If it happens, search with `cortex-docs/search` + the `product` scope; release notes show up because the search hit no canonical reference page | Tell the operator the canonical reference page is missing; cite the release note with that caveat |
| No KB examples + docs say `found: false` for everything | The operator's question is outside Cortex's documented surface (private internal field, custom playbook, etc.) | Don't invent. Tell the operator and ask for example syntax from their environment |
| `xsiam.get_datasets` returns `{"error": "xsiam instance has no api_key (Authorization header) configured"}` or similar XSIAM connector error | The operator hasn't installed/configured an XSIAM provider, OR the configured instance is missing the API key | **Do NOT retry via other XSIAM tools** (they will all fail the same way). Ask the operator directly for the dataset name (e.g. `cisco_esa_raw`, `xdr_data`) and proceed with cortex-docs/xql_lookup for syntax. The skill is designed to work end-to-end without XSIAM access — the operator's KB and cortex-docs cover the authoring path. Only mention XSIAM tools as a side note: *"If you'd like the agent to discover datasets automatically, configure an XSIAM provider in /providers."* |
| `xsiam_get_xql_doc` returns `{"error": "xql_doc.md not found"}` | This tool does not exist (there is no bundled offline XQL doc). | **Don't call this tool.** Use `cortex-docs/xql_lookup` instead (per the workflow above). |

## Operator-visible surfaces

After this skill runs, the agent's chat response should include:

- The composed query in a code fence
- One short sentence per cited docs source (e.g. "filter from Cortex XSIAM Documentation")
- A 1-2 line "notes" block flagging anything non-obvious (window size choice, threshold defaults, alternatives the agent considered but didn't pick)

The `cortex-docs` connector's full tool surface is also visible in `/observability/connectors` — operators auditing what the agent called can see each `cortex_search` and `cortex_xql_lookup` invocation in the live tool-call log.

## Adapting per deployment

Per-product narrowing matters. Different Cortex products have different idiomatic XQL — XSIAM datasets are wider than XDR's; AgentiX adds extension functions some other products don't expose. When the operator's product context is clear, **always** narrow `product` on the `cortex-docs/xql_lookup` calls. The cross-product `xql` default is correct only when context is absent.

For an operator who runs multiple Cortex products (XDR + XSIAM + Cloud), keep two fallback strategies in mind:

- **Same query intent, multiple products** — run lookups against each product's scope and present a comparison table
- **Org idioms cross products** — the operator's KB examples are the tiebreaker; the docs say "either form is valid", the org KB picks one

## Skill bodies elsewhere

This skill complements but doesn't replace the broader `cortex-deep-search` workflow (also in this connector via `cortex-docs/deep_research`). Use this skill for query authoring; use deep-research for whitepapers / partner briefings / migration guides.
