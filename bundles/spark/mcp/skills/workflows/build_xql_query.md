---
name: build_xql_query
displayName: Build a working Cortex XQL query from natural language (Cortex XDR / XSIAM)
category: workflows
description: '**LOAD-FIRST FOR ANY XQL QUERY REQUEST.** Whenever the operator asks to build, find, show, list, count, hunt, detect, alert on, or aggregate ANY data from Cortex XDR / XSIAM (endpoints, processes, network events, logins, alerts, incidents, files, etc.) — call `skills_read({file_path: "workflows/build_xql_query.md"})` IMMEDIATELY as your first tool call, BEFORE invoking `cortex_xql_lookup`, `knowledge_search`, `cortex_search`, or `xdr_run_xql_query`. The skill body contains a mandatory 7-step procedure that prevents wasted iterations on XDR-side syntax errors. Skipping the skill and going directly to the tools is an anti-pattern that burns retries on queries that should be right the first time. Skill chains: knowledge_search (operator KB of XQL examples) → top-5 → extract stages/functions/dataset → cortex_xql_lookup (each stage + function) → optional cortex_search (dataset field schema) → synthesize → xdr_run_xql_query → iterate on FAIL with 8 named error patterns. Lab-safe — read-only against XDR.'
icon: query_stats
source: platform
loadingMode: on-demand
locked: false
attack: []
---

> **WHY YOU ARE READING THIS:** because the user asked an XQL query question. If you reached this skill body via `skills_read`, do not skip ahead — the 7 steps below are mandatory in order. If you found yourself about to call `cortex_xql_lookup` or `xdr_run_xql_query` directly, STOP and start at Step 1 (`knowledge_search`). The chain exists because direct-to-cortex-docs synthesis produces queries XDR rejects with HTTP 500. A query that should take 1 XDR call takes 5 when Step 1 is skipped.

> ## ⚠️ XDR vs XSIAM tenant — tool selection
>
> Cortex XQL has the same syntax across both products, but **the tools target different connector instances which point at different tenants**:
>
> | If the operator's question is about... | Use these tools (NOT the other family) |
> |---|---|
> | Cortex **XDR** (endpoints, processes, XDR alerts) | `xdr_run_xql_query`, `xdr_xql_list_datasets`, `xdr_xql_get_results` |
> | Cortex **XSIAM** (broker-ingested logs, SIEM datasets, e.g. `*_raw` datasets like `amazon_web_services_aws_cloudtrail_raw`, `servicenow_servicenow_raw`, `okta_okta_raw`) | `xsiam.run_xql_query`, `xsiam.get_datasets` |
>
> **Routing rule**: if the operator names XSIAM, or asks about a `*_raw` dataset, or mentions broker / parsing rules / modeling rules — substitute every `xdr_*_xql_*` reference in this skill's procedure with the `xsiam_*` equivalent. Step 1's `knowledge_search` + Steps 2-3's `cortex_xql_lookup` / `cortex_search` are unchanged (the XQL syntax docs are tenant-neutral); only the **executor** changes.
>
> **Failure mode if you mis-route**: the query executes against the wrong tenant's data, returning 500 errors or wrong-tenant results that look like "0 events landed" when the events actually DID land in the correct tenant. Verifying XSIAM events via `xdr_run_xql_query` burns many tool calls — the verify step keeps failing because it looks at a different Cortex tenant.


# Skill: Build a working Cortex XQL query from natural language

## Category

workflows

## Purpose

Turn an analyst's natural-language question into a **working** XQL query without requiring the analyst to know XQL syntax. The skill chains four authoritative knowledge sources — the operator's own XSIAM-saved-query corpus (KB), the public Cortex documentation (via `cortex_xql_lookup` + `cortex_search`), and finally the live XDR tenant (via `xdr_run_xql_query`) — so the synthesized query carries the same shape as queries the operator has already proven work in production.

**"Working" means**: XDR accepts the query without a 4xx/5xx response. Specifically, `xdr_run_xql_query` returns `status: "SUCCESS"`. An empty result set (`total_rows: 0`) STILL counts as working — the dataset may simply not have matching events in the current time window. Only `status: "FAIL"` / `"FAILED"` / `"CANCELLED"` / `"TIMEOUT"` or a raised HTTPError indicates the query needs fixing.

## When to run

- Operator asks an SOC-analyst question that's clearly an XQL query: *"show me hosts with unusual outbound network traffic"*, *"find failed RDP login attempts in the last hour"*, *"detect rare PSEXEC process executions"*, *"users authenticated from new countries this week"*.
- Operator pastes a partial / broken XQL query and asks to "make it work" — same chain applies, with the broken query as additional context.
- Mid-investigation when a tool's output suggests a follow-up query (*"we found 3 hosts hitting suspicious IPs; pivot to find which processes initiated those connections"*).

## When NOT to run

