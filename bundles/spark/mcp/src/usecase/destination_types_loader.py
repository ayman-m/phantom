"""Destination types loader.

Reads `bundles/spark/destinations/<id>/spec.yaml` manifests at MCP boot
and exposes them as a typed catalogue. Each manifest declares a
type_id, display metadata (name/description/icon), the `fields[]`
config schema (ConfigParam-style + the new `visible_when` clause),
and the Python `handler` module path.

This module is the AVAILABILITY-side state per CLAUDE.md § Catalog
boundary ≠ credential boundary. The manifests contain field NAMES
and types — never secret values. Operator-created destinations
(rows in `log_destinations_store`) reference these type_ids and
carry actual config + secret REFS.

# Why a loader vs hardcoded enum

The loader is schema-driven (YAML manifests). Adding a new destination type = ship `<type_id>/spec.yaml` +
`handler.py` under `bundles/spark/destinations/`. The loader picks it
up automatically at boot; no code changes in the MCP REST surface or
the UI form renderer.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("Phantom MCP")


# ─── Path resolution ───────────────────────────────────────────────


def resolve_destinations_root() -> Path:
    """Find the bundled destinations root.

    Container layout: /app/bundle/destinations/
    Source-tree layout: <repo>/bundles/spark/destinations/

    Override via env `PHANTOM_DESTINATIONS_BUNDLE_ROOT` for tests.
    """
    override = os.environ.get("PHANTOM_DESTINATIONS_BUNDLE_ROOT")
    if override:
        return Path(override)
    container = Path("/app/bundle/destinations")
    if container.is_dir():
        return container
    # Walk up: this file lives at bundles/spark/mcp/src/usecase/<file>
    # → parents[3] = bundles/spark
    return Path(__file__).resolve().parents[3] / "destinations"


def resolve_schema_path() -> Path:
    return resolve_destinations_root() / "destination.schema.json"


# ─── Manifest schema cache ─────────────────────────────────────────


_schema_cache: dict[str, Any] | None = None


def load_schema() -> dict[str, Any]:
    """Cached destination.schema.json load."""
    global _schema_cache
    if _schema_cache is None:
        path = resolve_schema_path()
        if not path.is_file():
            raise FileNotFoundError(
                f"destination.schema.json not found at {path}"
            )
        _schema_cache = json.loads(path.read_text())
    return _schema_cache


def validate_manifest(manifest: dict[str, Any]) -> list[str]:
    """Validate a parsed manifest dict against the JSON Schema.

    Returns a list of human-readable error messages; empty list = ok.
    Uses `jsonschema` if available (already in requirements); falls back
    to manual field checks if not (tests prefer the manual fallback to
    keep test deps minimal).
    """
    errors: list[str] = []
    schema = load_schema()
    # Use jsonschema for the heavy lifting
    try:
        import jsonschema  # type: ignore[import-untyped]
    except ImportError:
        # Manual minimal check — required keys only
        required = schema.get("required", [])
        for key in required:
            if key not in manifest:
                errors.append(f"missing required key: {key}")
        return errors

    validator = jsonschema.Draft202012Validator(schema)
    for err in validator.iter_errors(manifest):
        loc = "/".join(str(p) for p in err.absolute_path) or "<root>"
        errors.append(f"{loc}: {err.message}")
    return errors


# ─── Manifest dataclass ────────────────────────────────────────────


@dataclass
class DestinationFieldDef:
    """One field in a manifest's fields[] array."""
    name: str
    display: str
    type: str
    required: bool = False
    defaultValue: str | None = None
    description: str | None = None
    options: list[str] | None = None
    visible_when: dict[str, Any] | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "DestinationFieldDef":
        return cls(
            name=str(d["name"]),
            display=str(d["display"]),
            type=str(d["type"]),
            required=bool(d.get("required", False)),
            defaultValue=(None if d.get("defaultValue") is None
                          else str(d.get("defaultValue"))),
            description=d.get("description"),
            options=([str(x) for x in d["options"]]
                     if "options" in d else None),
            visible_when=d.get("visible_when"),
        )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "name": self.name,
            "display": self.display,
            "type": self.type,
            "required": self.required,
        }
        if self.defaultValue is not None:
            out["defaultValue"] = self.defaultValue
        if self.description is not None:
            out["description"] = self.description
        if self.options is not None:
            out["options"] = self.options
        if self.visible_when is not None:
            out["visible_when"] = self.visible_when
        return out

    def is_secret(self) -> bool:
        """True when this field should land in SecretStore, not config_json."""
        return self.type in ("secret", "password")


