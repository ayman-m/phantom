#!/usr/bin/env python3
"""Categorize each bundled data source by ingest scenario.

Reads the fetched modeling + parsing rules (from
`scripts/maintainer/{modeling,parsing}_rules/`) plus the cortex
schema.json for each pack, and tags every pack with one of:

  S1 — Generic raw syslog. Parsing rule contains
       `parse_X(_raw_log)` (or similar transform that targets
       `_raw_log`). Dataset columns: `_raw_log` + `_json`
       (or a sibling json-typed parent). Sub-keys accessed at XQL
       query time via `_json -> X.Y`. Example: Cisco ASA.

  S2 — Pre-parsed wire (CEF / LEEF / Syslog k=v). NO parsing rule.
       Dataset schema declares many typed columns directly — the
       broker / XSIAM HTTP collector parses the wire format before
       it lands in the dataset. Detected via column-name overlap
       with the canonical CEF spec (`rt`, `dst`, `dpt`, `src`,
       `spt`, `act`, `dvc`, `dvchost`, `cs1`-`cs6`, etc.).

  S3 — HTTP-collector raw JSON. Zero packs in
       the public demisto/content repo actually use the literal
       `_raw_json` token. Cortex's HTTP-collector path materializes
       the JSON body as a JSON-typed *named* column instead
       (e.g. AWS_WAF's `httpRequest`). Those packs land in S2 or
       S4 depending on whether they ship a parsing rule for time
       normalization. Kept here for completeness — current count
       is 0 by the literal heuristic.

  S4 — API / DB direct mapping. NO parsing rule + dataset schema
       declares many native typed columns + columns don't look CEF.
       Vendor API integrations (camelCase, nested JSON sub-keys
       like `computer.external_ip`). Sample: AMP, AWS-SecurityHub,
       AbnormalSecurity, MongoDBAtlas.

  ?  — Could not categorize. Either schema is missing or the
       parsing rule does something we don't recognize. The output
       enumerates these for manual review.

Output:
  - Prints a count per scenario.
  - Writes `scripts/maintainer/ingest_categorization.json` with the
    per-pack verdict + the signal that decided it.

The categorization is deterministic — re-running on the same inputs
produces the same output.
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
BUNDLE_ROOT = REPO_ROOT / "bundles" / "spark" / "data-sources"
MODELING_ROOT = REPO_ROOT / "scripts" / "maintainer" / "modeling_rules"
PARSING_ROOT = REPO_ROOT / "scripts" / "maintainer" / "parsing_rules"
SCHEMA_ROOT = (
    REPO_ROOT / "bundles" / "spark" / "connectors" / "cortex-content"
    / "baked" / "Packs"
)
OUT_PATH = REPO_ROOT / "scripts" / "maintainer" / "ingest_categorization.json"


def read_yaml_header(yaml_path: Path) -> dict[str, str]:
    header: dict[str, str] = {}
    for line in yaml_path.read_text().split("\n"):
        if not line or line.startswith(" "):
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        value = value.strip()
        if key in ("pack_name", "rule_name", "dataset_name"):
            header[key] = value
        if {"pack_name", "rule_name", "dataset_name"}.issubset(header):
            break
    return header


def load_cortex_schema(pack: str, rule: str) -> dict[str, dict[str, Any]] | None:
    """Look up the upstream `<rule>_schema.json`. Returns the
    `{dataset_name: {col: {type, is_array}}}` map, or None if the
    file isn't on disk."""
    p = SCHEMA_ROOT / pack / "ModelingRules" / rule / f"{rule}_schema.json"
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError:
        return None


# Patterns for parsing-rule body inspection.
RE_PARSE_RAW_LOG = re.compile(
    r"alter\s+_json\s*=\s*parse_\w+\s*\(\s*_raw_log\s*\)",
    re.IGNORECASE,
)
RE_RAW_JSON_REF = re.compile(r"\b_raw_json\b")
RE_RAW_LOG_REF = re.compile(r"\b_raw_log\b")

