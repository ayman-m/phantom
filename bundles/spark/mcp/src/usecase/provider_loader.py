"""Bundle-aware model-provider summary (parallel to connector_loader).

Reads the bundle at boot:
  - manifest.yaml → providers[]

and reports how many instances each declared provider has configured in
`data_root/provider_instances.db`.

Model providers hold credentials and per-instance config; they contribute no
model catalog here. The catalog of models lives in one place, the agent's model
registry (mcp/agent/lib/providers/registry), which merges its curated tables
with each provider's live model list.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import yaml

from usecase.provider_store import ProviderStore

logger = logging.getLogger("Phantom MCP")

DEFAULT_BUNDLE_ROOT = "/app/bundle"


def _bundle_root() -> Path:
    raw = os.getenv("BUNDLE_ROOT", DEFAULT_BUNDLE_ROOT)
    root = Path(raw).resolve()
    if not root.is_dir():
        raise RuntimeError(
            f"Bundle root {root} does not exist. Set BUNDLE_ROOT env var "
            f"or mount the bundle at {DEFAULT_BUNDLE_ROOT}."
        )
    return root


def _load_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a YAML mapping")
    return data


def provider_summary(store: ProviderStore | None = None) -> dict[str, int]:
    """Per-provider configured instance counts.

    Every provider declared in `manifest.yaml:providers[]` appears; one with no
    configured instance counts zero.
    """
    if store is None:
        store = ProviderStore()
    root = _bundle_root()
    manifest = _load_yaml(root / "manifest.yaml")
    summary: dict[str, int] = {}
    declared = manifest.get("providers") or []
    if not isinstance(declared, list):
        logger.warning("manifest.yaml: providers is not a list — skipping")
        return summary
    for entry in declared:
        if not isinstance(entry, dict):
            continue
        pid = entry.get("id")
        if not isinstance(pid, str):
            continue
        summary[pid] = len(store.list_for(pid))
    return summary
