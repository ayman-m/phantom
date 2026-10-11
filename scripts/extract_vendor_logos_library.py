"""Extract a standalone vendor-logo library from the data-sources YAMLs.

Maintainer-only research/build tool per `scripts/CLAUDE.md`. Runtime
never re-runs it.

## Why

`bundles/spark/data-sources/*/data_source.yaml` files carry their logos
as inline base64 inside the YAML — that's the right shape for the
runtime catalog (one HTTP fetch, no baked-tree dependency). But:

  - The runtime never serves them as standalone files.
  - For docs / future UI components / brand-mark reuse, we want plain
    SVG/PNG files on disk, one per vendor.

This script grabs the inline base64 from each YAML, decodes it back to
raw bytes, and writes one file per VENDOR (not per pack, since most
vendors have multiple packs sharing the same logo) into
`docs/assets/vendor-logos/`.

## Output layout

```
docs/assets/vendor-logos/
├── README.md              ← human-readable inventory
├── manifest.yaml          ← machine-readable (vendor → file + provenance)
├── apache.svg
├── apple.svg
├── arista.svg
├── …
└── vmware.svg
```

Each file's name is `<vendor_key>.<ext>` where `vendor_key` is the
slugified `vendor:` field from the YAML (the same key used to group
the data-sources page's vendor cards).

## When to re-run

Whenever a logo is added/changed in a YAML. The script is idempotent:
re-running with the same YAMLs produces identical output (same file
names, same bytes — only mtime changes).
"""
from __future__ import annotations

import argparse
import base64
import re
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_SOURCES_DIR = REPO_ROOT / "bundles" / "spark" / "data-sources"
OUTPUT_DIR = REPO_ROOT / "docs" / "assets" / "vendor-logos"


def _slugify(s: str) -> str:
    """Match the runtime vendor_key derivation in
    `bundles/spark/mcp/src/usecase/data_sources_yaml_loader.py`.
    """
    # Replace any run of non-alphanumeric with a single '-'
    out = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()
    return out or "unknown"


def _ext_for_mime(mime: str) -> str:
    if mime == "image/svg+xml":
        return "svg"
    if mime == "image/png":
        return "png"
    if mime == "image/jpeg":
        return "jpg"
    return "bin"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not DATA_SOURCES_DIR.is_dir():
        print(f"ERROR: {DATA_SOURCES_DIR} not found", file=sys.stderr)
        return 1

    # vendor_key → FIRST YAML WITH AN INLINE LOGO. We don't pick rows[0]
    # regardless of whether it has a logo (as the VendorCard logo
    # selection must not either). For the library, we want a
    # representative WITH a logo, so we keep
    # scanning all YAMLs for a vendor until we find one. If none of
    # a vendor's YAMLs has a logo, the vendor lands in `missing`.
    chosen: dict[str, dict] = {}  # vendor_key → {vendor_display, doc, yaml_dir}
    vendor_yamls: dict[str, list[str]] = {}  # vendor_key → list[yaml dir]
    no_vendor: list[str] = []

    for d in sorted(DATA_SOURCES_DIR.iterdir()):
        if not d.is_dir():
            continue
        yaml_path = d / "data_source.yaml"
        if not yaml_path.is_file():
            continue
        try:
            doc = yaml.safe_load(yaml_path.read_text())
        except Exception:
            continue
        if not isinstance(doc, dict):
            continue

        vendor_raw = doc.get("vendor")
        if not vendor_raw:
            no_vendor.append(d.name)
            continue
        vk = _slugify(vendor_raw)
        vendor_yamls.setdefault(vk, []).append(d.name)

        # Already picked? Skip — first YAML with a logo wins for stability.
        if vk in chosen:
            continue

        logo = doc.get("logo")
        if not logo or not isinstance(logo, dict) or not logo.get("data"):
            # Don't give up on this vendor yet — keep scanning other
            # YAMLs in alphabetical order; maybe a sibling has the logo.
            continue

        chosen[vk] = {
            "vendor_display": vendor_raw,
            "doc": doc,
            "yaml_dir": d.name,
        }

    # Vendors with at least one YAML but no inline logo anywhere
    no_logo: dict[str, list[str]] = {
        vk: yamls for vk, yamls in vendor_yamls.items() if vk not in chosen
    }

    # Build the output dir
    if not args.dry_run:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Write each logo + collect manifest entries
    manifest_entries: list[dict] = []
    written = 0

    for vk in sorted(chosen.keys()):
        entry = chosen[vk]
        logo = entry["doc"]["logo"]
        mime = logo.get("mime_type", "image/svg+xml")
        ext = _ext_for_mime(mime)
        filename = f"{vk}.{ext}"
        target = OUTPUT_DIR / filename

        data = base64.b64decode(logo["data"])

        if not args.dry_run:
            with target.open("wb") as f:
                f.write(data)

        manifest_entries.append({
            "vendor_key": vk,
            "vendor_display": entry["vendor_display"],
            "file": filename,
            "mime_type": mime,
            "bytes": len(data),
            "source": logo.get("source", "unknown"),
            "license": logo.get("license", "unknown"),
            "fidelity": logo.get("fidelity", "unknown"),
            "extracted_from": entry["yaml_dir"],
        })
        written += 1
        print(f"  ✓ {filename:40s} ({len(data):>6,} B)  ← {entry['yaml_dir']}")

    # Sort the missing-vendor map for stable output
    missing_vendors = sorted(no_logo.keys())

    # Write manifest.yaml
    manifest = {
        "schema_version": 1,
        "description": (
            "Standalone vendor-logo library extracted from "
            "bundles/spark/data-sources/*/data_source.yaml. "
            "Maintainer artifact — runtime does not consume this. "
            "For docs / brand-mark reuse / future UI surfaces."
        ),
        "vendor_count_with_logo": len(manifest_entries),
        "vendor_count_without_logo": len(missing_vendors),
        "vendors_without_logo": missing_vendors,
        "logos": manifest_entries,
    }
    manifest_path = OUTPUT_DIR / "manifest.yaml"
    if not args.dry_run:
        with manifest_path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(
                manifest, f, default_flow_style=False, sort_keys=False, allow_unicode=True, width=120,
            )

    # Write README.md
    readme = _build_readme(manifest_entries, missing_vendors, no_vendor)
    readme_path = OUTPUT_DIR / "README.md"
    if not args.dry_run:
        readme_path.write_text(readme)

    print()
    print(f"=== Summary ===")
    print(f"  Output dir:                       {OUTPUT_DIR.relative_to(REPO_ROOT)}")
    print(f"  Vendors with logos written:       {written}")
    print(f"  Vendors without logos (skipped):  {len(missing_vendors)}")
    if missing_vendors:
        print(f"    {', '.join(missing_vendors)}")
    if no_vendor:
        print(f"  YAMLs without `vendor:` field:    {len(no_vendor)}")
    if args.dry_run:
        print("\n(dry-run; no files written)")
    return 0