# Canonical CEF field names. If a dataset's columns are
# ≥30% of these (or ≥4 absolute hits) the pack is almost certainly
# ingesting CEF-formatted syslog (broker pre-parses → typed columns).
# Source: ArcSight CEF v25 dictionary + the most-used extensions.
_CEF_FIELDS = frozenset({
    # CEF header fields
    "cefVersion", "cefDeviceVendor", "cefDeviceProduct",
    "cefDeviceVersion", "cefDeviceEventClassId", "cefName",
    "cefSeverity",
    # Device + network
    "rt", "dst", "dpt", "src", "spt", "act", "dvc", "dvchost",
    "dvcpid", "dproc", "sproc", "dmac", "smac", "shost", "dhost",
    "proto", "in", "out", "duser", "suser", "dpriv", "spriv",
    "dntdom", "sntdom",
    # Request + app
    "request", "requestMethod", "requestClientApplication",
    "requestContext", "requestCookies", "msg", "externalId", "app",
    "deviceAction", "deviceDirection", "deviceExternalId",
    "deviceFacility", "deviceProcessName",
    "deviceCustomDate1", "deviceCustomDate2",
    # Custom integers / strings / flex (label + value pairs)
    "cn1", "cn2", "cn3", "cn1Label", "cn2Label", "cn3Label",
    "cs1", "cs2", "cs3", "cs4", "cs5", "cs6",
    "cs1Label", "cs2Label", "cs3Label", "cs4Label",
    "cs5Label", "cs6Label",
    "flexString1", "flexString2",
    "flexString1Label", "flexString2Label",
    "flexNumber1", "flexNumber2",
    "flexNumber1Label", "flexNumber2Label",
    # File + outcome
    "cat", "reason", "outcome", "fname", "fileName", "filePath",
    "fileHash", "fileType", "fsize", "oldFileName",
})


def looks_cef(cols: list[str]) -> tuple[bool, float]:
    """Return (is_cef, hit_ratio). True when the column set has ≥30%
    overlap with the CEF dictionary, or ≥4 absolute CEF matches.

    Calibrated against hand-checked CEF packs (CheckpointFirewall =
    91% on smartdefense, 86% on application_control + identity_awareness)
    and clearly-non-CEF API packs (AMP, AbnormalSecurity, AWS-SecurityHub
    all score 0-5%). The 30% threshold cleanly separates the two clusters.
    """
    if not cols:
        return False, 0.0
    hits = sum(1 for c in cols if c in _CEF_FIELDS)
    ratio = hits / len(cols)
    return (ratio >= 0.30 or hits >= 4), ratio


def classify_parsing_rule(xif_text: str) -> str:
    """Pure parsing-rule classifier. Returns one of:
        'parse_raw_log'  → parses _raw_log into _json (S1 signature)
        'raw_json'       → references _raw_json (S3 signature)
        'other'          → has a parsing rule but neither signature
    """
    if RE_PARSE_RAW_LOG.search(xif_text):
        return "parse_raw_log"
    # Order matters: _raw_json takes precedence over _raw_log because
    # some rules touch both (rare, but the HTTP-collector case is
    # what dominates when _raw_json appears at all).
    if RE_RAW_JSON_REF.search(xif_text):
        return "raw_json"
    if RE_RAW_LOG_REF.search(xif_text):
        # The rule mentions _raw_log but doesn't have the canonical
        # parse_X(_raw_log) signature — could be a regex-only S1
        # variant or a hybrid path. Tag as S1-candidate.
        return "raw_log_other"
    return "other"


