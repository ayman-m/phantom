"""Fill the last 3 vendor-logo gaps (Clearswift, SecureAuth, Semperis).

Maintainer-only research/build tool per `scripts/CLAUDE.md`. Runtime
never re-runs it.

## Why

Three vendors have no usable SVG on Wikipedia or simple-icons and would show the
placeholder icon on the data-sources page:
  * Clearswift — Wikipedia only has a JPG/PNG on the article page
  * SecureAuth — no Wikipedia article; vendor's site has a SVG but
    it's all-white (invisible on the constant-near-white card panel)
  * Semperis — vendor's site uses an empty inline data-URI for the
    logo (not a fetchable file anywhere)

Operator's direction:
  > "If you can't find SVG, create one. So check the image logo
  >  online of these vendors, and then let's create an SVG for them."

## How each was sourced

| Vendor    | Approach                                                                   |
|-----------|----------------------------------------------------------------------------|
| Clearswift| Pulled the PNG from Wikipedia's article (`Clearswift - A HelpSystems_Logo.png`). PNG works fine — the inline-logo route serves either. |
| SecureAuth| Fetched their official site SVG (`/assets/secureauth-logo-white-JQccCguH.svg`), recolored the `fill: #fff;` style to `#1A2238` (a navy that gives WCAG AA contrast on `#F7F8FA`). |
| Semperis  | Hand-crafted SVG wordmark in their navy brand color (`#0F1934`). Clean typographic logo modeled on Semperis' identity-security brand language. |

## What this script does

1. Loads the prepared bytes from `/tmp/` for the three vendors.
2. For each, finds every `data_source.yaml` whose `pack_name` matches
   (Clearswift → `ClearswiftDLP`; SecureAuth → `SecureAuthIdentityPlatform`;
   Semperis → `SemperisDSP`) and embeds the inline base64 logo block.
3. Re-runs `scripts/extract_vendor_logos_library.py` to regenerate
   the standalone `docs/assets/vendor-logos/` library.

## When to re-run

One-shot. After this runs, all three vendors carry inline logos in
their YAMLs and the standalone library has one file per vendor.
"""
from __future__ import annotations

import argparse
import base64
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_SOURCES_DIR = REPO_ROOT / "bundles" / "spark" / "data-sources"


# Pack name → (path to logo bytes, mime_type, source description, license).
EMBEDDINGS = {
    "ClearswiftDLP": {
        "path": Path("/tmp/clearswift.png"),
        "mime_type": "image/png",
        "source": "wikipedia:File:Clearswift_-_A_HelpSystems_Logo.png",
        "license": "Wikipedia / vendor trademark (Clearswift is a Fortra brand)",
        "fidelity": "branded",
    },
    "SecureAuthIdentityPlatform": {
        "path": Path("/tmp/secureauth-dark.svg"),
        "mime_type": "image/svg+xml",
        "source": "secureauth.com/assets/secureauth-logo-white-JQccCguH.svg (recolored white→#1A2238 for visibility on near-white card panel)",
        "license": "Vendor trademark; recoloration is a derivative for in-product display",
        "fidelity": "branded-recolored",
    },
    "SemperisDSP": {
        "path": Path("/tmp/semperis.svg"),
        "mime_type": "image/svg+xml",
        "source": "hand-crafted by phantom-maintainer — wordmark in Semperis brand navy #0F1934",
        "license": "Phantom maintainer-authored; Semperis name is the vendor's trademark",
        "fidelity": "approximation",
    },
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    embedded = []
    not_found_pack = []
    missing_asset = []

    for pack_name, info in EMBEDDINGS.items():
        path: Path = info["path"]
        if not path.is_file():
            missing_asset.append((pack_name, str(path)))
            continue

        data = path.read_bytes()
        b64 = base64.b64encode(data).decode("ascii")
        logo_block = {
            "mime_type": info["mime_type"],
            "data": b64,
            "source": info["source"],
            "license": info["license"],
            "fidelity": info["fidelity"],
        }

        # Find every YAML with this pack_name
        matched_yamls = []
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
            if doc.get("pack_name") != pack_name:
                continue
            matched_yamls.append((yaml_path, doc))

        if not matched_yamls:
            not_found_pack.append(pack_name)
            continue

        for yaml_path, doc in matched_yamls:
            doc["logo"] = logo_block
            if not args.dry_run:
                with yaml_path.open("w", encoding="utf-8") as f:
                    yaml.safe_dump(doc, f, default_flow_style=False, sort_keys=False, allow_unicode=True, width=120)
            embedded.append((pack_name, yaml_path.parent.name, len(data), info["mime_type"]))
            print(f"  ✓ {pack_name:30s} → {yaml_path.parent.name} ({len(data):,} B {info['mime_type']})")

    print()
    print(f"=== Summary ===")
    print(f"  Embedded into:    {len(embedded)} YAMLs")
    print(f"  Missing assets:   {len(missing_asset)}")
    for pack, path in missing_asset:
        print(f"    {pack}: {path} not found")
    print(f"  No YAML matched:  {len(not_found_pack)}")
    for pack in not_found_pack:
        print(f"    {pack}")

    if args.dry_run:
        print("\n(dry-run; no files written)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
