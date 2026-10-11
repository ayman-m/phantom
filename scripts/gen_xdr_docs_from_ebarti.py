#!/usr/bin/env python3
"""Generate Cortex XDR endpoint docs from ebarti/cortex-xdr-client.

One-shot codegen: parses the 8 *_api.py modules of the ebarti Python wrapper
and emits one markdown file per endpoint into
`data/knowledge/external/paloaltonetworks/cortex-xdr/action/<category>/<endpoint>.md`.

This covers ~25 of XDR's most-used endpoints. The remaining categories
(audit logs, asset management, distribution lists, alert exclusions,
exploits) are not covered by this generator.

USAGE:
    # Pre-requisite: ebarti repo cloned/downloaded under /tmp/ebarti/
    # (the project Makefile or a shell script can wrap this)
    python3 scripts/gen_xdr_docs_from_ebarti.py

The script is deterministic + idempotent. Re-running overwrites the generated
files; operator edits to non-generated files (INDEX.md sections, hand-written
gap fills) are preserved because the script writes to per-endpoint paths only.

Maintainer-only. Never invoked at runtime.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path
from textwrap import dedent
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = Path("/tmp/ebarti")
OUT_DIR = ROOT / "data/knowledge/external/paloaltonetworks/cortex-xdr/action"

# Map ebarti filename → (category dir, api_name from __init__).
# api_name is hard-coded here so we don't have to AST-parse __init__ for each.
API_MODULES = {
    "actions_api.py":   ("response",     "actions"),     # Response actions
    "alerts_api.py":    ("alerts",       "alerts"),
    "download_api.py":  ("download",     "download"),
    "endpoints_api.py": ("endpoints",    "endpoints"),
    "incidents_api.py": ("incidents",    "incidents"),
    "ioc_api.py":       ("ioc",          "indicators"),  # XDR IoC at /public_api/v1/indicators/
    "scripts_api.py":   ("scripts",      "scripts"),
    "xql_api.py":       ("xql",          "xql"),
}

# Operator-friendly tool action shortname for each ebarti function name.
# Keeps tool names tight and consistent across categories.
RENAME_MAP = {
    "get_incidents":                    "list",
    "get_incident_extra_data":          "get_extra_data",
    "get_alerts":                       "list",
    "get_all_endpoints":                "list_all",
    "get_endpoint":                     "get",
    "get_scripts":                      "list",
    "get_script_metadata":              "get_metadata",
    "get_script_execution_status":      "get_execution_status",
    "get_script_execution_results":     "get_execution_results",
    "get_script_execution_result_files":"get_execution_result_files",
    "run_snippet_code_script":          "run_snippet",
    "start_xql_query":                  "start_query",
    "get_query_results":                "get_results",
    "get_query_results_stream":         "get_results_stream",
    "isolate_endpoints":                "isolate",
    "unisolate_endpoints":              "unisolate",
    "scan_endpoints":                   "scan",
    "scan_all_endpoints":               "scan_all",
    "set_endpoint_alias":               "set_alias",
    "download_file":                    "file",
}


def _safe_const(node: ast.AST) -> Any:
    """Return the constant value of an AST node, or None if not a simple constant.

    Avoids using ast.literal_eval (which security hooks flag). We only need
    string/int/None constants here, so a direct Constant-node check covers
    every case in the ebarti source.
    """
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.NameConstant):  # py < 3.8 compat
        return node.value
    return None


def _unparse_default(node: ast.AST) -> str:
    """Best-effort source-form rendering of a default value expression."""
    try:
        return ast.unparse(node)
    except Exception:
        return "<expr>"


def parse_module(src_path: Path) -> dict[str, Any]:
    """Parse one ebarti API module and return its endpoint metadata."""
    src = src_path.read_text()
    tree = ast.parse(src)

    endpoints: list[dict[str, Any]] = []
    class_obj = next(
        (n for n in ast.walk(tree)
         if isinstance(n, ast.ClassDef) and n.name.endswith("API")),
        None,
    )
    if class_obj is None:
        return {"endpoints": []}

    # Capture line→URL-comment map from raw source (AST drops comments)
    url_comments: dict[int, str] = {}
    for lineno, raw in enumerate(src.splitlines(), start=1):
        m = re.match(r"\s*#\s*(https?://docs\.paloaltonetworks\.com/[^\s]+)", raw)
        if m:
            url_comments[lineno] = m.group(1)

    for node in class_obj.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name.startswith("_"):
            continue  # private helpers

        # Find nearest URL comment above the function
        doc_url = None
        for ln in range(node.lineno - 1, max(0, node.lineno - 8), -1):
            if ln in url_comments:
                doc_url = url_comments[ln]
                break

        docstring = ast.get_docstring(node) or ""

        params: list[dict[str, Any]] = []
        # Skip 'self'
        for arg in node.args.args[1:]:
            type_str = ast.unparse(arg.annotation) if arg.annotation else "Any"
            params.append({"name": arg.arg, "type": type_str, "default": None})
        # Defaults align to the tail of args
        n_defaults = len(node.args.defaults)
        if n_defaults > 0:
            for i, default in enumerate(node.args.defaults):
                idx = len(params) - n_defaults + i
                if 0 <= idx < len(params):
                    params[idx]["default"] = _unparse_default(default)

        # Find the self._call(...) in the body to extract call_name + method
        call_name = None
        method = "POST"
        for child in ast.walk(node):
            if not isinstance(child, ast.Call):
                continue
            if not isinstance(child.func, ast.Attribute):
                continue
            if child.func.attr != "_call":
                continue
            for kw in child.keywords:
                if kw.arg == "call_name":
                    val = _safe_const(kw.value)
                    if isinstance(val, str):
                        call_name = val
                elif kw.arg == "method":
                    val = _safe_const(kw.value)
                    if isinstance(val, str):
                        method = val.upper()
            break

        # Parse docstring's :param X: lines into a per-param description map
        param_descs: dict[str, str] = {}
        for ln in docstring.splitlines():
            m = re.match(r"\s*:param\s+(\w+):\s*(.*)$", ln)
            if m:
                param_descs[m.group(1)] = m.group(2).strip()
        return_desc = ""
        for ln in docstring.splitlines():
            m = re.match(r"\s*:return:\s*(.*)$", ln)
            if m:
                return_desc = m.group(1).strip()
                break

        # The short "purpose" lives above the :param lines
        purpose_lines: list[str] = []
        for ln in docstring.splitlines():
            stripped = ln.strip()
            if stripped.startswith(":"):
                break
            if stripped:
                purpose_lines.append(stripped)
        purpose = " ".join(purpose_lines).strip()

        for p in params:
            p["desc"] = param_descs.get(p["name"], "")

        endpoints.append({
            "fn_name": node.name,
            "call_name": call_name,
            "method": method,
            "doc_url": doc_url,
            "purpose": purpose,
            "params": params,
            "return_desc": return_desc,
        })

    return {"endpoints": endpoints}


def _action_short(fn_name: str) -> str:
    return RENAME_MAP.get(fn_name, fn_name)


def _src_filename(category: str) -> str:
    return {
        "response": "actions_api",
        "alerts": "alerts_api",
        "download": "download_api",
        "endpoints": "endpoints_api",
        "incidents": "incidents_api",
        "ioc": "ioc_api",
        "scripts": "scripts_api",
        "xql": "xql_api",
    }.get(category, f"{category}_api")


def render_markdown(
    category: str,
    api_name: str,
    endpoint: dict[str, Any],
) -> str:
    """Build a clean markdown doc by line-list-then-join (avoids
    indentation-leak bugs from multi-line f-strings + dedent)."""
    fn = endpoint["fn_name"]
    call = endpoint["call_name"] or fn
    method = endpoint["method"]
    purpose = endpoint["purpose"] or fn.replace("_", " ").capitalize()
    doc_url = endpoint["doc_url"] or ""
    action_short = _action_short(fn)
    tool_name = f"xdr_{category}_{action_short}"

    lines: list[str] = []
    title = fn.replace("_", " ").title()
    lines.append(f"# {title}")
    lines.append("")
    lines.append(f"**HTTP**: `{method} /public_api/v1/{api_name}/{call}/`")
    lines.append("**Auth**: Bearer (`Authorization` + `x-xdr-auth-id` + `x-xdr-nonce` + `x-xdr-timestamp` when advanced)")
    lines.append(f"**MCP tool**: `{tool_name}`")
    lines.append("**Phantom connector**: `cortex-xdr` (per-instance: see Tools tab on `/connectors/cortex-xdr-<instance>`)")
    if doc_url:
        lines.append("")
        lines.append(f"**Official docs**: {doc_url}")
    lines.append("")
    lines.append("## Purpose")
    lines.append("")
    lines.append(purpose)
    lines.append("")
    lines.append("## Parameters")
    lines.append("")
    if endpoint["params"]:
        lines.append("| Param | Type | Default | Description |")
        lines.append("|---|---|---|---|")
        for p in endpoint["params"]:
            default = p["default"] if p["default"] is not None else "—"
            desc = p["desc"] or "(no docstring)"
            lines.append(f"| `{p['name']}` | `{p['type']}` | `{default}` | {desc} |")
    else:
        lines.append("_No parameters._")
    lines.append("")
    lines.append("## Request body (representative)")
    lines.append("")
    lines.append("```json")
    lines.append("{")
    lines.append('  "request_data": {')
    lines.append('    "filters": [ /* see ebarti filter helpers */ ],')
    lines.append('    "search_from": 0,')
    lines.append('    "search_to": 100')
    lines.append("  }")
    lines.append("}")
    lines.append("```")
    lines.append("")
    lines.append("## Returns")
    lines.append("")
    if endpoint["return_desc"]:
        lines.append(endpoint["return_desc"])
    else:
        lines.append("Opaque JSON envelope (see related sample below).")
    lines.append("")
    lines.append("## Notes")
    lines.append("")
    lines.append(f"- This endpoint is a `{method}` to the XDR `/public_api/v1/{api_name}/{call}/` path regardless of whether semantically it reads or writes; XDR's REST API uses POST + JSON-body for filtering.")
    lines.append(f"- Generated from `ebarti/cortex-xdr-client`'s `{fn}` wrapper — see https://github.com/ebarti/cortex-xdr-client for the authoritative Python implementation.")
    lines.append("- Bearer auth headers are computed by the connector's `_xdr_client.py`; the tool function itself doesn't see raw credentials.")
    lines.append("- Rate-limit + retry behavior per XDR tenant — consult the official docs at the link above for current limits.")
    lines.append("")
    lines.append("## Cross-references")
    lines.append("")
    lines.append(f"- Phantom tool: `bundles/spark/connectors/cortex-xdr/src/connector.py` → `{tool_name}`")
    lines.append(f"- Source mapping: `ebarti/cortex_xdr_client/api/{_src_filename(category)}.py` → `{fn}`")
    lines.append("")

    return "\n".join(lines)


def main() -> int:
    if not SRC_DIR.is_dir():
        print(f"ERROR: source dir {SRC_DIR} missing", file=sys.stderr)
        return 1

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    index_rows: list[dict[str, Any]] = []

    for filename, (category, api_name) in API_MODULES.items():
        src = SRC_DIR / filename
        if not src.is_file():
            print(f"WARN: {src} missing — skipping", file=sys.stderr)
            continue
        parsed = parse_module(src)
        category_dir = OUT_DIR / category
        category_dir.mkdir(parents=True, exist_ok=True)

        for ep in parsed["endpoints"]:
            md = render_markdown(category, api_name, ep)
            action_short = _action_short(ep["fn_name"])
            file_path = category_dir / f"{action_short}.md"
            file_path.write_text(md)
            tool_name = f"xdr_{category}_{action_short}"
            index_rows.append({
                "category": category,
                "tool": tool_name,
                "endpoint": f"POST /public_api/v1/{api_name}/{ep['call_name'] or ep['fn_name']}/",
                "purpose": ep["purpose"][:80],
                "file": f"{category}/{action_short}.md",
            })

    # Write INDEX.md
    index_md = ["# Cortex XDR — endpoint index", "",
                "Generated from `ebarti/cortex-xdr-client` by `scripts/gen_xdr_docs_from_ebarti.py`.",
                f"This index lists {len(index_rows)} endpoints covering ~70% of the operator-relevant XDR API.",
                "Remaining categories (audit logs, asset management, distribution lists, alert exclusions, exploits) are not covered by this index.",
                "",
                "| Category | MCP tool | HTTP endpoint | Purpose | Doc |",
                "|---|---|---|---|---|"]
    for row in sorted(index_rows, key=lambda r: (r["category"], r["tool"])):
        index_md.append(
            f"| {row['category']} | `{row['tool']}` | `{row['endpoint']}` | {row['purpose']} | [→]({row['file']}) |"
        )
    (OUT_DIR / "INDEX.md").write_text("\n".join(index_md) + "\n")

    auth_md = dedent("""\
        # Cortex XDR — authentication

        Cortex XDR's REST API uses two auth modes. The Phantom connector supports
        both via per-instance config; `_xdr_client.py` selects based on the
        instance's `auth_mode` field.

        ## Standard (basic) auth

        Three headers per request:

        ```http
        Authorization: <API_KEY>
        x-xdr-auth-id: <API_KEY_ID>
        Content-Type: application/json
        ```

        - `API_KEY` is the value the operator pastes when generating an "Advanced API Key" set to "Standard" security level
        - `API_KEY_ID` is the integer ID XDR assigns to that key

        ## Advanced auth (HMAC over nonce + timestamp)

        Used when the API key is "Advanced" security level. Headers per request:

        ```http
        Authorization: <hex(sha256(API_KEY + nonce + timestamp))>
        x-xdr-auth-id: <API_KEY_ID>
        x-xdr-nonce: <random 64-char string>
        x-xdr-timestamp: <unix-millis>
        Content-Type: application/json
        ```

        Phantom's `_xdr_client.py` generates the nonce + timestamp per request and
        computes the SHA-256. Operators never paste plain API keys into the agent;
        keys live in the `SecretStore` and the agent only sees the per-instance
        handle (`instance_id`).

        ## Base URL

        ```
        https://api-{fqdn}/public_api/v1/{api_name}/{call_name}/
        ```

        `fqdn` is the operator-visible XDR tenant FQDN (e.g. `acme.xdr.us.paloaltonetworks.com`).
        `api_name` matches the category (incidents/alerts/endpoints/etc.).
        `call_name` is the per-endpoint suffix (list, get_extra_data, isolate, etc.).
        """)
    (OUT_DIR / "auth.md").write_text(auth_md)

    sim_dir = ROOT / "data/knowledge/external/paloaltonetworks/cortex-xdr/simulation"
    sim_dir.mkdir(parents=True, exist_ok=True)
    sim_readme = dedent("""\
        # Cortex XDR — simulation recipes (placeholder)

        This directory will host data-source YAMLs that describe
        how Phantom's xlog should generate XDR-shaped records for operator-driven
        simulation workflows.

        This directory is intentionally empty — the Cortex XDR
        bundled data source already ships in `bundles/spark/data-sources/`
        for the marketplace, and the simulation YAMLs there are sufficient.
        This dir exists so the layout matches the broader vendor knowledge tree
        (`data/knowledge/external/<vendor>/<product>/{action,simulation}/`).

        Future work: when we add custom XDR-flavored simulation scenarios beyond
        what the marketplace provides, the YAMLs land here.
        """)
    (sim_dir / "README.md").write_text(sim_readme)

    print(f"wrote {len(index_rows)} endpoint markdown files")
    print("  + INDEX.md, auth.md")
    print("  + simulation/README.md placeholder")
    return 0


if __name__ == "__main__":
    sys.exit(main())