def categorize_pack(
    pack: str,
    rule: str,
    dataset_name: str,
) -> dict[str, Any]:
    """Return verdict for a single pack."""
    verdict: dict[str, Any] = {
        "pack": pack,
        "rule": rule,
        "dataset_name": dataset_name,
        "scenario": "?",
        "signal": "",
        "schema_cols": None,
        "parsing_rule_files": [],
    }

    # Schema lookup
    schema = load_cortex_schema(pack, rule)
    if schema and dataset_name in schema:
        cols = list(schema[dataset_name].keys())
        verdict["schema_cols"] = cols
    else:
        cols = None

    # Parsing-rule files for this pack
    parsing_files = sorted(PARSING_ROOT.glob(f"{pack}__*.xif"))
    verdict["parsing_rule_files"] = [p.name for p in parsing_files]

    has_parsing = bool(parsing_files)
    parsing_kinds = [classify_parsing_rule(p.read_text(errors="replace"))
                     for p in parsing_files]

    # Schema signals
    schema_has_raw_log = bool(cols) and "_raw_log" in cols
    schema_has_raw_json = bool(cols) and "_raw_json" in cols
    schema_has_json = bool(cols) and "_json" in cols
    col_count = len(cols) if cols else 0

    # ─── Decision tree ──────────────────────────────────────────
    # S3: _raw_json in schema OR any parsing rule references _raw_json
    if schema_has_raw_json or "raw_json" in parsing_kinds:
        verdict["scenario"] = "S3"
        verdict["signal"] = (
            "schema_has_raw_json" if schema_has_raw_json
            else "parsing_rule_refs_raw_json"
        )
        return verdict

    # S1: parsing rule has `parse_X(_raw_log)` AND schema has _raw_log
    if "parse_raw_log" in parsing_kinds:
        verdict["scenario"] = "S1"
        verdict["signal"] = "parsing_rule_parses_raw_log"
        return verdict

    # S1-candidate: schema has _raw_log + _json AND no parse_raw_log
    # signature. Still S1-shaped on the schema side. Cover the cases
    # where the parsing rule is regex-only or absent (a few packs).
    if schema_has_raw_log and schema_has_json:
        verdict["scenario"] = "S1"
        verdict["signal"] = "schema_raw_log_plus_json"
        return verdict

    # Generic _raw_log + nothing else: still S1-shaped — the dataset
    # is the rawlog-only / no-JSON variant.
    if schema_has_raw_log and col_count <= 2:
        verdict["scenario"] = "S1"
        verdict["signal"] = "schema_raw_log_only"
        return verdict

    # CEF column-shape discriminator. If the dataset
    # columns look like CEF spec field names (rt/dst/dpt/src/spt/act/
    # cs1-6/...), it's almost certainly S2 — broker pre-parses the
    # CEF wire format into typed columns before ingest. Applies
    # regardless of whether a parsing rule exists (some CEF packs
    # ship a parsing rule just for `_time` normalization).
    is_cef, cef_ratio = looks_cef(cols or [])
    if is_cef:
        verdict["scenario"] = "S2"
        verdict["signal"] = f"cef_column_ratio={cef_ratio:.0%}"
        verdict["cef_ratio"] = round(cef_ratio, 3)
        return verdict

    # No parsing rule + schema declares many typed cols + not CEF →
    # S4 (vendor API integration). Columns are camelCase, nested
    # JSON sub-keys, etc.
    if not has_parsing and col_count > 0:
        verdict["scenario"] = "S4"
        verdict["signal"] = f"no_parsing_rule__schema_has_{col_count}_cols"
        return verdict

    # Pack has a parsing rule but neither parse_raw_log nor _raw_json
    # — and columns don't look CEF. Typically an HTTP-collector pack
    # whose parsing rule does `_time` normalization on epoch-shaped
    # numeric columns (AWS_WAF pattern), OR a vendor API path where
    # someone wrote a minor parsing rule for ad-hoc cleanup.
    if has_parsing and not any(k in parsing_kinds for k in ("parse_raw_log", "raw_json")):
        verdict["scenario"] = "S2_or_S4"
        verdict["signal"] = "parsing_rule_other_no_raw_log_or_raw_json"
        return verdict

    # No schema known and no decisive parsing-rule signal
    verdict["scenario"] = "?"
    verdict["signal"] = "no_schema_and_no_decisive_parsing_rule"
    return verdict


def main() -> int:
    yaml_paths = sorted(BUNDLE_ROOT.glob("*/data_source.yaml"))
    verdicts: list[dict[str, Any]] = []
    for yp in yaml_paths:
        h = read_yaml_header(yp)
        pack = h.get("pack_name", "")
        rule = h.get("rule_name", "")
        dataset = h.get("dataset_name", "")
        if not pack or not dataset:
            continue
        verdicts.append(categorize_pack(pack, rule, dataset))

    counts = Counter(v["scenario"] for v in verdicts)
    signals = Counter(v["signal"] for v in verdicts)

    print("=== Ingest-scenario categorization ===")
    print(f"  total packs: {len(verdicts)}")
    print()
    print("  per-scenario counts:")
    for scenario in ("S1", "S2", "S2_or_S4", "S3", "S4", "?"):
        print(f"    {scenario:<10} {counts.get(scenario, 0)}")
    print()
    print("  signals breakdown:")
    for sig, count in signals.most_common():
        print(f"    {count:>4}  {sig}")

    # Output JSON for downstream tooling
    OUT_PATH.write_text(json.dumps({
        "summary": dict(counts),
        "signals": dict(signals),
        "packs": verdicts,
    }, indent=2, sort_keys=True) + "\n")
    print()
    print(f"  full output → {OUT_PATH.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
