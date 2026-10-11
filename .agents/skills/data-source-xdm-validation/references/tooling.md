# Tooling & invocations

Exact paths, commands, and tool params for the data-source XDM-validation loop.
All paths are relative to the repo root unless noted.

> **Delivery doctrine (see SKILL.md):** every synthetic log goes out over **syslog/CEF**
> to the Cortex Broker — **never** an HTTP collector or API integration, no matter how the
> real vendor is collected in production. `phantom_create_data_worker` is therefore always
> `type=CEF` (or SYSLOG/LEEF) to a `udp:<broker>:514` destination. The rules map on data
> *shape*, not transport; our job is to reverse-engineer the shape and craft it as CEF.

## Access to a running install (agent API + bearer)

Everything that touches a running install goes through the agent API at its base URL
(`https://localhost:3000` for a local stack), authenticated with a bearer API key.
Keep the key in your own gitignored `.env` and never echo its value. If the install runs
on another host, forward the agent port to your machine however you normally reach it
(for example an SSH port forward) and point `AGENT_BASE` at the forwarded port.

```bash
set -a && source .env && set +a             # PHANTOM_API_KEY, …
export AGENT_BASE="https://localhost:3000"  # or your forwarded port
# … POST your prompts to $AGENT_BASE/api/chat here …
```

- The agent API accepts **bearer** auth (`Authorization: Bearer $PHANTOM_API_KEY`),
  so no interactive login is needed (and the credential guardrail forbids it anyway).
- Use `/bin/sleep` (absolute path) in long/background bashes — the background shell
  can run under a stripped PATH where bare `sleep`/`head` are "command not found".
  Avoid bash arrays/`for`-loops in `run_in_background` bashes for the same reason;
  run foreground (it auto-backgrounds but keeps full PATH).

## 1. Pull modeling + parsing rules from GitHub

`scripts/fetch_demisto_modeling_rules.py` — mirrors `.xif` rules from `demisto/content`.

```bash
python3 scripts/fetch_demisto_modeling_rules.py            # fetch both, use cache
python3 scripts/fetch_demisto_modeling_rules.py --refresh  # ignore cache
python3 scripts/fetch_demisto_modeling_rules.py --only modeling
GH_TOKEN=ghp_…   python3 scripts/fetch_demisto_modeling_rules.py   # 5000/hr vs 60/hr unauth
```

- **Sources:**
  `https://raw.githubusercontent.com/demisto/content/master/Packs/<pack>/ModelingRules/<rule>/<rule>.xif`
  (parsing rules under `…/ParsingRules/…`; if 404, it lists the pack's `ParsingRules/`
  dir via the GitHub Contents API and fetches all).
- **Output:** `scripts/maintainer/modeling_rules/<Pack>__<Rule>.xif` and
  `scripts/maintainer/parsing_rules/<Pack>__<Rule>.xif`, plus a `_manifest.json`
  per dir. Version variants land as `<Pack>__<Rule>_1_3.xif`.
- These `.xif` files are the **ground truth** for reverse-engineering, and the
  validator (`check_gate_fields_satisfied`) re-derives gates from them live.

## 2. Classify the modeling-rule gate

`scripts/maintainer/reverse_engineer_gate.py`

```bash
python3 scripts/maintainer/reverse_engineer_gate.py CiscoFirepower__CiscoFirepower__cisco_firepower_raw
```
```python
# programmatic
import importlib.util, pathlib
spec = importlib.util.spec_from_file_location("reng", "scripts/maintainer/reverse_engineer_gate.py")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
info = m.analyze("AzureFirewall__AzureFirewall__msft_azure_firewall_raw")
# → {"kind": "raw"|"function"|"meta"|"computed"|"unconditional"|"not_found",
#    "gate_field": "category", "seed_fields": [...], "values": ["AZFW…", ...]}
```
See diagnostic-playbook.md §2 for what each `kind` means and how to seed it.

## 3. Drive simulate + verify on the tenant

Send one prompt per step to the agent's `/api/chat` endpoint (server-sent events) with the
bearer, or type the same prompt into the chat page of the UI; the agent runs the MCP tools.
Two single-prompt calls are the workhorse:

