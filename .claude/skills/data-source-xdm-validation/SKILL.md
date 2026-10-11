---
name: data-source-xdm-validation
description: >
  Reverse-engineer, create, update, and validate a Phantom data source against
  Cortex XSIAM — making a vendor's synthetic CEF logs route into their XSIAM
  dataset, clear the modeling-rule gate, and map a rich set of `xdm.*` fields.
  Use this WHENEVER you are: onboarding a new data source; debugging "why doesn't
  this map to XDM / why is xdm=0"; a source lands raw but maps few/zero fields;
  seeding a modeling-rule gate; shaping JSON composites for nested-JSON rules;
  pulling demisto/content modeling rules; promoting a source to `validated`; or
  reconciling a data_source.yaml schema against its parsing/modeling rules; or
  a source that "looks fine in raw" produces almost no XDM — which is usually the
  WORKER, not the rule (see Layer 0: no schema_override attached, 4 KB wire
  truncation, or `enum_values` silently ignored on a dotted JSON leaf). The
  work is COGNITIVE — every source differs — but the end-to-end loop, the
  failure-mode decision tree, and the supporting scripts are captured here.
  Reach for this skill even when the user just says "validate <vendor>",
  "make <vendor> map to XDM", or "this dataset isn't modeling."
paths:
  - bundles/spark/data-sources/**
  - scripts/maintainer/modeling_rules/**
  - scripts/maintainer/parsing_rules/**
  - tooling/validate/validated_data_sources.txt
  - xlog/app/dynamic_schema.py
  - xlog/app/override_sender.py
---

# Data-source XDM validation & reverse-engineering

This skill distils the method for validating a data source end-to-end
against a live XSIAM tenant. **It is a thinking harness, not a script to run.**
Each vendor's parsing + modeling rules are different; your job is to read the
rule, understand what it expects, shape the synthetic event to match, and prove
the mapping on the tenant. The steps below are the spine; the judgment is yours.

## Delivery doctrine — syslog/CEF ONLY (the load-bearing rule; read FIRST)

**Phantom delivers every synthetic log over syslog/CEF to the Cortex Broker. We NEVER
use an HTTP collector or an API integration to deliver logs — full stop.** This holds
*even when the real-world vendor is collected that way in production* (CrowdStrike FDR
pulling gzipped JSON from S3, Snowflake/Wiz/Rapid7/PingOne API pollers, an HTTP event
collector, etc.).

**One sanctioned exception:** the `http-sender` bundle connector sends JSON to an XSIAM HTTP Log
Collector when the operator chooses to: for HTTP-versus-CEF A/B tests, and for
**HTTP-delivery data sources** (`delivery: http` in `data_source.yaml`; the `*HttpCollector` Okta, Proofpoint TAP
and Google Drive sources today). An HTTP data source is for HTTP simulation. It does not change this loop:
validating and promoting a data source's mapping still goes over syslog/CEF, it carries no
`validated`/`raw_validated` tier, `phantom_create_data_worker` is not used for it, and an API poller is still
never used. The admission rule (a real parsing/modeling path must exist for the vendor) applies to it too.

**Pairing:** where a vendor has both a syslog source and an HTTP one (Okta, Proofpoint TAP, Google Drive), the syslog
one is for checking parsing and modeling and its `how_to_use` says to expect no Analytics alerts from it. To test Analytics the
operator uses the HTTP one with `http-sender`; to check a mapping, syslog/CEF stays the path.

**Second sanctioned exception:** the `wec-sender` bundle connector delivers Windows Event XML to the Broker VM's Windows Event
Collector applet over WS-Management (mutual TLS, TCP 5986) when the operator chooses to, because `_collector_type = WEC` cannot be set from an
event body. Same limits as above: it never validates or promotes a data source's mapping, carries no `validated`/`raw_validated` tier, and sends
only to the operator's own broker.

**Why this is sound, not a workaround:** the broker, parsing rules, and modeling rules
are **protocol-agnostic**. They do not care *how* an event arrived — they map on the
**data shape**: the field/column/JSON structure of the event. A modeling rule reading
`json_extract_scalar(evt, "$.a.b")` maps our event whether it arrived over an API or over
syslog, *as long as the event carries `a.b` in the expected shape*. The collection
mechanism is invisible to the rule.

**The limit of that claim: it covers parsing and modeling, not Cortex Analytics.** One Okta FastPass event that landed
in `okta_sso_raw` over both paths, with identical columns and `xdm.*` fields, alerted when sent through the HTTP collector and
raised nothing over syslog/CEF (observed in a side-by-side test). The cause is not established: the collector-type stamp and
a registered data-source stream both fit. Never promise an Analytics alert from a syslog/CEF source whose Cortex collector is an API or HTTP collector
(Okta, Proofpoint TAP, Google Workspace: they use Cortex's own API collectors). Reproduce the native feed through
`http-sender` (generic HTTP, or the Cribl integration with the source's dedicated UUID) or `wec-sender`, and do
not read a missing alert over syslog as a mapping failure.

**Therefore the whole job is reverse-engineering, not transport.** Read the vendor's
**parsing + modeling rules**, derive the exact data shape they expect (column names, JSON
paths, value types, the gate), and encode it into `data_source.yaml` `fields[]` (names,
types, descriptions, examples) + `how_to_use`. The phantom agent then crafts synthetic
events of that shape and ships them over syslog/CEF; the parsing rule extracts the
columns, the modeling rule maps them, `xdm.*` populates → validated.

**Consequences that correct the most common mistakes:**
- A vendor being "native-collector-only" or "API-integration" in real XSIAM is **irrelevant**
  to whether we can validate it. **Never** dismiss a source as un-validatable because its
  production collection is HTTP/API/FDR. Reverse-engineer the rule and replicate the *shape*
  over CEF.
- `raw > 0, xdm = 0` is **not** "this source can't map." It means **no modeling rule is bound
  to the dataset** — the rule isn't installed or doesn't exist yet. The fix is to obtain +
  reverse-engineer the rule (install the content pack so it binds, or export the tenant's
  rule), not to give up. (Example: PingFederate CEF lands raw rows but shows `xdm=0` on a
  tenant that has no PingFederate modeling rule bound.)
- The `how_to_use` documents the **data shape + the syslog/CEF routing literal** — NOT the
  vendor's real-world collection plumbing. Describing "FDR S3/SQS" or "API poller" as the
  *delivery mechanism* misleads the agent into thinking it needs an HTTP collector; it never
  does. State the field shape and that Phantom ships it as CEF.
- JSON-native rules are mapped by emitting the JSON as a **CEF composite extension**
  (dotted-leaf fields → nested JSON string on the wire — §4). No HTTP collector, ever.

## What counts as a data source (the admission rule — check BEFORE onboarding a vendor)

A Phantom data source MUST correspond to a real Cortex XSIAM **log-ingestion + parsing path**:
the vendor has a **parsing rule and/or modeling rule** — shipped in a content pack OR built-in
to the platform (e.g. PingFederate's native authentication parser + `ping_identity_pingfederate_raw`
dataset) — so its logs land in a dataset and get *structured*.

**A vendor whose only Cortex presence is an XSOAR/Marketplace integration with no Parsing/Modeling
rules is NOT a data source — it's an action integration** (it fetches alerts/incidents or runs
response actions via API; it never ingests + parses logs into a dataset). Do not onboard it. SIEMs
that are log *destinations* (IBM QRadar, Rapid7 InsightIDR) are likewise not sources.

**Quick admission triage (quota-free), run BEFORE any simulate cycle:**
1. `GET https://api.github.com/repos/demisto/content/contents/Packs/<Pack>/ParsingRules` and `…/ModelingRules`
   (200 = the pack ships rules → candidate data source; 404 on BOTH = no rules in the snapshot).
2. Inspect the pack contents: only `Integrations/`+`Playbooks/`+`Classifiers/` (no `ParsingRules`/
   `ModelingRules`/`Datasets`) ⇒ **XSOAR automation pack = action integration, not a data source.**
3. If demisto/content has nothing, check the Cortex docs for a NATIVE/built-in ingestion path
   ("Ingest <vendor> …" data-source page naming a dataset). Native parsers count (PingFederate).
4. No rule in a pack AND no native ingestion+parsing path ⇒ **not a data source. Do not add it.**

(Vendors that fail this test — for example CrowdStrike, Sophos, PingOne, Wiz, Rapid7, SAP, ESET,
Snowflake, Veeam and QRadar — are not data sources. They *land raw* over CEF but have no rule to map
them, so they can never green-pill and aren't useful as structured SOC-simulation sources.
PingFederate passes, because it has a native parser and a matching dataset.)

Two reference files carry the deep detail — read them when you hit the
corresponding work:

- **[references/diagnostic-playbook.md](references/diagnostic-playbook.md)** — the
  full `xdm=0 / low-field` decision tree, the gate taxonomy, JSON-composite
  mechanics, and the reverse-engineering deep-dive. **Read this the moment a
  source doesn't map as expected.**
- **[references/tooling.md](references/tooling.md)** — every script, MCP tool,
  exact invocation, the GitHub rule-pull command, and file paths. **Read this
  when you need to run something.**

---

## The mental model (internalize this first)

A synthetic event has to survive **two independent layers**. Diagnose them
separately — conflating them is the #1 time-sink.

```
  phantom worker → CEF/syslog over UDP → XSIAM Broker
        │                                     │
        │  LAYER 1: ROUTING + LANDING         │  raw rows appear in <dataset>_raw ?
        │  (vendor/product header → dataset)  │  → `dataset = X | comp count()`
        ▼                                     ▼
  Broker INGEST/parsing rule extracts columns  ──→ LAYER 2: MODELING (XDM)
        │                                     │  do xdm.* fields populate ?
        │  modeling rule reads columns →      │  → `datamodel dataset = X | fields xdm.*`
        ▼  xdm.* / XDM.Endpoint.*             ▼
```

Three load-bearing truths, each learned the hard way:

1. **Routing is by the CEF *header*, not the extensions.** The broker derives the
   target dataset from `<lower-vendor>_<lower-product>_raw` (or matches an explicit
   `[INGEST: vendor="X", product="Y"]` rule). The display `vendor`/`product` in the
   YAML are **not** the routing literals — derive them from the dataset name and
   verify (the "SentinelOne trap"). Casing can matter (`Cisco`/`Firepower`, not
   `cisco`/`firepower`).

2. **A modeling rule only binds to a dataset that is XDM-enabled — which means its
   content pack is installed in XSIAM.** A broker-**auto-created** dataset (unknown
   vendor/product, no INGEST rule) is raw-only: `datamodel dataset=X` returns
   **0 rows** no matter how perfect the event, because no rule is associated.
   **This is the single biggest blocker.** The fix is operator-side: install the
   vendor's content pack → it binds the modeling + parsing rules to the dataset.
   *(Symptom: raw rows present, columns extracted, `datamodel`=0.)*

3. **Modern cloud/SaaS rules are JSON-native.** They read **nested JSON** via
   `json_extract_scalar(properties, "$.extendedProperties.user name")` and
   `protoPayload -> methodName`. CEF-over-syslog still works — the worker emits
   composite fields as **JSON strings** on the wire, which the rule parses — but
   the `data_source.yaml` schema must carry **dotted-leaf fields**
   (`properties.alertDisplayName`, `properties.extendedProperties.user name`) so
   the generator synthesizes the nested object. No HTTP collector is needed.

---

## Layer 0 — the worker and the wire (read before blaming the rule)

The two-layer model above is missing a layer, and overlooking it can cost a full
diagnostic cycle. Before routing and before modeling there
is **what the worker actually put on the wire**, and it is the layer that fails
most often while looking exactly like a modeling failure.

```
  data_source.yaml  --(worker config)-->  WIRE  --> routing --> modeling --> xdm.*
                     ^^^^^^^^^^^^^^^^^^   ^^^^
                     LAYER 0: is the schema even attached, and did it fit?
```

**A typical case.** `fortinet_fortigate_raw` can show 6 of 191 XDM fields
populated across millions of events while every hypothesis points at the modeling
rule. The rule is fine and the schema is fine — the `data_source.yaml`
declares all 222 fields, covering all 152 columns the rule reads. The cause is
**generic CEF workers created with no `schema_override`**, emitting
only the CEF header plus `act`/`src`/`dst` as random tokens. A worker created
WITH a schema takes the same source from 6 to **35 populated fields at 100%**,
immediately.

**The tell.** Look at *which* fields survived: `observer.vendor`,
`observer.product`, `observer.version`, `event.log_level`, `event.is_completed`,
`observer.action`. Those come from the CEF **header**, from `cefSeverity`, from a
hard-coded constant, and from `act`. **When every populated field traces to the
header or a single extension, the worker has no schema attached.** That
signature is worth memorising; nothing else produces it.

### The 4 KB field budget — never send the whole schema

A Broker syslog collector accepts roughly **4096 bytes per event and silently
truncates past it**. FortiGate's 222 fields encode to ~5,259 bytes, so passing
the full `fields[]` array from `data_sources_get_schema` drops the tail with no
error at any layer: the event lands, the trailing columns are absent, and the
XDM targets they feed read null. **This reproduces the exact null pattern of a
broken modeling rule.**

Send a **20-40 field subset** chosen for the detection you are simulating. The
generator honours `xlog/app/override_sender.py::_guard_cef_length`, which trims
at an extension boundary and logs a warning — but the warning is in the xlog
container log, not anywhere you are looking.

### `enum_values` is flat-only — pin JSON leaves with `is_gate` + `example`

`enum_values` is honoured for flat CEF columns and **silently ignored on a
dotted-leaf field**. Declaring `{"name": "user.name", "type": "enum",
"enum_values": ["sameh"]}` produces `user = {"name": "XJ5Vm57q"}` — the
generator builds the nested object and fills the leaf randomly.

This is vicious because a sibling flat column often looks correct: Duo's flat
`username` column read `sameh` while `user.name` held a token, and the
authentication block reads the **leaf**
(`json_extract_scalar(user, "$.name")`), so the events landed and never modeled.
Raw looked healthy; `datamodel` was empty.

Pin leaves with `is_gate` + `example`, which resolves before `type`:

```json
{"name": "user.name", "isGate": true, "example": "sameh", "type": "string"}
```

That pins ONE scalar per worker. A scenario needing several values on a leaf is
therefore **several workers, one per identity** — which is also the correct
shape, because every field is sampled independently and multi-valued lists
decorrelate, destroying the entity key an analytics detector groups on.

### Value shapes that pass a rule's own gates

A field can be present, non-null, and still map nothing because the rule matches
a literal or a regex. The recurring families:

| Shape | Why | Example |
|---|---|---|
| Numeric protocol codes | literal ladder over `"0"`-`"137"` | `proto="6"` maps TCP; `proto="TCP"` does not |
| Numeric category codes | ladder over `"0"`-`"101"` | FortiGate `cat="26"`, not `access_control` |
| Bare dotted quads | members of arrays filtered by an IPv4 regex | a token yields an empty array and null `xdm.source.ipv4` |
| Length-selected hashes | `len()=32` → md5, `len()=64` → sha256 | any other length populates **neither** |
| Recognised enum tokens | ~50-branch ladders | DNS `qtype` must be `A`/`AAAA`/`TXT`; HTTP method uppercase |

**Disjoint entity pools.** Overlapping `shost`/`dhost` value lists produce alerts
that read "win11-manager connected to win11-manager". Source and target pools
must not intersect.

## The end-to-end loop (the proven method)

Run this against a running install with a bearer API key (see
tooling.md for the exact connection and prompts). The loop is
also encoded as the `stream_simulate_to_xsiam` MCP skill — this skill is the
*authoring/debugging* companion to that *runtime* skill.

1. **Pre-req: is the pack installed?** If you don't know, assume not. If
   `datamodel dataset=X` returns 0 while raw>0, the pack isn't bound — ask the
   operator to install the vendor's content pack in XSIAM. **Don't burn cycles
   tuning the event until the dataset is XDM-enabled.**

2. **Pull the rules.** `python3 scripts/fetch_demisto_modeling_rules.py` mirrors
   the `.xif` modeling + parsing rules from `demisto/content` into
   `scripts/maintainer/modeling_rules/` and `…/parsing_rules/`. These are your
   ground truth for what the rule reads. *(Caveat: the snapshot can lag the
   operator's **installed** rule version — if everything looks right but xdm=0,
   suspect a snapshot-vs-installed mismatch and ask the operator to export the
   tenant's actual rule.)*

3. **Reverse-engineer the gate.** `python3 scripts/maintainer/reverse_engineer_gate.py <ds_id>`
   classifies the modeling-rule gate: `unconditional` (maps regardless), `raw`
   (filter on a literal value set — **must seed**), `function` (coalesce-derived —
   seed the raw inputs), `computed` (regex/json-derived, e.g. GCP `logName` — seed a
   realistic value), `meta` (`_`-prefixed, ingestion-stamped — not seedable). See
   the gate taxonomy in the playbook.

4. **Derive the routing literal — read the INGEST/parsing rule FIRST.** If the pack
   has a parsing rule, it *hands* you the literal verbatim:
   `[INGEST: vendor="prisma", product="cloud_compute", target_dataset="prisma_cloud_compute_raw", no_hit=keep]`
   — also telling you the `_time` parse and `no_hit` behavior. Only if there's **no**
   INGEST rule do you fall back to deriving from the dataset name (`aws_guardduty_raw`
   → `AWS`/`GuardDuty`; broker lowercases, multi-word → underscores). **Beware
   non-derivable dataset names**: `imperva_inc__securesphere_raw` does NOT split to a
   clean literal — its routing comes from the vendor's **canonical CEF header**
   (`Imperva Inc.`/`SecureSphere`, which the broker normalizes to that dataset). When
   in doubt, look up the vendor's standard CEF header and **verify empirically which
   dataset the events land in** (and that `unknown_unknown_raw` didn't grow).

4b. **Pre-flight: diff the schema field names against the MR's source columns.** This
   one deterministic check catches the most common low-mapping cause *before* you
   spend a simulate cycle. **For CEF sources the schema field names MUST be the CEF
   wire keys the MR reads** — `cs1`–`cs6`, `cn1`–`cn3`, `src`, `dst`, `spt`, `dpt`,
   `act`, `app`, `duser`, `suser`, `cat`, `request`, `cefDeviceEventClassId`,
   `cefSeverity`, … — **NOT** the vendor's human-readable names. The broker extracts
   each CEF extension into a column named by its key, and the schema field name *is*
   that key. An auto-extracted schema with logical names (Imperva shipped
   `alertSeverity`/`destinationIP`/`httpMethod`) maps **zero**. Run the column-diff
   one-liner in the playbook (§3) — if the overlap with the MR's reads is poor, rebuild
   the schema fields to the MR's actual column names before simulating.

   **Run the diff on the SERVED schema, not the on-disk YAML.** The worker streams
   whatever `data_sources_get_schema` returns, which can lag the bundled file.
   After any bundled-schema edit, confirm `get_schema` actually returns your new fields
   **before** streaming — and after streaming, confirm by querying the landed raw
   columns (`dataset = X | sort desc _time | fields <new_key>, <old_key> | limit 1`):
   if the OLD column names landed (Imperva streamed `action`/`alertSeverity` even after
   the bundle was fixed to `cs1`/`src`), the served schema is stale and the edit is
   inert until the store refreshes. **Looking at the landed raw columns is the
   ground-truth check — never trust the bundled YAML alone.**

5. **Shape the schema.** For flat rules, the bundled `data_source.yaml` fields
   usually match. For JSON-native rules, ensure the composite (`type: json`) field
   has **dotted-leaf children matching the rule's `json_extract` paths**
   (read them off the `.xif`'s `json_extract_scalar(<composite>, "$.<path>")` calls).

6. **Simulate.** `phantom_create_data_worker(type="CEF", destination=<resolved>,
   vendor=…, product=…, count=400, schema_override=<FULL compact fields[]>,
   observables_dict={<gate_field>:[<value>]})`. **`observables_dict` values are
   LISTS** (scalar fails pydantic). Use `data_sources_get_schema(…, compact=true)` —
   it's lossless for the override and fits the agent's tool-result cap.

   **NEVER hardcode the broker address — resolve it with `log_destinations_list`
   every run.** The broker address and port are install-specific.
   A wrong destination is the worst failure mode on this whole path: UDP syslog is
   fire-and-forget, so the worker reports `status=running` and streams happily into a
   black hole. There is **no error anywhere** — `metrics_view` simply never grows a row
   for your vendor/product, which is indistinguishable from a routing-literal mistake.
   Confirm the destination *before* you spend a simulate cycle debugging the schema.

7. **Verify over a WIDE window AND across MANY rows.** Two independent traps:
   - **Wide window:** synthetic `_time` can land days in the past, so a 24h window
     reads zero on a clean mapping. Use ≥7 days, even 30.
   - **Many rows:** count distinct non-null `xdm.*` **across ≥20 rows**, never the
     newest single row (or even newest-5). Synthetic events are sparse and varied —
     any one row populates only a handful of fields, so a single-row count badly
     **undercounts** (Prisma Cloud Compute read `6` from the newest row but `29`
     across 20 rows — nearly its whole rule). Take the UNION across rows:
     `config timeframe = 30d | datamodel dataset = X | sort desc _time | fields xdm.* | limit 20`
     → count distinct field paths non-null in *any* of those rows.
   `datamodel` applies the rule at *query time*, so re-querying after a wait is valid.

8. **If it didn't map → go to the decision tree** (playbook). Do **not** guess —
   walk the layers in order.

9. **Promote to validated** only after a real field count on the tenant:
   set `validated: true` in the YAML, add the id to
   `tooling/validate/validated_data_sources.txt`, write a validated `how_to_use`,
   and run the validator (`check_validated_data_sources_manifest` +
   `check_gate_fields_satisfied` must pass). For gated sources the YAML's gate-field
   `example` must be a value the rule accepts, or the gate-check fails.

---

## Back-dating — the broker honours CEF `rt`, no parsing rule needed

Analytics detectors carry an **Activation Period** (commonly 14 days) and a **Training
Period** (commonly 30). A feed that only accrues history in wall-clock time cannot reach
either inside a POV. Back-dating is therefore not a nicety — it is what makes the
analytics surface reachable at all.

**The lever is the CEF `rt` extension, and it works on every CEF source.** The broker
consumes `rt` as `_time` during **generic extraction** — no parsing rule is involved, and
`rt` does **not** need to be a column any modeling rule reads. Confirmed on two independent
sources:

| Source | Route | Parsing rule derives `_time`? | Probe `rt` | Landed `_time` |
|---|---|---|---|---|
| `duo_duo_raw` | claimed pair | **no rule at all** | `1787022542985` | `1787022542000` |
| `panw_ngfw_traffic_raw` | derived (rule bypassed) | n/a — bypassed | `1787195628621` | `1787195628000` |

Both landed exactly where sent, truncated to whole seconds.

**Send it as an epoch INTEGER — 10 (s), 13 (ms), 16 (µs) or 19 (ns) digits. An ISO-8601
string is silently ignored** and `_time` falls back to ingestion time.

Two common misconceptions to avoid:

- *"Back-dating is only possible where a parsing rule derives `_time` from an event field."*
  **Wrong.** That is the only lever *inside* a parsing rule; `rt` works outside it. A source
  with no `_time` parse (PAN firewall traffic, for example) can still be back-dated by
  sending `rt`.
- *"The field has to be in the schema."* **Wrong.** `rt` is consumed at ingestion, so
  appending it to the `schemaOverride` works even when the bundled `data_source.yaml` never
  declared it. Add it to the YAML anyway so the next run does not have to rediscover it.

**The trap that defeats it:** declaring a timestamp field WITHOUT pinning it. The generator
fills any unpinned field with a synthesized value — `now()` for time-typed fields — which
then wins over your intended value. Always pass the back-dated values explicitly in
`observables_dict`, as a LIST spanning the window you want:

```python
now_ms = int(time.time() * 1000)
rt_pool = [str(now_ms - random.randint(0, 30 * 86_400_000)) for _ in range(3000)]
observables = {"rt": rt_pool, ...}
```

Verify the span landed before doing anything else — one query, and it is the cheapest
possible check that the whole run was worth making:

```
dataset = <ds> | comp count() as n, min(_time) as first, max(_time) as last
```

## Pin every member of a coalesce, and declare the SMALLEST schema that works

Two failure modes that both look exactly like a broken modeling rule, and are not. Both
show up on `microsoft_windows_raw`.

**1. An unpinned field EARLIER in a coalesce beats the pinned one behind it.** The generator
synthesises a random value for every DECLARED field you do not pin. If the rule reads

```
user_sid = coalesce(event_data -> SID, event_data -> SubjectUserSid, user -> identifier, ...)
xdm.source.host.fqdn = coalesce(event_data -> FQDN, event_data -> WorkstationName)
```

then pinning only `SubjectUserSid` and `WorkstationName` yields
`xdm.source.user.identifier = "hL42dIss"` and `xdm.source.host.fqdn = "host-a"` — the
synthesised first members won. **Read the whole coalesce chain and pin every member, or drop
the earlier ones from the schema override entirely.**

**2. A full-schema override drags in noise.** Declaring all 127 bundled fields on a Windows
logon produced `xdm.target.location.country = Bulgaria`, `xdm.target.asn.as_name = Cooolbox AD`
and `xdm.target.file.path = /usr/bin/curl` — every declared-but-unused field synthesised and
mapped. Declare only what the target event needs (27-34 fields here) and the record reads clean.

**Corollary — the subset is per event type, not per source.** Fields that belong only to an
interactive logon (`LogonType`, `AuthenticationPackageName`, `LogonProcessName`, `ElevatedToken`,
`Status`) must be dropped when generating Kerberos event IDs. Left declared, `LogonType` is
synthesised, and `xdm.logon.type` falls through the rule's if-chain to the raw string
(`"ASmSYVxp"`) instead of a `LOGON_TYPE_*` constant.

**The check that catches both**, run over >=20 rows rather than one:

```
datamodel dataset = <ds> | sort desc _time | fields xdm.* | limit 25
```

Scan for values that look like generator output — 8-character mixed-case tokens, geography that
does not belong, file paths from the wrong OS. Every one is a field you declared and did not
pin. A field count alone will not show this: the noise INCREASES the count, so a full-schema run
scores *higher* while being less correct.

## Entity identity — the prerequisite nothing else can substitute for

Cortex analytics split into two kinds, and only one of them cares about volume:

- **BIOC / pattern rules** fire on a matching event. Shape the event, they fire.
- **Profiling detectors** ("rare/unusual/new/first-time *for this host*") learn a
  baseline per ENTITY and alert on deviation. They need a stable entity, and the
  Analytics Engine will not activate at all without *EDR or network logs from
  >=30 endpoints over >=2 weeks* (or cloud audit logs over >=5 days).

A feed whose identity shuffles looks like this:

    hosts in fortinet_fortigate_raw : 40
    hosts with exactly one src IP   :  0
    worst offender                  : one shost, thousands of distinct src

Analytics raises only pattern-matching BIOC alerts and never a profiling alert, because there is no entity to profile. No
amount of extra volume or back-dated history changes that, and it is invisible
if you only check field counts: every event maps fine individually.

**Always pass identity fields as an entity group** (a known generator requirement). The generator
draws each field independently otherwise, so parallel lists emit the
cross-product:

    observables_dict = {
      "app": ["HTTP", "HTTPS"],              # independent — fine
      "__entities__": [                      # drawn as a UNIT, one per event
        {"shost": "wks-001", "src": "10.20.5.1", "suser": "ahmed"},
        {"shost": "wks-002", "src": "10.20.5.2", "suser": "sameh"}
      ]
    }

Anything naming a machine or person belongs in the group: hostname, IP, MAC,
logged-on user. Everything else stays independent.

**Verify it, every time.** The check is one query and it is unambiguous:

```xql
dataset = <ds> | filter shost != null and src != null
| comp count_distinct(src) as ips by shost | sort desc ips
```

Every row must read `ips = 1`. Anything else means the identity is shuffling and
no profiling detector on that source can ever fire.

## The tenant TELLS you when your event shape is wrong — read the HEALTH alerts

Cortex raises a **`Parsing Rule Error`** alert (alert_source `HEALTH`, alert_type
`Parsing`, domain `DOMAIN_HEALTH`) when a parsing rule throws at runtime on your data,
and the alert names the dataset, the vendor/product AND the reason. This is a free,
precise diagnostic and it is easy to never notice, because it lands in the alert list
rather than anywhere you would think to look while debugging a schema.

Example, when probing `msft_azure_aks_raw`:

    A Runtime error was identified for a Parsing Rule configured to use the dataset
    msft_azure_aks_raw on vendor msft, product azure.
    Error description:.  mandatory field _time is null

That one line identifies the defect exactly. The AKS parsing rule coalesces FOUR `_time`
sources (`requestreceivedtime`, `TimeGenerated`, `properties -> log ->
requestReceivedTimestamp`, `time`); an event whose `properties.log` is a nested object
satisfies none of them, because `properties -> log` then returns null.
Reshaping `properties.log` to a JSON *string* carrying `requestReceivedTimestamp`
makes the alert stop.

**Check it on every simulate cycle**, before assuming a mapping problem:

```xql
dataset = alerts
| filter alert_source = "HEALTH"
| fields alert_name, description, _time
| sort desc _time
| limit 10
```

Two things this catches that a field-count check cannot:
- **`mandatory field _time is null`** — the whole family of "the rule could not derive a
  timestamp" defects. `no_hit=keep` still lands the row, so raw>0 looks healthy while the
  rule is erroring on every event.
- A rule erroring on *some* events only, which shows up as a partial mapping that looks
  like a shape mismatch and is actually a runtime fault.

Note the column is `description`, not `alert_description` — the latter is not a field on
the `alerts` dataset and the query fails validation if you use it.

## The diagnostic decision tree (when xdm is 0 or low)

This is the scriptable spine of an otherwise-cognitive task. Walk it **in order** —
each step is one XQL query. Full version with the exact queries + fixes is in the
playbook; the summary:

| Observation | Layer | Likely cause → fix |
|---|---|---|
| `raw > 0`, but every populated `xdm.*` traces to the CEF header / `act` | **0** | The worker has NO `schema_override` — it is a generic keep-alive. → recreate it with a 20-40 field subset. This is the single most common cause and it mimics a broken rule. |
| `raw > 0`, leading columns present, trailing ones absent | **0** | 4 KB syslog truncation. → cut the field list; check the xlog container log for the `_guard_cef_length` warning. |
| Raw column looks right, `datamodel` still empty, rule reads a JSON leaf | **0** | `enum_values` ignored on a dotted leaf — the flat sibling column lied. → pin the leaf with `is_gate` + `example`. |
| `raw = 0` | 1 | Routing. Wrong vendor/product literal, OR tenant `[INGEST … no_hit=drop]` discards syslog. → fix literal / confirm an INGEST rule keeps it. **Check a wide window first — old `_time` reads 0.** |
| `raw > 0`, columns sit in `cefRawExtension` (not extracted) | 1.5 | The tenant INGEST/parsing rule is JSON-shaped (overrides generic CEF extraction) and your CEF event didn't "hit" its parse. → **NOT a dead-end** (doctrine: never fall back to an HTTP collector). Reverse-engineer the parsing rule and shape the CEF event so it hits — usually emit the JSON body the rule expects as a composite extension. If the tenant rule is `no_hit=drop` JSON-only, the operator widens the broker config to keep CEF; still syslog/CEF, never API/HTTP. |
| `raw > 0`, columns extracted, `datamodel = 0` | 2 | **Modeling rule not bound** — pack not installed. → operator installs the content pack. |
| `datamodel > 0` rows but `xdm.* = 0` populated | 2 | Gate not matched, OR the rule reads columns/paths your event doesn't produce. → seed the gate; check MR source columns vs schema field names; for JSON, check composite dotted-leaves vs `json_extract` paths. |
| Maps *some* `xdm.*` but fewer than the rule defines | 2 | Composite shape / column-name / value-type mismatch (e.g. `to_number(json_extract…)` needs a numeric leaf). → align the schema to the rule. |
| `datamodel` rows but `fields xdm.*` all null **and** rule says `model="Endpoint"` | 2 | Source maps to the **Endpoint preset** (`XDM.Endpoint.*`), not unified `xdm.*`. Query that namespace; note it may not be standard-XQL-enumerable. |

**Hypotheses that look right but are usually NOT the cause** (each was disproven on
real sources — don't waste time here without evidence): MTU truncation (UDP
fragments + reassembles; 2.5 KB events map fine), CEF space-mangling (the broker
reads an extension value until the next ` key=`, so JSON with spaces survives),
`compact=true` dropping fields (it's lossless), the generator emitting `{}` (it
builds nested JSON correctly when the leaves exist), materialization timing (counts
are stable within minutes). Confirm any of these with a query before believing them.

---

## Lessons & gotchas (the cognitive tips)

These don't fit a flowchart but will save you hours. The runtime skill
`stream_simulate_to_xsiam` encodes L1–L24; these are the
high-leverage ones plus the cloud-source additions.

- **Seed the gate or XDM stays 0** even when raw lands. The #1 layer-2 blocker.
- **`observables_dict` values are LISTS**: `{"category":["AZFWApplicationRule"]}`.
- **Wide verify window (≥7d).** The single most common false negative.
- **`sort desc _time` cannot tell one RUN from another once you back-date.** Every run shares
  the same 30-day window, so "newest by `_time`" is a random draw across all of them. A fix that
  worked reads as still-broken because the query keeps returning rows from an earlier run (a
  common trap on `microsoft_windows_raw`). Discriminate on a value unique to the run: a
  pinned `process_pid`, a `record_id` range, a marker user. Related, same shape: filtering on a
  field you set to a GENUINE vendor value (the real Microsoft Security-Auditing provider GUID)
  matches the tenant's REAL agent data, not your synthetic events, and the result looks like a
  mapping failure.
- **Verify freshness from the data** (`sort desc _time`), don't filter on
  `xdm.event.type != null` — firewall/endpoint rules lead with other fields.
- **Routing literal ≠ display vendor/product.** Reverse it from the dataset name.
- **Install-first.** A source can be perfect and still read `datamodel=0` purely
  because its pack isn't installed. Establish XDM-binding before tuning.
- **JSON-native ≠ unmappable over CEF.** Shape dotted-leaf composites; the worker
  JSON-stringifies them onto the wire and the rule parses them.
- **Endpoint-preset sources** (`model="Endpoint"`) bind + count rows but aren't
  enumerable via `datamodel | fields xdm.*` — a known verification gap.
- **Worker-ID collisions:** IDs are timestamp-second-granular; create workers ≥3–4s
  apart, or one clobbers another.
- **Snapshot vs installed rule drift:** the committed `.xif` can differ from the
  operator's installed pack. When the analysis is airtight but it won't map, ask
  for the tenant's actual rule text.
- **Background-shell PATH:** long-running/`run_in_background` bashes can run under a
  stripped PATH (`sleep`/`head` "command not found"); use absolute `/bin/sleep` and
  avoid array/loop constructs, or run foreground.
- **Two failure FAMILIES per fix:** when you fix one source, grep sibling sources
  for the same pattern (e.g. empty `{}` composites, scalar observables) — the bug
  is usually copy-pasted across the bundle.

### Schema and routing

- **CEF-source field names ARE the CEF wire keys** (`cs1`–`cs6`, `cn1`–`cn3`, `src`,
  `dst`, `spt`, `dpt`, `act`, `duser`, `cat`, …), never the vendor's logical names.
  A logical-name schema (Imperva's `alertSeverity`, `destinationIP`) maps **0/16**.
  Always run the pre-flight column diff (step 4b / playbook §3).
- **Read the parsing/INGEST rule first** — when present it hands you the routing
  literal, the `_time` parse, and `no_hit`, so you never guess. Prisma's
  `[INGEST: vendor="prisma", product="cloud_compute", … no_hit=keep]` provides all three.
- **Non-derivable dataset names** (double-underscore / vendor-specific, e.g.
  `imperva_inc__securesphere_raw`) → use the vendor's canonical CEF header
  (`Imperva Inc.`/`SecureSphere`) and verify empirically which dataset lands.
- **Bracket-notation JSON paths** `$['baseimage.name']` (keys containing a literal
  dot) cannot be expressed by the dotted-leaf convention — see playbook §4.
- **This skill is path-scoped** (`paths:` frontmatter → auto-activates when you edit
  `bundles/spark/data-sources/**`, the rules, or the generator/sender). It is NOT
  invoked by name via the Skill tool — follow it directly when it surfaces.
- **Count distinct `xdm.*` across ≥20 rows, never one row** (see step 7). Prisma Cloud Compute
  reads `6` from the newest row but `29` across 20 — a single-row count badly undercounts.
- **Served schema ≠ bundled YAML — the deploy/cache trap.** `data_sources_get_schema`
  serves an INSTALLED source from a **persistent SQLite store** (`data_sources.db`, in
  the `/app/data` volume), NOT from the bundled file. The volume survives container
  recreation and upgrades. **Current behaviour**: the store is kept in sync with the
  *effective* catalog YAML (bundle + operator edit overlay). Every boot re-composes each
  installed bundled source and updates its rows when they drifted, and an edit/rollback
  syncs the rows immediately (`installed_schema_synced: true` in the result). So a
  redeployed bundled `data_source.yaml` fix takes effect on the next boot with no
  re-install. **Only a PINNED source is skipped** (logged, listed under `skipped_pinned`
  in the `data_sources_refreshed` event in `/observability/events`); an explicit edit
  still outranks a pin. An edited source's baseline is frozen at first edit, so it won't
  pick up later bundle changes until you roll back to baseline. To force a full reset,
  re-run `data_sources_install(pack_name, rule_name, dataset_name)` — `dataset_name` is
  required, or it takes the cortex-extraction path. **Always verify the SERVED schema**
  (`data_sources_get_schema` — your new fields, the gate's `is_gate` + `example`, enum
  `enum_values`), not the on-disk YAML or the version marker.

### Rules, packs and admission

- **Ingestion mode is IRRELEVANT to validatability — but a modeling rule must EXIST to map.**
  The collection mechanism never changes our approach (always syslog/CEF — see the Delivery
  doctrine at the top). But a *rule* must exist to map the shape. Before burning any tenant
  cycle, run the quota-free triage: does the vendor's pack ship a modeling rule? Check
  `GET https://api.github.com/repos/demisto/content/contents/Packs/<Pack>/ModelingRules`
  (200 = has `.xif`; 404 = none). No modeling rule anywhere → nothing to reverse-engineer →
  the dataset lands raw but `datamodel = 0`. That is the honest `validated:false` outcome.
- **XSOAR pack ≠ XSIAM content pack.** A pack in demisto/content with only `Integrations/`
  / `Playbooks/` (API alert-fetch automation) is an XSOAR pack — it carries NO modeling rule.
  XSIAM *ingestion* content lives in packs WITH a `ModelingRules/` dir (often a separate
  `*EventCollector` / `*ModelingRules` pack). Vendors such as CrowdStrike, Sophos, Wiz,
  Rapid7, SAP, Snowflake, Veeam, QRadar, PingOne and ESET have XSOAR packs but no modeling
  rules in demisto/content, so none can saturate XDM on a stock tenant.
- **To validate a no-rule-in-snapshot vendor:** the rule must come from elsewhere — the
  operator installs the vendor's XSIAM content pack from the Cortex Marketplace (binds the
  rule to the dataset), or exports the tenant's installed rule. Then reverse-engineer it and
  craft the matching CEF shape. Until a rule exists, keep `validated:false` and document the
  precise prerequisite in `how_to_use`. Do NOT conflate "no rule yet" with "can't be done
  over CEF" — those are different problems.

- **Green-pill yield is GATED by the tenant's installed content packs — probe before you batch.** A candidate can have a perfect cortex-content/demisto modeling rule AND land millions of raw rows, yet `datamodel dataset=X` returns 0 because the rule isn't *bound* — the pack isn't installed on THIS tenant. Sources whose packs are installed (Entra, Zscaler NSS, Cisco ASA) saturate their rules; sources whose packs are not installed (BeyondTrust, VMware ESXi, Defender for Cloud, Proofpoint CASB, Barracuda CGFW, SecureAuth, Cisco Catalyst, FireEye HX, Arista, Azure App Service) land raw rows by the hundred thousand and still show `xdm=0`. **Before simulating a batch, cheaply probe which candidates are installed**: for a dataset that already carries raw data, `config timeframe = 30d | datamodel dataset = X | comp count() as modeled` >0 ⇒ rule bound (installed) ⇒ worth a simulate; =0 (with raw>0) ⇒ not installed ⇒ skip (or ask the operator to install the pack). Don't burn simulate cycles on un-installed datasets.
- **`_raw_log`-regex sources need a REALISTIC raw line, not random fields.** Many syslog-native cortex-content rules (firewalls/switches/EDR-audit: BeyondTrust PRA, VMware ESXi/vCenter, Barracuda CGFW, SecureAuth, Cisco Catalyst, FireEye HX, Arista) extract every field via `regextract(_raw_log, "…")` and gate on a *computed* column also carved from `_raw_log` (e.g. `event_type=arrayindex(regextract(_raw_log,"event=([^;]+)"),0) | filter event_type in(…)`). The OverrideSender emits random field values, so the `_raw_log` composite is random → the regex matches nothing → `xdm=0` even when the pack IS installed. To green-pill these, the generator must emit a realistic vendor wire line in `_raw_log` (per-vendor raw-line templates), or seed the full crafted line via `observables_dict={"_raw_log":["<realistic vendor syslog line>"]}`. **CEF-key + JSON-composite sources don't have this problem** — their fields are the real wire columns / json leaves the generator populates directly, which is why Cisco ASA (`_json` composite), Entra (`properties` JSON) and Zscaler NSS (CEF keys) saturate and the `_raw_log`-regex ones don't.

### Diagnostics and detection

- **Check Layer 0 first.** If every populated `xdm.*` field traces to the CEF
  header or `act`, stop reading the modeling rule — the worker has no schema.
- **Never pass the full `fields[]`.** 4 KB truncation reproduces a broken-rule
  null pattern exactly. 20-40 fields, chosen for the detection.
- **A healthy flat column can hide a hollow JSON leaf.** When a rule uses
  `json_extract_scalar`, verify the LEAF in the raw event, not its flat sibling.
- **One identity per worker.** Fields are sampled independently, so multi-valued
  lists decorrelate and the analytics entity key stops being coherent.
- **`type` steers generation; `example` is inert unless `is_gate`.** But a wrong
  `example` still does damage — it is the vocabulary the agent copies into a
  `schema_override`, so placeholders propagate into the wire.
- **Fixing the modeling gap is what makes detections possible at all.** Cortex
  analytics run on the datamodel; a hollow feed cannot fire anything. See the
  user-level `cortex-signal-path` skill for the detection half of this chain.

## What "validated" means (the bar)

A source is `validated: true` **only** after a live tenant run shows a rich,
fresh `xdm.*` field count through `simulate → XSIAM → XQL`. It is a customer-facing
green pill that asserts "this maps to XDM" — never set it on a source that merely
*should* map. If a source lands + is reverse-engineered but doesn't map on a stock
tenant (e.g. needs pack onboarding), **document it in `how_to_use` with the precise
reason and prerequisite — do not validate it.** That honesty is the whole point of
the pill.

## Scripts & tools at a glance

Full invocations + paths in **[references/tooling.md](references/tooling.md)**.

| Need | Use |
|---|---|
| Pull `.xif` rules from GitHub | `scripts/fetch_demisto_modeling_rules.py` |
| Classify the modeling-rule gate | `scripts/maintainer/reverse_engineer_gate.py` |
| Drive simulate+verify on the tenant | the agent chat (UI, or `POST /api/chat` with `PHANTOM_API_KEY`) |
| Author `how_to_use` from a rule | `scripts/maintainer/gen_cloud_how_to_use.py` (pattern) |
| Promote to validated (+manifest) | `scripts/maintainer/gen_cloud_validated.py` (pattern) |
| Inspect the generator/sender behavior locally | `xlog/app/dynamic_schema.py`, `xlog/app/override_sender.py` |
| Enforce the validated set + gate seeds in CI | `tooling/validate/validate_all.py` |

The `gen_cloud_*` scripts are **patterns**, not
universal tools — each is tuned to a batch. Read them, adapt the `TARGETS`/`VALIDATED`
dicts, re-run. They write minimal-diff YAML; verify with `git diff` before committing.
