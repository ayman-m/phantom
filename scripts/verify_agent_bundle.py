#!/usr/bin/env python3
"""Verify Phantom bundle checksums and optional HMAC signature metadata."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import subprocess
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_signing_key() -> str | None:
    key = os.getenv("BUNDLE_SIGNING_KEY")
    if key:
        return key
    key_file = os.getenv("BUNDLE_SIGNING_KEY_FILE")
    if key_file:
        return Path(key_file).read_text(encoding="utf-8").strip()
    return None


def verify_checksums(bundle_dir: Path) -> None:
    checksums = bundle_dir / "checksums.sha256"
    if not checksums.exists():
        print("No checksums.sha256 found; skipping checksum verification")
        return
    subprocess.run(["shasum", "-a", "256", "-c", "checksums.sha256"], cwd=bundle_dir, check=True)


def verify_signature(bundle_dir: Path, require_signature: bool) -> None:
    signature_path = bundle_dir / "bundle-signature.json"
    manifest_path = bundle_dir / "bundle-manifest.json"
    if not signature_path.exists() or not manifest_path.exists():
        if require_signature:
            raise SystemExit("Bundle signature or manifest is missing")
        print("No bundle signature metadata found; skipping signature verification")
        return

    signature = json.loads(signature_path.read_text(encoding="utf-8"))
    manifest_sha = sha256_file(manifest_path)
    expected_manifest_sha = signature.get("manifest", {}).get("sha256")
    if expected_manifest_sha != manifest_sha:
        raise SystemExit("Bundle manifest SHA does not match signature metadata")

    signature_block = signature.get("signature", {})
    status = signature_block.get("status")
    if status != "signed":
        if require_signature:
            raise SystemExit("Bundle is unsigned but signature verification is required")
        print("Bundle is unsigned; checksum verification still passed")
        return

    key = read_signing_key()
    if not key:
        if require_signature:
            raise SystemExit("Bundle is signed but no BUNDLE_SIGNING_KEY or BUNDLE_SIGNING_KEY_FILE was provided")
        print("Bundle is signed; set BUNDLE_SIGNING_KEY or BUNDLE_SIGNING_KEY_FILE to verify the HMAC")
        return

    expected = hmac.new(key.encode("utf-8"), manifest_sha.encode("utf-8"), hashlib.sha256).hexdigest()
    actual = signature_block.get("value")
    if not hmac.compare_digest(expected, str(actual)):
        raise SystemExit("Bundle HMAC signature verification failed")
    print("Bundle HMAC signature verified")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle_dir")
    parser.add_argument("--require-signature", action="store_true")
    args = parser.parse_args()

    bundle_dir = Path(args.bundle_dir).resolve()
    verify_checksums(bundle_dir)
    verify_signature(bundle_dir, args.require_signature)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
