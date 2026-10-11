#!/usr/bin/env python3
"""XSIAM tools battery (mirrors the XDR tools battery).

For each of the 59 XSIAM tools, validates:

  • CATALOG_PRESENCE — every expected xsiam_* tool name is in the
    `GET /api/v1/connectors/xsiam/tools` response.

  • TOGGLE_FILTER_PROBE — disables one safe tool via PATCH; confirms
    `disabled: true`; re-enables; confirms back. Validates the
    `disabled_tools` filter for the XSIAM connector instance.

Individual tool invocation tested via chat agent (probabilistic LLM
tool-selection — not amenable to a deterministic REST loop).

USAGE (against a running install, on the Docker host):
    MCP_TOKEN=$(docker exec phantom_agent env | grep MCP_TOKEN | cut -d= -f2-)
    docker exec -i -e MCP_TOKEN="$MCP_TOKEN" \\
      phantom_agent python3 - < scripts/e2e_xsiam_tools_battery.py

Exit 0 = catalog complete + toggle probe passes.
"""

from __future__ import annotations

import json
import os
import ssl
import sys
import urllib.request
from typing import Any

MCP_BASE = os.environ.get("MCP_BASE", "https://127.0.0.1:8080")


def read_mcp_token() -> str:
    token = os.environ.get("MCP_TOKEN")
    if token:
        return token
    try:
        with open("/proc/1/environ", "rb") as f:
            for line in f.read().decode("utf-8", errors="replace").split("\x00"):
                if line.startswith("MCP_TOKEN="):
                    return line[len("MCP_TOKEN="):]
    except Exception:
        pass
    sys.exit("ERROR: MCP_TOKEN not in env and not readable from /proc/1/environ")


TOKEN = read_mcp_token()
INSTANCE_ID = os.environ.get("INSTANCE_ID")
SSL_CTX = ssl._create_unverified_context()  # noqa: S323


# Expected XSIAM tool names (3 categories)
# NOTE: The original 14 xsiam tools are listed in connector.yaml's
# spec.tools[] with BARE names (no xsiam_ prefix); xsiam connector.yaml's
# `functionPrefix: "xsiam_"` makes the agent prepend xsiam_ at registration
# time. The /api/v1/connectors/xsiam/tools endpoint reflects the bare-name
# yaml entries verbatim. The newer tools are authored with explicit xsiam_
# prefix in the yaml `name` field, so they appear as-is.
SAFE_READS = {
    # Existing 14 — bare names per connector.yaml
    "run_xql_query", "get_cases", "send_webhook_log",
    "add_lookup_data", "get_lookup_data", "remove_lookup_data",
    "get_datasets", "create_dataset",
    "find_xql_examples_rag", "get_dataset_fields",
    "get_xql_examples",
    "get_asset_by_id", "get_assets", "get_issues",
    # Incident / alert reads
    "xsiam_incidents_list", "xsiam_alerts_list",
    # Endpoint / script reads
    "xsiam_endpoints_list_all", "xsiam_endpoints_get",
    "xsiam_scripts_list",
    # Audit / distribution reads
    "xsiam_audit_list_management_logs", "xsiam_audit_list_agent_logs",
    "xsiam_distribution_list", "xsiam_distribution_versions",
    "xsiam_alert_exclusions_list",
    "xsiam_exploits_list",
    "xsiam_parsers_list",
    "xsiam_broker_list",
}

DESTRUCTIVE = {
    # Incident / alert / IOC writes
    "xsiam_incidents_update", "xsiam_alerts_update",
    "xsiam_ioc_insert_json", "xsiam_ioc_disable", "xsiam_ioc_enable",
    "xsiam_download_file",
    # Endpoint / script writes
    "xsiam_endpoints_isolate", "xsiam_endpoints_unisolate",
    "xsiam_endpoints_scan", "xsiam_endpoints_scan_all",
    "xsiam_endpoints_set_alias",
    "xsiam_endpoints_retrieve_file", "xsiam_endpoints_quarantine_file",
    "xsiam_scripts_run_script", "xsiam_scripts_run_snippet",
    # Distribution / exclusion writes
    "xsiam_distribution_create",
    "xsiam_alert_exclusions_create", "xsiam_alert_exclusions_delete",
    "xsiam_hash_blocklist",
}

NEEDS_CONTEXT = {
    # Existing + new tools requiring per-tenant ids we don't know in the battery
    "xsiam_incidents_get_extra_data",  # needs incident_id
    "xsiam_response_get_action_status",  # needs action_id
    "xsiam_response_get_file_retrieval_details",
    "xsiam_scripts_get_metadata",
    "xsiam_scripts_get_execution_status",
    "xsiam_scripts_get_execution_results",
    "xsiam_scripts_get_execution_result_files",
    "xsiam_hash_get_analytics",  # arbitrary hash → 404 expected
    "xsiam_exploits_get_details",
    "xsiam_parsers_get",
    "xsiam_datamodel_describe",  # XSIAM-licensed; may fail on XDR-only tenant
    "xsiam_broker_get",
}