- The operator's question doesn't need data from XDR at all (*"what's the syntax of the `comp` stage?"* — that's just `cortex_xql_lookup`, no need for the full skill).
- No cortex-xdr connector is configured on the install (the skill will detect this on the final `xdr_run_xql_query` step and report a clean error rather than blindly retrying — but it's still wasted work to embark on the retrieval chain if there's no XDR to execute against).
- The operator's question is about a non-XQL SIEM (Splunk, Sentinel, etc.) — wrong tool for the job.
- "Test of telemetry coverage after a simulation" — that's `xdr_verify_simulation_telemetry`, NOT this skill. That skill uses `xdr_get_cases_and_issues` with operator-supplied time bounds; it doesn't synthesize a query.

## Tools used

In invocation order:

1. **`knowledge_search`** (built-in MCP tool) — embeds the user's question via Vertex AI's `text-embedding-004`, computes cosine similarity against the `xql-examples` KB (hundreds of curated entries), returns top-5 matches with scores.
2. **`cortex_xql_lookup`** (cortex-docs connector) — given a stage name (`comp`, `filter`, `alter`, `dedup`, `transaction`, ...) or a function name (`arrayindex`, `json_extract_scalar`, `count_distinct`, `regextract`, ...), returns the canonical documentation page from `docs-cortex.paloaltonetworks.com` — title, reader_url, summary_content. Returns `{found: false}` if the term doesn't resolve.
3. **`cortex_search`** (cortex-docs connector) — broader-search version of cortex_xql_lookup. Use when you need to look up a DATASET'S field schema (e.g. *"what fields does `xdr_data` have for network events?"*) or a multi-topic question (`cortex_xql_lookup` is single-term-focused).
4. **`xdr_run_xql_query`** (cortex-xdr connector) — executes the synthesized query against the configured XDR tenant. Returns one of: `{status: "SUCCESS", execution_id, results, total_rows, fields}` (working), `{status: "FAIL"|"FAILED"|"CANCELLED"|"TIMEOUT", error}` (rejected — read `error`), or `{status: "PENDING", execution_id}` (still polling — call `xdr_get_xql_results` to finish).

Optional fifth step if needed:

5. **`xdr_get_xql_results`** — for the PENDING case. Polls until SUCCESS or terminal failure.

> **Polling the REST API directly** (no connector): `POST /public_api/v1/xql/start_xql_query/`
> returns a `reply` (query id); poll `POST /public_api/v1/xql/get_query_results/` with that id.
> The status field is **UPPERCASE** — `SUCCESS` / `FAIL` / `PENDING`. A lowercase comparison
> (`status == "success"`) never matches and polls forever. On `FAIL`, read `validation_message`
> in the response — unknown-field and syntax errors are spelled out there.

## Procedure (the 7-step chain)

### Step 1 — Embed + search the KB for top-5 similar examples (MANDATORY — FIRST CALL)

This step is **NOT OPTIONAL** and must be the **FIRST** tool you call in this skill — BEFORE any `cortex_xql_lookup`, BEFORE any `xdr_run_xql_query`. Even when the user's question feels "obviously" composable from first principles (anomaly detection, top-N aggregations, statistical thresholds, etc.), you MUST start by searching the operator's XQL example KB. Three concrete reasons, each grounded in a real failure mode caught during operator testing:

1. **The operator's corpus encodes tenant-specific patterns the public docs don't reveal.** The XSIAM-saved-query examples carry the operator's actual field names, the actual `event_type` / `event_sub_type` enum values that the tenant uses, and the actual stage-ordering patterns that XDR's parser accepts. Synthesizing from `cortex_xql_lookup` alone gives you syntactically-correct queries that XDR's parser rejects because tenant-specific syntax variants aren't documented (a typical failure mode: an anomaly-detection query goes through several XDR-side syntax-error iterations that `knowledge_search` would have avoided by surfacing an existing `bin + comp + windowcomp` pattern).
2. **The corpus has wide stage-pattern coverage.** With examples spanning several categories (investigation, detection, alert-mapping, general, plus XDR patterns), the KB has at least 3-5 examples for virtually every analyst question — including statistical hunting, anomaly detection, multi-stage aggregation, and cross-dataset correlation. If you're tempted to skip this step because "the KB won't have this", you're almost certainly wrong; ALWAYS search before deciding.
3. **The skill is named `build_xql_query` not `compose_xql_query_from_docs`**. The whole reason this skill exists is to ground LLM synthesis in operator-validated patterns. Skipping `knowledge_search` turns this skill into "free-form XQL composition from cortex docs" — and there's no skill called that, because that's exactly what we don't want.

Call:

```
knowledge_search(
  kb_name="xql-examples",
  query="<user's natural-language request VERBATIM>",
  limit=5,
)
```

Returns up to 5 results sorted by descending similarity score. Empirically, the top-1 score lands in the 0.60-0.73 range for representative SOC questions; the top-5 score spread is narrow (within ~0.10 of top-1). **Use ALL five results for pattern synthesis, not just the top-1** — the lower-ranked entries carry comparable signal and often supply useful variations.

If `limit=5` returns fewer than 3 results OR all scores are below 0.55, the user's question is genuinely far from anything in the corpus. Even then, **do not skip the search** — the LOW-SCORE result is itself a signal: you proceed to `cortex_xql_lookup`-first synthesis but flag low KB confidence in the Evidence Summary (*"Top KB match was XQL-123 at score 0.48 — well below the 0.60 confidence floor. Synthesizing primarily from cortex docs with this match as a loose template."*).

**Forbidden**: skipping straight to `cortex_xql_lookup` because the user's question references advanced stages (`windowcomp`, `comp` with stats, `bin`, `arrayexpand`). The KB has these patterns; you must look first.

### Step 2 — Fetch each match's full body

For each of the top-5 results from step 1, call:

```
GET /api/v1/kbs/xql-examples/docs/{doc_id}
```

(Or via the agent UI proxy: `/api/agent/knowledge/xql-examples/docs/{doc_id}`. The skill SHOULD use the MCP-native path since it's running inside the agent process.)

The full body has four parts:

- The **dataset / preset / datamodel line** at the start of the SQL block (e.g. `dataset = xdr_data`, `preset = xdr_login_events`, `datamodel | filter event_type = ENUM.LOGIN`).
- The **pipeline stages** — `| filter`, `| alter`, `| comp`, `| fields`, `| sort`, `| limit`, etc. — applied in order.
- The **functions** used inside the stages — `json_extract_scalar(...)`, `arrayindex(...)`, `count(...)`, `incidr(...)`, `regextract(...)`.
- The `## When to use` description — intent text (the embed payload that produced the similarity match).

### Step 3 — Extract + aggregate stages/functions across the top-5

Build two sets (with frequency counts):

- **stages_used** = unique pipeline stages appearing in any of the 5 SQL bodies. Common examples: `filter`, `alter`, `comp`, `fields`, `sort`, `limit`, `dedup`, `transaction`, `join`, `bin`, `union`, `view`.
- **functions_used** = unique function names appearing inside stage bodies. Common examples: `count(...)`, `count_distinct(...)`, `values(...)`, `arrayindex(...)`, `json_extract_scalar(...)`, `regextract(...)`, `incidr(...)`, `to_timestamp(...)`, `to_integer(...)`, `uppercase(...)`, `lowercase(...)`, `replace(...)`, `len(...)`, `sum(...)`, `min(...)`, `max(...)`.

Frequency matters: a stage appearing in 5/5 matches is part of the query's canonical shape; one appearing in 1/5 is a variation worth knowing about but not necessarily including in the synthesized query.

Also record the **dataset(s)**:

- If 4/5 or 5/5 top matches share the same dataset (e.g. `xdr_data` for process queries, `xdr_login_events` for auth queries) → that's a strong signal the user's question maps to that dataset. Use it directly in the synthesized query.
- If the datasets diverge (e.g. 2 use `xdr_data`, 2 use `authentication_story`, 1 uses `cloud_audit_logs`) → the user's question is multi-dataset by nature. Either pick the most relevant by reading the `## When to use` text, or ask the operator to clarify (*"this looks like it could pull from `xdr_data` OR `authentication_story` — which tenant context?"*).

### Step 4 — Look up authoritative syntax for each unique stage + function (MANDATORY)

This step is **NOT OPTIONAL**, even when the top-1 KB match looks like an exact template for the user's question. The operator's brief for this skill is explicit: **"we don't understand what the user wants to query. We check using similarity check, embedded examples ... We extract these examples. The stages, the functions used in each example ... And then we use the knowledge base to find a lot of information about these functions and stages, how to use them."** The chain is not a shortcut — it's the whole point of the skill. Skipping Step 4 turns this skill into a glorified `knowledge_search` proxy.

**Minimum lookup contract**: call `cortex_xql_lookup` for at LEAST:

- **All stages with frequency ≥ 2/5 across the top-5 matches** (the canonical-shape stages — these are the ones the query MUST get syntactically right).
- **The top 3 most-frequent functions** across the top-5 matches (the ones doing the heavy lifting in the synthesized query).
- **Always look up `config` (kind="stage")** when the user's question implies a time window (*"in the last X"*, *"over the past Y"*, *"yesterday"*, *"this week"*, etc.). The `config timeframe = ...` stage is the canonical XQL idiom for time-windowing and is often UNDER-represented in the KB matches because operators tend to inherit it ambiently (it's at the top of every query without being thought of as a "stage"). A common mistake is writing `_time >= subtract(current_time(), 259200000)` instead of `config timeframe = 3d` — the lookup surfaces the canonical form. See Step 7's time-suffix vocabulary table.

So for a typical query with 5-6 unique stages and 8-10 unique functions, expect **5-9 `cortex_xql_lookup` calls** before synthesizing. If you find yourself synthesizing with fewer than 3 lookups total, you're cutting corners — re-read the user's question, re-examine the matches, and look up the terms you'd be most embarrassed to get wrong.

**Per-term call signature**:

```
cortex_xql_lookup(term="<stage>", kind="stage")
cortex_xql_lookup(term="<function>", kind="function")
```

**Per-returned-payload interpretation**:

- If `found: true` → **read `summary_content`, not just `title`**. The title can match an unrelated topic page (e.g. `set` → "Set up incident scoring" is NOT the XQL `set` function; only the summary makes the distinction clear). Quote the relevant syntax snippet from `summary_content` into your reasoning so the operator can audit your understanding.
- If `found: false` → check `suggestions` for alternative term names (e.g. `replex` → `regex_replace`). The operator's queries occasionally use shortened or aliased forms; the canonical form is what XDR will accept. If a function isn't findable, that's a signal: either the corpus uses a non-standard form OR the function is XDR-tenant-specific.
- If the lookup returns an error (transient timeout, network blip) → retry once. After 2 failures for the SAME term, proceed without the doc for that term but flag it in the output ("⚠ cortex_xql_lookup unavailable for `<term>` — using example syntax verbatim as fallback").

**Why this matters concretely** — three failure modes Step 4 catches:

1. **Subtle stage-syntax drift between XDR versions.** The operator's example query was written 6 months ago against a tenant on XDR v5.4; the running tenant is on v5.7 where `transaction` gained a new required arg. The example body works syntactically but the LLM's mental model of `transaction` is from training data that's older still. The cortex_xql_lookup result is the current-version source of truth.
2. **Function-name mismatch between example and tenant.** `lowercase(...)` works on all tenants; `lower(...)` is a shortened alias that some tenants accept and others reject. The lookup tells you which canonical form to use.
3. **Field-arity errors when synthesizing a new combination.** When the user's question requires combining stages in a way no top-5 example uses (e.g. `dedup` after `comp` instead of before), the LLM has to invent the right shape — that's exactly when the doc lookup prevents wasted XDR API calls on a syntactically-broken query.

### Step 5 — (Optional) Look up dataset field schema

When all top-5 matches share a single dataset AND the user's question references fields by name (*"show me hosts where action_remote_port = 4444"*, *"filter by event_type = ENUM.NETWORK"*) → confirm the field exists in that dataset by calling:

```
cortex_search(query="<dataset> <field>", product="xql")
```

For example: `cortex_search(query="xdr_data action_remote_port field", product="xql")`. This catches typos and dataset-mismatch bugs before they hit XDR.

This step is OPTIONAL — skip when the user's question doesn't reference specific field names (most natural-language phrasings don't). The example bodies already use real field names that the tenant has accepted; copying the field names verbatim from the example is usually safe.

### Step 5.5 — Handle parameter placeholders in the example query (MANDATORY when present)

Many examples in the KB carry XSIAM saved-query parameters — placeholders the operator's UI substitutes at runtime. They look like `$host`, `$domain`, `$ip`, `$user`, `$timeframe`, etc. — a `$` followed by a single token. These EXAMPLES were never meant to execute as-is; they're templates.

When the top-1 (or any chosen) example has `$<name>` placeholders, the skill MUST handle them before passing the query to `xdr_run_xql_query` — XDR will return HTTP 500 on a literal `$host` in the filter clause. Two acceptable strategies, choose by user intent:

1. **Drop the placeholder filter line entirely.** If the user's question is broader than the example's parameterized scope (e.g. user asks *"show endpoint details"*, example is *"endpoint details by domain (`domain in($domain)`)"*) — drop the parameterized filter line. The remaining query gives a tenant-wide view. Note the change in your Part 2 evidence summary: *"Dropped `| filter domain in($domain)` from XQL-315's template — your question didn't constrain to a domain, so we removed the parameter rather than guessing."*

2. **Substitute the placeholder with a concrete value the user implied.** If the user named a specific value (*"show details for endpoints in the marketing domain"* → substitute `$domain` → `"marketing"`), do the substitution + name it in your evidence summary: *"Substituted `$domain` → `\"marketing\"` based on your question's named scope."*

**Forbidden**: passing a literal `$var` token to XDR. It will fail; you'll waste a retry-loop iteration; the operator will see a confusing 500 error instead of getting a useful answer.

### Step 5.6 — Detect parameter shape across the matches

`grep -E "\$[a-zA-Z_]\w*"` (mentally) against the SQL block. Track which placeholders appear across the top-5 matches; high-frequency placeholders (4/5 or 5/5 matches use `$host`) are part of the canonical pattern for this query class and the operator likely expects them. Low-frequency (1/5) are tenant-specific quirks you can drop without losing the query's intent.

### Step 6 — Synthesize the candidate query

Compose the query from the gathered evidence. The shape:

```
<dataset = X | preset = X | datamodel>
| <stage 1> <args>
| <stage 2> <args>
...
| <final stage>
```

Synthesis principles:

- **Lead with the dataset/preset line** that 4/5+ top matches agree on. When all 5 disagree, use the top-1's choice and note the divergence in the output.
- **Add stages in the order they appear in the highest-frequency example.** A query rarely has random stage ordering — `filter` typically comes before `alter` which typically comes before `comp` which comes before `sort` and `limit`. The top-frequency example's order is your template.
- **Use real field names from the examples**, not invented ones. Even if `cortex_search` (step 5) is skipped, the example body's field references are tenant-verified.
- **Translate the user's natural-language phrase into a filter clause**: *"hosts with unusual outbound traffic"* → `filter event_type = ENUM.NETWORK | filter not incidr(action_remote_ip, "10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16")`.
- **When the user's question implies aggregation** (*"top 10 ..."*, *"count by ..."*, *"hosts grouped by ..."*) → add `| comp count(...) as <name> by <field>` and `| sort desc <name>` and `| limit 10`.
- **When the user implies a time window** (*"in the last hour"*, *"this week"*) → add `| filter _time > to_timestamp(current_time() - duration("PT1H"))` (for hour) or similar. The `to_timestamp(current_time() - duration(...))` pattern appears across the operator's queries.

### Step 7 — Execute against XDR + check the response

Call:

```
xdr_run_xql_query(
  query="<synthesized query text>",
  timeframe_from=None,   # default: 24h ago
  timeframe_to=None,     # default: now
)
```

**Critical timeframe-arg gotcha**: `timeframe_from` and `timeframe_to` are ISO datetime strings, NOT relative-time expressions. A value like `"24h"`, `"1d"`, `"last hour"`, or `"yesterday"` will produce `"Invalid isoformat string"` immediately — the tool's argument parser rejects these at the connector layer before the query even reaches XDR.

**Two valid ways to express a time window**:

1. **Preferred — `config timeframe = <N><unit>` at the start of the query body** (the XQL-native way). Examples:
   ```
   config timeframe = 24h
   | dataset = xdr_data
   | filter ...
   ```
   ```
   config timeframe = 7d
   | dataset = xdr_data
   | ...
   ```
   This is the form 95% of the operator's KB examples use. **Default to this.**

   **Time-suffix vocabulary** for the `config timeframe = N{unit}` stage — these are the only valid suffixes (per `cortex_xql_lookup(term="bin")`'s "Time Suffixes" table):
   - `MS` — milliseconds
   - `S` — seconds
   - `M` — minutes (single char)
   - `H` — hours
   - `D` — days
   - `W` — weeks
   - `MO` — months (two-char)
   - `Y` — years

   **Common shapes** (memorize — these cover ~90% of user intents):
   - *"last hour"* → `config timeframe = 1h`
   - *"last 24 hours"* / *"last day"* → `config timeframe = 24h` (NOT `1d` — `24h` is what 95% of KB examples use; both work, prefer `24h`)
   - *"last 3 days"* / *"last 72 hours"* → `config timeframe = 3d`
   - *"last week"* / *"last 7 days"* → `config timeframe = 7d`
   - *"last 30 days"* / *"last month"* → `config timeframe = 30d`
   - *"last quarter"* → `config timeframe = 90d`
   - *"last year"* → `config timeframe = 1y`

   **Forbidden — manual epoch math** NEVER write `filter _time >= subtract(current_time(), 259200000)` or `filter timestamp_diff(current_time(), _time, "DAY") <= 3` as a substitute for `config timeframe = 3d`. The manual-math form works but:
   - is verbose + error-prone (off-by-one ms math, hardcoded magic numbers like `259200000`)
   - misses XDR's query-planner optimization that `config timeframe` enables (the planner can prune partitions by time before scanning)
   - looks foreign to operators who read 100s of XQL queries every day in the XSIAM UI where `config timeframe` is the canonical idiom
   - costs more XDR API quota (the query has to do the time filter inline rather than at scan boundaries)

   If you find yourself synthesizing `subtract(current_time(), <N>)` or `timestamp_diff(current_time(), _time, ...)`, STOP and rewrite as a `config timeframe = N{unit}` line at the top of the query body. The user-facing semantics are identical; the canonical form is preferred.

2. **Alternative — explicit ISO datetimes in the function args** (when the user named a specific time window):
   ```
   xdr_run_xql_query(
     query="dataset = xdr_data | filter ...",
     timeframe_from="2026-05-19T00:00:00Z",
     timeframe_to="2026-05-19T23:59:59Z",
   )
   ```
   Use this when the user said *"between 9am and 5pm yesterday"* or *"on the 15th"* — i.e. when an absolute window matters.

**Forbidden**: passing relative expressions (`"24h"`, `"1d"`, `"last week"`) to `timeframe_from` or `timeframe_to`. The tool layer fails immediately; this is a wasted iteration that the operator pays for.

If the user says *"in the last 24 hours"*, use form 1 (`config timeframe = 24h`).
If the user says *"between yesterday at noon and today at noon"*, use form 2.

Inspect the response. Per the operator's "working" definition:

| Response | Interpretation | Action |
|---|---|---|
| `{status: "SUCCESS", total_rows: N, results: [...], fields: [...]}` | **WORKING** — XDR accepted the query. N might be 0; that's still success. | Return the query + results to the operator. Output shape: query text, row count, field schema, sample rows (up to ~10), and a note if `total_rows: 0`: *"query is valid syntactically; no events matched in the 24h window — try a wider `timeframe_from` if you expect events"*. |
| `{status: "FAIL"\|"FAILED", error: "<msg>"}` | **NOT WORKING** — XDR rejected the query. The error tells you what's wrong. Common patterns: *"Field X not found in dataset Y"* (field typo or wrong dataset), *"Unknown function Z"* (function name mismatch), *"Stage W expects N args, got M"* (arity mismatch). | Read the error → adjust the synthesized query → call `xdr_run_xql_query` again. Maximum 3 iterations; after 3 failures, report the query + the error to the operator and ask for guidance. |
| `{status: "CANCELLED"\|"TIMEOUT"}` | XDR took longer than the bounded poll window. The query itself MAY be valid (just slow). | Return `execution_id` to the operator + advise calling `xdr_get_xql_results(execution_id=...)` later, OR narrow the timeframe and retry. |
| `{status: "PENDING", execution_id, note: "..."}` | Polling window ran out but the query is still alive in XDR. | Same as TIMEOUT — return the `execution_id` for later polling, or retry with a narrower timeframe. |
| `{ok: false, error: "<msg>"}` (HTTP-level error) | The cortex-xdr connector itself failed (auth, network, connector not configured). | Surface the error to the operator with the canonical hint: *"Configure /connectors → cortex-xdr first"* if it's "no connector instance" / "authentication failed" / similar. Do NOT retry — the connector layer needs the operator's attention. |

### Iteration loop

For non-fatal failures (FAIL/FAILED from XDR with an error message, OR HTTP 500 from `/xql/start_xql_query/`), iterate up to **3 times**:

1. **Iteration 1** — read the error message → adjust the synthesized query → execute. Special cases below.
2. **Iteration 2** — if the same class of error repeats, broaden context: re-run step 4 with more terms, or step 5 to verify field names.
3. **Iteration 3** — last try. If it still fails, hand back to the operator with: the synthesized query as-is, the last error message, the top-5 KB matches that informed it, and a suggested next investigation.

Don't loop indefinitely — repeated identical errors usually mean the question itself needs operator clarification, not more synthesis attempts.

### Common XDR-rejection patterns + tenant-fallback recipes

These patterns recur across diverse scenarios. The skill handles each by class:

**Pattern A — HTTP 500 / "An unexpected error" / dataset-not-found.** Some operator examples target vendor-specific datasets (`microsoft_windows_raw`, `servicenow_generic_alert_raw`, `arista_cloud_vision_wireless_*`, etc.) that not every XDR tenant has configured. When you see HTTP 500 from `/xql/start_xql_query/` with no clear field-error message, the most likely cause is "the tenant does not have the dataset."

  - **Fallback**: re-examine the top-5 KB matches. Is there an alternative match that targets a **tenant-universal** dataset? The universals across XDR/XSIAM tenants are: `xdr_data` (process / network / file / login telemetry; the workhorse), `xdr_login_events` (auth-specific preset), `endpoints` (the agent-inventory dataset; available wherever XDR is deployed), `alerts` (XSIAM's built-in alerts dataset), `issues` (XSIAM's built-in incident/issue dataset). NOT universal: `panw_ngfw_*` (only on tenants with NGFW integration), `microsoft_windows_raw` (Windows event-log connector), `servicenow_*` / `jira_*` (ticketing integrations) — these are tenant-specific and the SAME query may 500 on one tenant + succeed on another. Pick the top-5-ranked match whose dataset is in the universal set AND whose `## When to use` text matches the user's question intent. Re-synthesize.
  - **Document the swap in your evidence summary**: *"XQL-352's `microsoft_windows_raw` dataset returned HTTP 500 — not configured on the tenant. Fell back to XQL-XXX which targets `xdr_data | filter event_type = ENUM.LOGIN` for the same intent."*
  - **If no top-5 match has a universal dataset**: report to the operator: *"All 5 top KB matches target tenant-specific datasets (`microsoft_windows_raw`, `servicenow_generic_alert_raw`, ...). This environment doesn't appear to have these connectors. Could you tell me which connector your `<user-question>` data comes from?"* — and STOP iterating. The fix is operator-side connector configuration, not skill iteration.

**Pattern B — "Field X not found in dataset Y".** The example query references a field that the tenant does not have, OR the field name has drifted between XDR versions. Common when the example used `agent_hostname` and the tenant uses `endpoint_hostname`, or vice versa.

  - **Fallback**: call `cortex_search(query="<dataset> <field>", product="xql")` to confirm the canonical field name. Substitute. Retry.
  - If the field is genuinely absent: drop the filter clause that references it (changes intent slightly but unblocks execution) OR fall back to a related top-5 match that doesn't reference the missing field.

**Pattern C — "Unknown function Z".** A function name typo or alias mismatch (e.g. `replex` vs `regex_replace`, `lower` vs `lowercase`). Often catchable in Step 4's cortex_xql_lookup `suggestions` field if you did your homework. If you didn't (because Step 4 timed out or was skipped — see CLAUDE.md's prohibition on skipping Step 4), re-run the lookup with `kind="function"` to surface alternatives.

**Pattern D — "Stage W expects N args, got M".** Arity mismatch — the example used a stage syntax variant that this XDR version doesn't accept. Usually fixable by removing optional args (most XQL stages tolerate trimming) OR by re-reading the cortex_xql_lookup `summary_content` for current-version syntax.

**Pattern E — Parameter placeholder leaked through.** The synthesized query has a literal `$host` / `$domain` / etc. somewhere. This means Step 5.5 was skipped. Go back to Step 5.5; either substitute or drop the placeholder filter; retry.

**Pattern F — "Invalid isoformat string: '<value>'".** You passed a relative-time expression (`"24h"`, `"1d"`, `"last week"`) to the `timeframe_from` or `timeframe_to` argument. These args take ISO datetime strings, NOT relative expressions. Fix: drop the function-arg timeframe entirely + put `config timeframe = 24h` (or equivalent) at the START of the query body. See Step 7's "Critical timeframe-arg gotcha" above.

**Pattern G — `windowcomp` syntax confusion.** XQL's `windowcomp` stage has a specific syntax that confuses naive synthesis. The CORRECT form is:

```
| windowcomp <func>(<field>) by <partition_field> as <output_name>
| windowcomp <func>(<field>) by <partition_field> as <output_name>, <func2>(<field>) by <partition_field> as <output_name2>
```

Common mistakes that produce `bad query syntax`:
- Combining two `windowcomp` functions into one stage WITHOUT both `by` + `as` clauses per function: `windowcomp avg(x) by host as a, stddev_population(x) by host as b` ← `by` must come BEFORE `as`, but BOTH must be specified for EACH function.
- Putting `by` after `as`: `windowcomp avg(x) as a by host` ← WRONG. Correct: `windowcomp avg(x) by host as a`.
- Trying to chain `by` for shared partitioning: `windowcomp avg(x), stddev_population(x) by host` ← WRONG. Each function needs its own `by`.

When you see `bad query syntax` with `parse_err.text: "by"` or `parse_err.text: "("` on a `windowcomp` line, this is Pattern G. The fix is to either:
- (a) **Split into TWO separate `windowcomp` stages**, each computing one function:
  ```
  | windowcomp avg(hourly_exec_count) by actor_process_image_name as daily_avg
  | windowcomp stddev_population(hourly_exec_count) by actor_process_image_name as daily_stddev
  ```
- (b) **Keep one `windowcomp` but specify `by` + `as` for EACH function explicitly**:
  ```
  | windowcomp avg(hourly_exec_count) by actor_process_image_name as daily_avg, stddev_population(hourly_exec_count) by actor_process_image_name as daily_stddev
  ```

Both forms work; (a) is more readable, (b) is what cortex_xql_lookup's docs example shows. If the first form returns 500, fall back to the other.

**Pattern H — Arithmetic operators rejected by XDR (`+`, `-`, `*`, `/`).** XQL's `alter` stage does NOT accept C-style arithmetic operators. Expressions like `alter threshold = daily_avg + (2 * daily_stddev)` produce `bad query syntax`. The fix: replace with XQL math functions:
- `a + b` → `add(a, b)`
- `a - b` → `subtract(a, b)`
- `a * b` → `multiply(a, b)`
- `a / b` → `divide(a, b)`

So the example becomes: `alter threshold = add(daily_avg, multiply(2, daily_stddev))`. Call `cortex_xql_lookup` for `add`, `subtract`, `multiply`, `divide` to confirm signatures the first time you encounter this pattern.

## Output shape (what the operator sees)

A clear three-part response in the chat transcript:

### Part 1 — The synthesized query

```sql
<the query text in a SQL code block>
```

### Part 2 — Evidence summary

The evidence summary MUST surface the full retrieval chain so the operator can audit your decision. Required elements (all MANDATORY — a summary missing any of these is a skill-prompt failure):

- **Top-5 KB matches** with scores: e.g. *"`XQL-190 Rare Executions of PSEXEC` (score 0.734), `XQL-239 Rare processes started by Powershell` (0.662), `XQL-180 QR - Procdump LSASS` (0.618), `XQL-498 PUA - Sysinternals` (0.618), `XQL-525 Credential Dumping LSASS` (0.618)"*. **If you don't list KB matches, it means you skipped Step 1 — that's an immediate failure flag.**
- **Dataset clustering**: e.g. *"4/5 matches use `xdr_data`; 1 uses `endpoints` — went with `xdr_data` because the operator's question is about runtime telemetry."*
- **Stages extracted with frequency**: e.g. *"`filter` 5/5, `fields` 5/5, `comp` 3/5, `alter` 2/5, `sort` 2/5."*
- **Functions extracted with frequency**: e.g. *"`count` 3/5, `lowercase` 3/5, `replace` 1/5."*
- **`cortex_xql_lookup` calls + outcomes** (REQUIRED — surfaces Step 4 was actually walked): e.g. *"Looked up `filter` (HIT — 'filter narrows results'), `fields` (HIT), `comp` (HIT — 'aggregation stage with `as` and `by`'), `alter` (HIT), `count` (HIT), `lowercase` (HIT). 6/6 lookups hit."*

A summary that names KB matches + extracted terms but doesn't list the lookups + outcomes means Step 4 was skipped — that's a skipped step. **Always list the lookup calls explicitly.**

### Part 3 — Execution result

> XDR responded `status: SUCCESS` in N seconds. Returned M rows. Fields: action_remote_ip, agent_hostname, event_count. First 5 rows:
> ```json
> [{ "action_remote_ip": "1.2.3.4", "agent_hostname": "host-a", "event_count": 42 }, ...]
> ```

OR, on failure:

> XDR rejected on iteration 1 with: *"Field action_remote_ip2 not found in xdr_data"*. Adjusted to `action_remote_ip` and retried. Iteration 2 succeeded.

OR, on max-iteration failure:

> XDR rejected on 3 iterations. Last error: *"<the err_message>"*. The synthesized query (above) is preserved for your inspection. Suggested next step: <best guess based on the error pattern>.

## Inputs (caller-supplied)

When invoked from another orchestration skill (rare today; included for future composability):

| Field | Type | Purpose |
|---|---|---|
| `user_request` | str (required) | The natural-language question to translate. |
| `additional_context` | str (optional) | Free-text context from the parent skill (e.g. *"we just ran a phishing kill chain on hosts A, B, C; pivot to find related processes"*). Appended to the embedding input. |
| `time_window` | str (optional) | Hint like "1h", "24h", "7d". Translated into the `| filter _time > to_timestamp(current_time() - duration(...))` clause. |
| `max_iterations` | int (default 3) | Cap on the synthesis-retry loop. |
| `dry_run` | bool (default false) | If true, return the synthesized query WITHOUT executing it against XDR. Useful when the operator wants to review before running. |

For standalone invocation (operator types in chat), the operator's message IS `user_request`; the other fields default.

## Lab-safety profile

This skill is **read-only against XDR**. The only XDR tool it calls is `xdr_run_xql_query`, which executes a SELECT-equivalent — no mutation. The synthesized queries follow the operator's existing safe patterns (no `delete`, no `config write` — neither is supported in the XQL surface anyway).

The skill consumes XDR API quota per query. Heavy iteration loops can burn quota fast; the `max_iterations: 3` cap is the guardrail. If a tenant runs into quota issues, raise the cap configurable via the skill's caller-supplied inputs.

## Anti-patterns (forbidden)

- **Don't synthesize a query without consulting the KB first.** The operator's corpus is the authority on what queries work in their tenant. Synthesizing from raw `cortex_xql_lookup` knowledge alone produces syntactically-correct queries that may not match the tenant's field schema.
- **Don't loop forever on FAIL responses.** Cap at 3 iterations. Identical errors after iteration 2 mean the question needs operator clarification, not more synthesis.
- **Don't treat empty results as failure.** `total_rows: 0` with `status: SUCCESS` is a working query that simply found no events — the operator might widen the time window or accept the answer.
- **Don't auto-execute queries that look destructive.** Today XQL doesn't support destructive operations, so this is theoretical — but if a future XQL surface adds DELETE/UPDATE, the skill must gate those behind an explicit operator confirmation step.
- **Don't skip step 5 (`cortex_search` for fields) when the user explicitly names a field.** If the user says *"show me events where event_subtype = 'EXEC'"*, verify `event_subtype` exists in the chosen dataset BEFORE executing; a field typo wastes an XDR API call and produces a misleading FAIL message.

## Reference: retrieval smoke queries

These five queries are a baseline for verifying the retrieval chain. Each should return the named example among its top matches:

1. *"show hosts with unusual outbound network traffic to public IPs"* — should match `XQL-382 Hosts Connected to Specific IP Address`.
2. *"find failed RDP login attempts in the last hour"* — should match `XQL-167 RDP Failed Logins`.
3. *"detect rare PSEXEC process executions on Windows hosts"* — should match `XQL-190 Rare Executions of PSEXEC`.
4. *"alert when a process makes outbound DNS queries to unusual domains"* — should match `XQL-218 Machines making DNS queries for very long domain names`.
5. *"show me which users authenticated from new countries this week"* — should match `XQL-375 Geolocations Specific User Logged in From`.
