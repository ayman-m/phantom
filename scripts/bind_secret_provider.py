#!/usr/bin/env python3
"""Bind Phantom secret references through a target provider without storing raw values."""

from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request
from pathlib import Path


def load_env_refs(path: Path) -> dict[str, str]:
    refs: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise SystemExit(f"Invalid secret reference line in {path}: {line}")
        key, value = line.split("=", 1)
        refs[key.strip()] = value.strip()
    return refs


def write_file_provider(output: Path, agent_id: str, bindings: dict[str, str]) -> None:
    payload = {
        "agentId": agent_id,
        "mode": "provider-references",
        "rawValuesIncluded": False,
        "bindings": bindings,
    }
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote provider binding document: {output}")


def post_http_provider(url: str, token: str | None, agent_id: str, bindings: dict[str, str]) -> None:
    body = json.dumps(
        {
            "agentId": agent_id,
            "mode": "provider-references",
            "rawValuesIncluded": False,
            "bindings": bindings,
        }
    ).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            print(f"Provider accepted {len(bindings)} bindings: HTTP {response.status}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"Provider binding failed: HTTP {exc.code} {detail}") from exc


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refs", default=".env.secret-refs")
    parser.add_argument("--agent-id", default="phantom-soc-simulation-agent")
    parser.add_argument(
        "--provider",
        choices=["file", "http"],
        default=os.environ.get("SECRET_PROVIDER_KIND", "file"),
    )
    parser.add_argument("--output", default=os.environ.get("SECRET_PROVIDER_OUTPUT", ".secret-provider-bindings.json"))
    parser.add_argument("--url", default=os.environ.get("SECRET_PROVIDER_API_URL", ""))
    parser.add_argument("--token", default=os.environ.get("SECRET_PROVIDER_TOKEN", ""))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    refs_path = Path(args.refs).resolve()
    bindings = load_env_refs(refs_path)
    if not bindings:
        raise SystemExit(f"No secret references found in {refs_path}")

    if args.dry_run:
        print(json.dumps({"agentId": args.agent_id, "bindings": bindings}, indent=2, sort_keys=True))
        return

    if args.provider == "file":
        write_file_provider(Path(args.output).resolve(), args.agent_id, bindings)
        return

    if not args.url:
        raise SystemExit("SECRET_PROVIDER_API_URL or --url is required for the http provider")
    post_http_provider(args.url, args.token or None, args.agent_id, bindings)


if __name__ == "__main__":
    main()
