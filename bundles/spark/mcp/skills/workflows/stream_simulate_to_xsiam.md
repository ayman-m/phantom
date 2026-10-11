---
name: stream_simulate_to_xsiam
displayName: Stream simulated logs to Cortex XSIAM (end-to-end)
category: workflows
description: 'Drive an end-to-end simulation pipeline: discover a vendor data source, fire a CEF stream via `xlog.create_data_worker`, wait for XSIAM ingest, then verify with XQL queries against the right dataset. Use when the operator says "send Okta logs to XSIAM", "stream AWS CloudTrail traffic into my tenant and confirm they arrived", or any phrasing that combines vendor simulation + downstream XSIAM validation. Encodes the lessons (L1 onward) that keep the agent clear of the routing, discriminator, MTU, JSON-synthesis, and verification pitfalls.'
icon: send_and_archive
source: platform
loadingMode: on-demand
locked: false
---

# Skill: Stream simulated logs to Cortex XSIAM (end-to-end)

## When this skill applies

The operator's request combines BOTH:

1. **Simulation** — "send", "stream", "simulate", "fire", "generate" logs for a named vendor
2. **XSIAM target** — "to XSIAM", "to my tenant", "into XSIAM", or "and confirm they arrived" / "and verify them"

Examples that match:
- *"Send Okta SSO logs to my XSIAM."*
- *"Stream AWS CloudTrail traffic into my tenant and confirm they landed."*
- *"Fire 50 ServiceNow events and verify XDM populated."*
- *"Simulate Azure WAF logs in XSIAM."*

Examples that do **not** match (route elsewhere):
- *"Just generate 50 FortiGate records — I'll review them locally."* → `simulate_vendor_logs` (returns records to chat; no XSIAM round-trip)
- *"Did my last kill chain show up in XDR?"* → `xdr_verify_simulation_telemetry` (verification only, no new simulation)

## Why this skill exists

The agent's chat path can drive `xlog.create_data_worker` via MCP. But to land events in the **right** XSIAM dataset, the chat needs to:

1. **Discover** which dataset the operator means
2. **Translate display names to broker-routing values**. The operator's XSIAM tenant's installed parsing rules filter on specific CEF vendor/product literals that frequently differ from the YAML's display name (`Amazon Web Services` / `AWS-CloudTrail` derives `amazon_web_services_aws_cloudtrail_raw` at the broker, but the operator's PR routes from `amazon` / `aws` → `amazon_aws_raw`)
3. **Set the right discriminator** for multi-dataset packs (Okta SSO uses `eventType=user.authentication.sso`; O365 Exchange uses `Workload=Exchange`; Azure AKS uses `category=kube-audit`)
4. **Verify** with the right XQL query type (`dataset = X` for raw landing; `datamodel dataset = X` for XDM saturation — they're different views and return different things)

This skill encodes those decisions so the chat doesn't re-derive them per session.

## Procedure

### Step 1 — Discover the data source

Call `data_sources_list` filtered by what the operator named:

```
data_sources_list(filter="<vendor or product the operator named>")
```

Decision tree:
- **Exactly 1 result + names match the operator's intent** → use it. Note its `pack_name`, `rule_name`, `dataset_name`.
- **Multiple results** — narrow by what the operator emphasized (sub-product, workload, audit-vs-sign-in, etc.). If still ambiguous, ASK the operator which one before continuing.
- **No results** → tell the operator: *"No installed data source matches '<vendor>'. Open /data-sources, click Browse, and install the matching schema first."* STOP. Don't auto-install.

### Step 2 — Fetch the full schema + how_to_use guidance

```
data_sources_get_schema(
  data_source_id="<pack_name>/<rule_name>/<dataset_name> from step 1",
  compact=true     # ⚠️ REQUIRED — see the compact note below
)
```

**⚠️ ALWAYS pass `compact=true` here.** With descriptions, a large
vendor's schema (SentinelOne ~105 fields, Zscaler ~108) exceeds the agent's
tool-result size cap, so the field list arrives TRUNCATED mid-way — you then
forward an incomplete `schema_override` and the worker silently emits a partial
event, capping XDM (the back half of the list, where nested-JSON composites
live, never reaches you). `compact=true` returns only `name`/`type`/`is_array`/
`is_meta` — exactly what `schema_override` consumes (xlog discards the rest
anyway) — so the WHOLE field list fits. SentinelOne XDM went **0 → mapped** once
the complete field list reached the worker.

The response carries:
- `fields[]` — the full vendor field schema (with `compact=true` each entry is
  `{name, type, is_array, is_meta}`). Pass it **verbatim and complete** as
  `schema_override` to the worker.
- `how_to_use` — markdown with the **"Sending these logs to Cortex XSIAM"** sub-section that names the EXACT CEF vendor + product values to use and any discriminator field requirements. **The modeling-rule GATE seed lives here** (`how_to_use` is preserved under `compact=true`), so you don't need per-field descriptions to seed the gate.

**Critical**: parse `how_to_use` to extract the CEF routing values. They appear as:

```
**Required CEF header for XSIAM**:

- **vendor**: `<cef_vendor>`
- **product**: `<cef_product>`
```

Use those literal values for the worker's `vendor` + `product` arguments — NOT the YAML's top-level `vendor` / `product` (those are operator-facing display names that frequently differ from the broker-routing values).

For multi-dataset packs, also extract any discriminator field guidance — strings like:
- `eventType=user.authentication.sso` → must be in the synthetic event's payload
- `Workload=Exchange` → ditto
- `category=AuditLogs` → ditto

These are PR-side filters; without them, events fall through to a sibling dataset.

### Step 3 — Resolve the operator's XSIAM broker destination

Default broker destination: `udp:10.0.0.8:514`. If the operator has named log destinations configured, prefer the one with `type_id=syslog`:

```
log_destinations_list(filter="syslog")
```

Pick the destination matching the operator's intent or default to `udp:10.0.0.8:514`.

### Step 4 — Fire `xlog.create_data_worker`

**Fire directly — do NOT re-confirm.** If this skill is active, the operator already said "send / stream / fire / simulate" — that IS your go-ahead. Call `xlog.create_data_worker` now; never pause to ask "shall I fire it?" or print "about to call …" and stop. The operator asked you to send the logs — send them.

**⚠️ MANDATORY for XDM — seed the modeling-rule GATE field via `observables_dict`.** Every modeling rule opens with `filter <field> = "<value>"` (or `… in (…)`). If your event does not carry that EXACT value, the rule **never fires and XDM stays 0** even though raw landing succeeds — this is the #1 cause of "0 XDM". Find the gate field from `data_sources_get_schema`: it is the field whose `description` begins **"Modeling-rule GATE — must equal …"** (or read `how_to_use`'s "Make it map to XDM" line, or the L21 table below). You MUST pass that field+value in `observables_dict` on EVERY simulate-and-verify run. Proven live: Azure FlowLogs over CEF went from **0 → 25+ `xdm.*` fields** the instant `observables_dict={"category":["NetworkSecurityGroupFlowEvent"]}` was added. Never fire `xlog.create_data_worker` for an XDM run without seeding the gate. (Exception: a few sources gate on a `_`-prefixed META field like `_log_type` that the broker/collector stamps at onboarding — not settable from the payload; their `how_to_use` says so. Raw lands; XDM there needs the operator's source onboarding, not a seed.)

**Use the EXACT `vendor` / `product` literals from Step 2 — never invent or prettify them from the source's friendly/display name.** For the "Okta — SSO" data source the product is `Okta` (NOT `Okta SSO`) — "Okta SSO" is a UI label, not a CEF value. The SSO-vs-System-Log split is driven by the `eventType` discriminator in `observables_dict`, NOT the product string. Same trap for any multi-word/sub-product source: pass the literal `product` field from `data_sources_get_schema`, not a derived name.

```
xlog.create_data_worker(
  type="CEF",
  destination="<udp:host:port from step 3>",
  count=3,                       # 3 events per tick is plenty for verification
  interval=2,                    # 2-second tick keeps total UDP volume low
  vendor="<cef_vendor from how_to_use>",     # NOT the display name
  product="<cef_product from how_to_use>",   # NOT the display name
  schema_override=<the COMPLETE compact fields[] from data_sources_get_schema(compact=true)>,
  observables_dict=<see below>,  # MANDATORY for XDM — seed the GATE field (see ⚠️ block above)
)
```

**For multi-dataset packs**, set the discriminator value via `observables_dict`:

```python
observables_dict={
  "eventType": ["user.authentication.sso"],     # Okta SSO
  # or
  "Workload": ["Exchange"],                     # O365 Exchange
  # or
  "category": ["kube-apiserver"],               # Azure AKS (NOT kube-audit)
  # or
  "category": ["AuditLogs"],                    # Entra ID audit
}
```

**Beyond multi-dataset routing, ALSO seed the MR's XDM classifier here** (L21) — e.g. `eventType` for Okta, `event_type` for Qualys/Proofpoint, `Category` for Azure WAF, `auditCode` for CyberArk. Without a valid classifier value the MR drops the event and XDM stays 0 even though raw landing succeeds.

If the worker creation succeeds, capture `worker_id` (the `worker` field in the response) for later cleanup.

### Step 5 — Wait for XSIAM ingest

XSIAM ingest typically lands events in 30-120 seconds after they reach the broker. Wait at least 90 seconds before querying — querying too early means an empty result that's not a real signal.

If the orchestration session is interactive: tell the operator *"Streaming now. Ingest typically lands within 60-120s — I'll check back in ~90 seconds."*

### ⚠️ Tool selection — read before Step 6

The agent's catalog exposes TWO XQL-shaped tools because two Cortex connectors are installed:

| Tool | Connector | Tenant URL pattern | Use for THIS skill? |
|---|---|---|---|
| **`xsiam.run_xql_query`** | xsiam | `https://api-<operator>.xdr.<region>.paloaltonetworks.com` | ✅ **YES — only this one** |
| `xdr_run_xql_query` / `xdr_xql_run_query` / `xdr_xql_get_results` / `xdr_xql_list_datasets` | cortex-xdr | A DIFFERENT Cortex tenant (legacy XDR product) | ❌ NEVER for THIS skill |

**Why this matters**: the skill simulates logs to the operator's XSIAM broker, which lands them in their XSIAM tenant. Querying via `xdr_*` tools hits the cortex-xdr connector instance, which routes to a different Cortex tenant entirely — frequently returning 500 errors or empty results because the data lives elsewhere. Picking the wrong tool burns many tool calls and ends in a false "couldn't verify XDM" report.

**Hard rule**: every XQL call in this skill — Step 6 raw verification, Step 7 datamodel verification, troubleshooting queries — MUST use `xsiam.run_xql_query`. If the tool isn't available in the agent's catalog, surface the gap to the operator (xsiam connector not configured); do NOT fall back to `xdr_*` variants.

### Step 6 — Verify raw landing

```
xsiam.run_xql_query(
  query="dataset = <dataset_name> | sort desc _time | limit 5",
  tenant_timeframe={"relativeTime": 600000}  # last 10 minutes
)
```

Inspect the result:
- `reply.status == "SUCCESS"` and `reply.number_of_results > 0` → events landed. Note the `_time` field on the most recent row; if it's after the worker creation time, those rows came from THIS run.
- `reply.number_of_results == 0` → events did NOT land in this dataset. Likely causes (in priority order):
  1. **Wrong CEF vendor/product** — re-read `how_to_use`, double-check the literal values
  2. **Wrong discriminator** for multi-dataset packs — re-read `how_to_use` for the PR filter requirements
  3. **Operator's broker has an applet/filter** that intercepts these events. Ask the operator to check `XSIAM → Settings → Broker → Applets` for any rule matching this vendor.
  4. **Broker auto-derives a different dataset name** — try querying `dataset = <broker-derived name>` as a fallback (e.g. `amazon_web_services_aws_cloudtrail_raw` for AWS CT)
- `reply.status == "FAIL"` or error → the dataset does not exist in the tenant. Tell the operator: *"The dataset `<X>` isn't registered in your XSIAM tenant. Install the upstream Cortex Marketplace pack for this vendor first."*

### Step 7 — Verify XDM materialization (datamodel view)

If raw landing succeeded, also check whether the modeling rule populated XDM fields:

```
xsiam.run_xql_query(
  query="datamodel dataset = <dataset_name> | sort desc _time | fields xdm.* | limit 1",
  tenant_timeframe={"relativeTime": 600000}
)
```

L13 critical: `dataset = X` returns RAW columns; `datamodel dataset = X` returns the MR-transformed XDM view. Both queries must succeed for full saturation.

Report the XDM saturation count to the operator:
- *"✅ 5 events landed in `okta_okta_raw` (raw), and XDM materialized 17 fields including `xdm.event.outcome`, `xdm.source.user.username`, `xdm.observer.product`. End-to-end pipeline verified."*

### Step 8 — Cleanup

Stop the worker so it doesn't keep emitting after the verification:

```
xlog.list_workers()
# find the worker by `name` matching what you captured in Step 4
xlog.kill_worker(worker_id="<from list_workers>")
```

## Lessons to honor

These findings are encoded so the chat doesn't re-discover them:

**L1 — `call <RULE>` chains imply field inheritance.** Per-dataset MRs that `call ngfw_standalone` inherit every field that helper reads — don't skip the helper's fields when assembling schema_override.

**L7 — XQL `status=FAIL` vs `SUCCESS, n=0` differ semantically.** `FAIL` = dataset does not exist in the tenant (PR not installed). `SUCCESS, n=0` = dataset exists but no events match the filter (routing gap). Report each differently to the operator.

**L12 — CEF over UDP is the universal transport.** Even JSON-native vendors (Okta, AWS CT, Azure AD) can be CEF-wrapped: pack their named fields as CEF extension k=v pairs; the same PR/MR fires regardless of transport.

**L13 — `dataset =` returns RAW columns only.** `datamodel dataset =` returns the XDM view. Use BOTH to verify the path end-to-end. A successful raw-landing query with `xdm.* = NULL` means the MR didn't fire — **the #1 cause is a missing classifier value** (the MR's `filter <field> in (…)` rejected the event; see L21), not composite synthesis.

