#!/usr/bin/env python3
"""XDR tools battery against deployed Cortex_XDR instance.

The MCP exposes tool invocation via JSON-RPC over the FastMCP stream endpoint,
not per-tool REST routes. This battery validates what IS REST-testable:

  • CATALOG_PRESENCE — every expected XDR tool name is in the
    `GET /api/v1/connectors/cortex-xdr/tools` response. Asserts count
    and per-tool presence.

  • TOGGLE_FILTER_PROBE — disables one safe tool via PATCH; confirms
    `disabled: true` in catalog response; re-enables; confirms back.
    Validates the `disabled_tools` filter end-to-end through
    the REST + audit surface.

Individual tool invocation testing belongs in the chat-agent E2E
workflow (operator types prompts, agent picks tools) — that's not
amenable to a deterministic REST probe because LLM tool-selection is
probabilistic. The "did each tool work" validation lives in operator
hands-on smoking + chat-driven test prompts post-deploy.

USAGE (against a running install, on the Docker host):
    MCP_TOKEN=$(docker exec phantom_agent env | grep MCP_TOKEN | cut -d= -f2-)
    INSTANCE_ID=$(docker exec phantom_agent ... | jq -r ".instances[0].id")
    docker exec -i -e MCP_TOKEN="$MCP_TOKEN" -e INSTANCE_ID="$INSTANCE_ID" \\
      phantom_agent python3 - < scripts/e2e_xdr_tools_battery.py

Exit code 0 = catalog complete + toggle probe passes.
"""

from __future__ import annotations

import json
import os
import ssl
import sys
import urllib.request
from typing import Any

# ─── Config + bearer discovery ────────────────────────────────────

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
INSTANCE_ID = os.environ.get("INSTANCE_ID")  # may be None; we discover via REST
SSL_CTX = ssl._create_unverified_context()  # noqa: S323

# ─── Tool classifications ─────────────────────────────────────────


# READ-ONLY: safe to call. Map tool name → kwargs for a no-op call.
SAFE_READS: dict[str, dict[str, Any]] = {
    # Legacy aliases
    "get_cases_and_issues":            {"limit": 1},
    "get_incident_extra_data":         None,  # requires real incident_id; skip-handle
    "get_alerts":                      {"limit": 1},
    "run_xql_query":                   None,  # needs valid XQL + may take time; skip-handle
    "get_xql_results":                 None,  # requires real execution_id; skip-handle
    "list_datasets":                   {"include_empty": False, "probe_timeout_s": 5},

    # Renames (aliases of above)
    "xdr_incidents_list":              {"limit": 1},
    "xdr_incidents_get_extra_data":    None,
    "xdr_alerts_list":                 {"limit": 1},
    "xdr_xql_run_query":               None,
    "xdr_xql_get_results":             None,
    "xdr_xql_list_datasets":           {"include_empty": False, "probe_timeout_s": 5},

    # Endpoint / response / script reads
    "xdr_endpoints_list_all":          {},
    "xdr_endpoints_get":               {"isolate": ["isolated"]},  # filter to isolated subset
    "xdr_response_get_action_status":  None,  # needs real action_id; skip-handle
    "xdr_response_get_file_retrieval_details": None,
    "xdr_scripts_list":                {},
    "xdr_scripts_get_metadata":        None,  # needs real script_uid
    "xdr_scripts_get_execution_status": None,
    "xdr_scripts_get_execution_results": None,
    "xdr_scripts_get_execution_result_files": None,

    # Audit reads
    "xdr_audit_list_management_logs":  {"search_to": 5},
    "xdr_audit_list_agent_logs":       {"search_to": 5},
    "xdr_assets_list":                 {"search_to": 5},
    "xdr_assets_get":                  None,  # needs real asset_id
    "xdr_distribution_list":           {},
    "xdr_distribution_versions":       {},
    "xdr_distribution_get_url":        None,  # needs real distribution_id
    "xdr_alert_exclusions_list":       {"search_to": 5},
    "xdr_hash_get_analytics":          None,  # arbitrary hash → 404 expected; skip
    "xdr_exploits_list":               {"search_to": 5},
    "xdr_exploits_get_details":        None,
}

# DESTRUCTIVE: catalog-presence check only, never invoked.
DESTRUCTIVE = {
    "xdr_endpoints_isolate", "xdr_endpoints_unisolate",
    "xdr_endpoints_scan", "xdr_endpoints_scan_all",
    "xdr_endpoints_set_alias",
    "xdr_endpoints_retrieve_file", "xdr_endpoints_quarantine_file",
    "xdr_download_file",
    "xdr_scripts_run_script", "xdr_scripts_run_snippet",
    "xdr_incidents_update", "xdr_alerts_update",
    "xdr_ioc_insert_json", "xdr_ioc_disable", "xdr_ioc_enable",
    "xdr_distribution_create",
    "xdr_alert_exclusions_create", "xdr_alert_exclusions_delete",
    "xdr_hash_blocklist",
}

# A safe tool used for the toggle-filter probe (disable + re-enable)
PROBE_TOOL = "xdr_assets_list"


# ─── HTTP helpers ─────────────────────────────────────────────────


def mcp_request(method: str, path: str, body: dict | None = None) -> dict:
    url = f"{MCP_BASE}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {TOKEN}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30, context=SSL_CTX) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace")
        return {"_status": e.code, "_body": body_text}