```text
Simulate <Vendor>. Step 1: data_sources_get_schema <pack>/<rule>/<dataset> compact=true.
Step 2: phantom_create_data_worker type=CEF destination=the XSIAM Broker count=400 interval=1
vendor=<V> product=<P> observables_dict={"<gate>":["<value>"]} schema_override=<the COMPLETE compact fields[]>.
Report the worker_id.
```
Then, after a wait, a second call to verify:
```text
Run via xsiam_run_xql_query, 30-day window:
config timeframe = 30d | datamodel dataset = <dataset> | sort desc _time | fields xdm.* | limit 20
Count distinct non-null xdm.* fields across all rows. Output exactly: 'xdm=<n>'.
```
- Env: `AGENT_BASE` (the agent base URL) + `PHANTOM_API_KEY` (from your `.env`).
- Verbose answers can truncate in captured output — ask for
  a terse, fixed-shape answer (`Output EXACTLY '…'`).
- Worker IDs are timestamp-second-granular → space worker creations ≥3–4s apart, or
  create them in one agent turn ("one at a time so the IDs differ").
- The agent occasionally returns `answer (0 chars)` (transient) — just retry with a
  fresh connection.

## 4. Schema-shaping scripts (patterns — adapt per batch)

These write minimal-diff YAML edits. Read them, edit the `TARGETS`/`VALIDATED`
dict at the top, re-run, then `git diff` to confirm a clean additive change.

- Dotted-leaf completion for JSON-native sources: parse the source's `.xif` for
  `json_extract_scalar/array(<composite>, "$.<path>")` and insert the missing
  `<composite>.<path>` dotted-leaf fields into the YAML (numeric leaves inferred from
  `to_number()`/`to_integer()` wrappers). Needed when a JSON-native source maps few
  fields because its composite has no leaves.
- `scripts/maintainer/gen_cloud_how_to_use.py` — authors a `how_to_use` block from the
  `.xif` (routing literal, gate, JSON-native note, field inventory). Idempotent.
- `scripts/maintainer/gen_cloud_validated.py` — promotes sources to `validated: true`:
  strips the prior `how_to_use`, sets the flag, writes a validated `how_to_use`, appends
  to the manifest. Edit its `VALIDATED` dict (dataset, vendor, product, pack, field
  count, gate, json_native, ns) with the live-verified counts, then run.

## 5. Inspect the generator + sender locally (no deployed install)

`xlog/app/dynamic_schema.py` and `xlog/app/override_sender.py` — to see exactly what
your schema produces on the wire before deploying.

```python
import sys, yaml; sys.path.insert(0, "xlog")
from app.dynamic_schema import generate_records_with_override   # (count, vendor_fields, base_datetime=None, observable_overrides=None, omit_meta=True)
from app.override_sender import _flatten_extension
fields = yaml.safe_load(open("bundles/spark/data-sources/<dir>/data_source.yaml").read())["fields"]
rec = generate_records_with_override(1, fields, observable_overrides={"category": "AZFWApplicationRule"})[0]
print(rec.get("properties"))          # composite should be a rich nested dict, not {}
print(len(_flatten_extension(rec)))   # wire-extension size (informational; UDP fragments fine)
```
- `_generate_value` priority: `observable_overrides` → declared `type` → field-name
  pattern (srcip→IP, sentbyte→int, …) → random string fallback.
- `_build_nested` folds dotted-leaf fields into composite JSON (see playbook §4).
- `override_sender` data types: **CEF** (broker routes by `CEF:0|vendor|product|…`
  header), SYSLOG (`vendor-product:` tag), LEEF, JSON. **JSON over UDP has no routing
  header → the broker drops it** — always use CEF for XSIAM broker destinations.

## 6. MCP tools (driven through the agent chat)

Defined in `bundles/spark/mcp/src/api/data_sources.py` +
`bundles/spark/mcp/src/usecase/builtin_components/`, registered in `src/main.py`.