**L15 — Nested JSON survives CEF extension wrapping.** Pack composite fields like `actor` as JSON-string CEF extensions: `actor={"id":"...","alternateId":"a@b.com"}`. The MR's `json_extract_scalar(actor, "$.alternateId")` parses at query time.

**L17 — PR filter rejection is vendor-specific.** "dataset exists, n=0" most often means the PR's filter (timestamp shape, discriminator field, computed value) didn't match. The CEF wrapping pattern itself is fine; tune the synthetic event per-vendor.

**L18 — UDP MTU 1500 is a hard ceiling.** Saturating events > 1500 bytes get truncated by the broker. Keep single events to ~25-30 CEF extensions. For more XDM coverage, split into 2-3 events sharing a marker.

**L19 — CEF JSON values become STRING columns, not JSON-typed columns.** MR functions expecting JSON-typed inputs (`object_create`, `field -> sub`, array indexing) may return null. Prefer SHALLOW CEF extensions mapping to flat MR field reads.

**L20 — Nested-JSON composites synthesize fully.** Composite (`type: json`) fields are synthesized as real nested JSON from their dotted-leaf children, so `json_extract_scalar` works and nested-JSON MRs reach high ceilings: Okta 46, O365 General 52, Azure Flow Logs 48, Entra ID 44. Do NOT pre-emptively split nested-JSON vendors expecting a ~10 cap.

