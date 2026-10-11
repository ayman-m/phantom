"""The single answer to "which connectors exist?".

Two kinds of connector exist side by side:

  bundle  declared in the bundle's `manifest.yaml` `toolConnectors[]`, with the
          connector.yaml (and source) baked into the agent image.
  user    uploaded through the marketplace (`POST /api/v1/marketplace/upload`) and
          stored at `<DATA_ROOT>/user_connectors/<id>/connector.yaml`. The container
          image is the operator's own; only the yaml lives here.

Everything that needs the list of connectors (tool registration, the connector state
routes, the Tools panel) reads it from here. Before this module each of them read
`manifest.yaml` on its own, so a user connector could be uploaded, installed and
started but was invisible to all of them.

A bundle id always wins a collision: the upload route refuses such ids, and if one is
hand-placed on the volume the bundle connector is kept.

This module imports nothing heavy on purpose, so the API routes and the loader can
both use it without a circular import.
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import yaml

from usecase.marketplace_store import ORIGIN_BUNDLE, ORIGIN_USER, resolved_data_root

logger = logging.getLogger("Phantom MCP")

# The connector.schema.json id rule. Checked again here because this reads files that
# could have been placed on the volume by hand, and the id becomes part of tool names.
_ID_RE = re.compile(r"^[a-z][a-z0-9-]*$")


@dataclass(frozen=True)
class ConnectorRef:
    """Where one connector lives. `dir` holds its connector.yaml."""

    id: str
    dir: Path
    origin: str

    @property
    def yaml_path(self) -> Path:
        return self.dir / "connector.yaml"


def bundle_root() -> Path:
    """The spark bundle on disk: $BUNDLE_ROOT, else /app/bundle, else the repo tree."""
    explicit = os.environ.get("BUNDLE_ROOT")
    if explicit:
        return Path(explicit)
    for cand in (Path("/app/bundle"), Path("/app/bundle/spark")):
        if (cand / "manifest.yaml").is_file():
            return cand
    # Dev and test runs from a checkout: this file is <bundle>/mcp/src/usecase/.
    return Path(__file__).resolve().parents[3]


def user_connectors_root() -> Path:
    """Where uploaded connector.yaml files live: `<DATA_ROOT>/user_connectors`."""
    return resolved_data_root() / "user_connectors"


def _read_yaml(path: Path) -> dict[str, Any]:
    """Load a yaml mapping, or {} when the file is missing or unreadable."""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        logger.warning("connector catalog: cannot read %s: %s", path, exc)
        return {}
    return data if isinstance(data, dict) else {}


def bundle_connectors(root: Path | None = None) -> list[ConnectorRef]:
    """Bundle connectors from manifest.yaml, in manifest order.

    Lenient on purpose: an entry without an id or path, or pointing at a directory with
    no connector.yaml, is skipped with a warning. (Tool registration at boot reads the
    manifest strictly itself; this list feeds the read-only routes.)
    """
    base = root or bundle_root()
    manifest = _read_yaml(base / "manifest.yaml")
    refs: list[ConnectorRef] = []
    for entry in manifest.get("toolConnectors") or []:
        cid = entry.get("id") if isinstance(entry, dict) else None
        rel = entry.get("path") if isinstance(entry, dict) else None
        if not isinstance(cid, str) or not isinstance(rel, str):
            logger.warning("connector catalog: manifest toolConnectors entry needs id and path: %r", entry)
            continue
        ref = ConnectorRef(cid, (base / rel).resolve(), ORIGIN_BUNDLE)
        if not ref.yaml_path.is_file():
            logger.warning("connector catalog: %s is in the manifest but %s is missing", cid, ref.yaml_path)
            continue
        refs.append(ref)
    return refs


def user_connectors(exclude_ids: Iterable[str] = ()) -> list[ConnectorRef]:
    """Uploaded connectors, sorted by directory name. Ids in `exclude_ids` are skipped
    (pass the bundle ids so a bundle connector always wins)."""
    skip = set(exclude_ids)
    root = user_connectors_root()
    if not root.is_dir():
        return []
    refs: list[ConnectorRef] = []
    for child in sorted(root.iterdir()):
        yaml_path = child / "connector.yaml"
        if not child.is_dir() or not yaml_path.is_file():
            continue
        cid = _read_yaml(yaml_path).get("id")
        if not isinstance(cid, str) or not _ID_RE.match(cid):
            logger.warning("connector catalog: %s has no valid id; ignoring it", yaml_path)
            continue
        if cid in skip:
            logger.warning("connector catalog: user connector %s collides with a bundle connector; keeping the bundle one", cid)
            continue
        refs.append(ConnectorRef(cid, child, ORIGIN_USER))
    return refs


def effective_connectors() -> list[ConnectorRef]:
    """Every connector the agent can know about: bundle first, then user."""
    bundle = bundle_connectors()
    return bundle + user_connectors(exclude_ids={r.id for r in bundle})


def find_connector(connector_id: str) -> ConnectorRef | None:
    for ref in effective_connectors():
        if ref.id == connector_id:
            return ref
    return None
