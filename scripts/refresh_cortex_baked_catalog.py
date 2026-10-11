#!/usr/bin/env python3
"""Refresh the baked cortex-content catalog.

Pre-fetches the xsiam-tagged subset of demisto/content into
`bundles/spark/connectors/cortex-content/baked/` so the runtime
cortex-content connector reads everything from local files instead of
hitting GitHub. Operator runs this script manually when they want to
refresh the catalog (manual update only). The result is committed to the repo, so customer installs ship
with the catalog already baked into the agent image — zero runtime
GitHub dependency.

# Approach

Single `git clone --depth=1` of demisto/content into a tempdir. Walks
`Packs/<pack>/pack_metadata.json` to filter to xsiam-tagged packs.
For each surviving pack, copies:

  - pack_metadata.json
  - Author_image.png (if present — root-level fallback logo)
  - Every ModelingRules/<rule>/<rule>_schema.json
  - First found Integrations/<int>/<int>_dark.svg or _image.png
    (the logo extraction uses an "alphabetical first integration"
    rule today; pre-resolving here saves a runtime ls)

Writes a `_manifest.json` with refresh timestamp + upstream git SHA +
counts so the UI can show provenance ("Catalog refreshed <date>
from demisto/content@<sha>; <n> packs, <n> schemas, <n> logos").

# Why not GitHub API + token

GitHub anonymous API is rate-limited at 60 req/h. Walking ~217 rules
would need ~600 requests → guaranteed throttle. Authenticated raises
to 5000/h but still slow + requires token plumbing. Shallow clone is
~50 MB transferred + completes in 10-30 seconds.

# Usage

  python3 scripts/refresh_cortex_baked_catalog.py

Optional flags:
  --output DIR      Override baked output dir (default: bundles/spark/connectors/cortex-content/baked/)
  --branch NAME     demisto/content branch to clone from (default: master)
  --keep-clone      Don't delete the temporary clone after copying.
                    Useful for incremental debugging.
  --include-rawlog  Also bake rules whose schema is rawlog-only.
                    Default omits them; they need separate regex-based extraction.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

logger = logging.getLogger("refresh-cortex-baked-catalog")
logging.basicConfig(format="[%(levelname)s] %(message)s", level=logging.INFO)


# The 6 standard meta fields every ModelingRule includes. When the only
# fields in a schema are these, the rule is "rawlog-only" — extraction
# needs regex.
_META_SCHEMA_FIELDS = {"_id", "_product", "_raw_log", "_vendor", "_time", "_collector_name"}


def _has_xsiam_module(metadata: dict) -> bool:
    """True if the pack supports the xsiam module."""
    modules = metadata.get("supportedModules") or []
    if not isinstance(modules, list):
        return False
    return any(str(m).strip().lower() == "xsiam" for m in modules)


def _is_rawlog_only_schema(schema: dict) -> bool:
    """True if every dataset in the schema has only meta fields."""
    if not isinstance(schema, dict) or not schema:
        return True
    for dataset_name, fields_dict in schema.items():
        if not isinstance(fields_dict, dict):
            continue
        non_meta = [f for f in fields_dict.keys() if f not in _META_SCHEMA_FIELDS]
        if non_meta:
            return False
    return True


def _find_first_logo(pack_dir: Path) -> tuple[Path, str] | None:
    """Pick the first available vendor logo for a pack. Mirrors the runtime
    cortex_extract_vendor_logo search order: Integrations/<int>/<int>_dark.svg
    → _image.png → Author_image.png. Returns (source_path, kind) where kind
    is "svg" or "png", or None if no logo exists."""
    integrations_dir = pack_dir / "Integrations"
    if integrations_dir.is_dir():
        for int_subdir in sorted(integrations_dir.iterdir()):
            if not int_subdir.is_dir():
                continue
            int_name = int_subdir.name
            svg = int_subdir / f"{int_name}_dark.svg"
            png = int_subdir / f"{int_name}_image.png"
            if svg.is_file():
                return svg, "svg"
            if png.is_file():
                return png, "png"
    # Pack-root fallback
    author_png = pack_dir / "Author_image.png"
    if author_png.is_file():
        return author_png, "png"
    return None


def _short_sha(repo_dir: Path) -> str:
    """Return short SHA of the cloned demisto/content HEAD for provenance."""
    out = subprocess.run(
        ["git", "rev-parse", "--short=12", "HEAD"],
        cwd=repo_dir,
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout.strip()


def _clone_demisto_content(branch: str, target: Path) -> None:
    """Shallow-clone demisto/content into the given target dir."""
    cmd = [
        "git",
        "clone",
        "--depth=1",
        "--single-branch",
        f"--branch={branch}",
        "https://github.com/demisto/content.git",
        str(target),
    ]
    logger.info("cloning demisto/content (shallow, single-branch=%s)...", branch)
    subprocess.run(cmd, check=True)


def refresh(
    output_dir: Path,
    branch: str = "master",
    keep_clone: bool = False,
    include_rawlog: bool = False,
) -> dict:
    """Refresh the baked catalog into output_dir. Returns a summary dict."""
    started = time.time()
    summary = {
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "branch": branch,
        "include_rawlog": include_rawlog,
        "packs_total": 0,
        "packs_xsiam": 0,
        "packs_baked": 0,
        "schemas_total": 0,
        "schemas_baked": 0,
        "schemas_rawlog_only": 0,
        "logos_baked": 0,
        "metadata_baked": 0,
    }

    # Clean + recreate output dir so stale data doesn't survive
    if output_dir.exists():
        logger.info("clearing existing %s", output_dir)
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)
    (output_dir / "Packs").mkdir()

    # Clone upstream
    clone_dir = Path(tempfile.mkdtemp(prefix="cortex-content-clone-"))
    try:
        _clone_demisto_content(branch, clone_dir)
        summary["upstream_sha"] = _short_sha(clone_dir)

        packs_dir = clone_dir / "Packs"
        if not packs_dir.is_dir():
            raise RuntimeError(f"clone is missing Packs/ directory at {packs_dir}")

        catalog_rows: list[dict] = []

        for pack_dir in sorted(packs_dir.iterdir()):
            if not pack_dir.is_dir():
                continue
            summary["packs_total"] += 1
            pack_name = pack_dir.name

            # pack_metadata.json
            metadata_path = pack_dir / "pack_metadata.json"
            if not metadata_path.is_file():
                continue
            try:
                metadata = json.loads(metadata_path.read_text())
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("pack=%s: bad pack_metadata.json (%s)", pack_name, exc)
                continue

            if not _has_xsiam_module(metadata):
                continue
            summary["packs_xsiam"] += 1

            # No modeling rules → skip (we'd have nothing to install)
            modeling_rules_dir = pack_dir / "ModelingRules"
            if not modeling_rules_dir.is_dir():
                continue
            rule_names = sorted(
                r.name
                for r in modeling_rules_dir.iterdir()
                if r.is_dir() and (r / f"{r.name}_schema.json").is_file()
            )
            if not rule_names:
                continue

            # Process each rule's schema
            kept_any_rule = False
            for rule_name in rule_names:
                summary["schemas_total"] += 1
                rule_dir = modeling_rules_dir / rule_name
                schema_path = rule_dir / f"{rule_name}_schema.json"
                try:
                    schema = json.loads(schema_path.read_text())
                except (json.JSONDecodeError, OSError) as exc:
                    logger.warning(
                        "pack=%s rule=%s: bad schema.json (%s)",
                        pack_name,
                        rule_name,
                        exc,
                    )
                    continue
                is_rawlog = _is_rawlog_only_schema(schema)
                if is_rawlog:
                    summary["schemas_rawlog_only"] += 1
                if is_rawlog and not include_rawlog:
                    continue

                # Bake the schema
                out_rule_dir = (
                    output_dir / "Packs" / pack_name / "ModelingRules" / rule_name
                )
                out_rule_dir.mkdir(parents=True, exist_ok=True)
                (out_rule_dir / f"{rule_name}_schema.json").write_text(
                    json.dumps(schema, separators=(",", ":")),
                )
                summary["schemas_baked"] += 1

                # Build catalog rows — one per dataset within the schema
                for dataset_name, fields_dict in schema.items():
                    if not isinstance(fields_dict, dict):
                        continue
                    field_count = len(fields_dict)
                    non_meta_count = sum(
                        1 for f in fields_dict.keys() if f not in _META_SCHEMA_FIELDS
                    )
                    catalog_rows.append(
                        {
                            "pack_name": pack_name,
                            "rule_name": rule_name,
                            "dataset_name": dataset_name,
                            "field_count": field_count,
                            "non_meta_field_count": non_meta_count,
                            "is_rawlog_only": non_meta_count == 0,
                            "supported_modules": metadata.get("supportedModules") or [],
                            "pack_description": metadata.get("description"),
                            "pack_version": metadata.get("currentVersion"),
                            # logo_url + logo_type are stamped after we know
                            # which logo we baked (or didn't) for this pack
                            "logo_url": None,
                            "logo_type": None,
                        }
                    )
                kept_any_rule = True

            if not kept_any_rule:
                continue

            # Bake pack_metadata.json (we use this at install time)
            out_pack_dir = output_dir / "Packs" / pack_name
            out_pack_dir.mkdir(parents=True, exist_ok=True)
            (out_pack_dir / "pack_metadata.json").write_text(
                json.dumps(metadata, separators=(",", ":")),
            )
            summary["metadata_baked"] += 1

            # Bake the first available vendor logo
            logo_info = _find_first_logo(pack_dir)
            logo_url = None
            logo_type = None
            if logo_info is not None:
                src_path, kind = logo_info
                rel_path = src_path.relative_to(pack_dir)
                dest_path = out_pack_dir / rel_path
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src_path, dest_path)
                summary["logos_baked"] += 1
                # URL the connector returns when running in baked-mode.
                # Agent-side route /api/agent/data-sources/logo/<pack>
                # resolves to baked/Packs/<pack>/<rel_path>.
                logo_url = f"/api/agent/data-sources/logo/{pack_name}"
                logo_type = kind

            # Stamp the resolved logo info onto every catalog row for this pack
            for row in catalog_rows:
                if row["pack_name"] == pack_name and row["logo_url"] is None:
                    row["logo_url"] = logo_url
                    row["logo_type"] = logo_type

            summary["packs_baked"] += 1

        # Build the rollup catalog.json
        catalog_obj = {
            "ok": True,
            "rows": catalog_rows,
            "packs_scanned": summary["packs_baked"],
            "rules_found": len(catalog_rows),
            "structured_rules": sum(
                1 for r in catalog_rows if not r["is_rawlog_only"]
            ),
            "rawlog_rules": sum(1 for r in catalog_rows if r["is_rawlog_only"]),
            "filter": {
                "xsiam_only": True,
                "include_rawlog": include_rawlog,
                "pack_limit": 0,
            },
        }
        (output_dir / "catalog.json").write_text(
            json.dumps(catalog_obj, separators=(",", ":")),
        )

        summary["finished_at"] = time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
        )
        summary["elapsed_seconds"] = round(time.time() - started, 1)
        (output_dir / "_manifest.json").write_text(
            json.dumps(summary, indent=2),
        )

        logger.info(
            "DONE in %ss: %s packs (xsiam-tagged: %s, baked: %s), %s schemas, %s logos, %s metadata files",
            summary["elapsed_seconds"],
            summary["packs_total"],
            summary["packs_xsiam"],
            summary["packs_baked"],
            summary["schemas_baked"],
            summary["logos_baked"],
            summary["metadata_baked"],
        )
    finally:
        if not keep_clone:
            logger.info("removing clone at %s", clone_dir)
            shutil.rmtree(clone_dir, ignore_errors=True)
        else:
            logger.info("kept clone at %s (--keep-clone)", clone_dir)

    return summary


def main() -> int:
    p = argparse.ArgumentParser(description="Refresh the baked cortex-content catalog.")
    repo_root = Path(__file__).resolve().parents[1]
    default_output = (
        repo_root / "bundles" / "spark" / "connectors" / "cortex-content" / "baked"
    )
    p.add_argument(
        "--output",
        type=Path,
        default=default_output,
        help=f"baked output dir (default: {default_output.relative_to(repo_root)})",
    )
    p.add_argument("--branch", default="master")
    p.add_argument("--keep-clone", action="store_true")
    p.add_argument("--include-rawlog", action="store_true")
    args = p.parse_args()

    try:
        refresh(
            output_dir=args.output.resolve(),
            branch=args.branch,
            keep_clone=args.keep_clone,
            include_rawlog=args.include_rawlog,
        )
    except KeyboardInterrupt:
        logger.error("interrupted")
        return 130
    except Exception as exc:  # noqa: BLE001
        logger.exception("refresh failed: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
