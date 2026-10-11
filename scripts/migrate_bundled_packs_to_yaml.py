#!/usr/bin/env python3
"""One-time migration: bundled cortex-content packs → data_source.yaml.

For each pack in `bundles/spark/connectors/cortex-content/baked/Packs/`:
  1. Read catalog.json row (pack_name, rule_name, dataset_name, supported_modules, etc.)
  2. Read pack_metadata.json (description, categories, currentVersion)
  3. Read vendor_map.yaml entry (canonical vendor name + key)
  4. Read the SVG logo from `vendor_svgs/<vendor>_light.svg` and base64-encode
  5. Read schema fields if available (catalog row only has counts; full fields require schema extraction)
  6. Write `bundles/spark/data-sources/<pack_id>/data_source.yaml`

Maintainer-only. Never invoked at runtime.

USAGE:
    python3 scripts/migrate_bundled_packs_to_yaml.py [--dry-run]
"""

from __future__ import annotations

import argparse
import base64
import datetime as _dt
import json
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    print("ERROR: PyYAML required. Install with `pip install pyyaml`.", file=sys.stderr)
    sys.exit(1)

ROOT = Path(__file__).resolve().parent.parent
BAKED = ROOT / "bundles/spark/connectors/cortex-content/baked"
OUT_DIR = ROOT / "bundles/spark/data-sources"
NOW = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _slugify(s: str, max_len: int = 128) -> str:
    """url-safe slug from a pack/vendor identifier. Keeps alphanumerics + dashes + underscores.

    Default max_len 128 chars matches the data_source.schema.json id pattern limit
    (allows full <pack>__<rule>__<dataset> tuples without truncation collisions).
    """
    import re
    s = re.sub(r"[^A-Za-z0-9_.-]", "-", s).strip("-_.")
    return s[:max_len] or "unknown"


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r") as f:
        return yaml.safe_load(f) or {}


def _read_logo_b64(vendor_key: str) -> dict[str, Any] | None:
    """Return logo dict or None. Reads vendor_svgs/<vendor>_light.svg."""
    svg_path = BAKED / "vendor_svgs" / f"{vendor_key}_light.svg"
    if not svg_path.is_file():
        return None
    data = svg_path.read_bytes()
    if len(data) > 50 * 1024:  # 50KB guideline
        # Bundled SVGs that exceed the guideline still ship; the guideline is for OPERATOR uploads.
        # No filtering here.
        pass
    return {
        "mime_type": "image/svg+xml",
        "data": base64.b64encode(data).decode("ascii"),
        "source": "phantom-bundle",
        "license": "MIT",
        "fidelity": "branded",  # may be wordmark-fallback for some; refinement deferred
    }


def _load_catalog_rows() -> list[dict[str, Any]]:
    catalog_path = BAKED / "catalog.json"
    if not catalog_path.is_file():
        print(f"ERROR: no catalog at {catalog_path}", file=sys.stderr)
        sys.exit(1)
    data = json.loads(catalog_path.read_text())
    return data.get("rows", [])


def _build_pack_to_vendor_map() -> dict[str, dict[str, str]]:
    """pack_name → {vendor_display_name, vendor_key}."""
    vmap_path = BAKED / "vendor_map.yaml"
    if not vmap_path.is_file():
        return {}
    data = _load_yaml(vmap_path)
    out: dict[str, dict[str, str]] = {}
    for vk, info in (data.get("vendors") or {}).items():
        for pack in info.get("packs") or []:
            out[pack] = {
                "vendor": info.get("display_name", vk),
                "vendor_key": vk,
            }
    return out


def _read_pack_metadata(pack_name: str) -> dict[str, Any]:
    meta_path = BAKED / "Packs" / pack_name / "pack_metadata.json"
    if not meta_path.is_file():
        return {}
    try:
        return json.loads(meta_path.read_text())
    except Exception:
        return {}


