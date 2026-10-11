# `scripts/` — maintainer research + build tooling

This directory contains **maintainer-side scripts**. They are NOT part of the customer-facing Phantom runtime, NOT installed on customer machines, and NOT triggered by any customer action.

**Repo-wide rules live in the [root CLAUDE.md](../CLAUDE.md)**. This file holds only conventions LOCAL to `scripts/`.

## What goes here, what does NOT

| Belongs in `scripts/` | Does NOT belong in `scripts/` |
|---|---|
| Research tools that harvest data once per upstream refresh | Anything that runs at customer install/upgrade time |
| YAML/bundle builders that produce committed artifacts | Anything customers' running stack imports at runtime |
| One-shot migrations + cohort cleanups | Service code (use `mcp/agent/`, `bundles/spark/mcp/`, `xlog/`) |
| Validation + audit checks run in CI (the validators that gate builds) | Tooling that bakes into a Docker image |

If a script is consumed by service-runtime code, the runtime code is broken. Refactor the dependency out.

## Modeling-rule extraction is RESEARCH, not pipeline

Modeling-rule extraction is a one-off research step to harvest raw field information at scale: download the modeling rules, check the field mapping, and write the result into `data_source.yaml`. It is not part of the pipeline for adding data sources to the marketplace, and nothing in Phantom depends on it at runtime.

Concrete contract:

1. **The artifact runtime consumes** is `bundles/spark/data-sources/*/data_source.yaml` (vendor-faithful field schemas + descriptions). Plus the `bundles/spark/connectors/cortex-content/baked/` tree for logos and pack metadata. Both are committed to git, baked into the agent image at CI build time.

2. **The path to producing those YAMLs** runs through `scripts/`:
   - `fetch_demisto_modeling_rules.py` — fetches upstream demisto/content
   - `extract_xif_alter_intermediates.py` — parses .xif modeling-rule files for regex `extract` patterns to discover vendor-emitted field names
   - `extract_cortex_fields_into_yamls.py` — reads cortex schema.json + writes per-pack `fields[]`
   - `refresh_cortex_baked_catalog.py` — rebakes the baked tree (logos, manifest)
   - `migrate_missing_packs.py` — fills gaps when upstream adds new packs

3. **The runtime never re-runs these scripts.** No "live" XSIAM/demisto fetch from a customer install. Customer downloads the agent image; image has baked YAMLs; runtime reads YAMLs. Period.

4. **Modeling rules are time-saving research, not engineering.** Adding a new vendor data source does NOT require a modeling rule to exist anywhere. The minimum is hand-curated `data_source.yaml` with the right `fields[]`. Modeling rules are just a shortcut for harvesting those `fields[]` at scale from public Cortex / Splunk / Sentinel / Elastic content.

If you add a new vendor and there's no modeling rule available, you hand-curate the YAML from vendor docs. If a modeling rule IS available, you use the extraction script to bootstrap. Either way the YAML is the only thing runtime cares about.

## Cross-vendor research backlog

The same extract-fields-from-public-content approach applies to vendors beyond Cortex. Future research targets in priority order:

| Source | What to extract | Tool sketch | Status |
|---|---|---|---|
| **Splunk** | Public Splunk app + addon `props.conf` + `transforms.conf` files declare `EXTRACT-*`, `REPORT-*`, `FIELDALIAS-*` → reveals raw fields per vendor | Crawl `https://splunkbase.splunk.com/` listings, download apps, parse `default/props.conf` | TODO |
| **Elastic / Sentinel** | ECS data streams + Sentinel data connectors specify ingestion mappings | Public ECS YAML at `github.com/elastic/integrations/` / Sentinel data connectors at `github.com/Azure/Azure-Sentinel/` | TODO |
| **Vendor official docs** | Many vendors publish field reference tables (FortiGate field reference, Palo Alto LogFormat reference, etc.) | Per-vendor scraper or LLM-assisted extraction | partial (vendor-doc fallback covers the top 30 vendors) |
| **Logstash / Beats** | Filebeat + Logstash community grok patterns reveal raw fields for syslog vendors | github.com/logstash-plugins/, elastic/beats | TODO |

When inventorying a new source:

