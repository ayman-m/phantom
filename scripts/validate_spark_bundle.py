#!/usr/bin/env python3
"""Validate the local Spark-compatible Phantom bundle projection."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    import yaml
except ImportError as exc:  # pragma: no cover - environment guard
    raise SystemExit("PyYAML is required: pip install pyyaml") from exc


def load_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return data


def require_file(bundle_dir: Path, rel_path: str, label: str) -> Path:
    path = (bundle_dir / rel_path).resolve()
    if not path.exists() or not path.is_file():
        raise ValueError(f"{label} not found: {rel_path}")
    return path


def require_dir(bundle_dir: Path, rel_path: str, label: str) -> Path:
    path = (bundle_dir / rel_path).resolve()
    if not path.exists() or not path.is_dir():
        raise ValueError(f"{label} not found: {rel_path}")
    return path


def validate_json(path: Path) -> None:
    with path.open("r", encoding="utf-8") as handle:
        json.load(handle)


def validate_jsonl(path: Path) -> None:
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            if line.strip():
                json.loads(line)


def validate_manifest(bundle_dir: Path, manifest: dict) -> list[str]:
    errors: list[str] = []

    schema_version = manifest.get("schemaVersion")
    if schema_version != "1.2":
        errors.append(f"schemaVersion must be 1.2 (got {schema_version!r})")

    for field in ["name", "displayName", "version", "description", "signature", "runtime", "agent"]:
        if field not in manifest:
            errors.append(f"missing required field: {field}")

    # v1.2 forbids the renamed top-level keys.
    for legacy_key in ("dependencies", "instances", "bundledDependencies"):
        if legacy_key in manifest:
            errors.append(
                f"{legacy_key!r} is removed in v1.2 — fold into messagingConnectors:"
            )

    # Tool-providing connectors + embedded MCP cross-checks.
    tool_connectors = manifest.get("toolConnectors") or []
    if tool_connectors and not isinstance(tool_connectors, list):
        errors.append("toolConnectors must be a list")
        tool_connectors = []

    embedded = manifest.get("embeddedMcp")
    if tool_connectors:
        if not isinstance(embedded, dict):
            errors.append("embeddedMcp is required when toolConnectors[] is non-empty")
        else:
            mcp_path = embedded.get("path")
            if isinstance(mcp_path, str):
                try:
                    mcp_dir = require_dir(bundle_dir, mcp_path, "embeddedMcp.path")
                    require_file(mcp_dir, "server.yaml", "embeddedMcp server.yaml")
                except ValueError as exc:
                    errors.append(str(exc))
            else:
                errors.append("embeddedMcp.path must be a string")

    seen_ids: set[str] = set()
    for entry in tool_connectors:
        if not isinstance(entry, dict):
            errors.append("toolConnectors[] entries must be mappings")
            continue
        cid = entry.get("id")
        if not isinstance(cid, str):
            errors.append("toolConnectors[].id must be a string")
            continue
        if cid in seen_ids:
            errors.append(f"toolConnectors[].id {cid!r} duplicated")
        seen_ids.add(cid)
        path = entry.get("path")
        if not isinstance(path, str):
            errors.append(f"toolConnectors[{cid}].path must be a string")
            continue
        try:
            connector_dir = require_dir(bundle_dir, path, f"toolConnectors[{cid}].path")
            connector_yaml = require_file(connector_dir, "connector.yaml", f"connectors/{cid}/connector.yaml")
            try:
                spec = load_yaml(connector_yaml)
                if spec.get("id") != cid:
                    errors.append(
                        f"connectors/{cid}/connector.yaml id={spec.get('id')!r} "
                        f"does not match manifest toolConnectors[].id={cid!r}"
                    )
                tools = (spec.get("spec") or {}).get("tools") or []
                if not isinstance(tools, list):
                    errors.append(f"connectors/{cid}/connector.yaml: spec.tools must be a list")
            except ValueError as exc:
                errors.append(str(exc))
        except ValueError as exc:
            errors.append(str(exc))

    # setup.bindsInstances cross-check: every required tool connector
    # must be covered.
    setup_block = manifest.get("setup") or {}
    bindings = setup_block.get("bindsInstances") or []
    bound_ids = {b.get("connectorId") for b in bindings if isinstance(b, dict)}
    for entry in tool_connectors:
        if isinstance(entry, dict) and entry.get("required") and entry.get("id") not in bound_ids:
            errors.append(
                f"toolConnectors[{entry.get('id')!r}] is required but has no "
                f"matching setup.bindsInstances[].connectorId"
            )

    # v1.2 §7.6 — providers parallel to tool connectors.
    providers = manifest.get("providers") or []
    if providers and not isinstance(providers, list):
        errors.append("providers must be a list")
        providers = []

    seen_provider_ids: set[str] = set()
    for entry in providers:
        if not isinstance(entry, dict):
            errors.append("providers[] entries must be mappings")
            continue
        pid = entry.get("id")
        if not isinstance(pid, str):
            errors.append("providers[].id must be a string")
            continue
        if pid in seen_provider_ids:
            errors.append(f"providers[].id {pid!r} duplicated")
        if pid in seen_ids:
            errors.append(
                f"provider id {pid!r} collides with a toolConnectors[] id "
                f"(spec §7.6: provider IDs must be unique across both)"
            )
        seen_provider_ids.add(pid)
        path = entry.get("path")
        if not isinstance(path, str):
            errors.append(f"providers[{pid}].path must be a string")
            continue
        try:
            provider_dir = require_dir(bundle_dir, path, f"providers[{pid}].path")
            provider_yaml = require_file(provider_dir, "provider.yaml", f"providers/{pid}/provider.yaml")
            try:
                spec = load_yaml(provider_yaml)
                if spec.get("id") != pid:
                    errors.append(
                        f"providers/{pid}/provider.yaml id={spec.get('id')!r} "
                        f"does not match manifest providers[].id={pid!r}"
                    )
                models = (spec.get("spec") or {}).get("models") or []
                if not isinstance(models, list):
                    errors.append(f"providers/{pid}/provider.yaml: spec.models must be a list")
            except ValueError as exc:
                errors.append(str(exc))
        except ValueError as exc:
            errors.append(str(exc))

    # setup.bindsProviders cross-check: every required provider must be covered.
    provider_bindings = setup_block.get("bindsProviders") or []
    bound_provider_ids = {b.get("providerId") for b in provider_bindings if isinstance(b, dict)}
    for entry in providers:
        if isinstance(entry, dict) and entry.get("required") and entry.get("id") not in bound_provider_ids:
            errors.append(
                f"providers[{entry.get('id')!r}] is required but has no "
                f"matching setup.bindsProviders[].providerId"
            )

    agent = manifest.get("agent") or {}
    if not isinstance(agent, dict):
        errors.append("agent must be a mapping")
        agent = {}

    prompt = agent.get("systemPromptTemplate")
    if isinstance(prompt, str):
        try:
            require_file(bundle_dir, prompt, "agent.systemPromptTemplate")
        except ValueError as exc:
            errors.append(str(exc))
    else:
        errors.append("agent.systemPromptTemplate must be a string")

    ui = agent.get("ui")
    if ui is not None:
        if not isinstance(ui, dict):
            errors.append("agent.ui must be a mapping")
        else:
            mode = ui.get("mode")
            if mode not in {"a2ui", "nextjs"}:
                errors.append("agent.ui.mode must be a2ui or nextjs")
            if mode == "a2ui":
                a2ui = ui.get("a2ui") or {}
                if not isinstance(a2ui, dict):
                    errors.append("agent.ui.a2ui must be a mapping")
                else:
                    manifest_path = a2ui.get("manifest")
                    if isinstance(manifest_path, str):
                        try:
                            validate_a2ui(bundle_dir, require_file(bundle_dir, manifest_path, "agent.ui.a2ui.manifest"))
                        except ValueError as exc:
                            errors.append(str(exc))
                    else:
                        errors.append("agent.ui.a2ui.manifest must be a string")
            if mode == "nextjs" and not ui.get("entryPoint"):
                errors.append("agent.ui.entryPoint is required for nextjs mode")

    setup = manifest.get("setup")
    if setup is not None:
        if not isinstance(setup, dict):
            errors.append("setup must be a mapping")
        else:
            if setup.get("secrets", {}).get("source") != "requiredSecrets":
                errors.append("setup.secrets.source must be requiredSecrets")
            if setup.get("settings", {}).get("source") != "settings":
                errors.append("setup.settings.source must be settings")
            surfaces = setup.get("surfaces") or {}
            if surfaces.get("mode") != "a2ui":
                errors.append("setup.surfaces.mode must be a2ui")
            a2ui = surfaces.get("a2ui") or {}
            if isinstance(a2ui.get("manifest"), str):
                try:
                    require_file(bundle_dir, a2ui["manifest"], "setup.surfaces.a2ui.manifest")
                except ValueError as exc:
                    errors.append(str(exc))

    for skill in manifest.get("skills") or []:
        if isinstance(skill, dict) and isinstance(skill.get("path"), str):
            try:
                require_file(bundle_dir, skill["path"], f"skill {skill.get('name', '<unknown>')}")
            except ValueError as exc:
                errors.append(str(exc))

    for kb in (manifest.get("knowledge") or {}).get("bundled") or []:
        if not isinstance(kb, dict):
            continue
        for key, checker in [("path", require_dir), ("schema", require_file)]:
            if isinstance(kb.get(key), str):
                try:
                    checker(bundle_dir, kb[key], f"knowledge.{kb.get('name', '<unknown>')}.{key}")
                except ValueError as exc:
                    errors.append(str(exc))

    return errors


def validate_a2ui(bundle_dir: Path, manifest_path: Path) -> None:
    validate_json(manifest_path)
    a2ui_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    a2ui = a2ui_manifest.get("a2ui")
    if not isinstance(a2ui, dict):
        raise ValueError(f"{manifest_path}: missing a2ui object")

    for catalog in a2ui.get("catalogs") or []:
        if isinstance(catalog, dict) and isinstance(catalog.get("path"), str):
            validate_json(require_file(manifest_path.parent, catalog["path"], "A2UI catalog"))

    events = a2ui.get("events") or {}
    if isinstance(events.get("schema"), str):
        validate_json(require_file(manifest_path.parent, events["schema"], "A2UI events schema"))

    for surface in a2ui.get("surfaces") or []:
        if isinstance(surface, dict) and isinstance(surface.get("path"), str):
            validate_jsonl(require_file(manifest_path.parent, surface["path"], "A2UI surface"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle_dir", nargs="?", default="bundles/spark")
    args = parser.parse_args()

    bundle_dir = Path(args.bundle_dir).resolve()
    manifest_path = bundle_dir / "manifest.yaml"
    if not manifest_path.exists():
        print(f"Spark bundle manifest not found: {manifest_path}", file=sys.stderr)
        return 1

    manifest = load_yaml(manifest_path)
    errors = validate_manifest(bundle_dir, manifest)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1

    print(f"Spark bundle validation passed: {bundle_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
