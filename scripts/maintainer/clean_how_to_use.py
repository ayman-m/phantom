#!/usr/bin/env python3
"""Merge the two `how_to_use` sections into one and drop
the hardcoded broker IP/port, across the 22 validated data sources.

Each validated `data_source.yaml` carries a two-section `how_to_use`:

    ## Simulating this data source        <- generic CEF/broker routing +
                                              hardcoded `10.0.0.8:514`
    ## Sending these logs to Cortex XSIAM  <- "destination-neutral" preamble +
                                              the SAME routing re-explained +
                                              per-vendor Required-CEF-header /
                                              MR-pattern / Composite content

This collapses them to ONE `## Sending these logs to Cortex XSIAM` section with
a fully generic broker reference (no `10.0.0.8`, no `:514`). The per-vendor
content (everything from `**Required CEF header` onward) is preserved verbatim;
only the two duplicate routing headers in front of it are replaced.

Operates on `validated: true` YAMLs (robust to slug renames). Idempotent:
a YAML whose `how_to_use` no longer contains `## Simulating this data source`
is left untouched.

    python3 scripts/maintainer/clean_how_to_use.py            # dry run (diff)
    python3 scripts/maintainer/clean_how_to_use.py --apply    # rewrite
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

DS_DIR = Path(__file__).resolve().parents[2] / "bundles" / "spark" / "data-sources"

OLD_SECTION_1_MARKER = "## Simulating this data source"
# The per-vendor content always begins at this marker (verified across all 22).
PER_VENDOR_MARKER = "**Required CEF header"

# The single merged section — fully generic broker (no IP, no port number).
NEW_HEADER = """## Sending these logs to Cortex XSIAM

Phantom emits this vendor's wire format as CEF over UDP — point a data worker
at your XSIAM broker's syslog destination and these records flow straight in.
The schema below describes the vendor's fields independent of destination, so
the same records also work for Splunk, Elastic, or any syslog receiver.

The CEF header's **vendor** + **product** drive XSIAM's parsing-rule routing:
the broker normalizes them to `<lowercased-vendor>_<lowercased-product>_raw`
(non-alphanumerics -> `_`) and matches your installed parsing rule. The PR/MR
rules read NAMED COLUMNS, so the transport is invisible to them — pack the
vendor's field names as CEF extension `key=value` pairs."""


def validated_yamls() -> list[Path]:
    out = []
    for p in sorted(DS_DIR.glob("*/data_source.yaml")):
        try:
            doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except Exception:
            continue
        if doc.get("validated") is True:
            out.append(p)
    return out


def merged_how_to_use(htu: str) -> str | None:
    """Return the rewritten how_to_use, or None if it's already clean / can't
    be split (idempotent + defensive)."""
    if OLD_SECTION_1_MARKER not in htu:
        return None  # already single-section — no-op
    idx = htu.find(PER_VENDOR_MARKER)
    if idx == -1:
        return None  # no per-vendor body to preserve — leave it alone
    per_vendor = htu[idx:].strip()
    return f"{NEW_HEADER}\n\n{per_vendor}"


def process(path: Path, apply: bool) -> tuple[str, str]:
    """Returns (status, detail). status in {changed, skipped, error}."""
    text = path.read_text(encoding="utf-8")
    doc = yaml.safe_load(text)
    htu = doc.get("how_to_use") or ""
    new_htu = merged_how_to_use(htu)
    if new_htu is None:
        return "skipped", "already single-section"
    if new_htu == htu:
        return "skipped", "no change"
    doc["how_to_use"] = new_htu
    if apply:
        with path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(
                doc, f,
                sort_keys=False,
                default_flow_style=False,
                allow_unicode=True,
                width=100,
            )
    return "changed", f"{len(htu)} -> {len(new_htu)} chars"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true",
                    help="rewrite the YAMLs (default: dry run)")
    args = ap.parse_args()

    if not DS_DIR.is_dir():
        print(f"ERROR: data-sources dir not found: {DS_DIR}", file=sys.stderr)
        return 1

    yamls = validated_yamls()
    mode = "APPLY" if args.apply else "DRY RUN"
    print(f"=== clean_how_to_use.py [{mode}] — {len(yamls)} validated YAMLs ===\n")
    changed = skipped = 0
    for p in yamls:
        status, detail = process(p, args.apply)
        if status == "changed":
            changed += 1
            print(f"  CHANGE  {p.parent.name}  ({detail})")
        else:
            skipped += 1
    print(f"\n{'APPLIED' if args.apply else 'DRY RUN'}: {changed} changed, "
          f"{skipped} skipped (already clean).")
    if not args.apply and changed:
        print("Re-run with --apply to rewrite.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