# Individual-tool invocation is intentionally NOT done via this REST loop.
# The MCP uses JSON-RPC over /api/v1/stream/mcp for tool calls; the chat-
# agent E2E workflow is the proper validation path because LLM tool-
# selection is probabilistic and chat-driven. This battery focuses on
# the deterministic REST surface: catalog presence + toggle filter.


# ─── Discovery ────────────────────────────────────────────────────


def discover_instance_id() -> str:
    """Find the Cortex_XDR instance id (REST list-instances + filter)."""
    if INSTANCE_ID:
        return INSTANCE_ID
    resp = mcp_request("GET", "/api/v1/instances?connector_id=cortex-xdr")
    instances = resp.get("instances", []) if isinstance(resp, dict) else []
    if not instances:
        sys.exit("ERROR: no cortex-xdr instances on this install")
    return instances[0]["id"]


def list_catalog_tools() -> list[dict[str, Any]]:
    resp = mcp_request("GET", "/api/v1/connectors/cortex-xdr/tools")
    if not isinstance(resp, dict) or "tools" not in resp:
        sys.exit(f"ERROR: catalog endpoint returned unexpected shape: {resp}")
    return resp["tools"]


# ─── Battery execution ────────────────────────────────────────────


def run_battery() -> tuple[int, int, int]:
    """Returns (passed, skipped, failed)."""
    print("=== XDR tools battery (catalog + toggle probe) ===")
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

    # Expected names from connector.yaml's spec.tools[]
    # (drawn from the xdr_* tools + the 5 original entries — get_alerts is in
    # __all__ but not in connector.yaml, by design: xdr_alerts_list is
    # its marketplace-facing replacement)
    expected_destructive = DESTRUCTIVE
    expected_safe_reads = set(SAFE_READS.keys())
    expected_safe_reads.discard("get_alerts")  # python-only, no yaml entry

    expected_all = expected_destructive | expected_safe_reads
    missing = expected_all - catalog_names
    extras = catalog_names - expected_all

    if missing:
        print(f"  ✗ FAIL  catalog missing {len(missing)} expected tool(s):")
        for t in sorted(missing):
            print(f"      - {t}")
        failed += 1
        fail_details.append(f"catalog missing: {sorted(missing)}")
    else:
        print(f"  ✓ PASS  catalog has all {len(expected_all)} expected tools")
        passed += 1

    if extras:
        print(f"  ⊝ INFO  catalog has {len(extras)} unrecognized tool(s) (newly-added or test-only):")
        for t in sorted(extras):
            print(f"      - {t}")

    # Catalog row classification
    print()
    print("--- Per-tool classification ---")
    for tool in sorted(catalog_names):
        if tool in DESTRUCTIVE:
            print(f"  ⊝ SKIP destructive (catalog ✓)  {tool}")
            skipped += 1
        elif tool in SAFE_READS:
            print(f"  ⊝ SKIP read-only/needs-context (catalog ✓)  {tool}")
            skipped += 1
        else:
            print(f"  ⊝ SKIP unclassified (catalog ✓)  {tool}")
            skipped += 1

    print()
    print("--- Toggle filter probe ---")

    # Probe: disable PROBE_TOOL, confirm it disappears, re-enable, confirm return
    try:
        # Get current disabled_tools
        inst = mcp_request("GET", f"/api/v1/instances/{instance_id}")
        original = (inst.get("instance") or {}).get("disabled_tools", [])

        # Disable PROBE_TOOL
        new_list = sorted(set(original) | {PROBE_TOOL})
        mcp_request("PATCH", f"/api/v1/instances/{instance_id}",
                    body={"disabled_tools": new_list})

        catalog_after = list_catalog_tools()
        names_after = {t["name"] for t in catalog_after}
        tool_entry = next((t for t in catalog_after if t["name"] == PROBE_TOOL), None)
        # The /tools endpoint includes ALL tools but marks `disabled: True`
        # for the disabled ones, by design. Verify both:
        #   - PROBE_TOOL is still in the list (entry exists)
        #   - it shows disabled=True with the instance_id query param
        catalog_with_inst = mcp_request(
            "GET",
            f"/api/v1/connectors/cortex-xdr/tools?instance_id={instance_id}",
        )
        tool_with_inst = next(
            (t for t in (catalog_with_inst.get("tools") or []) if t["name"] == PROBE_TOOL),
            None,
        )
        if tool_with_inst and tool_with_inst.get("disabled") is True:
            print(f"  ✓ PASS disable {PROBE_TOOL!r} → catalog endpoint shows disabled=True")
            passed += 1
        else:
            print(f"  ✗ FAIL disable {PROBE_TOOL!r} → did not surface as disabled in catalog")
            failed += 1
            fail_details.append(f"disable {PROBE_TOOL}: tool_with_inst={tool_with_inst}")

        # Restore original
        mcp_request("PATCH", f"/api/v1/instances/{instance_id}",
                    body={"disabled_tools": original})

        catalog_restored = mcp_request(
            "GET",
            f"/api/v1/connectors/cortex-xdr/tools?instance_id={instance_id}",
        )
        tool_restored = next(
            (t for t in (catalog_restored.get("tools") or []) if t["name"] == PROBE_TOOL),
            None,
        )
        if tool_restored and tool_restored.get("disabled") is False:
            print(f"  ✓ PASS re-enable {PROBE_TOOL!r} → catalog endpoint shows disabled=False")
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
        print()
        print("Failure details:")
        for d in fail_details[:10]:
            print(f"  - {d}")
        if len(fail_details) > 10:
            print(f"  ... and {len(fail_details) - 10} more")

    return passed, skipped, failed


def main() -> int:
    passed, skipped, failed = run_battery()
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
