#!/usr/bin/env python3
"""Generate a portable MCP tool snapshot for the Phantom agent bundle."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


UNSUPPORTED_SCHEMA_KEYS = {
    "$id",
    "$schema",
    "additionalItems",
    "additionalProperties",
    "const",
    "contains",
    "default",
    "dependentRequired",
    "dependentSchemas",
    "else",
    "examples",
    "exclusiveMaximum",
    "exclusiveMinimum",
    "if",
    "maxProperties",
    "minProperties",
    "not",
    "pattern",
    "patternProperties",
    "propertyNames",
    "then",
    "title",
    "unevaluatedItems",
    "unevaluatedProperties",
}


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_sse(body: str) -> dict[str, Any]:
    last_event: dict[str, Any] | None = None
    for line in body.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            event = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            last_event = event
    if last_event is None:
        raise RuntimeError("No JSON payload found in MCP SSE response")
    return last_event


class McpClient:
    def __init__(self, url: str, token: str | None) -> None:
        self.url = url
        self.token = token
        self.session_id: str | None = None
        self.protocol_version: str | None = None

    def headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "text/event-stream, application/json",
        }
        if self.token:
            headers["Authorization"] = self.token
        if self.session_id:
            headers["mcp-session-id"] = self.session_id
        if self.protocol_version:
            headers["mcp-protocol-version"] = self.protocol_version
        return headers

    def rpc(self, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(self.url, data=body, headers=self.headers(), method="POST")
        # Self-signed cert support: when the MCP serves HTTPS with the
        # auto-generated /tls/cert.pem (TLS-by-default mode), urllib's
        # default verification rejects the cert. Build an unverified
        # context for https:// URLs only — http:// URLs ignore it. The
        # script runs only against trusted localhost / compose-internal
        # MCPs in CI and operator-side bundle exports, so skipping
        # verification is the right trade-off here.
        ctx = ssl._create_unverified_context() if self.url.startswith("https") else None
        with urllib.request.urlopen(request, timeout=20, context=ctx) as response:
            session_id = response.headers.get("mcp-session-id")
            if session_id:
                self.session_id = session_id
            content_type = response.headers.get("content-type", "")
            raw = response.read().decode("utf-8", errors="replace")
        if "text/event-stream" in content_type:
            return parse_sse(raw)
        return json.loads(raw) if raw.strip() else {}

    def initialize(self) -> None:
        payload = self.rpc(
            {
                "jsonrpc": "2.0",
                "id": int(time.time() * 1000),
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "phantom-bundle-exporter", "version": "1.0.0"},
                },
            }
        )
        version = payload.get("result", {}).get("protocolVersion")
        if isinstance(version, str):
            self.protocol_version = version

        try:
            self.rpc(
                {
                    "jsonrpc": "2.0",
                    "method": "notifications/initialized",
                    "params": None,
                }
            )
        except Exception:
            # Some transports legitimately return no body for notifications.
            pass

    def list_tools(self) -> list[dict[str, Any]]:
        self.initialize()
        payload = self.rpc(
            {
                "jsonrpc": "2.0",
                "id": int(time.time() * 1000),
                "method": "tools/list",
                "params": None,
            }
        )
        tools = payload.get("result", {}).get("tools", [])
        if not isinstance(tools, list):
            raise RuntimeError("MCP tools/list response did not contain a tools list")
        return [tool for tool in tools if isinstance(tool, dict)]


def sanitize_schema(schema: Any, defs: dict[str, Any] | None = None, depth: int = 0, processing: set[str] | None = None) -> Any:
    if not isinstance(schema, dict):
        return schema
    if depth > 10:
        return {"type": "object", "description": "Complex schema (truncated)"}

    defs = defs if defs is not None else {}
    processing = processing if processing is not None else set()
    local = dict(schema)

    for key in list(local):
        if key in UNSUPPORTED_SCHEMA_KEYS:
            del local[key]

    for defs_key in ("$defs", "definitions"):
        if isinstance(local.get(defs_key), dict):
            defs.update(local[defs_key])
            del local[defs_key]

    ref = local.pop("$ref", None)
    if isinstance(ref, str):
        ref_name = ref.split("/")[-1] or ref
        if ref_name in processing:
            return {"type": "object", "description": f"Recursive reference to {ref_name}"}
        resolved = defs.get(ref_name)
        if isinstance(resolved, dict):
            processing.add(ref_name)
            sanitized = sanitize_schema(resolved, defs, depth + 1, set(processing))
            processing.remove(ref_name)
            return sanitized
        return {"type": "string", "description": f"Reference to {ref_name}"}

    complex_variant = False
    for key in ("oneOf", "anyOf", "allOf"):
        if key in local:
            del local[key]
            complex_variant = True

    if isinstance(local.get("properties"), dict):
        local["properties"] = {
            key: sanitize_schema(value, defs, depth + 1, set(processing))
            for key, value in local["properties"].items()
        }

    if isinstance(local.get("items"), dict):
        local["items"] = sanitize_schema(local["items"], defs, depth + 1, set(processing))
    elif isinstance(local.get("items"), list):
        local["items"] = [sanitize_schema(item, defs, depth + 1, set(processing)) for item in local["items"]]

    if complex_variant:
        local.setdefault("type", "object")
        description = local.get("description")
        local["description"] = f"{description or 'Complex variant'} (simplified)"

    return local


def unavailable_snapshot(url: str, error: str) -> dict[str, Any]:
    return {
        "apiVersion": "phantom.agentic/v1alpha1",
        "kind": "MCPToolSnapshot",
        "metadata": {
            "agentId": "phantom-soc-simulation-agent",
            "generatedAt": utc_now(),
            "sourceUrl": url,
            "status": "unavailable",
            "error": error,
        },
        "schemaMode": "gemini-compatible-sanitized",
        "toolCount": 0,
        "tools": [],
    }


def build_snapshot(url: str, token: str | None) -> dict[str, Any]:
    tools = McpClient(url, token).list_tools()
    normalized = []
    for tool in sorted(tools, key=lambda item: str(item.get("name", ""))):
        schema = tool.get("inputSchema") or tool.get("input_schema") or {"type": "object", "properties": {}}
        normalized.append(
            {
                "name": tool.get("name"),
                "description": tool.get("description") or "",
                "inputSchema": sanitize_schema(schema),
            }
        )
    return {
        "apiVersion": "phantom.agentic/v1alpha1",
        "kind": "MCPToolSnapshot",
        "metadata": {
            "agentId": "phantom-soc-simulation-agent",
            "generatedAt": utc_now(),
            "sourceUrl": url,
            "status": "available",
        },
        "schemaMode": "gemini-compatible-sanitized",
        "toolCount": len(normalized),
        "tools": normalized,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    # Default scheme is https:// to match the TLS-by-default stack
    # (entrypoint.sh auto-generates a self-signed cert at /tls/cert.pem
    # on first boot, so MCP serves HTTPS on 8080). Operators on legacy
    # HTTP-mode deployments can override with MCP_SNAPSHOT_URL or --url.
    parser.add_argument("--url", default=os.getenv("MCP_SNAPSHOT_URL") or f"https://localhost:{os.getenv('MCP_PORT', '8080')}{os.getenv('MCP_PATH', '/api/v1/stream/mcp')}")
    parser.add_argument("--token", default=os.getenv("MCP_TOKEN"))
    parser.add_argument("--output", required=True)
    parser.add_argument("--required", action="store_true")
    args = parser.parse_args()

    try:
        snapshot = build_snapshot(args.url, args.token)
    except (urllib.error.URLError, TimeoutError, RuntimeError, json.JSONDecodeError) as exc:
        if args.required:
            raise
        print(f"MCP tool snapshot unavailable: {exc}", file=sys.stderr)
        snapshot = unavailable_snapshot(args.url, str(exc))

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote MCP tool snapshot: {output} ({snapshot['toolCount']} tools, {snapshot['metadata']['status']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
