#!/usr/bin/env python3
"""Auto-extract fields from cortex-content into bundled
data_source.yaml files where `fields: []`.

# Why

Without this step the agent's Browse catalog shows `0 fields` for packs
that are not manually curated, even though opening the card's drawer
shows fields (the drawer goes through `_extract_and_compose_data_sources`,
which reads the modeling-rule schema.json directly). This script keeps
the catalog and the drawer in agreement.

# What this script does

Walks `bundles/spark/data-sources/<id>/data_source.yaml` for every
entry with `fields: []`. For each, looks up the matching
`bundles/spark/connectors/cortex-content/baked/Packs/<pack>/
ModelingRules/<rule>/<rule>_schema.json`. If present, extracts the
specific dataset's field inventory (minus meta fields), maps cortex
types to data_source.schema.json types, and writes the fields back
into the YAML.

Idempotent — re-running only touches YAMLs that still have empty
fields[]. Safe to re-run after a cortex-content refresh.

Reuses the `_yaml_scalar()` helper from extend_data_source_fields.py
to avoid YAML-render bug class (dates / ints / bools rendered as
strings, @-leading names quoted, etc.).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

# Reuse the render helper
sys.path.insert(0, str(Path(__file__).parent))
from extend_data_source_fields import render_field_yaml, update_one_yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
BUNDLE_ROOT = REPO_ROOT / "bundles" / "spark" / "data-sources"
BAKED_ROOT = REPO_ROOT / "bundles" / "spark" / "connectors" / "cortex-content" / "baked" / "Packs"

# Cortex publishes these on every modeling rule regardless of vendor.
# Drop them — they pollute the field count without representing real
# vendor-emitted fields.
META_FIELDS = {"_id", "_product", "_raw_log", "_vendor", "_time", "_collector_name"}

# Map cortex schema.json types to data_source.schema.json's controlled
# vocabulary. Anything unmapped falls through as "string" (the most
# permissive — xlog's name-pattern matching will pick a reasonable
# generator at runtime).
TYPE_MAP = {
    "string": "string",
    "int": "integer",
    "boolean": "boolean",
    "datetime": "datetime",
    "float": "float",
}


def read_yaml_fields_count(yaml_path: Path) -> tuple[int, dict[str, str]]:
    """Return (fields_count, parsed_header_fields). Doesn't require yaml lib —
    we only need to know if `fields: []` is on disk.

    Also extracts pack_name + rule_name + dataset_name from the YAML's
    header fields (they live as top-level scalars).
    """
    text = yaml_path.read_text()
    header: dict[str, str] = {}
    in_fields = False
    fields_lines = 0
    for line in text.split("\n"):
        if line.startswith("fields:"):
            # fields: []   → 0
            # fields:\n  - name: ...   → count following list items
            stripped = line[7:].strip()
            if stripped == "[]":
                return 0, header
            in_fields = True
            continue
        if in_fields:
            if line.startswith("  - name:") or line.startswith("- name:"):
                fields_lines += 1
            elif line and not line[0].isspace() and not line.startswith("-"):
                # next top-level key — end of fields block
                in_fields = False
        # Track top-level header keys we care about
        if not line.startswith(" ") and ":" in line:
            key, _, value = line.partition(":")
            value = value.strip()
            if key in ("pack_name", "rule_name", "dataset_name"):
                header[key] = value
    return fields_lines, header


def extract_cortex_fields(
    pack_name: str, rule_name: str, dataset_name: str,
) -> list[dict[str, Any]] | None:
    """Find the rule's _schema.json and return its non-meta fields for
    the specified dataset. Returns None if schema file missing OR the
    dataset isn't present in the schema.
    """
    schema_path = (
        BAKED_ROOT / pack_name / "ModelingRules" / rule_name
        / f"{rule_name}_schema.json"
    )
    if not schema_path.is_file():
        return None
    try:
        schema = json.loads(schema_path.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(schema, dict):
        return None
    ds = schema.get(dataset_name)
    if not isinstance(ds, dict):
        return None

    fields: list[dict[str, Any]] = []
    for field_name, info in ds.items():
        if field_name in META_FIELDS:
            continue
        if not isinstance(info, dict):
            continue
        cortex_type = info.get("type", "string")
        mapped_type = TYPE_MAP.get(cortex_type, "string")
        entry: dict[str, Any] = {
            "name": field_name,
            "type": mapped_type,
        }
        if info.get("is_array"):
            entry["is_array"] = True
        fields.append(entry)

    return fields


def main() -> int:
    if not BUNDLE_ROOT.is_dir():
        print(f"ERROR: bundle root missing: {BUNDLE_ROOT}", file=sys.stderr)
        return 1
    if not BAKED_ROOT.is_dir():
        print(f"ERROR: baked tree missing: {BAKED_ROOT}", file=sys.stderr)
        return 1

    print(f"=== cortex-content field extraction ===")
    print(f"  bundle root: {BUNDLE_ROOT}")
    print(f"  baked root:  {BAKED_ROOT}\n")

    total = 0
    already_has_fields = 0
    no_cortex_match = 0
    cortex_empty = 0
    extracted = 0
    extracted_field_counts: list[int] = []

    for yaml_path in sorted(BUNDLE_ROOT.glob("*/data_source.yaml")):
        total += 1
        count, header = read_yaml_fields_count(yaml_path)
        if count > 0:
            already_has_fields += 1
            continue

        pack = header.get("pack_name")
        rule = header.get("rule_name")
        dataset = header.get("dataset_name")
        if not (pack and rule and dataset):
            print(f"  ⚠  {yaml_path.parent.name}: missing pack/rule/dataset")
            continue

        fields = extract_cortex_fields(pack, rule, dataset)
        if fields is None:
            no_cortex_match += 1
            continue
        if not fields:
            cortex_empty += 1
            # Schema exists but every field is meta — record stays empty
            continue

        ok, msg = update_one_yaml(yaml_path, fields)
        if ok:
            extracted += 1
            extracted_field_counts.append(len(fields))
            print(f"  ✓ {yaml_path.parent.name}: {len(fields)} fields")
        else:
            print(f"  ✗ {yaml_path.parent.name}: {msg}")

    print()
    print(f"=== Summary ===")
    print(f"  total bundled data sources : {total}")
    print(f"  already had curated fields : {already_has_fields}")
    print(f"  no cortex schema available : {no_cortex_match}")
    print(f"  cortex schema all-meta     : {cortex_empty}")
    print(f"  newly extracted            : {extracted}")
    if extracted_field_counts:
        avg = sum(extracted_field_counts) / len(extracted_field_counts)
        print(f"  avg fields per extracted   : {avg:.1f}")
        print(f"  max fields per extracted   : {max(extracted_field_counts)}")
        print(f"  total fields added         : {sum(extracted_field_counts)}")
    print()
    final_with_fields = already_has_fields + extracted
    print(f"  After this run: {final_with_fields}/{total} data sources have fields[]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
