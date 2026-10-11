---
name: cortex_kb_search_patterns
displayName: Cortex KB Search — Query Patterns & Quality Guide
category: foundation
description: 'Lazy-loaded companion to cortex_kb_search. Holds the query-shaping tables (by intent, per Cortex product), the fallback strategies for when search returns 0 or off-topic hits, the XQL stage quick-lookup reference, and the response quality checklist. The parent skill loads THIS skill only when one of these triggers fires: search returned 0 or irrelevant hits, the user question is vague, or the agent is about to write a final answer and wants the quality checklist. Not loaded preemptively — keeps the agent context lean for standard search-fetch-answer flows.'
icon: pattern
source: platform
loadingMode: on-demand
locked: false
attack: []
---

# Skill: Cortex KB Search — Query Patterns & Quality Guide

> **Load this skill only when one of these conditions is true:**
> - Search returned 0 results or all hits seem off-topic → use § Fallback Strategies
> - The user's question is vague or uses industry terms Palo Alto doesn't use → use § Query Shaping by Intent
> - You are about to write a final answer and want to verify quality → use § Response Quality Checklist
>
> You do NOT need this skill for a standard `cortex-docs/search` → `cortex-docs/fetch_topic` → answer workflow.

---

## Query Shaping by Intent

Map the user's question type to effective search keywords:

### XQL / Query Language

> **Important:** XQL stage topics are titled with just the stage name (`filter`, `dedup`, `comp`).
> Do NOT append "stage XQL" — that matches dashboard widget topics, not the stage reference pages.
> See § XQL Stage Reference for the complete list.

| User says | Search query | `product` value |
|---|---|---|
| "how to write an XQL query" | `XQL query syntax` | `agentix` |
| "filter stage in XQL" | `Cortex Query Language filter` | `agentix` |
| "aggregate / group by" | `Cortex Query Language comp` | `agentix` |
| "deduplicate results" | `Cortex Query Language dedup` | `agentix` |
| "join datasets" | `Cortex Query Language call` | `agentix` |
| "time-based filtering" | `Cortex Query Language config` | `agentix` |
| "regex in XQL" | `XQL regex pattern match` | `agentix` |
| "array operations" | `Cortex Query Language arrayexpand` | `agentix` |
| "call a dataset / sub-query" | `Cortex Query Language call` | `agentix` |
| "limit fields in output" | `Cortex Query Language fields` | `agentix` |
| "sort results" | `Cortex Query Language sort` | `agentix` |
| "alter / transform fields" | `Cortex Query Language alter` | `agentix` |
| "bin values / bucket" | `Cortex Query Language bin` | `agentix` |

### Cortex XSIAM — SOC / Analyst Workflows
| User says | Search query | `product` value |
|---|---|---|
| "alert triage" | `alert triage XSIAM` | `xsiam` |
| "investigation workflow" | `investigation work plan war room` | `xsiam` |
| "playbook automation" | `playbook XSIAM automation` | `xsiam` |
| "incident management" | `incident XSIAM management` | `xsiam` |
| "correlation rule" | `XSIAM correlation rule create` | `xsiam` |
| "BIOC rule" | `Behavioral Indicator of Compromise rule` | `xsiam` |
| "IOC management" | `Indicator of Compromise management` | `xsiam` |
| "detection stack overview" | `XSIAM detection analytics overview` | `xsiam` |
| "MITRE coverage" | `MITRE ATT&CK coverage mapping` | `xsiam` |
| "user risk score / UEBA" | `user risk score UEBA XSIAM` | `xsiam` |
| "threat intelligence" | `threat intel XSIAM feed` | `xsiam` |
| "network threat analysis" | `network analytics XSIAM` | `xsiam` |

### Cortex XDR — Endpoint Detection
| User says | Search query | `product` value |
|---|---|---|
| "install agent" | `XDR agent install deployment` | `xdr` |
| "Broker VM setup" | `Broker VM system requirements` | `xdr` |
| "Broker VM hardware requirements" | `Broker VM hardware requirements` | `xdr` |
| "prevention profile" | `XDR prevention policy profile` | `xdr` |
| "exclusions / exceptions" | `XDR exclusion exception allow` | `xdr` |
| "response actions" | `XDR response isolate remediate` | `xdr` |
| "live terminal / remote" | `XDR live terminal remote session` | `xdr` |
| "forensics / causality" | `XDR causality chain forensics` | `xdr` |
| "ransomware protection" | `XDR ransomware protection prevention` | `xdr` |
| "ITDR / identity threat" | `Identity Threat Detection and Response` | `xdr` |
| "disaster recovery" | `Cortex XDR disaster recovery Elasticsearch` | `xsoar` |