**Broker auto-route mismatches YAML name.** The CEF header's vendor + product values normalize to `<lowercased-vendor>_<lowercased-product>_raw`. The YAML's `dataset_name` field is what the operator's PR ROUTES to — these names often differ. Always read `how_to_use` for the CEF literal values that produce the YAML's expected dataset, not the YAML's `vendor`/`product` display fields.

**L21 — Seed the MR's classifier field, or XDM stays 0.** Many modeling rules open with `filter <field> in (<allow-list>)` — if that classifier field carries a random value, the MR drops the event and XDM is 0 *even though raw landing succeeded*. Before simulating, read the source's `how_to_use` (and, if available, the MR) for the classifier the rule keys on, and seed a VALID value via `observables_dict`. This is the single biggest XDM-saturation lever. Validated examples (0 → high XDM):

| Vendor | Seed via `observables_dict` |
|---|---|
| Okta (System Log) | `eventType=user.session.start` (any non-SSO Okta event) |
| Okta SSO | `eventType=user.authentication.sso` |
| Alibaba ActionTrail | `event_eventtype=ApiCall` |
| Proofpoint Email | `event_type=message` |
| Qualys | `event_type=activity_log` |
| Azure Flow Logs | `category=NetworkSecurityGroupFlowEvent` |
| Azure WAF | `Category=FrontDoorAccessLog` |
| Azure AKS | `category=kube-apiserver` (NOT `kube-audit`) |
| CyberArk ISP | `auditCode=IDP2005` (sets `is_auth=true`) |