PROBE_TOOL = "xsiam_alert_exclusions_list"


def mcp_request(method: str, path: str, body: dict | None = None) -> dict:
    url = f"{MCP_BASE}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {TOKEN}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30, context=SSL_CTX) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace")
        return {"_status": e.code, "_body": body_text}


def discover_instance_id() -> str:
    if INSTANCE_ID:
        return INSTANCE_ID
    resp = mcp_request("GET", "/api/v1/instances?connector_id=xsiam")
    instances = resp.get("instances", []) if isinstance(resp, dict) else []
    if not instances:
        sys.exit("ERROR: no xsiam instances on this install — create one + retry")
    return instances[0]["id"]


def list_catalog_tools() -> list[dict[str, Any]]:
    resp = mcp_request("GET", "/api/v1/connectors/xsiam/tools")
    if not isinstance(resp, dict) or "tools" not in resp:
        sys.exit(f"ERROR: catalog endpoint unexpected: {resp}")
    return resp["tools"]


def run_battery() -> tuple[int, int, int]:
    print("=== XSIAM tools battery (catalog + toggle probe) ===")
    print(f"MCP_BASE={MCP_BASE}")

    instance_id = discover_instance_id()
    print(f"instance_id={instance_id}")

    catalog = list_catalog_tools()
    catalog_names = {t["name"] for t in catalog}
    print(f"catalog_tools={len(catalog)}")
    print()

    passed = 0
    skipped = 0
    failed = 0
    fail_details: list[str] = []

    expected_all = SAFE_READS | DESTRUCTIVE | NEEDS_CONTEXT
    missing = expected_all - catalog_names
    extras = catalog_names - expected_all

    if missing:
        print(f"  ✗ FAIL  catalog missing {len(missing)} expected tools:")
        for t in sorted(missing):
            print(f"      - {t}")
        failed += 1
        fail_details.append(f"missing: {sorted(missing)}")
    else:
        print(f"  ✓ PASS  catalog has all {len(expected_all)} expected XSIAM tools")
        passed += 1

    if extras:
        print(f"  ⊝ INFO  {len(extras)} unrecognized tool(s):")
        for t in sorted(extras):
            print(f"      - {t}")

    print()
    print("--- Per-tool classification ---")
    for tool in sorted(catalog_names):
        cls = "destructive" if tool in DESTRUCTIVE else ("read-only" if tool in SAFE_READS else "needs-context")
        print(f"  ⊝ SKIP {cls} (catalog ✓)  {tool}")
        skipped += 1

    print()
    print("--- Toggle filter probe ---")
    try:
        inst = mcp_request("GET", f"/api/v1/instances/{instance_id}")
        original = (inst.get("instance") or {}).get("disabled_tools", [])

        new_list = sorted(set(original) | {PROBE_TOOL})
        mcp_request("PATCH", f"/api/v1/instances/{instance_id}",
                    body={"disabled_tools": new_list})
        catalog_with_inst = mcp_request("GET",
            f"/api/v1/connectors/xsiam/tools?instance_id={instance_id}")
        tool_with_inst = next(
            (t for t in (catalog_with_inst.get("tools") or []) if t["name"] == PROBE_TOOL),
            None,
        )
        if tool_with_inst and tool_with_inst.get("disabled") is True:
            print(f"  ✓ PASS disable {PROBE_TOOL!r} → catalog shows disabled=True")
            passed += 1
        else:
            print(f"  ✗ FAIL disable {PROBE_TOOL!r}")
            failed += 1

        mcp_request("PATCH", f"/api/v1/instances/{instance_id}",
                    body={"disabled_tools": original})
        catalog_restored = mcp_request("GET",
            f"/api/v1/connectors/xsiam/tools?instance_id={instance_id}")
        tool_restored = next(
            (t for t in (catalog_restored.get("tools") or []) if t["name"] == PROBE_TOOL),
            None,
        )
        if tool_restored and tool_restored.get("disabled") is False:
            print(f"  ✓ PASS re-enable {PROBE_TOOL!r} → catalog shows disabled=False")
            passed += 1
        else:
            print(f"  ✗ FAIL re-enable {PROBE_TOOL!r}")
            failed += 1
    except Exception as e:
        print(f"  ✗ FAIL toggle probe → {type(e).__name__}: {e}")
        failed += 1
        fail_details.append(f"toggle probe: {e}")

    print()
    print(f"=== SUMMARY: {passed} passed, {skipped} skipped, {failed} failed ===")
    if fail_details:
        print("\nFailure details:")
        for d in fail_details[:10]:
            print(f"  - {d}")

    return passed, skipped, failed


def main() -> int:
    passed, skipped, failed = run_battery()
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
