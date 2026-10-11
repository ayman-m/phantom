#!/usr/bin/env python3
"""Fetch demisto/content modeling + parsing
rules for each of our bundled data sources.

# Why

Pulls modeling-rule .xif files to backfill XDM-derived field
descriptions, and ALSO parsing-rule .xif files. The parsing
rule is the key to categorizing each pack's ingest pattern:

  Scenario 1 — Generic raw syslog. Parsing rule contains
              `parse_X(_raw_log)` (or `parse_Y_log_to_json(...)`),
              the dataset schema declares just `_raw_log` + `_json`.
              Cisco ASA is the canonical example. Every nested key
              is accessed at query time via XQL `_json -> X.Y`.

  Scenario 2 — Pre-parsed wire format (CEF / LEEF / Syslog
              key=value). Parsing rule is trivial or absent — the
              broker / XSIAM HTTP collector pre-extracts fields
              before they hit the dataset. Schema declares typed
              columns directly.

  Scenario 3 — HTTP-collector raw JSON. Parsing rule references
              `_raw_json` (or the dataset schema declares
              `_raw_json` as the source column). The collector
              forwards the JSON body verbatim; XQL accesses keys
              via `_raw_json -> X.Y` similar to Scenario 1 but with
              a different source column name.

  Scenario 4 — API / DB direct mapping. No parsing rule at all
              (or one that's strictly XDM-only). Dataset schema
              declares every native column; nothing to parse out
              of an opaque blob.

The categorization is mechanical once both rule families are on disk
locally — a future companion script will walk these files and tag
each pack with its ingest scenario.

# What this script does

For each unique (pack_name, modeling_rule_name) pair derived from our
bundled `data_source.yaml` files:

  1. Modeling rule
       GET raw.githubusercontent.com/.../Packs/<pack>/ModelingRules/
           <modeling_rule>/<modeling_rule>.xif
       → scripts/maintainer/modeling_rules/<pack>__<rule>.xif

  2. Parsing rule — name need not match modeling-rule name. Two-pass:
     (a) Try the modeling-rule name as the parsing-rule name first
         (the common case: same suffix `_1_3`, etc.).
     (b) On 404, list the pack's ParsingRules/ directory via the
         GitHub Contents API. If exactly one entry, use it. If
         multiple, fetch each (one file per parsing-rule directory).
     → scripts/maintainer/parsing_rules/<pack>__<parsing_rule>.xif

     Some packs have NO ParsingRules directory at all — recorded as
     `no_parsing_rule` in the manifest (signal for Scenario 2/4
     categorization).

A manifest (`_manifest.json` per directory) summarizes coverage.

# Run

    python3 scripts/fetch_demisto_modeling_rules.py            # fetch both, use cache
    python3 scripts/fetch_demisto_modeling_rules.py --refresh  # ignore cache
    python3 scripts/fetch_demisto_modeling_rules.py --only modeling  # only modeling rules
    python3 scripts/fetch_demisto_modeling_rules.py --only parsing   # only parsing rules

The script is polite to unauthenticated GitHub: 0.1s delay between
fetches, gracefully skips on transient errors. With a personal token
in `GH_TOKEN`/`GITHUB_TOKEN` it uses the higher 5000/hour limit.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
BUNDLE_ROOT = REPO_ROOT / "bundles" / "spark" / "data-sources"
MAINTAINER_ROOT = REPO_ROOT / "scripts" / "maintainer"
MODELING_OUTPUT = MAINTAINER_ROOT / "modeling_rules"
PARSING_OUTPUT = MAINTAINER_ROOT / "parsing_rules"

BRANCH = "master"
RAW_BASE = f"https://raw.githubusercontent.com/demisto/content/{BRANCH}/Packs"
API_BASE = f"https://api.github.com/repos/demisto/content/contents/Packs"

FETCH_DELAY_S = 0.1


def _gh_token() -> str | None:
    """Read a GitHub PAT from the environment if available — pushes
    the unauthenticated 60/hour quota up to 5000/hour for the Contents
    API calls."""
    return (
        os.environ.get("GH_TOKEN")
        or os.environ.get("GITHUB_TOKEN")
    )


def _request(url: str, accept: str = "text/plain") -> tuple[bytes, int]:
    """Generic HTTP GET wrapper. Returns (body, status). status=0 on
    network error, otherwise the HTTP response code."""
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "phantom-rule-fetcher/0.17.75",
            "Accept": accept,
        },
    )
    token = _gh_token()
    if token and "api.github.com" in url:
        # Only attach the token to the API calls. raw.githubusercontent
        # serves public CDN content; no auth needed and the PAT does
        # nothing useful there.
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read(), 200
    except urllib.error.HTTPError as e:
        return b"", e.code
    except (urllib.error.URLError, TimeoutError) as e:
        sys.stderr.write(f"  ! network error for {url}: {e}\n")
        return b"", 0


def read_yaml_header(yaml_path: Path) -> dict[str, str]:
    """Extract pack_name + rule_name + dataset_name from the YAML
    header. Top-level scalar parse only — avoids the PyYAML dep."""
    header: dict[str, str] = {}
    for line in yaml_path.read_text().split("\n"):
        if not line or line.startswith(" "):
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        value = value.strip()
        if key in ("pack_name", "rule_name", "dataset_name"):
            header[key] = value
        if {"pack_name", "rule_name", "dataset_name"}.issubset(header):
            break
    return header


# ─── Modeling rules ───────────────────────────────────────────────

def fetch_modeling_rule(pack: str, rule: str) -> tuple[bytes, int]:
    url = f"{RAW_BASE}/{pack}/ModelingRules/{rule}/{rule}.xif"
    return _request(url)


def run_modeling(pairs: list[tuple[str, str]], refresh: bool) -> dict[str, Any]:
    """Fetch every modeling rule. Factored out so we can run modeling +
    parsing back-to-back."""
    MODELING_OUTPUT.mkdir(parents=True, exist_ok=True)
    stats: dict[str, Any] = {
        "fetched": 0, "cached": 0, "not_found": 0, "errors": 0,
        "errors_detail": [],
    }
    for (pack, rule) in pairs:
        out_path = MODELING_OUTPUT / f"{pack}__{rule}.xif"
        if out_path.is_file() and out_path.stat().st_size > 0 and not refresh:
            stats["cached"] += 1
            continue
        body, status = fetch_modeling_rule(pack, rule)
        if status == 200 and body:
            out_path.write_bytes(body)
            stats["fetched"] += 1
            if stats["fetched"] % 20 == 0:
                print(f"  modeling: ... fetched {stats['fetched']}")
            time.sleep(FETCH_DELAY_S)
        elif status == 404:
            stats["not_found"] += 1
            stats["errors_detail"].append(f"404 {pack}/{rule}")
        else:
            stats["errors"] += 1
            stats["errors_detail"].append(f"err({status}) {pack}/{rule}")

    # Write the modeling-rule manifest
    existing = sorted(p.stem for p in MODELING_OUTPUT.glob("*.xif"))
    (MODELING_OUTPUT / "_manifest.json").write_text(json.dumps({
        "total_pairs": len(pairs),
        "have_xif": len(existing),
        "missing_pairs": [
            f"{p}__{r}" for (p, r) in pairs
            if not (MODELING_OUTPUT / f"{p}__{r}.xif").is_file()
        ],
        "fetched_branch": BRANCH,
    }, indent=2, sort_keys=True) + "\n")
    return stats


# ─── Parsing rules ────────────────────────────────────────────────

def list_parsing_rule_dirs(pack: str) -> tuple[list[str], int]:
    """List the directory names inside Packs/<pack>/ParsingRules via
    the GitHub Contents API. Returns ([dir_names], status_code).

    status=404 → the pack has no ParsingRules directory at all
                 (a strong Scenario-2/4 signal).
    status=200 → list of subdirectory names. Each is a parsing-rule
                 directory containing a `<name>.xif` file.
    """
    url = f"{API_BASE}/{pack}/ParsingRules?ref={BRANCH}"
    body, status = _request(url, accept="application/vnd.github.v3+json")
    if status != 200:
        return [], status
    try:
        entries = json.loads(body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return [], 0
    return [
        e["name"] for e in entries
        if isinstance(e, dict) and e.get("type") == "dir"
    ], 200


def fetch_parsing_rule(pack: str, parsing_rule_name: str) -> tuple[bytes, int]:
    url = (
        f"{RAW_BASE}/{pack}/ParsingRules/"
        f"{parsing_rule_name}/{parsing_rule_name}.xif"
    )
    return _request(url)


def run_parsing(pairs: list[tuple[str, str]], refresh: bool) -> dict[str, Any]:
    """For each unique pack:
      1. Try the modeling-rule name as the parsing-rule name first
         (cheap raw fetch — no API quota cost).
      2. On 404, list ParsingRules/ via the Contents API.
      3. If the directory has exactly one entry, fetch that. If
         multiple, fetch all (different ingest paths share one pack).

    Records `no_parsing_rule` in the manifest when the directory
    itself is 404 — that's the Scenario-2/4 signal.
    """
    PARSING_OUTPUT.mkdir(parents=True, exist_ok=True)
    # Many YAMLs share a pack — we only need to enumerate ParsingRules
    # once per pack. Use the first rule_name we see as the seed for
    # the cheap fallback fetch.
    pack_seen: dict[str, str] = {}
    for (pack, rule) in pairs:
        pack_seen.setdefault(pack, rule)

    stats: dict[str, Any] = {
        "fetched": 0,
        "cached": 0,
        "no_parsing_rule": 0,    # 404 on the directory itself (S2/S4 signal)
        "errors": 0,
        "errors_detail": [],
        "fetched_files": [],     # for the per-pack manifest
        "no_parsing_packs": [],
    }

    total_packs = len(pack_seen)
    for i, (pack, seed_rule) in enumerate(sorted(pack_seen.items())):
        if (i + 1) % 25 == 0:
            print(f"  parsing: ... {i+1}/{total_packs} packs scanned")

        # Step 1: cheap try — assume the parsing rule has the same name
        # as the modeling rule. Skip if already cached.
        same_name_out = PARSING_OUTPUT / f"{pack}__{seed_rule}.xif"
        if (
            same_name_out.is_file()
            and same_name_out.stat().st_size > 0
            and not refresh
        ):
            stats["cached"] += 1
            stats["fetched_files"].append(same_name_out.stem)
            continue

        body, status = fetch_parsing_rule(pack, seed_rule)
        if status == 200 and body:
            same_name_out.write_bytes(body)
            stats["fetched"] += 1
            stats["fetched_files"].append(same_name_out.stem)
            time.sleep(FETCH_DELAY_S)
            continue

        # Step 2: list the ParsingRules directory.
        dir_names, list_status = list_parsing_rule_dirs(pack)
        if list_status == 404:
            stats["no_parsing_rule"] += 1
            stats["no_parsing_packs"].append(pack)
            time.sleep(FETCH_DELAY_S)
            continue
        if list_status != 200:
            stats["errors"] += 1
            stats["errors_detail"].append(
                f"list-err({list_status}) {pack}"
            )
            time.sleep(FETCH_DELAY_S)
            continue
        if not dir_names:
            # Empty ParsingRules directory (unusual but possible)
            stats["no_parsing_rule"] += 1
            stats["no_parsing_packs"].append(pack)
            continue

        # Step 3: fetch each directory listed.
        for dn in dir_names:
            out = PARSING_OUTPUT / f"{pack}__{dn}.xif"
            if (
                out.is_file()
                and out.stat().st_size > 0
                and not refresh
            ):
                stats["cached"] += 1
                stats["fetched_files"].append(out.stem)
                continue
            body, status = fetch_parsing_rule(pack, dn)
            if status == 200 and body:
                out.write_bytes(body)
                stats["fetched"] += 1
                stats["fetched_files"].append(out.stem)
                time.sleep(FETCH_DELAY_S)
            elif status == 404:
                # ParsingRules/<dn>/ exists in the listing but the .xif
                # name doesn't match the directory name. Rare; record
                # under errors so a maintainer can inspect.
                stats["errors"] += 1
                stats["errors_detail"].append(
                    f"404-xif {pack}/ParsingRules/{dn}/{dn}.xif"
                )
            else:
                stats["errors"] += 1
                stats["errors_detail"].append(
                    f"err({status}) {pack}/ParsingRules/{dn}"
                )

    # Write the parsing-rule manifest
    existing = sorted(p.stem for p in PARSING_OUTPUT.glob("*.xif"))
    (PARSING_OUTPUT / "_manifest.json").write_text(json.dumps({
        "total_packs_scanned": total_packs,
        "have_xif": len(existing),
        "no_parsing_rule_packs": sorted(stats["no_parsing_packs"]),
        "fetched_branch": BRANCH,
    }, indent=2, sort_keys=True) + "\n")
    return stats


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--refresh", action="store_true",
        help="Ignore local cache and re-fetch every .xif",
    )
    parser.add_argument(
        "--only", choices=("modeling", "parsing", "both"),
        default="both",
        help="Limit which rule family to fetch (default: both)",
    )
    parser.add_argument(
        "--limit", type=int, default=0,
        help="Stop after this many (pack, rule) pairs (0 = no limit)",
    )
    args = parser.parse_args()

    yaml_paths = sorted(BUNDLE_ROOT.glob("*/data_source.yaml"))
    print("=== Fetching demisto/content rules ===")
    print(f"  bundle root      : {BUNDLE_ROOT}")
    print(f"  modeling output  : {MODELING_OUTPUT}")
    print(f"  parsing output   : {PARSING_OUTPUT}")
    print(f"  yaml count       : {len(yaml_paths)}")
    print(f"  gh token         : {'set' if _gh_token() else 'unset (60/hr limit)'}")
    print()

    pair_to_yaml: dict[tuple[str, str], Path] = {}
    for yp in yaml_paths:
        h = read_yaml_header(yp)
        pack = h.get("pack_name")
        rule = h.get("rule_name")
        if not (pack and rule):
            continue
        key = (pack, rule)
        if key not in pair_to_yaml:
            pair_to_yaml[key] = yp

    pairs = sorted(pair_to_yaml.keys())
    if args.limit:
        pairs = pairs[: args.limit]
    print(f"  unique (pack, rule) pairs : {len(pairs)}")
    print()

    modeling_stats = None
    parsing_stats = None

    if args.only in ("modeling", "both"):
        print("--- Modeling rules ---")
        modeling_stats = run_modeling(pairs, args.refresh)
        print()
        print("  cached      :", modeling_stats["cached"])
        print("  fetched     :", modeling_stats["fetched"])
        print("  not_found   :", modeling_stats["not_found"])
        print("  errors      :", modeling_stats["errors"])
        print()

    if args.only in ("parsing", "both"):
        print("--- Parsing rules ---")
        parsing_stats = run_parsing(pairs, args.refresh)
        print()
        print("  cached            :", parsing_stats["cached"])
        print("  fetched           :", parsing_stats["fetched"])
        print("  no_parsing_rule   :", parsing_stats["no_parsing_rule"])
        print("  errors            :", parsing_stats["errors"])
        if parsing_stats["errors_detail"][:5]:
            print("  first issues:")
            for e in parsing_stats["errors_detail"][:10]:
                print(f"    -", e)
        print()

    print("=== Done fetching ===")
    if modeling_stats:
        m_existing = sorted(p.stem for p in MODELING_OUTPUT.glob("*.xif"))
        print(f"  modeling .xif files on disk: {len(m_existing)}/{len(pairs)}")
    if parsing_stats:
        p_existing = sorted(p.stem for p in PARSING_OUTPUT.glob("*.xif"))
        # Note: parsing-rule count is per unique PACK, not per pair —
        # one pack can have multiple parsing rules (one per ingest path).
        unique_packs = len({p for p, _ in pairs})
        print(
            f"  parsing  .xif files on disk: {len(p_existing)} "
            f"(across {unique_packs} unique packs; "
            f"{parsing_stats['no_parsing_rule']} packs have no ParsingRules dir)"
        )

    # After fetching the flat folders, reorganize into the
    # per-dataset tree so the operator can see at a glance which packs
    # need broker-applet setup (raw_log_based) vs which work out of the
    # box (direct_mapped). See organize_rules_by_dataset.py for details.
    print()
    print("=== Reorganizing rules by dataset ===")
    try:
        # Import + invoke directly so we share the process — keeps the
        # output ordered + lets us surface failures.
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "organize_rules_by_dataset",
            Path(__file__).resolve().parent / "organize_rules_by_dataset.py",
        )
        if spec and spec.loader:
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            mod.main()
        else:
            print("  WARN: could not load organize_rules_by_dataset.py — "
                  "run it manually with `python3 scripts/organize_rules_by_dataset.py`")
    except Exception as exc:  # noqa: BLE001
        print(f"  WARN: organize step failed: {exc}")
        print("  Re-run manually: python3 scripts/organize_rules_by_dataset.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
