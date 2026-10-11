# Diagnostic playbook — XDM mapping & reverse-engineering

Read this when a source doesn't map as expected, or when you're reverse-engineering
a rule from scratch. It is the detailed companion to the SKILL.md summary.

## Table of contents
1. The `xdm=0 / low-field` decision tree (exact queries + fixes)
2. Modeling-rule gate taxonomy (the 6 kinds + how to seed each)
3. Reading a `.xif` — what a modeling rule actually expects
4. JSON-composite mechanics (the dotted-leaf → nested-JSON pipeline)
5. The Endpoint preset
6. The list of disproven hypotheses (don't re-chase these)

---

## 1. The decision tree (walk in order, one query per step)

Always query a **wide window** first — `config timeframe = 30d | …`. Synthetic
`_time` frequently lands in the past, and a narrow window is the most common false
"it's broken."

### Step A — did anything land? (Layer 1: routing)
```
config timeframe = 30d | dataset = <dataset>_raw | comp count() as raw
```
- **raw = 0** → routing failed. Causes:
  - Wrong CEF `vendor`/`product` literal → events went to `unknown_unknown_raw` or a
    differently-named dataset. Reverse the literal from the dataset name and re-send;
    also check `dataset = unknown_unknown_raw | comp count()` to see misroutes.
  - The tenant has `[INGEST: vendor="X" product="Y" … no_hit=drop]` with no parsing
    body → it silently drops syslog-CEF. Confirm against the parsing-rule snapshot;
    this is a tenant-onboarding gap, not a Phantom-side fix.
  - Casing: some INGEST rules match case-sensitively (`Cisco`/`Firepower`).
- **raw > 0** → routing works. Go to Step B.

### Step B — are the columns extracted, or trapped in the raw blob?
```
config timeframe = 30d | dataset = <dataset>_raw | sort desc _time | fields <col> | limit 1
config timeframe = 30d | dataset = <dataset>_raw | fields cefRawExtension | limit 1
```
- If `<col>` errors with **`unknown field`** and `cefRawExtension` holds the raw
  `key=value …` blob → the broker did **not** extract CEF extensions into columns.
  This happens when the tenant's content INGEST rule is JSON-shaped (it overrides
  generic CEF auto-extraction and its own parse doesn't "hit" on your CEF event).
  **This is NOT a reason to reach for an HTTP collector** (delivery doctrine: always
  syslog/CEF). The fix: reverse-engineer that parsing/INGEST rule and shape the CEF
  event so it *hits* — typically carry the JSON body the rule expects as a composite
  extension (`properties={…}`), or align to the columns the rule extracts. If the
  tenant rule is `[INGEST … no_hit=drop]` JSON-only, the operator widens the broker
  config so CEF is kept; the event still arrives over syslog/CEF, never via API/HTTP.
- If the column **exists** with your value → extraction works. Go to Step C.

### Step C — does the modeling rule produce any rows? (Layer 2: binding)
```
config timeframe = 30d | datamodel dataset = <dataset>_raw | comp count() as modeled
```
- **modeled = 0** (while raw > 0) → **the modeling rule is not bound to this dataset.**
  Almost always: the content pack isn't installed in XSIAM, so the broker-auto-created
  dataset is raw-only. **Fix: operator installs the vendor's content pack.** Re-check —
  `modeled` should jump from 0 to ~raw immediately (it binds, then applies at query time).
- **modeled > 0** → the rule runs. Go to Step D.

### Step D — do xdm fields actually populate?
```
config timeframe = 30d | datamodel dataset = <dataset>_raw | sort desc _time | fields xdm.* | limit 5
```
Count distinct non-null `xdm.*` paths across the rows.
- **All null / very few** → the rule ran but its source reads resolved to null. Three sub-causes:
  1. **Gate not matched.** The rule's `filter <field> in (…)` excluded your rows.
     Re-derive the gate (§2) and seed it. Verify the gate column actually carries the
     value: `dataset = X | comp count() as c by <gate_field>`.
  2. **Column-name mismatch.** The rule reads `Type`, `Title`, `Resource`… but your
     schema emits different field names. Compare the rule's source columns (§3)
     against the YAML `fields[]`. Rename the schema fields to match.
  3. **JSON-composite shape mismatch.** The rule reads `json_extract_scalar(properties,
     "$.x")` but your `properties` is `{}` (no dotted leaves) or the leaves don't match
     the paths. Fix the composite (§4).
- **Rich count** → you're done; promote to validated.

### Step E — special case: Endpoint preset
If `datamodel` returns rows but `fields xdm.*` is empty **and** the `.xif` header is
`[MODEL: dataset=X, model="Endpoint"]`, the rule targets the **Endpoint** datamodel
(`XDM.Endpoint.*`), not unified `xdm.*`. See §5.

---

## 2. Gate taxonomy — the 6 kinds (`reverse_engineer_gate.py` output)

The modeling rule's leading `filter` decides which rows it maps. Classify it, then
seed the gate field in `observables_dict` (and the YAML `example` for the validator).

| kind | what it looks like | how to seed |
|---|---|---|
| **unconditional** | no leading `filter`, or a catch-all `… not in (…)` | nothing — maps regardless |
| **raw** | `filter category in ("AZFWApplicationRule", "AZFWNetworkRule", …)` | `observables_dict={"category":["AZFWApplicationRule"]}` — pick the **richest** branch (usually the one with the most `alter xdm.*` lines) |
| **function** | `filter get_category in (…)` where `get_category = coalesce(category, Category)` | seed any one of the coalesce inputs (`category` **or** `Category`) with a literal from the set |
| **computed** | `filter source_log_event = json_extract…` or a regex like GCP `arrayindex(regextract(logName, …))` | seed the underlying field with a **realistic** value (e.g. `logName="projects/P/logs/cloudaudit.googleapis.com%2Factivity"`) so the regex/branch resolves |
| **meta** | `filter _log_type = "…"` (underscore-prefixed) | **not seedable from payload** — stamped by the Broker applet / HTTP Collector at ingestion. Allow-listed by the validator; can't be forced via CEF. |
| **not_found** | no `.xif` in the snapshot | pull rules first, or the pack genuinely has no MR |

The richest branch matters: a `raw` gate often has 3–5 branches (`page`, `application`,
`alert`, `audit`, `network` for Netskope; `AZFW*` for Azure Firewall). The
`application`/main branch usually maps the most fields — seed that one.

The CI check `check_gate_fields_satisfied` re-derives this live from the `.xif` each
run, then asserts the YAML carries the seed field with an `example` in the value set.
So after validating a gated source, set the gate field's `example` accordingly
(e.g. Azure Firewall `category: AZFWApplicationRule`), or CI fails.

---

## 3. Reading a `.xif` — what the rule expects

A modeling rule (`scripts/maintainer/modeling_rules/<Pack>__<Rule>.xif`) looks like:

```
[MODEL: dataset = microsoft_defender_for_cloud_raw]
filter properties != null
| alter
    xdm.alert.name        = json_extract_scalar(properties, "$.alertDisplayName"),
    xdm.alert.severity    = json_extract_scalar(properties, "$.severity"),
    xdm.source.user.username = json_extract_scalar(properties, "$.extendedProperties.user name"),
    xdm.source.process.pid   = to_number(json_extract_scalar(properties, "$.extendedProperties.process id")),
    ...
```

To reverse-engineer what to emit, extract:
- **The gate** — the leading `filter` (→ §2).
- **The source columns** — every bare identifier or `json_extract_scalar(<col>, …)` /
  `<col> -> <path>` on the RHS. These are the column names the rule reads; your CEF
  extensions (= schema field names) must match them.
- **The JSON paths** — `$.<path>` inside each `json_extract_*`. These become the
  dotted-leaf field names (`<col>.<path>`) your schema needs (→ §4).
- **Value-type expectations** — `to_number(…)`, `to_integer(…)` → that leaf must be
  numeric or the conversion yields null. `arraycreate(…)` / `json_extract_array` →
  array-shaped.
- **The preset** — `model="Endpoint"` vs unified `xdm.*` (→ §5).
- **Multiple `[MODEL …]` / filter blocks** — a rule can model several datasets or
  branch by gate value; only the block whose `dataset=` matches and whose filter your
  event satisfies will fire.

Quick extraction one-liner pattern (adapt as needed):
```python
import re
xif = open("scripts/maintainer/modeling_rules/<Pack>__<Rule>.xif").read()
cols = set(re.findall(r'json_extract_(?:scalar|array)\(\s*([A-Za-z_]\w*)\s*,\s*"\$\.([^"]+)"', xif))
gate = re.search(r'^\s*filter\s+(.+)$', xif, re.M)
targets = sorted(set(re.findall(r'(?:xdm|XDM)\.[A-Za-z0-9_.]+', xif)))  # what it CAN map
```

---

### 3b. Pre-flight column diff (deterministic — run before every simulate)

The most common low-mapping cause is the schema field names not matching the MR's
source columns. Diff them up front. **For CEF sources especially: the schema field
name IS the CEF wire key the broker extracts** (`cs1`, `src`, `dpt`, `act`, `duser`,
`cefDeviceEventClassId`, …), never the vendor's logical name. A
logical-name schema (Imperva WAF's `alertSeverity`, `destinationIP`, `httpMethod`) maps
only **1 of 16** fields until they are renamed to the CEF keys the rule reads.

```python
import re, yaml, pathlib
def mr_source_cols(xif_path):
    t = pathlib.Path(xif_path).read_text()
    cols = set()
    for rhs in re.findall(r'xdm\.[A-Za-z0-9_.]+\s*=\s*(.+?)[,;]\s*$', t, re.M):
        cols |= set(re.findall(r'\b([a-z][A-Za-z0-9_]*)\b', rhs))   # bare RHS identifiers
    cols |= set(re.findall(r'json_extract_(?:scalar|array)\(\s*([A-Za-z_]\w*)', t))
    return cols   # NOTE: still includes XQL builtins, ~= regex string literals
                  # (aws/linux/win…), and intermediate `alter X = …` vars — filter
                  # those out cognitively; the rule's real raw columns are the rest.
sf = {f["name"] for f in yaml.safe_load(pathlib.Path("<…>/data_source.yaml").read_text())["fields"]}
cols = mr_source_cols("scripts/maintainer/modeling_rules/<Pack>__<Rule>.xif")
print("PRESENT:", sorted(c for c in cols if c in sf))
print("MISSING:", sorted(c for c in cols if c not in sf))
```

The extractor over-reports (it can't tell a raw column from a `~=` string literal or
an intermediate alter var) — that's the cognitive half: scan MISSING and keep the
ones that are genuinely vendor columns. If the genuine overlap is poor (Imperva: 0),
**rebuild the schema fields to the MR's column names** before wasting a simulate cycle.

## 4. JSON-composite mechanics (`_build_nested` in `xlog/app/dynamic_schema.py`)

When a rule reads `json_extract_scalar(properties, "$.extendedProperties.user name")`,
the wire must carry `properties={"extendedProperties":{"user name":"…"}}` as a JSON
string. The generator builds this **only from dotted-leaf fields** in the schema:

- A **composite parent** is a top-level field that is `type: json` OR has dotted-leaf
  children.
- A **leaf** is a field whose name contains `.`: `properties.extendedProperties.user name`.
  The part after the first `.` is the path *relative to the composite*; `_build_nested`
  splits on `.` and folds each leaf into the parent's nested object. Spaces in keys are
  fine (`"user name"` is a valid JSON key). The leaves do **not** appear as separate
  flat extensions — they materialize as one `properties={…}` value.

**Therefore the most common low-mapping fix:** the schema has the composite as
`type: json, example: {}` (empty) with no `properties.*` leaves → the generator emits
`properties={}` → every `json_extract` returns null → xdm=0. Add the leaves matching
the rule's `$.<path>` set: parse the `.xif` for every `json_extract_scalar(<composite>, "$.<path>")`
call and insert the missing `<composite>.<path>` leaves (numeric leaves inferred from
`to_number()` wrappers).

**Verify the synthesis locally before deploying** (no deployed install needed):
```python
import yaml
import sys; sys.path.insert(0, "xlog")
from app.dynamic_schema import generate_records_with_override
fields = yaml.safe_load(open("<…>/data_source.yaml").read())["fields"]
rec = generate_records_with_override(1, fields)[0]
print(rec["properties"])   # should be a rich nested dict, not {}
```
And measure the wire size if you suspect bloat (informational — UDP fragments fine):
```python
from app.override_sender import _flatten_extension
print(len(_flatten_extension(rec)))
```

**Caveat that cost real hours:** the schema's leaves can sit under the *wrong* parent
(e.g. top-level `ExtendedProperties.*` while the installed rule reads
`properties.extendedProperties.*`). The generator + schema can both be perfect and the
landed JSON valid, yet xdm=0 — because the **installed** rule differs from the snapshot
you analyzed. When every mechanical check passes, get the tenant's actual rule.

---

## 5. The Endpoint preset

Rules headed `[MODEL: dataset=X, model="Endpoint"]` map to `XDM.Endpoint.*` (e.g.
`XDM.Endpoint.original_event_sub_type = Type`), not unified `xdm.*`. Consequences:
- `datamodel dataset=X | comp count()` returns rows (the rule binds), but
  `fields xdm.*` is all null — you queried the wrong namespace.
- `fields xdm.endpoint.*` / `XDM.Endpoint.*` frequently errors `unknown field` in the
  ad-hoc `datamodel` surface — the Endpoint preset isn't reliably enumerable there.
- Practical upshot: these sources *bind and map* but are hard to **quantify** via
  standard XQL. Treat as a known verification gap; don't mark validated on a count you
  can't produce. (AWS GuardDuty is the canonical example.)

---

## 6. Disproven hypotheses — don't re-chase without evidence

Each of these was a plausible cause that turned out wrong on real sources. If you
suspect one, prove it with a query first:
- **UDP MTU truncation** — UDP fragments + reassembles; a 2.5 KB event (Cloud Logging)
  maps 52 fields. Not a truncation problem.
- **CEF space-mangling of JSON** — the broker reads an extension value until the next
  ` <word>=`, so JSON containing spaces (`"Client IP Address"`) lands intact and valid.
- **`compact=true` dropping fields** — `_compact_schema_payload` only strips
  description/example/logo; it keeps `name`+`type` for **all** fields. Lossless for the
  override.
- **Generator emitting `{}`** — `generate_records_with_override` builds correct nested
  JSON whenever the dotted leaves exist (verify locally, §4).
- **Materialization timing** — `datamodel` applies the rule at query time; counts are
  stable within minutes. A persistent 0 is not "give it time."

When all of the above are ruled out and the analysis is airtight but xdm is still 0,
the residual explanation is **installed-rule-vs-snapshot drift** (§4 caveat).