1. Add the research script under `scripts/` (e.g. `scripts/research/extract_splunk_props_fields.py`).
2. The script's OUTPUT is a delta against existing `data_source.yaml` files — either patches existing YAMLs (more `fields[]`, sourced from Splunk addon) or creates new ones for vendors we don't yet cover.
3. Write the changes to `bundles/spark/data-sources/*/data_source.yaml`, commit, ship as a normal release.
4. **Do not** add Splunk/Elastic/Sentinel as a runtime dependency. Runtime only ever reads our YAMLs.

## How to tell whether a new script belongs here

Ask: *"Does a customer install ever run this code?"*

- **No** → `scripts/`. Documentation what the output is and where it lands in the runtime tree.
- **Yes** → NOT `scripts/`. Pick the right runtime module: `mcp/agent/`, `bundles/spark/mcp/`, `bundles/spark/connectors/<id>/`, or `xlog/`.

If the answer is *"only if the operator runs it manually"* — still `scripts/`. Operator-invoked maintenance ≠ customer-runtime.

## Script catalogue

| Script | Purpose | Cadence |
|---|---|---|
| `refresh_cortex_baked_catalog.py` | Re-bake `bundles/spark/connectors/cortex-content/baked/` from upstream demisto/content | Manual, ~quarterly |
| `fetch_demisto_modeling_rules.py` | Download .xif modeling rules from demisto/content | Manual, paired with refresh |
| `extract_xif_alter_intermediates.py` | Parse .xif files for regex `extract` patterns to harvest vendor field names | Paired with refresh |
| `extract_cortex_fields_into_yamls.py` | Walk cortex schema.json + write per-pack `fields[]` into YAMLs | Paired with refresh |
| `migrate_bundled_packs_to_yaml.py` | One-shot migration of bundled packs to YAML format | Done; archived |
| `migrate_missing_packs.py` | Idempotent: add YAML for any baked pack we don't yet cover | Run after each refresh |
| `extend_data_source_fields.py` | Vendor-doc field augmentation for top 30 vendors | Done; archived |
| `source_vendor_svgs.py` | Generate `vendor_svgs/<vk>_light.svg` files for the baked tree | Manual, when adding vendor logos |
| `e2e_*.py` | End-to-end harnesses (one-shot test orchestration) | Per-release, manual |
| `classify_transport_intent.py` | Categorize each bundled pack by transport (raw_log / raw_json / direct) | Paired with fetch |
| `categorize_pack_ingest.py` | Transport-categorization variant (S1/S2/S4) — kept for reference | Paired with fetch |
| `organize_rules_by_dataset.py` | Group fetched PR+MR pairs by dataset name into `scripts/maintainer/rules_by_dataset/{raw_log_based,raw_json_based,direct_mapped}/<dataset>/` with per-dataset manifest documenting the operator-side broker-applet config required | Auto-called by fetch_demisto_modeling_rules.py |
| `validate_*.py`, `check_*.py` | CI validators (gate builds) | Auto, on every PR |

## `scripts/maintainer/rules_by_dataset/` — dataset-grouped rules + operator setup docs

After every fetch the rules are reorganized into per-dataset subfolders so the operator can see at a glance which packs require **manual broker-applet configuration** before simulated logs will land in the right Cortex dataset.

Three categories:

| Folder | Trigger | Operator setup |
|---|---|---|
| `raw_log_based/<dataset>/` | PR or MR references `_raw_log` | Operator must add a **Broker VM Syslog Applet** with the pack's `vendor` + `product` + a dedicated source port. Without this, simulated logs land in `unknown_unknown_raw` and the parsing rule never fires. |
| `raw_json_based/<dataset>/` | PR or MR references `_raw_json` | Operator must configure the XSIAM HTTP Collector with the matching vendor/product source tag. (Currently zero packs in this category from public content.) |
| `direct_mapped/<dataset>/` | Neither token referenced | Works via CEF auto-extraction OR HTTP-collector typed-column ingestion. Usually no extra setup beyond standard Cortex ingestion. |

Each per-dataset folder contains `parsing.xif`, `modeling.xif`, and `manifest.json`. The manifest's `operator_setup_notes` field carries the exact remediation text the operator needs to follow.

Scripts marked "Done; archived" stay in the repo as documentation of the migration — they don't get re-run. Re-running them on a current tree should be a no-op (idempotent by design).

## A note on `validate_*.py` + `check_*.py`

These are the exception to the "maintainer-only" rule. They run in CI (per `.github/workflows/`) to gate PRs from landing broken state. They're still NOT customer-runtime — but they're not one-off either. Cadence: every push.
