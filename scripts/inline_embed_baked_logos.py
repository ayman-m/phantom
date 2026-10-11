"""Inline-embed baked logos into bundled data_source.yaml files.

Per scripts/CLAUDE.md framing: this is a MAINTAINER-ONLY research/build
tool. Runtime never re-runs it.

## Why

The legacy logo-resolution path in `bundles/spark/mcp/src/api/data_sources.py:
get_vendor_logo` walks the baked cortex-content tree to find one of:

  1. `Packs/<pack>/Integrations/<int>/<int>_image_light.svg` (R3+ per-pack override)
  2. `vendor_map.yaml` → `vendor_svgs/<vk>_light.svg` (vendor SVG dir)
  3. `Packs/<pack>/Integrations/<int>/<int>_dark.svg` or `_image.png` (legacy)
  4. `Packs/<pack>/Author_image.png` (pack-author fallback)

On the deployed agent, the `vendor_svgs/` directory + `vendor_map.yaml`
may be absent, in which case the only path that resolves is Priority 3/4. The catalog returns
`logo_url: /api/agent/data-sources/logo/<pack>` unconditionally; for
packs with NO baked asset that URL 404s and the UI shows a placeholder.

## What this script does

For each `bundles/spark/data-sources/*/data_source.yaml` where
`logo: null`:

  1. Walks the baked tree at `bundles/spark/connectors/cortex-content/
     baked/Packs/<pack_name>/`.
  2. Picks the best available asset by priority:
       _image_light.svg → _dark.svg → _image.png → Author_image.png
  3. Base64-encodes it, embeds into the YAML's `logo:` block with
     mime_type + a `source:` provenance note.

After running, the per-pack YAML carries the logo bytes. The runtime
inline-logo route serves them. The legacy /logo/<pack>
route is vestigial — kept for backward compat but not
referenced by catalog responses.

## What this script does NOT do

It does NOT source NEW SVGs from outside the repo. Vendors that have
no baked asset (Apache, Apple, Arista, Brocade, Citrix, NGINX,
Kubernetes, etc.) remain with
`logo: null` after this run. Sourcing those is a separate content
task (e.g. via simple-icons / vendor websites).

## Cadence

One-shot per refresh cycle. Idempotent: re-running won't overwrite a
YAML that already has an inline logo.
"""
from __future__ import annotations

import argparse
import base64
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_SOURCES_DIR = REPO_ROOT / "bundles" / "spark" / "data-sources"
BAKED_ROOT = REPO_ROOT / "bundles" / "spark" / "connectors" / "cortex-content" / "baked"


def find_logo_asset(pack_name: str) -> tuple[Path, str] | None:
    """Walk baked tree for the pack's best-available logo.

    Returns (path, mime_type) or None.

    Priority:
      1. Integrations/<int>/<int>_image_light.svg  (image/svg+xml)
      2. Integrations/<int>/<int>_dark.svg         (image/svg+xml)
      3. Integrations/<int>/<int>_image.png        (image/png)
      4. Author_image.png                          (image/png)

    "First integration in sorted order" — matches the runtime route's
    same convention so behavior is identical pre/post-inline-embedding.
    """
    pack_dir = BAKED_ROOT / "Packs" / pack_name
    if not pack_dir.is_dir():
        return None

    integrations_dir = pack_dir / "Integrations"
    if integrations_dir.is_dir():
        for int_subdir in sorted(integrations_dir.iterdir()):
            if not int_subdir.is_dir():
                continue
            int_name = int_subdir.name
            for suffix, mime in (
                (f"{int_name}_image_light.svg", "image/svg+xml"),
                (f"{int_name}_dark.svg", "image/svg+xml"),
                (f"{int_name}_image.png", "image/png"),
            ):
                candidate = int_subdir / suffix
                if candidate.is_file():
                    return candidate, mime

    author_png = pack_dir / "Author_image.png"
    if author_png.is_file():
        return author_png, "image/png"

    return None


def encode_logo(path: Path, mime_type: str) -> dict:
    """Build the YAML `logo:` block from a baked asset on disk."""
    data = path.read_bytes()
    b64 = base64.b64encode(data).decode("ascii")
    return {
        "mime_type": mime_type,
        "data": b64,
        "source": f"baked/{path.relative_to(BAKED_ROOT)}",
        "fidelity": "branded",
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="Report changes without writing")
    ap.add_argument("--limit", type=int, default=None,
                    help="Process only the first N YAMLs (smoke test)")
    args = ap.parse_args()

    if not DATA_SOURCES_DIR.is_dir():
        print(f"ERROR: {DATA_SOURCES_DIR} not found", file=sys.stderr)
        return 1
    if not BAKED_ROOT.is_dir():
        print(f"ERROR: {BAKED_ROOT} not found — refresh the baked catalog first", file=sys.stderr)
        return 1

    yaml_dirs = sorted(d for d in DATA_SOURCES_DIR.iterdir() if d.is_dir())
    if args.limit:
        yaml_dirs = yaml_dirs[: args.limit]

    embedded: list[tuple[str, str, int]] = []   # (dir, source_path, size)
    skipped_have_logo: list[str] = []
    no_baked_asset: list[str] = []

    for d in yaml_dirs:
        yaml_path = d / "data_source.yaml"
        if not yaml_path.is_file():
            continue
        try:
            doc = yaml.safe_load(yaml_path.read_text())
        except Exception as exc:
            print(f"  ⚠ skip {d.name}: parse error: {exc}", file=sys.stderr)
            continue
        if not isinstance(doc, dict):
            continue

        # Idempotent: skip if YAML already has an inline logo.
        if doc.get("logo"):
            skipped_have_logo.append(d.name)
            continue

        pack_name = doc.get("pack_name")
        if not pack_name:
            continue

        found = find_logo_asset(pack_name)
        if found is None:
            no_baked_asset.append(d.name)
            continue
        path, mime_type = found
        doc["logo"] = encode_logo(path, mime_type)
        embedded.append((d.name, str(path.relative_to(BAKED_ROOT)), path.stat().st_size))

        if not args.dry_run:
            with yaml_path.open("w", encoding="utf-8") as f:
                yaml.safe_dump(
                    doc, f, default_flow_style=False, sort_keys=False,
                    allow_unicode=True, width=120,
                )

    print(f"\n=== Inline-embed summary ===")
    print(f"  Already had inline logo (skipped): {len(skipped_have_logo)}")
    print(f"  Newly inline-embedded:             {len(embedded)}")
    print(f"  No baked asset (left as null):     {len(no_baked_asset)}")

    if embedded:
        print(f"\nSample of newly-embedded (first 15):")
        for name, src, size in embedded[:15]:
            print(f"  {name:60s}  ← {src} ({size} bytes)")
        if len(embedded) > 15:
            print(f"  ... + {len(embedded) - 15} more")

    if no_baked_asset:
        print(f"\nPacks with no baked asset (need external SVG sourcing):")
        for name in no_baked_asset[:30]:
            print(f"  {name}")
        if len(no_baked_asset) > 30:
            print(f"  ... + {len(no_baked_asset) - 30} more")

    if args.dry_run:
        print("\n(dry-run; no files written)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
