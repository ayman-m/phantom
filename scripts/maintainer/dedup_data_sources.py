#!/usr/bin/env python3
"""Dedup the bundled data-source tree, strip MR-version
suffixes from every source, and consolidate the Amazon → Amazon Web Services
vendor.

The tree at `bundles/spark/data-sources/<slug>/data_source.yaml` accumulated
duplicate families during modeling-rule extraction: the fetch pipeline was
re-run at different upstream content versions, leaving e.g.

    AWS-GuardDuty__AWSGuardDutyModelingRules_1_3__aws_guardduty_raw  (62 fields)
    AWS-GuardDuty__AWSGuardDutyModelingRules__aws_guardduty_raw      (43 fields)

These collide on (vendor, product, dataset_name) and show as duplicate rows on
the Browse page. They are NOT meaningful operator versions — just extraction
artifacts. The version suffix lives ONLY in the middle (rule_name) segment of
the slug; `id` / `pack_name` / `dataset_name` are clean.

This migration does three things:

  1. DEDUP — group by a CASE-INSENSITIVE (vendor, product, dataset_name) key
     (catches near-dups like `VMware_ESXi_raw` vs `vmware_esxi_raw`). Per
     family, keep one by:

        winner = validated:true first
                 → else most fields
                 → else the already-unversioned variant (tie)

     Delete the rest. (Recoverable from git history if ever wanted as seed
     versions for a future version store.)

  2. STRIP VERSION — for EVERY surviving source whose rule_name carries a
     trailing `_X_Y` MR-version suffix, strip it from the `rule_name:` field
     AND the directory name. `id` / `pack_name` / `dataset_name` are untouched.
     The separate `version:` field (e.g. `1.3.70`) stays intact, so no version
     *information* is lost — only the cruft in the name. Safe: stripping
     rule_name never changes the (vendor, product, dataset) identity, and the
     pass refuses if two survivors would collide on the same slug.

  3. VENDOR FIX — `AWS_ELB`'s `vendor: Amazon` → `vendor: Amazon Web Services`
     (the only stray "Amazon" string; folds ELB's card into AWS).

IDEMPOTENT: re-running on an already-clean tree is a no-op (no >1 families, no
versioned survivors, no `vendor: Amazon`). Works from a pristine OR a
partially-migrated tree — it always converges to the same final state.

    python3 scripts/maintainer/dedup_data_sources.py            # dry run
    python3 scripts/maintainer/dedup_data_sources.py --apply    # mutate
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from collections import defaultdict
from pathlib import Path

DS_DIR = Path(__file__).resolve().parents[2] / "bundles" / "spark" / "data-sources"

# Trailing modeling-rule version suffix on the rule_name segment:
# `_1_3`, `_2_0`, `_2_10`, `_2_9`, `_1_4`. Anchored at end; one or two groups.
_VERSION_SUFFIX = re.compile(r"_\d+(?:_\d+)?$")

# The ELB vendor consolidation (the only stray "Amazon" string in the tree).
_ELB_DIR = "AWS_ELB__AWS_ELB__aws_elb_raw"


def _scalar(text: str, key: str) -> str:
    """Read a top-level scalar `key: value` from raw YAML text (first match)."""
    m = re.search(rf"^{re.escape(key)}:[ \t]*(.*)$", text, re.MULTILINE)
    return m.group(1).strip().strip("'\"") if m else ""


def _field_count(text: str) -> int:
    """Count top-level `- name:` list entries (the fields[] list)."""
    return len(re.findall(r"^- name:", text, re.MULTILINE))


def _strip_version(segment: str) -> str:
    return _VERSION_SUFFIX.sub("", segment)


class Entry:
    __slots__ = ("dir", "path", "text", "vendor", "product", "dataset",
                 "rule_name", "pack_name", "fields", "validated")

    def __init__(self, ds_dir: Path):
        self.dir = ds_dir
        self.path = ds_dir / "data_source.yaml"
        self.text = self.path.read_text(encoding="utf-8")
        self.vendor = _scalar(self.text, "vendor")
        self.product = _scalar(self.text, "product")
        self.dataset = _scalar(self.text, "dataset_name")
        self.rule_name = _scalar(self.text, "rule_name")
        self.pack_name = _scalar(self.text, "pack_name")
        self.fields = _field_count(self.text)
        self.validated = _scalar(self.text, "validated").lower() == "true"

    @property
    def key(self) -> tuple[str, str, str]:
        # CASE-INSENSITIVE grouping key — catches near-dups where only the
        # dataset_name casing differs (VMware_ESXi_raw vs vmware_esxi_raw).
        return (self.vendor.lower(), self.product.lower(), self.dataset.lower())

    @property
    def rule_segment(self) -> str:
        """The middle (rule) segment of the dir slug — filesystem truth.

        maxsplit=2: pack and rule never contain `__`, but a dataset_name can
        (e.g. `imperva_inc__securesphere_raw`), so the 3rd part captures the
        full dataset.
        """
        parts = self.dir.name.split("__", 2)
        if len(parts) != 3:
            raise SystemExit(
                f"unexpected slug shape (no pack__rule__dataset): {self.dir.name}"
            )
        return parts[1]

    @property
    def is_versioned(self) -> bool:
        return bool(_VERSION_SUFFIX.search(self.rule_segment))

    def stripped_dir_name(self) -> str:
        parts = self.dir.name.split("__", 2)
        return f"{parts[0]}__{_strip_version(parts[1])}__{parts[2]}"


def load_entries() -> list[Entry]:
    return [Entry(p.parent) for p in sorted(DS_DIR.glob("*/data_source.yaml"))
            if p.is_file()]


def pick_winner(members: list[Entry]) -> Entry:
    # validated first (0 < 1), then most fields, then the shortest dir name
    # (the unversioned / non-stub variant) on a tie.
    return sorted(
        members,
        key=lambda e: (0 if e.validated else 1, -e.fields, len(e.dir.name)),
    )[0]


def plan_deletes(entries: list[Entry]) -> list[Entry]:
    families: dict[tuple, list[Entry]] = defaultdict(list)
    for e in entries:
        families[e.key].append(e)
    deletes: list[Entry] = []
    for members in families.values():
        if len(members) < 2:
            continue
        winner = pick_winner(members)
        deletes.extend(m for m in members if m is not winner)
    return deletes


def plan_strips(survivors: list[Entry]) -> list[tuple[Entry, str, str]]:
    """(entry, new_rule_name, new_dir_name) for every versioned survivor.
    Refuses if two survivors would converge on the same slug."""
    strips = [
        (e, _strip_version(e.rule_segment), e.stripped_dir_name())
        for e in survivors if e.is_versioned
    ]
    # Collision guard: post-strip dir names must stay unique across ALL
    # survivors (versioned + already-clean).
    final_names: dict[str, str] = {}
    for e in survivors:
        name = e.stripped_dir_name() if e.is_versioned else e.dir.name
        if name in final_names:
            raise SystemExit(
                f"version-strip would collide: {e.dir.name} and "
                f"{final_names[name]} both -> {name}"
            )
        final_names[name] = e.dir.name
    return strips


def find_elb(entries: list[Entry]) -> Entry | None:
    for e in entries:
        if e.dir.name == _ELB_DIR and e.vendor == "Amazon":
            return e
    return None


def _rewrite_rule_name(path: Path, text: str, new_rule: str):
    # Replace only the FIRST top-level `rule_name:` line (never touch any
    # occurrence inside how_to_use prose).
    return re.sub(r"^rule_name:[ \t]*.*$", f"rule_name: {new_rule}",
                  text, count=1, flags=re.MULTILINE)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true",
                    help="actually mutate the tree (default: dry run)")
    args = ap.parse_args()

    if not DS_DIR.is_dir():
        print(f"ERROR: data-sources dir not found: {DS_DIR}", file=sys.stderr)
        return 1

    entries = load_entries()
    deletes = plan_deletes(entries)
    delete_dirs = {e.dir for e in deletes}
    survivors = [e for e in entries if e.dir not in delete_dirs]
    strips = plan_strips(survivors)
    elb_fix = find_elb(entries)

    mode = "APPLY" if args.apply else "DRY RUN"
    print(f"=== dedup_data_sources.py [{mode}] ===")
    print(f"scanned {len(entries)} data sources under {DS_DIR}\n")

    print(f"DELETE ({len(deletes)} dirs — dedup losers, case-insensitive):")
    for e in sorted(deletes, key=lambda x: x.dir.name):
        print(f"  - {e.dir.name}  (fields={e.fields}, validated={e.validated})")

    print(f"\nSTRIP VERSION ({len(strips)} dirs):")
    for e, new_rule, new_dir in sorted(strips, key=lambda x: x[0].dir.name):
        print(f"  - {e.dir.name}")
        print(f"      -> {new_dir}   (rule_name -> {new_rule})")

    print("\nVENDOR FIX:")
    print(f"  - {elb_fix.dir.name}: 'Amazon' -> 'Amazon Web Services'"
          if elb_fix else "  - (none — ELB already consolidated or absent)")

    if args.apply:
        # 1. delete losers first so a stripped winner can take a freed slug
        for e in deletes:
            shutil.rmtree(e.dir)
        # 2. strip version from every surviving versioned source
        for e, new_rule, new_dir_name in strips:
            target = e.dir.parent / new_dir_name
            if target.exists() and target != e.dir:
                raise SystemExit(f"strip target exists: {new_dir_name}")
            e.path.write_text(_rewrite_rule_name(e.path, e.text, new_rule),
                              encoding="utf-8")
            e.dir.rename(target)
        # 3. ELB vendor consolidation
        if elb_fix:
            elb_fix.path.write_text(
                re.sub(r"^vendor:[ \t]*Amazon[ \t]*$",
                       "vendor: Amazon Web Services",
                       elb_fix.text, count=1, flags=re.MULTILINE),
                encoding="utf-8",
            )
        remaining = len(load_entries())
        print(f"\nAPPLIED. tree now has {remaining} data sources "
              f"(was {len(entries)}; removed {len(entries) - remaining}).")
    else:
        projected = len(entries) - len(deletes)
        print(f"\nDRY RUN — no changes written. Projected tree size: {projected} "
              f"(was {len(entries)}). Re-run with --apply to mutate.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