### Cortex AgentiX
| User says | Search query | `product` value |
|---|---|---|
| "what is AgentiX" | `AgentiX overview introduction` | `agentix` |
| "AI agent / agentic" | `AgentiX agent workflow` | `agentix` |
| "data sources" | `AgentiX data source connect` | `agentix` |
| "natural language query" | `AgentiX natural language query` | `agentix` |

### Cortex Cloud / Cloud Security
| User says | Search query | `product` value |
|---|---|---|
| "DSPM" | `Cortex Cloud Data Security` (**not** "DSPM" — Palo Alto uses this brand name) | `cloud` |
| "data security posture" | `what is Cortex Cloud Data Security` | `cloud` |
| "cloud posture management / CSPM" | `what is Cortex Cloud Posture Management` | `cloud` |
| "cloud identity security / CIEM" | `Cortex Cloud Identity Security` | `cloud` |
| "cloud runtime security" | `Cortex Cloud Runtime Security` | `cloud` |
| "shadow data / data exposure" | `Cortex Cloud Data Security shadow data` | `cloud` |
| "AWS onboarding / permissions" | `AWS cloud account onboarding permissions` | `cloud` |
| "Azure onboarding" | `Azure cloud account onboarding` | `cloud` |
| "GCP onboarding" | `GCP cloud account onboarding` | `cloud` |
| "OCI onboarding" | `OCI Oracle cloud account onboarding` | `cloud` |

> **Terminology note:** Palo Alto does not prominently use the industry acronyms DSPM, CSPM, or CIEM. Always translate to the Palo Alto brand names before searching.

### Administration / Configuration
| User says | Search query | `product` value |
|---|---|---|
| "add user / RBAC" | `user management roles permissions` | _(any)_ |
| "API key" | `API key create manage` | _(any)_ |
| "SSO / identity" | `SSO SAML identity provider` | _(any)_ |
| "data retention" | `data retention policy` | _(any)_ |
| "audit log" | `audit log activity` | _(any)_ |
| "onboarding / tenant setup" | `onboarding tenant configuration` | _(any)_ |

---

## Terminology Reference

Use this as a normalization guide when rewriting user queries.

| Canonical term | User variants / common misspellings |
|---|---|
| `Cortex XDR` | `xdr`, `xtr`, `cortex xdr` |
| `Cortex AgentiX` | `agentix`, `agentx`, `agntx`, `agentics`, `cortex agentix` |
| `Cortex XSIAM` | `xsiam`, `xim`, `cortex xsiam` |
| `Cortex XSOAR` | `xsoar`, `cortex xsoar`, `soar` |
| `Cortex Cloud` | `cortex cloud`, `prisma cloud`, `cloud security` |
| `Cortex Xpanse` | `xpanse`, `cortex xpanse`, `expander` |
| `Broker VM` | `brokervm`, `broker virtual machine`, `log collector vm` |
| `XDR Engine` | `xdr engine`, `automation engine` |
| `Command Center` | `command center`, `central dashboard` |
| `Cases` | `case`, `incident case` |
| `Issues` | `issue`, `alerts/issues` |
| `Playbooks` | `playbook`, `playbox`, `automation playbook` |
| `Cloud Identity Engine` | `cie`, `cloud identity engine`, `identity engine` |
| `WildFire` | `wildfire`, `sandbox`, `signature matching` |
| `Behavioral Indicator of Compromise` | `bioc`, `behavior indicator of compromise` |
| `XQL (Extended Query Language)` | `xql`, `extended query language` |
| `Data Security Posture Management` | `dspm` |
| `Cloud Security Posture Management` | `cspm` |

Notes:
- Keep normalization conservative; avoid aggressive remapping when intent is unclear.
- Prefer canonical terms in search variants but preserve user intent language.

---

## Relevance Check (Before Using Fetched Content)

After fetching a topic, verify the content actually addresses what the user asked **before** using it to answer. This API is exact-match — irrelevant but keyword-matching topics are returned frequently.

| Situation | Action |
|---|---|
| Topic title references a **different product** than asked (e.g., user asked about Broker VM but fetched XSOAR hardware) | Discard. Fetch the next hit from search results instead. |
| Topic is about "misconfiguration alerts" or "rule reference" when user asked for configuration steps | Discard. Add `product` scope and re-search. |
| Topic title matches but content is a 1-2 sentence overview with no steps | Use `max_children=5` to load sub-topics. |
| Topic is about the right concept but a different product version than what's deployed | Use it but note the version caveat in the answer. |
| No relevant topic found after 2 retries | Acknowledge the gap. Provide only what the evidence supports and note the limitation. |

---

## Fallback Strategies (When Search Returns Poor Results)

Try these in order when initial search yields low relevance or empty results:

0. **Run autocomplete first** — Returns exact topic titles from the knowledge base, preventing keyword mismatch:
   ```
   cortex-docs/suggest(input_text="<core term>", product="xdr")
   ```
   Use the returned phrase verbatim as your next search query.

1. **Simplify the query** — Remove product name, keep only the feature term.
   - `"Cortex XSIAM filter XQL stage"` → `"filter stage"`

2. **Use the exact doc term** — Palo Alto docs use specific vocabulary:
   - "pipeline" → `stage` (XQL)
   - "groupBy / aggregate" → `comp stage`
   - "time window" → `timeframe`
   - "deduplication" → `dedup stage`
   - "join / lookup" → `call stage`
   - "war room" → `investigation war room`
   - "storyline" → `causality chain`
   - "DSPM" → `Cortex Cloud Data Security`
   - "CSPM" → `Cortex Cloud Posture Management`
   - "CIEM" → `Cortex Cloud Identity Security`
   - "incident" (XSOAR context) → `case` (XDR context uses "case")

3. **Scope with `product`** — Global search may drown signal in noise:
   ```
   cortex-docs/search(query="filter", product="agentix")
   ```

4. **Browse the TOC** — When you know the product but not the exact topic, list the book's pages and scan for a matching title:
   ```
   cortex-docs/suggest(input_text="broker vm", product="xsiam")        # pages whose address matches the words
   cortex-docs/fetch_toc(book="xsiam", max_items=300)                   # the book's pages in site order (over 2,000 for XSIAM)
   ```
   Take the `reader_url` of the page you want and pass it to `cortex-docs/fetch_topic(url=...)`.

5. **Fetch the parent page** — If a page is thin, fetch the page one level up (drop the last path segment of its `reader_url`).

---

## XQL Stage Reference (Quick Lookup)

For one XQL stage or function, use the purpose-built tool; it asks the docs the right question for you:

```
cortex-docs/xql_lookup(term="dedup")
cortex-docs/xql_lookup(term="arrayindexof", kind="function")
```

A general question about the language works too: `cortex-docs/search(query="How does the XQL comp stage group results?", product="xql")`.

| Stage | Description | Lookup |
|---|---|---|
| `alter` | Add/modify dataset fields | `xql_lookup(term=\"alter\")` |
| `arrayexpand` | Expand array fields to rows | `xql_lookup(term=\"arrayexpand\")` |
| `bin` | Bucket numeric/time values | `xql_lookup(term=\"bin\")` |
| `call` | Sub-query / dataset join | `xql_lookup(term=\"call\")` |
| `comp` | Aggregate / group by | `xql_lookup(term=\"comp\")` |
| `config` | Query config (timeframe, runtime) | `xql_lookup(term=\"config\")` |
| `dedup` | Deduplicate results | `xql_lookup(term=\"dedup\")` |
| `fields` | Select/rename output fields | `xql_lookup(term=\"fields\")` |
| `filter` | Filter rows by condition | `xql_lookup(term=\"filter\")` |
| `sort` | Sort results | `xql_lookup(term=\"sort\")` |
| All stages | The stage list | `fetch_toc(book="xsiam")`, then the pages under the XQL reference |

---

## Response Quality Checklist

Before finalizing an answer, verify:

- [ ] **Direct answer first** — Lead with a 1-sentence answer to the question.
- [ ] **Source is present** — Every answer ends with a `Source:` line citing the doc title.
- [ ] **Code blocks used** — XQL syntax, CLI commands, and JSON shown in ` ``` ` fences.
- [ ] **Steps are numbered** — Procedural instructions use a numbered list (3-6 items).
- [ ] **Uncertainty flagged** — If no relevant result was found, state: "I couldn't find specific documentation on this. Here's what I know generally…"
- [ ] **No hallucination** — Only assert facts that appeared in the fetched content.
- [ ] **Excerpt cited correctly** — When quoting, use the actual excerpt text returned by the API.
- [ ] **Product name accurate** — Distinguish: Cortex XDR (endpoint), XSIAM (SOC platform), AgentiX (agentic AI), Cortex CLOUD (cloud security).

---

## Source Line Format

```
Source: docs-cortex.paloaltonetworks.com — <Topic Title> (<Publication Name>)
```

Examples:
```
Source: docs-cortex.paloaltonetworks.com — filter Stage (Cortex AgentiX Documentation)
Source: docs-cortex.paloaltonetworks.com — Alert Triage Overview (Cortex XSIAM Admin Guide)
Source: General knowledge (docs lookup returned no results for this query)
```

## Cross-references

- Parent skill: `cortex_kb_search` (loads this one only when needed)
- Sibling skill: `cortex_kb_api_reference` (raw API spec; load when crafting custom API calls beyond what the connector tools expose)
