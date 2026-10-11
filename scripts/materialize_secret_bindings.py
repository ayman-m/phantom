#!/usr/bin/env python3
"""Materialize Phantom secret binding references for an orchestrator import."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any


def load_yaml(path: Path) -> dict[str, Any]:
    try:
        import yaml  # type: ignore
    except ImportError as exc:
        return load_binding_template_without_yaml(path)
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise SystemExit(f"Secret binding template is not a mapping: {path}")
    return data


def load_binding_template_without_yaml(path: Path) -> dict[str, Any]:
    bindings: dict[str, dict[str, Any]] = {}
    in_bindings = False
    current: str | None = None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        if raw_line.startswith("bindings:"):
            in_bindings = True
            continue
        if not in_bindings:
            continue
        if raw_line and not raw_line.startswith(" "):
            break
        if raw_line.startswith("  ") and not raw_line.startswith("    ") and raw_line.rstrip().endswith(":"):
            current = raw_line.strip()[:-1]
            bindings[current] = {}
            continue
        if current and raw_line.startswith("    ") and ":" in raw_line:
            key, value = raw_line.strip().split(":", 1)
            bindings[current][key] = value.strip().strip('"').strip("'")
    return {"bindings": bindings}


def provider_ref(provider: str, target_path: str) -> str:
    if provider == "infisical":
        return f"infisical://{target_path}"
    return f"{provider}://{target_path}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--format",
        choices=("dotenv", "json"),
        default="dotenv",
        help="Output format for the secret references, not raw secret values.",
    )
    args = parser.parse_args()

    template = load_yaml(Path(args.template))
    bindings = template.get("bindings", {})
    if not isinstance(bindings, dict):
        raise SystemExit("Secret binding template has no bindings mapping")

    refs: dict[str, str] = {}
    for name, binding in sorted(bindings.items()):
        if not isinstance(binding, dict):
            continue
        env_name = str(binding.get("env") or name)
        provider = str(binding.get("provider") or "unknown")
        target_path = str(binding.get("targetPath") or "")
        if not target_path:
            continue
        refs[env_name] = provider_ref(provider, target_path)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    if args.format == "json":
        import json

        output.write_text(json.dumps(refs, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    else:
        lines = [
            "# Secret references generated from secret-bindings.example.yaml.",
            "# These are provider references, not raw secret values.",
        ]
        lines.extend(f"{name}={value}" for name, value in refs.items())
        output.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"Wrote secret binding references: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
