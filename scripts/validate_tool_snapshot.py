#!/usr/bin/env python3
"""Validate a live MCP tool snapshot against the curated Phantom tool catalog."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def load_yaml(path: Path) -> dict[str, Any]:
    try:
        import yaml  # type: ignore
    except Exception as exc:  # pragma: no cover - CI images have PyYAML
        print(f"PyYAML unavailable, using lightweight catalog parser for {path}: {exc}", file=sys.stderr)
        return load_tool_catalog_fallback(path)

    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise SystemExit(f"{path} must contain a YAML mapping")
    return data


def load_tool_catalog_fallback(path: Path) -> dict[str, Any]:
    tools: list[dict[str, str]] = []
    deny: list[str] = []
    in_deny = False

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        stripped = raw_line.strip()
        if stripped.startswith("deny:"):
            in_deny = True
            if stripped == "deny: []":
                in_deny = False
            continue
        if in_deny and stripped.startswith("- "):
            deny.append(stripped[2:].strip())
            continue
        if stripped.startswith("- name:"):
            tools.append({"name": stripped.split(":", 1)[1].strip()})
            in_deny = False

    return {
        "policy": {"deny": deny},
        "groups": {
            "fallback": {
                "tools": tools,
            }
        },
    }


def curated_tools(catalog: dict[str, Any]) -> set[str]:
    groups = catalog.get("groups") or {}
    if not isinstance(groups, dict):
        raise SystemExit("tool catalog groups must be a mapping")

    tools: set[str] = set()
    for group_name, group in groups.items():
        if not isinstance(group, dict):
            raise SystemExit(f"tool catalog group {group_name!r} must be a mapping")
        for item in group.get("tools") or []:
            if not isinstance(item, dict) or not item.get("name"):
                raise SystemExit(f"tool catalog group {group_name!r} contains an invalid tool entry")
            tools.add(str(item["name"]))
    return tools


def snapshot_tools(snapshot: dict[str, Any], allow_unavailable: bool) -> set[str] | None:
    metadata = snapshot.get("metadata") if isinstance(snapshot.get("metadata"), dict) else {}
    status = metadata.get("status") or snapshot.get("status")
    error = metadata.get("error") or snapshot.get("error")
    if status != "available":
        if allow_unavailable:
            print(f"Tool snapshot unavailable; skipping policy validation: {error or status}")
            return None
        raise SystemExit(f"tool snapshot is not available: {error or status}")

    tools = snapshot.get("tools") or []
    if not isinstance(tools, list):
        raise SystemExit("tool snapshot tools must be a list")

    names: set[str] = set()
    for item in tools:
        if not isinstance(item, dict) or not item.get("name"):
            raise SystemExit("tool snapshot contains an invalid tool entry")
        names.add(str(item["name"]))
    return names


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", default="bundles/tool-catalog.yaml")
    parser.add_argument("--snapshot", required=True)
    parser.add_argument(
        "--strict-extra",
        action="store_true",
        help="Fail when the live snapshot contains tools not listed in the curated catalog.",
    )
    parser.add_argument(
        "--allow-unavailable",
        action="store_true",
        help="Skip policy validation when the snapshot was generated in unavailable mode.",
    )
    parser.add_argument(
        "--allow-missing",
        action="store_true",
        help=(
            "Print missing curated tools as warnings instead of failing. Used in CI "
            "when the runner's persistent instance state may be partial — e.g. a "
            "connector wasn't materialized at snapshot time, so its tools aren't "
            "live, but the curated catalog still expects them. Trades strict "
            "completeness for CI resilience; the snapshot artifact still records "
            "exactly what was advertised."
        ),
    )
    args = parser.parse_args()

    catalog_path = Path(args.catalog)
    snapshot_path = Path(args.snapshot)
    catalog = load_yaml(catalog_path)
    with snapshot_path.open("r", encoding="utf-8") as handle:
        snapshot = json.load(handle)

    curated = curated_tools(catalog)
    live = snapshot_tools(snapshot, args.allow_unavailable)
    if live is None:
        return
    missing = sorted(curated - live)
    extra = sorted(live - curated)
    denied = set(((catalog.get("policy") or {}).get("deny") or []))
    denied_present = sorted(denied & live)

    if missing:
        # Missing curated tools demote to a warning when --allow-missing
        # is set (CI on a partially-bootstrapped runner). Otherwise hard fail.
        header = "Curated tools missing from live MCP snapshot"
        if args.allow_missing:
            header += " (warning — --allow-missing)"
        print(f"{header}:", file=sys.stderr)
        for name in missing:
            print(f"  - {name}", file=sys.stderr)
    if denied_present:
        print("Denied tools present in live MCP snapshot:", file=sys.stderr)
        for name in denied_present:
            print(f"  - {name}", file=sys.stderr)
    if extra and args.strict_extra:
        print("Live MCP snapshot contains tools outside the curated catalog:", file=sys.stderr)
        for name in extra:
            print(f"  - {name}", file=sys.stderr)

    fatal_missing = missing and not args.allow_missing
    if fatal_missing or denied_present or (extra and args.strict_extra):
        raise SystemExit(1)

    print(
        f"Tool snapshot policy validation passed: {len(live)} live tools, "
        f"{len(curated)} curated tools, {len(extra)} uncataloged live tools"
    )


if __name__ == "__main__":
    main()