| Tool | Key args | Returns |
|---|---|---|
| `data_sources_list` | `filter`, `limit`, `offset` | `{sources:[{id,vendor,product,dataset_name,validated}], total}` |
| `data_sources_get_schema` | `data_source_id` (`pack/rule/dataset`), `compact=true` | `{vendor,product,dataset_name,fields[],how_to_use,validated}` — **always compact=true** (lossless for override, fits the tool-result cap) |
| `phantom_create_data_worker` | `type` (CEF/SYSLOG/LEEF/JSON), `destination` (**resolve via `log_destinations_list`; never hardcode**), `count`, `interval`, `vendor`, `product`, `schema_override` (FULL `fields[]`), `observables_dict` (**list values**: `{"field":["val"]}`) | `{worker: worker_id, status}` |
| `phantom_list_workers` | — | `[{worker_id,status,type,destination,…}]` |
| `phantom_kill_worker` | `worker_id` | `{status:"stopped"}` |
| `xsiam_run_xql_query` (agent-side proxy) | `query`, `tenant_timeframe={"relativeTime":ms}` (or inline `config timeframe = 30d \| …`) | `{number_of_results, rows:[{_time,_raw_log,xdm.*}]}` |
| `run_xql_query` (xsiam connector DIRECT, port 9000) | **`query` ONLY** — a single flat string; window goes inline via `config timeframe = …` | `{reply:{status, number_of_results, results:{data:[…]}}}` |

> **Gotcha that produces a false all-zero result — the connector-direct
> `run_xql_query` takes a SINGLE flat `{"query": "..."}` argument.** Passing the
> agent-side wrapper shape `{"request": {"query": …, "tenant_timeframe": …}}` to
> the connector (port 9000) is rejected by its Pydantic model with
> `1 validation error … Unexpected keyword argument`, and the error comes back
> *inside* the tool result (`isError:true`) — so a naive parser reads it as
> "0 results" and every dataset looks unmapped even when events landed and XDM
> saturated. Always send the flat `query` with `config timeframe` inline, and
> confirm a real `reply.results.data` came back before trusting a 0. Then, per
> §3, count **distinct `xdm.*` across ≥20 rows**, never `limit 1` (one synthetic
> event can map 0 fields while the dataset's recent events map 40, as on Azure WAF).
> `scripts/maintainer/wide_verify_datasets.py` bakes both rules in; use it to
> re-verify any dataset cohort.

> **XQL has a daily compute-unit quota — and an exhausted quota reads as "0 rows".**
> The tenant caps daily XQL Compute Units (`max_quota`, resets 00:00 UTC). When
> spent, `run_xql_query` returns `{"error":"Error running XQL: Server error 500: …
> QUOTA_EXCEEDED … remaining Compute Units (0.0) …","success":false}` — with MCP
> `isError:false`, so a naive parser reads it as an empty result (same failure
> family as the arg-shape bug). A large multi-vendor re-verify plus a
> few probe rounds can exhaust it in one session. **Budget queries:** prefer ONE wide pass (`limit 20`, distinct-xdm)
> over many small ones; don't re-query a dataset row-by-row when a single union
> pass answers it. On a sudden all-zero across datasets that mapped minutes ago,
> **dump the raw response before concluding "0"** — it's almost always quota, not
> a mapping regression. (Generation-side checks via `xlog/app/*` are quota-free —
> use them to inspect what an event carries when you can't query the tenant.)

## 7. Validate + ship

```bash
# the two checks that gate the validated set (run inside tooling/validate/)
python3 -c "import validate_all as v; \
  [print(('PASS' if c.ok else 'FAIL'), c.name, c.detail[:120]) \
   for c in (v.check_validated_data_sources_manifest(), v.check_gate_fields_satisfied())]"
```
- `check_validated_data_sources_manifest` — the set flagged `validated: true` in the
  bundled YAMLs MUST equal `tooling/validate/validated_data_sources.txt`.
- `check_gate_fields_satisfied` — for each validated, gated source, the YAML's gate
  field must carry an `example` in the rule's accepted value set (re-derived live from
  the `.xif`). After validating a gated source, set that `example`.
- Pre-deploy gate before pushing: `cd mcp/agent && npx tsc --noEmit && npm run lint &&
  npm run build` for TS, and `cd bundles/spark/mcp && PYTHONPATH=$PWD/src python3 -m
  pytest tests/ -x` for the YAML loader (the data_source.yaml files are test-loaded).
- The customer-facing surfaces to update when validating (per the repo's documentation
  discipline): the YAML `validated`+`how_to_use`, the manifest, `CHANGELOG.md`, and
  `mcp/agent/lib/release-notes.ts`. The validated green pill is data-driven from the
  YAML — no UI edit needed.

## Related runtime skill

`bundles/spark/mcp/skills/workflows/stream_simulate_to_xsiam.md` is the **runtime**
skill the agent uses to *execute* a simulate→verify run (encodes lessons L1–L24
plus a vendor quick-reference table). This skill is the
*authoring/debugging* companion: use this one to reverse-engineer and fix a source,
that one to drive the live run.
