#!/usr/bin/env python3
"""Add data_source.yaml for triples in the new baked tree
that we don't have yet. Idempotent — preserves existing YAMLs.

Run after `python3 scripts/refresh_cortex_baked_catalog.py
--include-rawlog`. Reuses the migration helpers from
migrate_bundled_packs_to_yaml.py so YAMLs follow the same shape.
"""
from __future__ import annotations
import json, sys
from pathlib import Path
from typing import Any
import yaml

sys.path.insert(0, str(Path(__file__).parent))
from migrate_bundled_packs_to_yaml import (
    _slugify, _row_to_yaml, _read_logo_b64, _read_pack_metadata,
    _build_pack_to_vendor_map, OUT_DIR, BAKED,
)

# Walk the new baked tree to enumerate all (pack, rule, dataset)
cortex_triples: list[tuple[str, str, str, dict]] = []
for pack_dir in sorted(BAKED.glob("Packs/*/")):
    pack = pack_dir.name
    mrs = pack_dir / "ModelingRules"
    if not mrs.is_dir():
        continue
    for rule_dir in sorted(mrs.iterdir()):
        if not rule_dir.is_dir():
            continue
        rule = rule_dir.name
        sf = rule_dir / f"{rule}_schema.json"
        if not sf.is_file():
            continue
        try:
            schema = json.loads(sf.read_text())
        except Exception:
            continue
        for dataset, ds_info in schema.items():
            # ds_info is the raw cortex schema dict (field -> {type, is_array})
            cortex_triples.append((pack, rule, dataset, ds_info))

# Existing YAMLs
existing: set[tuple[str, str, str]] = set()
for ds in OUT_DIR.glob("*/"):
    yp = ds / "data_source.yaml"
    if not yp.is_file():
        continue
    try:
        d = yaml.safe_load(yp.read_text()) or {}
    except Exception:
        continue
    if all(d.get(k) for k in ("pack_name", "rule_name", "dataset_name")):
        existing.add((d["pack_name"], d["rule_name"], d["dataset_name"]))

print(f"Existing YAML triples : {len(existing)}")
print(f"Cortex baked triples  : {len(cortex_triples)}")

pack_to_vendor = _build_pack_to_vendor_map()
META_FIELDS = {"_id", "_product", "_raw_log", "_vendor", "_time", "_collector_name"}
TYPE_MAP = {
    "string": "string", "int": "integer", "boolean": "boolean",
    "datetime": "datetime", "float": "float",
}

added = 0
skipped = 0
no_vendor = 0

for pack, rule, dataset, ds_info in cortex_triples:
    if (pack, rule, dataset) in existing:
        skipped += 1
        continue

    vendor_info = pack_to_vendor.get(pack)
    if not vendor_info:
        vendor_info = {"vendor": pack, "vendor_key": _slugify(pack).lower()}
        no_vendor += 1

    pack_meta = _read_pack_metadata(pack)
    logo = _read_logo_b64(vendor_info["vendor_key"])

    # Synthesize a catalog-like row for _row_to_yaml
    field_count = sum(1 for k in ds_info.keys() if isinstance(ds_info[k], dict))
    non_meta_count = sum(
        1 for k in ds_info.keys()
        if isinstance(ds_info[k], dict) and k not in META_FIELDS
    )
    row = {
        "pack_name": pack,
        "rule_name": rule,
        "dataset_name": dataset,
        "field_count": field_count,
        "non_meta_field_count": non_meta_count,
        "is_rawlog_only": non_meta_count == 0,
    }

    yaml_doc = _row_to_yaml(row, vendor_info, pack_meta, logo)

    # Populate fields[] from the cortex schema.json
    fields_list: list[dict[str, Any]] = []
    for fname, finfo in ds_info.items():
        if fname in META_FIELDS:
            continue
        if not isinstance(finfo, dict):
            continue
        entry: dict[str, Any] = {"name": fname,
                                 "type": TYPE_MAP.get(finfo.get("type", "string"), "string")}
        if finfo.get("is_array"):
            entry["is_array"] = True
        fields_list.append(entry)
    yaml_doc["fields"] = fields_list

    # Write
    pack_id_full = _slugify(f"{pack}__{rule}__{dataset}")
    dest_dir = OUT_DIR / pack_id_full
    dest_path = dest_dir / "data_source.yaml"
    dest_dir.mkdir(parents=True, exist_ok=True)
    with dest_path.open("w") as f:
        yaml.safe_dump(yaml_doc, f, default_flow_style=False, sort_keys=False, width=120)
    added += 1

print()
print(f"Added : {added} new YAMLs")
print(f"Skipped (already had): {skipped}")
print(f"No vendor_map entry: {no_vendor}")