If the value isn't in `how_to_use`, the field's `description` usually lists valid examples — pick one. Pass it as `observables_dict={"<field>": ["<value>"]}` (a single-element list is unwrapped to the scalar).

**L22 — Pass the FULL `fields[]`, never a trimmed subset.** Hand `data_sources_get_schema`'s entire `fields[]` to `schema_override` verbatim — flat fields, top-level composites (`type: json`), AND their dotted-leaf children. The generator synthesizes each composite's nested object FROM its dotted leaves, so dropping leaves starves the composite. More fields mapped = more XDM. The operator's intent is maximum field coverage — don't pre-trim to "save bytes" (split into 2 events sharing a marker if you hit the 1500-byte MTU, per L18, rather than dropping fields).

**L23 — Fetch the schema with `compact=true`, or large vendors silently truncate.** `data_sources_get_schema` defaults to verbose (per-field `description` + `example`) for the UI. For a 100+-field vendor that payload exceeds the agent's tool-result size cap, so the field list you receive is TRUNCATED mid-way — you then forward an incomplete `schema_override` and XDM caps or stays 0 even though raw landing succeeds. This is NOT a trim-to-save-bytes choice (L22 still holds — pass ALL fields); it's that the verbose payload literally doesn't fit. `compact=true` returns only the 4 keys the worker uses (`name`/`type`/`is_array`/`is_meta`), so the COMPLETE list fits and reaches the worker. Symptom this prevents: a 100+-field vendor lands many raw rows but maps 0 XDM because only about a third of the fields survived truncation; with `compact=true` the full schema arrives and the nested Threat-branch composites map. `how_to_use` (gate seed + CEF routing) is preserved under compact, so nothing else in this skill changes.

**L24 — Verifying fresh XDM in a polluted dataset.** Once a tenant holds days of test data, naive verification lies — three rules keep it honest: **(a) isolate fresh events with `sort desc _time`.** `datamodel dataset = X | sort desc _time | fields xdm.* | limit 50` reads THIS run's events; a bare `| fields xdm.* | limit 40` samples arbitrary old rows and under-reports (it can falsely show 0). **(b) Do NOT filter on `xdm.event.type != null` as a universal "mapped" proxy.** Firewall/endpoint rules (FortiGate, MS Windows) never set `xdm.event.type` — they map `xdm.event.outcome` / `xdm.event.id` instead — so that filter returns ZERO rows for them and looks like total failure. Count DISTINCT non-null `xdm.*` columns across the recent rows instead. **(c) Prove freshness from the data, not the query** — report the newest row's `_time` and confirm it falls in your run window; a relativeTime param alone may not isolate (it can return dataset totals). Typical fresh ceilings under this method: **FortiGate 76, Salesforce 43, SentinelOne 34 (2-event split), MS Windows 29, Zscaler 17.**

## Quick reference — validated vendors

These vendors are validated end-to-end. Routing values are baked in each YAML's `how_to_use`; this table is a convenient summary:

| Vendor (data source) | CEF vendor → product | Multi-dataset discriminator |
|---|---|---|
| Okta okta_okta_raw | `Okta` → `Okta` | (default) |
| Okta SSO | `Okta` → `Okta` | `eventType=user.authentication.sso` or `user.session.start` |
| Alibaba ActionTrail | `alibaba` → `action_trail` | — |
| AWS CloudTrail (amazon_aws_raw) | `amazon` → `aws` | — |
| AWS Security Hub | `aws` → `security_hub` | — |
| AWS WAF | `aws` → `waf` | — |
| Jira | `Atlassian` → `Jira` | — |
| ServiceNow | `ServiceNow` → `ServiceNow` | — |
| CyberArk ISP | `cyberark` → `isp` | — |
| Entra ID audit | `msft` → `azure_ad_audit` | `category=AuditLogs` |
| Entra ID sign-in | `msft` → `azure_ad` | `category=SignInLogs` |
| O365 General | `msft` → `o365_general` | — |
| O365 Exchange | `msft` → `o365_exchange_online` | `Workload=Exchange` |
| O365 SharePoint | `msft` → `o365_sharepoint_online` | `Workload=SharePoint` |
| O365 Emails | `msft` → `o365_emails` | `Operation=EmailEvent` |
| O365 DLP | `msft` → `o365_dlp` | `Workload=DLP` |
| Qualys | `Qualys` → `Qualys` | — |
| ProofPoint Email | `proofpoint` → `email_security` | — |
| ProofPoint TAP | `Proofpoint` → `TAP` | — |
| Azure Flow Logs | `msft` → `azure_flowlogs` | — |
| Azure WAF | `msft` → `azure_waf` | — |
| Azure AKS | `msft` → `azure_aks` | `category=kube-apiserver` (control-plane category; NOT `kube-audit`) |

For vendors not in this table, fall back to `data_sources_get_schema` + parse `how_to_use` — every data source YAML carries the routing guidance.

## Forbidden under this skill

- **Don't query XSIAM before waiting at least 90s.** Ingest latency is real; querying too early reports a false negative. Tell the operator you're waiting.
- **Don't tell the operator events landed without RUNNING the verification query.** Worker creation success ≠ landing success. Always run Step 6 + 7.
- **Don't use the YAML's top-level `vendor` / `product` for `xlog.create_data_worker` arguments.** Parse `how_to_use` for the CEF routing literals. Using display names will route to the wrong dataset (sometimes silently — events land in `unknown_unknown_raw` or `<display-vendor>_<display-product>_raw` which isn't where the operator's PRs route from).
- **Don't auto-install missing Cortex Marketplace packs.** XSIAM dataset registration is operator-owned. If the dataset doesn't exist, surface the gap + point to the Marketplace.
- **Don't claim XDM saturation without running `datamodel dataset = X | fields xdm.*`.** Raw landing ≠ XDM materialization. The MR transforms raw into XDM lazily.
- **Don't leave workers running after verification.** They keep emitting UDP at the broker. Always call `xlog.kill_worker` in Step 8.
- **Don't use any `xdr_*_xql_*` tool for verification.** Those route to the cortex-xdr connector → a DIFFERENT Cortex tenant from the operator's XSIAM. Use `xsiam.run_xql_query` exclusively. See the "Tool selection" callout above Step 6.

## Output template (operator-facing)

```
**Streaming `<vendor>` logs to Cortex XSIAM**

1. ✅ Discovered data source `<dataset_name>` (pack: `<pack_name>`, rule: `<rule_name>`)
2. ✅ Routing values from how_to_use: vendor=`<cef_vendor>`, product=`<cef_product>` <discriminator if any>
3. ✅ Worker created: `<worker_id>` streaming CEF to `<destination>` at <count>/2s
4. ⏳ Waiting 90s for XSIAM ingest...
5. <verify result>:
   - ✅ **Raw landing**: <N> events in `<dataset_name>` since worker start
   - ✅ **XDM materialization**: <M> XDM fields populated, including: <list top 8>
6. ✅ Worker stopped (`<worker_id>`)

End-to-end pipeline verified for **<vendor>**.
```

If any step fails, replace ✅ with ❌ + report the specific diagnostic + next-step suggestion (re-read how_to_use, install Cortex pack, check broker applets, etc.).

## Related skills + tools

- `simulate_vendor_logs` — generate vendor-faithful records ONLY (no XSIAM round-trip). Use when operator wants to inspect records locally.
- `xdr_verify_simulation_telemetry` — verification skill for **Cortex XDR** (not XSIAM). Different connector, different procedure.
- `data_sources_list` / `data_sources_get_schema` — discovery tools used in Step 1-2.
- `xlog.create_data_worker` / `xlog.list_workers` / `xlog.kill_worker` — the simulation tools.
- `xsiam.run_xql_query` — **the only** verification tool. NOT `xdr_run_xql_query` / `xdr_xql_run_query` — those hit a different Cortex tenant. See "Tool selection" callout above Step 6.
- `log_destinations_list` — get the operator's named XSIAM broker destination.
