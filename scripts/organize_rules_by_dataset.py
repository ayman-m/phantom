#!/usr/bin/env python3
"""Organize fetched parsing + modeling rules by dataset name.

# Why this exists

The flat `scripts/maintainer/{modeling,parsing}_rules/` folders make it
hard to see *which packs use which dataset* and even harder to spot the
operator-side configuration each pack requires before logs will land in
Cortex correctly.

This script groups every PR + MR by the dataset name they share
(PR's `target_dataset="X"` matches MR's `[MODEL: dataset=X]`) and writes
them into a per-dataset subfolder under
`scripts/maintainer/rules_by_dataset/`. Each subfolder is categorized
as:

  • **raw_log_based** — the PR or MR references `_raw_log`. These
    require a **Broker VM Syslog Applet pre-configured with the
    pack's vendor + product + a dedicated port** before simulated logs
    will be routed to the correct dataset. Without that applet, logs
    silently land in `unknown_unknown_raw` and the modeling rule never
    fires.

  • **raw_json_based** — the PR or MR references `_raw_json` (the
    HTTP-collector raw-JSON pattern). Requires an XSIAM HTTP collector
    configured with the matching vendor/product source tag.

  • **direct_mapped** — neither `_raw_log` nor `_raw_json` is
    referenced. The pack's data arrives via CEF auto-extraction OR
    HTTP-collector with typed-column mapping. Usually no operator
    setup beyond standard XSIAM ingestion config.

# Output structure

```
scripts/maintainer/rules_by_dataset/
├── _manifest.json                 # roll-up summary
├── raw_log_based/                 # needs broker applet
│   ├── cisco_asa_raw/
│   │   ├── parsing.xif
│   │   ├── modeling.xif
│   │   └── manifest.json
│   └── ...
├── raw_json_based/                # needs HTTP collector applet
│   └── ...
└── direct_mapped/                 # works via CEF auto-route / typed cols
    └── ...
```

# Run

    python3 scripts/organize_rules_by_dataset.py

Re-runnable. Cleans the `rules_by_dataset/` tree on each run so stale
entries don't accumulate. Source data: the existing flat folders +
each pack's `bundles/spark/data-sources/*/data_source.yaml` for vendor/
product/pack_name lookups.

This script is also called from the tail of
`fetch_demisto_modeling_rules.py` so the organized tree stays in sync
with every fetch.
"""
from __future__ import annotations

import json
import re
import shutil
from collections import defaultdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
MAINTAINER = REPO_ROOT / "scripts" / "maintainer"
MODELING_ROOT = MAINTAINER / "modeling_rules"
PARSING_ROOT = MAINTAINER / "parsing_rules"
OUTPUT_ROOT = MAINTAINER / "rules_by_dataset"
BUNDLE_ROOT = REPO_ROOT / "bundles" / "spark" / "data-sources"

# ─── Regex extractors ────────────────────────────────────────────

# PR header line: [INGEST:vendor="X", product="Y", target_dataset="Z", ...]
# vendor/product/target_dataset are extracted independently to tolerate
# any field order.
RE_INGEST_VENDOR = re.compile(r'vendor\s*=\s*"([^"]*)"')
RE_INGEST_PRODUCT = re.compile(r'product\s*=\s*"([^"]*)"')
RE_INGEST_DATASET = re.compile(r'target_dataset\s*=\s*"([^"]*)"')

# MR block: [MODEL: dataset=X] OR [MODEL: dataset="X"] OR
#           [MODEL: dataset ="X"]
RE_MODEL_DATASET = re.compile(
    r'\[MODEL\s*:\s*dataset\s*=\s*"?([a-zA-Z0-9_]+)"?',
    re.IGNORECASE,
)

RE_RAW_LOG = re.compile(r"\b_raw_log\b")
RE_RAW_JSON = re.compile(r"\b_raw_json\b")

