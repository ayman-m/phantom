#!/usr/bin/env python3
"""Create a file manifest and optional HMAC signature for a Phantom bundle directory."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import hmac
import json
import os
from pathlib import Path

EXCLUDED = {"checksums.sha256", "bundle-manifest.json", "bundle-signature.json"}


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_signing_key() -> tuple[str | None, str | None]:
    key = os.getenv("BUNDLE_SIGNING_KEY")
    if key:
        return key, "env:BUNDLE_SIGNING_KEY"
    key_file = os.getenv("BUNDLE_SIGNING_KEY_FILE")
    if key_file:
        return Path(key_file).read_text(encoding="utf-8").strip(), f"file:{key_file}"
    return None, None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle_dir")
    args = parser.parse_args()

    bundle_dir = Path(args.bundle_dir).resolve()
    files = []
    for path in sorted(bundle_dir.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(bundle_dir).as_posix()
        if rel in EXCLUDED:
            continue
        files.append({"path": rel, "size": path.stat().st_size, "sha256": sha256_file(path)})

    manifest = {
        "apiVersion": "phantom.agentic/v1alpha1",
        "kind": "AgentBundleManifest",
        "metadata": {
            "agentId": "phantom-soc-simulation-agent",
            "generatedAt": utc_now(),
        },
        "integrity": {
            "algorithm": "sha256",
            "fileCount": len(files),
        },
        "files": files,
    }

    manifest_path = bundle_dir / "bundle-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest_sha = sha256_file(manifest_path)

    key, key_ref = read_signing_key()
    signature = {
        "apiVersion": "phantom.agentic/v1alpha1",
        "kind": "AgentBundleSignature",
        "metadata": {
            "agentId": "phantom-soc-simulation-agent",
            "generatedAt": utc_now(),
        },
        "manifest": {
            "path": "bundle-manifest.json",
            "sha256": manifest_sha,
        },
        "signature": {
            "status": "unsigned",
            "algorithm": "none",
        },
    }
    if key:
        signature["signature"] = {
            "status": "signed",
            "algorithm": "hmac-sha256",
            "keyRef": key_ref,
            "value": hmac.new(key.encode("utf-8"), manifest_sha.encode("utf-8"), hashlib.sha256).hexdigest(),
        }

    signature_path = bundle_dir / "bundle-signature.json"
    signature_path.write_text(json.dumps(signature, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote bundle manifest: {manifest_path}")
    print(f"Wrote bundle signature metadata: {signature_path} ({signature['signature']['status']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
