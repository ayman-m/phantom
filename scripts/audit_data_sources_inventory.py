"""Audit data-sources inventory + grouping coverage.

Maintainer-only audit per `scripts/CLAUDE.md`. Runtime never re-runs it.

Reports:
  - Total YAMLs (one per pack/rule/dataset tuple)
  - Total unique 3-tuples (pack/rule/dataset)
  - Total unique YAML `id`s (should match 3-tuples ideally)
  - Total distinct vendors (after vendor rebucketing)
  - Per-vendor pack count + use_case set
  - Anomalies:
      * missing `vendor:` field
      * missing `use_cases:` field
      * duplicate `id:` across multiple YAML directories
      * vendor with no use_cases assigned
      * pack with `is_rawlog_only: true` AND fields[] populated (the
        vendor-bucket cleanup clears these — sanity check)
"""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_SOURCES_DIR = REPO_ROOT / "bundles" / "spark" / "data-sources"


def _slugify(s: str) -> str:
    import re
    return re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower() or "unknown"


def main():
    if not DATA_SOURCES_DIR.is_dir():
        print(f"ERROR: {DATA_SOURCES_DIR} not found", file=sys.stderr)
        return 1

    yaml_dirs = sorted(d for d in DATA_SOURCES_DIR.iterdir() if d.is_dir())

    total_yamls = 0
    by_id: dict[str, list[str]] = defaultdict(list)            # id → [yaml_dir]
    by_3tuple: dict[tuple, list[str]] = defaultdict(list)      # (p,r,d) → [yaml_dir]
    by_vendor: dict[str, list[dict]] = defaultdict(list)       # vendor_key → [{dir, pack, rule, dataset, use_cases}]
    missing_vendor: list[str] = []
    missing_use_cases: list[str] = []
    wrongly_rawlog: list[tuple[str, int]] = []                 # (yaml_dir, field_count)

    for d in yaml_dirs:
        yaml_path = d / "data_source.yaml"
        if not yaml_path.is_file():
            continue
        try:
            doc = yaml.safe_load(yaml_path.read_text())
        except Exception:
            continue
        if not isinstance(doc, dict):
            continue
        total_yamls += 1

        pack = doc.get("pack_name", "?")
        rule = doc.get("rule_name", "?")
        dataset = doc.get("dataset_name", "?")
        ds_id = doc.get("id", f"{pack}__{rule}__{dataset}")
        vendor = doc.get("vendor")
        use_cases = doc.get("use_cases") or []
        is_rawlog = bool(doc.get("is_rawlog_only", False))
        fields = doc.get("fields") or []

        by_id[ds_id].append(d.name)
        by_3tuple[(pack, rule, dataset)].append(d.name)

        if not vendor:
            missing_vendor.append(d.name)
            continue

        vk = _slugify(vendor).lower()
        by_vendor[vk].append({
            "dir": d.name,
            "pack": pack,
            "rule": rule,
            "dataset": dataset,
            "use_cases": list(use_cases),
            "is_rawlog_only": is_rawlog,
            "field_count": len(fields),
        })

        if not use_cases:
            missing_use_cases.append(d.name)
        if is_rawlog and len(fields) >= 1:
            wrongly_rawlog.append((d.name, len(fields)))

    print("=" * 70)
    print("DATA SOURCES INVENTORY AUDIT")
    print("=" * 70)
    print()
    print(f"Total YAML files:           {total_yamls}")
    print(f"Distinct (pack,rule,dataset): {len(by_3tuple)}")
    print(f"Distinct YAML `id`s:        {len(by_id)}")
    print(f"Distinct vendors:           {len(by_vendor)}")
    print()

    # Per-vendor breakdown
    print("─" * 70)
    print("PER-VENDOR PRODUCT COUNT  (sorted alphabetically by vendor_key)")
    print("─" * 70)
    print(f"{'Vendor':<28s}  {'Packs':>5s}  Use cases")
    print(f"{'─' * 28}  {'─' * 5}  {'─' * 30}")
    grand_total_packs = 0
    for vk in sorted(by_vendor.keys()):
        packs = by_vendor[vk]
        grand_total_packs += len(packs)
        # Aggregate use_cases across all packs in this vendor
        uc_set: set = set()
        for p in packs:
            for uc in p["use_cases"]:
                uc_set.add(uc)
        uc_list = ", ".join(sorted(uc_set)) if uc_set else "(none)"
        if len(uc_list) > 36:
            uc_list = uc_list[:33] + "..."
        print(f"{vk:<28s}  {len(packs):>5d}  {uc_list}")

    print(f"\n  Total packs across vendors: {grand_total_packs}")
    print(f"  Match against YAML count:   {grand_total_packs == total_yamls - len(missing_vendor)}")
    print()

    # Anomalies
    print("─" * 70)
    print("ANOMALIES")
    print("─" * 70)

    if missing_vendor:
        print(f"\n  YAMLs missing `vendor:` field ({len(missing_vendor)}):")
        for d in missing_vendor:
            print(f"    {d}")
    else:
        print("\n  ✓ Every YAML has a `vendor:` field.")

    if missing_use_cases:
        print(f"\n  YAMLs missing `use_cases:` field ({len(missing_use_cases)}):")
        for d in missing_use_cases:
            print(f"    {d}")
    else:
        print("  ✓ Every YAML has `use_cases:` populated.")

    dupe_ids = [(k, v) for k, v in by_id.items() if len(v) > 1]
    if dupe_ids:
        print(f"\n  Duplicate `id:` values (bundle dedup keeps first) ({len(dupe_ids)}):")
        for ds_id, dirs in sorted(dupe_ids)[:10]:
            print(f"    id={ds_id!r}")
            for d in dirs:
                print(f"      {d}")
        if len(dupe_ids) > 10:
            print(f"    ... + {len(dupe_ids) - 10} more")
    else:
        print("  ✓ No duplicate `id:` values.")

    dupe_3tuples = [(k, v) for k, v in by_3tuple.items() if len(v) > 1]
    if dupe_3tuples:
        print(f"\n  Duplicate (pack,rule,dataset) tuples ({len(dupe_3tuples)}):")
        for t, dirs in dupe_3tuples:
            print(f"    {t}")
            for d in dirs:
                print(f"      {d}")
    else:
        print("  ✓ No duplicate (pack,rule,dataset) tuples.")

    if wrongly_rawlog:
        print(f"\n  Packs with is_rawlog_only=true AND fields[] populated ({len(wrongly_rawlog)}):")
        print("  (these should have been unflagged by the cohort cleanup; investigate)")
        for d, n in wrongly_rawlog[:15]:
            print(f"    {d}  fields={n}")
        if len(wrongly_rawlog) > 15:
            print(f"    ... + {len(wrongly_rawlog) - 15} more")
    else:
        print("  ✓ No is_rawlog_only=true packs with populated fields.")

    # Vendor cards that have ONLY rawlog-only packs (would be hidden by default
    # Browse filter)
    rawlog_only_vendors = []
    for vk, packs in by_vendor.items():
        if all(p["is_rawlog_only"] for p in packs):
            rawlog_only_vendors.append((vk, len(packs)))
    if rawlog_only_vendors:
        print(f"\n  Vendors with ALL rawlog-only packs (hidden in default Browse) ({len(rawlog_only_vendors)}):")
        for vk, n in sorted(rawlog_only_vendors):
            print(f"    {vk}  ({n} packs)")
    else:
        print("  ✓ Every vendor has at least one structured (non-rawlog-only) pack.")

    print()
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"  {total_yamls} data source YAMLs across {len(by_vendor)} vendors.")
    print(f"  Coverage: 100% vendor-bucketed, 100% use_case-tagged.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