def _row_to_yaml(
    row: dict[str, Any],
    vendor_info: dict[str, str],
    pack_meta: dict[str, Any],
    logo: dict[str, Any] | None,
) -> dict[str, Any]:
    """Compose the YAML dict for one catalog row."""
    pack_name = row["pack_name"]
    rule_name = row["rule_name"]
    dataset_name = row["dataset_name"]
    pack_id = _slugify(pack_name)

    categories = pack_meta.get("categories") or []
    # cap at 3 per schema constraint
    categories = [c for c in categories if isinstance(c, str)][:3]

    # The catalog row only has field counts, not the full schema. The schema lives
    # in the modeling rule's schema.json and gets extracted at install time. For
    # the bundled migration, we DO NOT inline the full fields[] here — that
    # would duplicate ~50KB per pack. The install path still reads the
    # cortex-content baked tree to extract fields. The loader can either
    # (a) read fields from the cortex-content tree on demand, or (b) leave the
    # fields[] empty until install. We pick (b) for the bundled-pack YAMLs:
    # field_count is informational; full schema is extracted at install. This
    # matches the existing pre-install behavior where the catalog row shows
    # field counts but not the full inventory.
    fields_placeholder: list[dict[str, Any]] = []

    yaml_doc: dict[str, Any] = {
        "schema_version": 1,
        "id": pack_id,
        "pack_name": pack_name,
        "rule_name": rule_name,
        "dataset_name": dataset_name,
        "vendor": vendor_info.get("vendor", pack_name),
        "product": pack_name,
        "description": pack_meta.get("description", "") or "",
        "categories": categories,
        "version": pack_meta.get("currentVersion", ""),
        "origin": "bundle",
        "author": "phantom-bundle",
        "uploaded_by": None,
        "created_at": NOW,
        "updated_at": NOW,
        "logo": logo,
        "formats": ["SYSLOG", "CEF", "JSON"],  # defaults; per-pack format support is in pack_metadata.supportedModules
        "is_rawlog_only": bool(row.get("is_rawlog_only", False)),
        "fields": fields_placeholder,
        "xdm_mappings": [],
    }
    return yaml_doc


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="don't write files, just report")
    args = parser.parse_args()

    rows = _load_catalog_rows()
    pack_to_vendor = _build_pack_to_vendor_map()
    print(f"loaded {len(rows)} catalog rows + {len(pack_to_vendor)} pack→vendor mappings")

    if not args.dry_run:
        OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Group by pack — multiple rows per pack possible (one per dataset within a rule).
    # We write one YAML per (pack/rule/dataset) tuple so identity round-trips cleanly.
    written = 0
    no_vendor = 0
    no_logo = 0
    for row in rows:
        pack_name = row["pack_name"]
        rule_name = row["rule_name"]
        dataset_name = row["dataset_name"]

        vendor_info = pack_to_vendor.get(pack_name)
        if not vendor_info:
            vendor_info = {"vendor": pack_name, "vendor_key": _slugify(pack_name).lower()}
            no_vendor += 1

        pack_meta = _read_pack_metadata(pack_name)
        logo = _read_logo_b64(vendor_info["vendor_key"])
        if not logo:
            no_logo += 1

        yaml_doc = _row_to_yaml(row, vendor_info, pack_meta, logo)

        # Per-tuple id: <pack_id>__<rule>__<dataset> to avoid collisions when a
        # single pack has multiple datasets. Slashes aren't path-safe, so
        # double-underscore separator.
        pack_id_full = _slugify(f"{pack_name}__{rule_name}__{dataset_name}")
        dest_dir = OUT_DIR / pack_id_full
        dest_path = dest_dir / "data_source.yaml"

        if args.dry_run:
            written += 1
            continue

        dest_dir.mkdir(parents=True, exist_ok=True)
        with dest_path.open("w") as f:
            yaml.safe_dump(yaml_doc, f, default_flow_style=False, sort_keys=False, width=120)
        written += 1

    print(f"wrote {written} data_source.yaml files {'(dry-run)' if args.dry_run else ''}")
    print(f"  packs without vendor_map entry: {no_vendor}")
    print(f"  packs without a vendor SVG: {no_logo}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