@dataclass
class DestinationTypeManifest:
    """One full destination type manifest."""
    schema_version: int
    id: str
    name: str
    description: str
    category: str
    icon: str
    iconColor: str
    iconBg: str
    handler: str  # Python module path
    fields: list[DestinationFieldDef] = field(default_factory=list)
    probe: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "DestinationTypeManifest":
        return cls(
            schema_version=int(d["schema_version"]),
            id=str(d["id"]),
            name=str(d["name"]),
            description=str(d["description"]),
            category=str(d["category"]),
            icon=str(d["icon"]),
            iconColor=str(d["iconColor"]),
            iconBg=str(d["iconBg"]),
            handler=str(d["handler"]),
            fields=[DestinationFieldDef.from_dict(f) for f in d.get("fields", [])],
            probe=dict(d.get("probe") or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "icon": self.icon,
            "iconColor": self.iconColor,
            "iconBg": self.iconBg,
            "fields": [f.to_dict() for f in self.fields],
            "handler": self.handler,
            "probe": self.probe,
        }

    def secret_slot_names(self) -> list[str]:
        """Names of fields whose values must land in SecretStore."""
        return [f.name for f in self.fields if f.is_secret()]

    def non_secret_field_names(self) -> list[str]:
        """Names of fields whose values land in the row's config_json."""
        return [f.name for f in self.fields if not f.is_secret()]


# ─── Loader ────────────────────────────────────────────────────────


class DestinationTypesLoader:
    """Reads + caches destination type manifests from disk.

    Lifecycle: instantiated once at MCP boot; cached in module globals.
    The cache is invalidated on `reload()` which a future hot-reload
    endpoint could call.
    """

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or resolve_destinations_root()
        self._cache: dict[str, DestinationTypeManifest] | None = None

    def _load_all_uncached(self) -> dict[str, DestinationTypeManifest]:
        import yaml

        out: dict[str, DestinationTypeManifest] = {}
        if not self.root.is_dir():
            logger.warning(
                "destinations root not found at %s", self.root,
            )
            return out

        for child in sorted(self.root.iterdir()):
            if not child.is_dir():
                continue
            spec_path = child / "spec.yaml"
            if not spec_path.is_file():
                continue
            try:
                data = yaml.safe_load(spec_path.read_text())
            except yaml.YAMLError as e:
                logger.error(
                    "destination type %s: YAML parse error: %s",
                    child.name, e,
                )
                continue
            if not isinstance(data, dict):
                logger.error(
                    "destination type %s: spec.yaml is not a dict",
                    child.name,
                )
                continue
            errors = validate_manifest(data)
            if errors:
                logger.error(
                    "destination type %s: schema validation failed:\n  %s",
                    child.name, "\n  ".join(errors),
                )
                continue

            manifest = DestinationTypeManifest.from_dict(data)
            if manifest.id != child.name:
                logger.error(
                    "destination type %s: spec.id=%r mismatches dir name",
                    child.name, manifest.id,
                )
                continue
            out[manifest.id] = manifest

        logger.info(
            "DestinationTypesLoader: loaded %d types from %s: %s",
            len(out), self.root, sorted(out.keys()),
        )
        return out

    def list_all(self) -> dict[str, DestinationTypeManifest]:
        if self._cache is None:
            self._cache = self._load_all_uncached()
        return self._cache

    def get(self, type_id: str) -> DestinationTypeManifest | None:
        return self.list_all().get(type_id)

    def reload(self) -> dict[str, DestinationTypeManifest]:
        self._cache = None
        return self.list_all()


# ─── Singleton accessor ────────────────────────────────────────────


_loader: DestinationTypesLoader | None = None


def get_destination_types_loader() -> DestinationTypesLoader:
    global _loader
    if _loader is None:
        _loader = DestinationTypesLoader()
    return _loader


def reset_loader_for_tests() -> None:
    """Test-only hook to clear the singleton (env overrides changed)."""
    global _loader
    _loader = None
