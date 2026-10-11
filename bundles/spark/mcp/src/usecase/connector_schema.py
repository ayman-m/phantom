"""Connector manifest schema validation — canonical surface.

Loads `bundles/spark/connectors/connector.schema.json` at module
import time and exposes a `validate_connector_spec(spec, source_path)`
function the bundle loader calls on every connector.yaml.

# Why this exists

A connector.yaml shape that is schema-by-example (every connector
copying fields from the previous one, with no automated check) drifts.
The class of regressions this guards against:

  * Inconsistent field names across connectors (e.g. secretSlots[]
    entries using `name` in one and `slot_name` in another), so the
    setup form renders them inconsistently.
  * A missing `version` field, so the instance store falls back to
    'unknown' and version comparison in the UI breaks.
  * A typo in runtimeMapping.style ('moudle') that silently disables
    tool registration for that connector.

Each of those is caught at boot by a schema check. The schema check
is authoritative: every connector.yaml,
bundle or user-uploaded, validates against
`bundles/spark/connectors/connector.schema.json` before its tools
register. A drift produces a clear error message naming the field
+ the connector + the file path; the boot fails fast.

# What this does NOT do

It validates the *manifest shape*. It does NOT:
  * Verify the connector's source actually exists (that's the loader's
    job — see connector_loader._resolve_callable).
  * Verify the configSchema is itself valid JSON Schema (no nested
    metaschema validation; we trust the bundle author here).
  * Validate per-instance config (that's instance_store.create's job
    when an operator submits the setup form).

# Single source of truth

The schema file is at `bundles/spark/connectors/connector.schema.json`,
co-located with the connectors themselves. Both bundle connectors
and user-uploaded connectors validate against the same
file — no separate schemas for system vs user.

# Import behavior

`jsonschema` is in the MCP image's runtime dependencies (already used
elsewhere). The schema file is loaded once at module import; the
compiled Draft-2020-12 validator is held in module state. Subsequent
calls reuse the same validator object — fast.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger("Phantom MCP")

# ─────────────────────────────────────────────────────────────────
# Schema discovery
# ─────────────────────────────────────────────────────────────────


def _schema_search_paths() -> list[Path]:
    """Ordered candidates where the schema might live.

    Inside the agent image the bundle's COPY-target is /app/bundle
    (see mcp/agent/Dockerfile). At repo-root for local pytest the
    schema sits at bundles/spark/connectors/connector.schema.json.
    """
    candidates: list[Path] = []
    explicit = os.environ.get("BUNDLE_ROOT")
    if explicit:
        candidates.append(Path(explicit) / "connectors" / "connector.schema.json")
    candidates.append(Path("/app/bundle/connectors/connector.schema.json"))
    candidates.append(
        Path(__file__).resolve().parents[3]
        / "connectors"
        / "connector.schema.json"
    )
    return candidates


def _load_schema() -> dict[str, Any]:
    for cand in _schema_search_paths():
        if cand.is_file():
            with cand.open("r", encoding="utf-8") as fh:
                return json.load(fh)
    raise FileNotFoundError(
        f"connector.schema.json not found in any of: "
        f"{[str(p) for p in _schema_search_paths()]}"
    )


# ─────────────────────────────────────────────────────────────────
# Validator (module-level singleton)
# ─────────────────────────────────────────────────────────────────


_SCHEMA: dict[str, Any] | None = None
_VALIDATOR: Any = None  # jsonschema.Draft202012Validator


def _validator() -> Any:
    """Return the compiled JSON Schema validator. Built lazily.

    Lazy build so a startup logging line can name the schema file
    when it FAILS to load, not when this module is imported.
    """
    global _SCHEMA, _VALIDATOR
    if _VALIDATOR is not None:
        return _VALIDATOR
    try:
        # Imported lazily so test environments without jsonschema can
        # at least import this module (the validator just won't run).
        from jsonschema import Draft202012Validator  # type: ignore[import-not-found]
    except ImportError as err:
        raise RuntimeError(
            "jsonschema not available; cannot validate connector.yaml files. "
            "Add `jsonschema` to bundles/spark/mcp/requirements.txt."
        ) from err
    _SCHEMA = _load_schema()
    _VALIDATOR = Draft202012Validator(_SCHEMA)
    return _VALIDATOR


# ─────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────


class ConnectorSpecError(ValueError):
    """Schema-validation failure on a connector.yaml.

    Includes the source path so the operator can fix the right file.
    """

    def __init__(self, message: str, *, source_path: Path | str | None = None) -> None:
        super().__init__(message)
        self.source_path = source_path


def validate_connector_spec(
    spec: dict[str, Any],
    *,
    source_path: Path | str | None = None,
    expected_id: str | None = None,
) -> None:
    """Validate one connector.yaml-loaded dict against the schema.

    Raises ConnectorSpecError on the first error (with a path-into-
    the-spec indicator so the operator can find the offending field
    quickly). Returns None on success.

    `expected_id` enables a defense-in-depth check: when the loader
    knows what id it expected (e.g. "the connector dir is named
    'caldera', so the YAML's id field should also be 'caldera'"),
    it can pass that in and we'll fail loudly on mismatch. Catches
    a copy-paste class of error where someone forks a connector
    directory but forgets to update the id.
    """
    validator = _validator()
    errors = list(validator.iter_errors(spec))
    if errors:
        first = errors[0]
        # jsonschema's path is a deque of keys/indices. Stringify for
        # the operator-readable error.
        if first.absolute_path:
            field_path = ".".join(str(p) for p in first.absolute_path)
        else:
            field_path = "<root>"
        msg = (
            f"connector.yaml schema validation failed at `{field_path}`: "
            f"{first.message}"
        )
        if source_path is not None:
            msg += f" (source: {source_path})"
        if len(errors) > 1:
            msg += f" [+{len(errors) - 1} more issue(s)]"
        raise ConnectorSpecError(msg, source_path=source_path)

    if expected_id is not None and spec.get("id") != expected_id:
        raise ConnectorSpecError(
            f"connector.yaml id mismatch: declared id={spec.get('id')!r} "
            f"but expected id={expected_id!r} based on directory name "
            f"(source: {source_path})",
            source_path=source_path,
        )


def validate_all_bundle_connectors(bundle_root: Path) -> list[ConnectorSpecError]:
    """Validate every bundle connector.yaml under <bundle_root>/connectors/.

    Returns a list of errors (empty on success). Used by the loader's
    boot path to validate the whole catalogue at once and report all
    issues, not just the first. The agent boot then fails fast if
    the list is non-empty.

    Subdirectories starting with `_` (e.g. `_runtime`) are skipped —
    they hold shared infrastructure (Dockerfiles, helpers) rather
    than tool connectors.
    """
    errors: list[ConnectorSpecError] = []
    connectors_dir = bundle_root / "connectors"
    if not connectors_dir.is_dir():
        return errors

    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:
        errors.append(
            ConnectorSpecError(
                "pyyaml not importable; cannot validate connector.yaml files",
            )
        )
        return errors

    for child in sorted(connectors_dir.iterdir()):
        if not child.is_dir():
            continue
        if child.name.startswith("_"):
            continue
        yaml_path = child / "connector.yaml"
        if not yaml_path.is_file():
            continue
        try:
            with yaml_path.open("r", encoding="utf-8") as fh:
                spec = yaml.safe_load(fh)
        except (OSError, yaml.YAMLError) as err:
            errors.append(
                ConnectorSpecError(
                    f"could not read {yaml_path}: {err}",
                    source_path=yaml_path,
                )
            )
            continue
        try:
            validate_connector_spec(
                spec, source_path=yaml_path, expected_id=child.name,
            )
        except ConnectorSpecError as err:
            errors.append(err)
    return errors