# CEF-shape detector. When a direct_mapped MR references
# columns that look like ArcSight CEF spec fields (`rt`, `src`, `dst`,
# `act`, `cs1`-`cs6`, etc.), the pack is CEF-routable through the
# broker — Phantom emits `CEF:0|vendor|product|...|<extensions>` and
# the broker auto-extracts k=v pairs into typed columns matching the
# CEF dictionary. The MR reads from those typed columns directly.
_CEF_DICT = frozenset({
    "rt", "dst", "dpt", "src", "spt", "act", "dvc", "dvchost",
    "dvcpid", "dproc", "sproc", "dmac", "smac", "shost", "dhost",
    "proto", "duser", "suser", "dpriv", "spriv", "dntdom", "sntdom",
    "request", "requestMethod", "requestClientApplication",
    "requestContext", "requestCookies", "msg", "externalId", "app",
    "deviceAction", "deviceDirection", "deviceExternalId",
    "deviceFacility", "deviceProcessName",
    "deviceCustomDate1", "deviceCustomDate2",
    "cn1", "cn2", "cn3", "cn1Label", "cn2Label", "cn3Label",
    "cs1", "cs2", "cs3", "cs4", "cs5", "cs6",
    "cs1Label", "cs2Label", "cs3Label", "cs4Label",
    "cs5Label", "cs6Label",
    "flexString1", "flexString2",
    "flexString1Label", "flexString2Label",
    "flexNumber1", "flexNumber2",
    "flexNumber1Label", "flexNumber2Label",
    "cefVersion", "cefDeviceVendor", "cefDeviceProduct",
    "cefDeviceVersion", "cefDeviceEventClassId", "cefName",
    "cefSeverity",
    "cat", "reason", "outcome", "fname", "fileName", "filePath",
    "fileHash", "fileType", "fsize", "oldFileName",
})