def _build_readme(entries: list[dict], missing: list[str], no_vendor: list[str]) -> str:
    """Human-readable inventory of the library."""
    lines = [
        "# Vendor-logo library",
        "",
        "Standalone SVG/PNG files for every vendor that ships a data source bundled with Phantom.",
        "",
        "## What this is",
        "",
        "One file per vendor (not per pack). Extracted from the inline base64 logos in",
        "`bundles/spark/data-sources/<pack-id>/data_source.yaml` files via",
        "`scripts/extract_vendor_logos_library.py`.",
        "",
        "## What this is NOT",
        "",
        "This directory is a **maintainer artifact**. Phantom's runtime (the agent + MCP) does NOT",
        "consume any file in this directory — runtime reads logos from the YAMLs themselves via the",
        "inline-logo route (see `bundles/spark/mcp/src/api/data_sources.py`).",
        "",
        "Intended consumers:",
        "- Documentation / marketing material",
        "- Future UI surfaces that want brand marks outside the data-sources page",
        "- Operator-side reference",
        "",
        "## How to regenerate",
        "",
        "```bash",
        "python3 scripts/extract_vendor_logos_library.py",
        "```",
        "",
        "Idempotent: same YAMLs → same files. Re-run whenever a YAML's inline logo is added or",
        "changed.",
        "",
        f"## Inventory ({len(entries)} vendors)",
        "",
        "| Vendor | File | Format | Bytes | Source |",
        "|---|---|---|---|---|",
    ]
    for e in entries:
        fmt = e["mime_type"].split("/")[-1].upper()
        if fmt == "SVG+XML":
            fmt = "SVG"
        lines.append(
            f"| {e['vendor_display']} | "
            f"[`{e['file']}`](./{e['file']}) | "
            f"{fmt} | "
            f"{e['bytes']:,} | "
            f"`{e['source']}` |"
        )
    if missing:
        lines += [
            "",
            f"## Vendors without a logo ({len(missing)})",
            "",
            "These vendors have YAMLs but no inline logo embedded. No file in this directory.",
            "Hand-curated SVGs need to be sourced from each vendor's official media kit.",
            "",
        ]
        for vk in missing:
            lines.append(f"- `{vk}`")
    if no_vendor:
        lines += [
            "",
            f"## YAMLs missing a `vendor:` field ({len(no_vendor)})",
            "",
            "Defensive note: a few YAMLs apparently have no `vendor:` field. They were skipped:",
            "",
        ]
        for d in no_vendor:
            lines.append(f"- `{d}`")
    lines += [
        "",
        "## License",
        "",
        "Each logo's license is recorded in `manifest.yaml` under its `license:` field. Many are",
        "trademarks of their respective owners; some are CC-licensed (CC BY-SA 3.0 / 4.0,",
        "CC0-1.0). When reusing these files outside Phantom, check the license per vendor.",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