# Word-boundary token extractor — looks for identifiers that could be
# column references in an MR. Catches `src`, `cs1Label`, `requestMethod`,
# etc. without grabbing strings inside quotes or comments. Good enough
# for the heuristic; not a full XQL parser.
_IDENTIFIER = re.compile(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\b")


def _looks_cef_mr(text: str) -> tuple[bool, int]:
    """Return (is_cef, dict_hit_count). True when ≥3 distinct CEF
    dictionary tokens appear as identifiers in the MR body.
    Calibrated against Checkpoint (50+ hits), AWS_WAF (httpRequest-
    based, ~2 hits), AbnormalSecurity (0 hits). The 3-hit threshold
    cleanly separates."""
    if not text:
        return False, 0
    seen = set()
    for m in _IDENTIFIER.finditer(text):
        token = m.group(1)
        if token in _CEF_DICT:
            seen.add(token)
    return len(seen) >= 3, len(seen)


# ─── YAML header reader (for pack metadata) ──────────────────────

def _read_yaml_header(path: Path) -> dict[str, str]:
    """Top-level scalar parse to grab pack_name, vendor, product, etc.
    Avoids a PyYAML dependency."""
    h: dict[str, str] = {}
    for line in path.read_text(errors="replace").split("\n"):
        if not line or line.startswith(" "):
            continue
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        val = val.strip().strip('"').strip("'")
        if key in ("pack_name", "rule_name", "dataset_name", "vendor",
                   "product", "id"):
            h[key] = val
        if {"pack_name", "rule_name", "dataset_name",
            "vendor", "product"}.issubset(h):
            break
    return h


def _build_pack_lookup() -> dict[str, dict[str, str]]:
    """Walk every bundled data_source.yaml; return
    {dataset_name: {pack_name, vendor, product, rule_name, ...}}"""
    out: dict[str, dict[str, str]] = {}
    for d in sorted(BUNDLE_ROOT.iterdir()):
        if not d.is_dir():
            continue
        y = d / "data_source.yaml"
        if not y.exists():
            continue
        h = _read_yaml_header(y)
        ds = h.get("dataset_name")
        if not ds:
            continue
        # If we've seen this dataset before (some packs have multiple
        # entries that target the same dataset), keep the first one.
        out.setdefault(ds, h)
    return out


# ─── PR/MR scanning ──────────────────────────────────────────────

def _scan_parsing_rules() -> dict[str, dict[str, Any]]:
    """Return {dataset: {file: Path, vendor, product, uses_raw_log,
    uses_raw_json, text}} for every parsing rule on disk that declares
    a target_dataset."""
    out: dict[str, dict[str, Any]] = {}
    for f in sorted(PARSING_ROOT.glob("*.xif")):
        text = f.read_text(errors="replace")
        ds_match = RE_INGEST_DATASET.search(text)
        if not ds_match:
            # Some PR files don't have an INGEST header (e.g. they
            # contain only [RULE: ...] blocks). Skip — they get linked
            # via the MR's [MODEL: dataset=...] indirectly if needed.
            continue
        ds = ds_match.group(1)
        v_match = RE_INGEST_VENDOR.search(text)
        p_match = RE_INGEST_PRODUCT.search(text)
        out[ds] = {
            "file": f,
            "vendor": v_match.group(1) if v_match else "",
            "product": p_match.group(1) if p_match else "",
            "uses_raw_log": bool(RE_RAW_LOG.search(text)),
            "uses_raw_json": bool(RE_RAW_JSON.search(text)),
            "text": text,
        }
    return out


def _scan_modeling_rules() -> dict[str, list[dict[str, Any]]]:
    """Return {dataset: [{file: Path, uses_raw_log, uses_raw_json,
    text}]}. One MR file can declare multiple [MODEL: dataset=X] blocks
    (CheckpointFirewall has 5), so each dataset gets the same file
    referenced from its own entry."""
    out: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for f in sorted(MODELING_ROOT.glob("*.xif")):
        text = f.read_text(errors="replace")
        datasets_in_file = sorted(set(RE_MODEL_DATASET.findall(text)))
        if not datasets_in_file:
            continue
        for ds in datasets_in_file:
            out[ds].append({
                "file": f,
                "uses_raw_log": bool(RE_RAW_LOG.search(text)),
                "uses_raw_json": bool(RE_RAW_JSON.search(text)),
                "text": text,
            })
    return out


# ─── Per-dataset folder writer ───────────────────────────────────

OPERATOR_NOTES = {
    "raw_log_based": (
        "This data source uses `_raw_log`-based parsing. Cortex's parsing "
        "rule reads from `_raw_log` to populate `_json` (or directly to "
        "extract XDM fields), and the modeling rule does `regextract`/"
        "`json_extract_scalar` on `_raw_log`. For simulated logs sent from "
        "Phantom to land in this dataset, **the operator must add a Broker "
        "VM Syslog Applet pre-configured with the matching vendor + "
        "product + a dedicated source port**. Without that applet, logs "
        "are tagged `unknown/unknown` and routed to `unknown_unknown_raw` "
        "— the parsing rule never fires. \n\n"
        "Setup: XSIAM → Settings → Configurations → Data Broker → Applets "
        "→ Add Applet (Syslog) → Vendor = `{vendor}`, Product = `{product}`, "
        "Port = (operator picks an unused port, e.g. 1514, 1515, ...). "
        "Phantom must then send to that port — current default is 514, "
        "which is reserved for the ASA applet."
    ),
    "raw_json_based": (
        "This data source uses `_raw_json`-based ingestion (XSIAM HTTP "
        "collector). The operator must configure an XSIAM HTTP Collector "
        "with the source-tag mapping to vendor=`{vendor}`, product=`{product}`. "
        "Phantom emits JSON POST events to the collector URL; without the "
        "right source tag, events land in `phantom_logs_raw`."
    ),
    "direct_mapped_cef": (
        "This data source's modeling rule reads CEF-shaped columns (rt, "
        "src, dst, spt, dpt, cs1-6, act, etc.). Phantom emits CEF over "
        "syslog (`CEF:0|{vendor}|{product}|...|<extensions>`) — the broker "
        "auto-extracts CEF k=v pairs into typed columns matching the CEF "
        "dictionary, and the broker routes to this dataset via the CEF "
        "header's vendor/product. Usually NO operator-side broker config "
        "is required beyond standard CEF ingestion."
    ),
    "direct_mapped_other": (
        "This data source has typed-column data that doesn't look like "
        "CEF (columns are camelCase API fields, JSON sub-objects, etc.). "
        "Most likely arrives via the XSIAM HTTP Collector with a source "
        "tag mapped to vendor=`{vendor}`, product=`{product}`, or via a "
        "vendor-specific XDR connector pull. Phantom can POST JSON to the "
        "HTTP collector; the operator must configure the collector's "
        "source tag to land events in this dataset."
    ),
}


def _categorize(uses_raw_log: bool, uses_raw_json: bool,
                mr_text: str) -> tuple[str, dict[str, Any]]:
    """Return (category, extra_meta)."""
    # raw_json takes precedence when both appear (rare).
    if uses_raw_json:
        return "raw_json_based", {}
    if uses_raw_log:
        return "raw_log_based", {}
    # Direct-mapped: split CEF vs other based on MR column references.
    is_cef, hits = _looks_cef_mr(mr_text or "")
    if is_cef:
        return "direct_mapped_cef", {"cef_dict_hits": hits}
    return "direct_mapped_other", {"cef_dict_hits": hits}


def _write_dataset_folder(
    dataset: str,
    pr: dict[str, Any] | None,
    mrs: list[dict[str, Any]],
    pack_meta: dict[str, str],
) -> dict[str, Any]:
    """Write per-dataset folder with parsing.xif + modeling.xif +
    manifest.json. Returns the manifest entry."""
    uses_raw_log = (
        (pr and pr.get("uses_raw_log"))
        or any(m.get("uses_raw_log") for m in mrs)
    )
    uses_raw_json = (
        (pr and pr.get("uses_raw_json"))
        or any(m.get("uses_raw_json") for m in mrs)
    )
    mr_combined_text = "\n".join(m.get("text", "") for m in mrs)
    category, extra = _categorize(
        bool(uses_raw_log), bool(uses_raw_json), mr_combined_text
    )

    out_dir = OUTPUT_ROOT / category / dataset
    out_dir.mkdir(parents=True, exist_ok=True)

    # Copy PR (one file at most per dataset)
    if pr:
        shutil.copyfile(pr["file"], out_dir / "parsing.xif")
        pr_filename = pr["file"].name
    else:
        pr_filename = None

    # Copy MR — if multiple MR files map to the same dataset (unusual
    # but possible — different pack versions), suffix with a counter.
    mr_filenames: list[str] = []
    if len(mrs) == 1:
        shutil.copyfile(mrs[0]["file"], out_dir / "modeling.xif")
        mr_filenames.append(mrs[0]["file"].name)
    elif len(mrs) > 1:
        for i, m in enumerate(mrs):
            shutil.copyfile(m["file"], out_dir / f"modeling_{i}.xif")
            mr_filenames.append(m["file"].name)

    # Resolve vendor + product. Prefer parsing-rule INGEST line; fall
    # back to YAML metadata.
    vendor = (pr.get("vendor") if pr else "") or pack_meta.get("vendor", "")
    product = (pr.get("product") if pr else "") or pack_meta.get("product", "")

    operator_notes = OPERATOR_NOTES[category].format(
        vendor=vendor or "<vendor>",
        product=product or "<product>",
    )

    manifest = {
        "dataset": dataset,
        "pack_name": pack_meta.get("pack_name", ""),
        "vendor": vendor,
        "product": product,
        "category": category,
        "parsing_rule_present": pr is not None,
        "parsing_rule_source_filename": pr_filename,
        "modeling_rule_present": bool(mrs),
        "modeling_rule_source_filenames": mr_filenames,
        "uses_raw_log": bool(uses_raw_log),
        "uses_raw_json": bool(uses_raw_json),
        "operator_setup_required": category != "direct_mapped_cef",
        "operator_setup_notes": operator_notes,
        **extra,
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    return manifest


# ─── Main ────────────────────────────────────────────────────────

def main() -> int:
    if not MODELING_ROOT.exists() or not PARSING_ROOT.exists():
        print(f"ERROR: expected {MODELING_ROOT} + {PARSING_ROOT} to exist. "
              f"Run fetch_demisto_modeling_rules.py first.")
        return 1

    # Wipe stale tree so re-runs produce a clean state.
    if OUTPUT_ROOT.exists():
        shutil.rmtree(OUTPUT_ROOT)
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)

    print("=== Organize rules by dataset ===")
    pack_lookup = _build_pack_lookup()
    print(f"  packs with YAML metadata: {len(pack_lookup)}")

    parsing_by_ds = _scan_parsing_rules()
    print(f"  parsing rules indexed (with target_dataset): {len(parsing_by_ds)}")

    modeling_by_ds = _scan_modeling_rules()
    print(f"  unique datasets in modeling rules: {len(modeling_by_ds)}")
    print()

    # Union of datasets from PR + MR — write folders for everything
    all_datasets = sorted(set(parsing_by_ds) | set(modeling_by_ds))
    print(f"  total unique datasets to organize: {len(all_datasets)}")
    print()

    summary: dict[str, list[dict[str, Any]]] = {
        "raw_log_based": [],
        "raw_json_based": [],
        "direct_mapped_cef": [],
        "direct_mapped_other": [],
    }

    for ds in all_datasets:
        pr = parsing_by_ds.get(ds)
        mrs = modeling_by_ds.get(ds, [])
        pack_meta = pack_lookup.get(ds, {})
        if not pack_meta:
            # No matching YAML pack — skip (or could still organize as
            # "orphan"). For now we record it but skip the folder write,
            # since lacking pack metadata means we can't compose useful
            # operator notes.
            summary.setdefault("_orphans_no_yaml", []).append(ds)
            continue
        entry = _write_dataset_folder(ds, pr, mrs, pack_meta)
        summary[entry["category"]].append({
            "dataset": ds,
            "pack_name": entry["pack_name"],
            "vendor": entry["vendor"],
            "product": entry["product"],
        })

    # Top-level summary manifest
    overview = {
        "_meta": {
            "generated_by": "scripts/organize_rules_by_dataset.py",
            "source_modeling": str(MODELING_ROOT.relative_to(REPO_ROOT)),
            "source_parsing": str(PARSING_ROOT.relative_to(REPO_ROOT)),
        },
        "counts": {
            "raw_log_based": len(summary["raw_log_based"]),
            "raw_json_based": len(summary["raw_json_based"]),
            "direct_mapped_cef": len(summary["direct_mapped_cef"]),
            "direct_mapped_other": len(summary["direct_mapped_other"]),
            "orphans_no_yaml": len(summary.get("_orphans_no_yaml", [])),
            "total": sum(
                len(v) for k, v in summary.items() if not k.startswith("_")
            ),
        },
        "by_category": {
            k: v for k, v in summary.items()
        },
    }
    (OUTPUT_ROOT / "_manifest.json").write_text(
        json.dumps(overview, indent=2, sort_keys=True) + "\n"
    )

    print("=== Done ===")
    for cat, items in summary.items():
        if cat.startswith("_"):
            print(f"  {cat:18}: {len(items)}")
        else:
            print(f"  {cat:18}: {len(items)} → {OUTPUT_ROOT / cat}")
    print(f"  manifest: {OUTPUT_ROOT / '_manifest.json'}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
