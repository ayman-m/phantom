"""Bundle-aware model-provider loader (parallel to connector_loader).

Reads the bundle at boot:
  - manifest.yaml → providers[]
  - providers/<id>/provider.yaml → spec.models[] + runtimeMapping

For each provider that has ≥1 instance in `data_root/provider_instances.db`,
loads the Provider class from `provider.yaml.source.entrypoint` and
queries it for the active model catalog (or falls back to the static
`spec.models[]` block). The resulting catalog is what the agent's
`modelRequirements:` resolver picks from.

Spec §7.6: providers and connectors share the same lifecycle pattern
but contribute different things at runtime — connectors contribute
tools, providers contribute models. Providers with zero configured
instances contribute zero models to the catalog (objective 5
parallel for providers).
"""

from __future__ import annotations

import importlib
import logging
import os
from pathlib import Path
from typing import Any, NamedTuple

import yaml

from usecase.provider_store import ProviderInstance, ProviderStore
from usecase.secret_store import SecretStore

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


class ProviderModel(NamedTuple):
    """One model advertised by a configured provider instance."""

    provider_id: str
    instance_name: str
    model_id: str
    family: str | None
    kind: str  # "chat" | "embedding"
    context_window: int | None
    supports: list[str]
    extra: dict[str, Any]


def _instantiate_provider(
    provider_id: str,
    provider_dir: Path,
    spec_yaml: dict,
    instance: ProviderInstance,
    secret_store: SecretStore | None = None,
) -> Any | None:
    """Import the Provider class and instantiate with the instance's
    config + RESOLVED secrets. Secrets are resolved at this
    point (instantiation time) since provider classes typically need
    them in __init__ (e.g. to construct an authenticated client).
    """
    source = spec_yaml.get("source") or {}
    entrypoint = source.get("entrypoint", "src.provider:Provider")
    if ":" not in entrypoint:
        logger.warning(
            "providers/%s/provider.yaml: source.entrypoint %r missing class symbol — "
            "skipping dynamic Provider instantiation, using static catalog",
            provider_id, entrypoint,
        )
        return None

    bundle_relative = provider_dir.relative_to(_bundle_root())
    pkg_prefix = ".".join(bundle_relative.parts)  # "providers.<id>"
    module_path, symbol = entrypoint.split(":", 1)
    full_module = f"{pkg_prefix}.{module_path}"

    # Resolve secrets via SecretStore if available; legacy
    # literal values pass through.
    resolved_secrets: dict[str, Any] = {}
    for slot, ref_or_value in instance.secret_refs.items():
        if (
            secret_store is not None
            and isinstance(ref_or_value, str)
            and ref_or_value.startswith("/")
        ):
            try:
                resolved_secrets[slot] = secret_store.read(ref_or_value)
            except Exception as exc:
                logger.warning(
                    "provider %s: could not resolve secret %s at %s — using empty. (%s)",
                    provider_id, slot, ref_or_value, exc,
                )
                resolved_secrets[slot] = ""
        else:
            resolved_secrets[slot] = ref_or_value

    try:
        mod = importlib.import_module(full_module)
        cls = getattr(mod, symbol)
        return cls(config=instance.config, secrets=resolved_secrets)
    except Exception as exc:
        logger.warning(
            "providers/%s: could not instantiate %s.%s — using static catalog. (%s)",
            provider_id, full_module, symbol, exc,
        )
        return None


def list_active_models(
    store: ProviderStore | None = None,
    secret_store: SecretStore | None = None,
) -> list[ProviderModel]:
    """Return the union of model catalogs across configured providers.

    For each provider in `manifest.yaml:providers[]` with ≥1 instance:
      1. Read provider.yaml
      2. Try to instantiate the Provider class with the instance's
         config + secrets
      3. Try `Provider.list_models()` for a dynamic catalog;
         if it returns an empty list (or instantiation failed), fall
         back to the static `spec.models[]` block from provider.yaml
      4. Yield one ProviderModel per advertised model

    Providers without instances contribute zero models (objective 5
    parallel for providers).
    """
    if store is None:
        store = ProviderStore()

    root = _bundle_root()
    manifest = _load_yaml(root / "manifest.yaml")
    declared = manifest.get("providers") or []
    if not isinstance(declared, list):
        logger.warning("manifest.yaml: providers is not a list — skipping")
        return []

    out: list[ProviderModel] = []
    advertised: list[str] = []
    skipped: list[str] = []

    for entry in declared:
        if not isinstance(entry, dict):
            continue
        pid = entry.get("id")
        path = entry.get("path")
        if not isinstance(pid, str) or not isinstance(path, str):
            continue

        instances = store.list_for(pid)
        if not instances:
            skipped.append(pid)
            continue

        provider_dir = (root / path).resolve()
        provider_yaml = provider_dir / "provider.yaml"
        if not provider_yaml.is_file():
            logger.warning("providers/%s: provider.yaml not found at %s", pid, provider_yaml)
            continue
        spec = _load_yaml(provider_yaml)

        # Single instance per provider (matches the connector
        # convention); the first instance is used.
        primary = instances[0]
        provider_obj = _instantiate_provider(
            pid, provider_dir, spec, primary, secret_store=secret_store
        )

        # Try dynamic catalog first; fall back to static spec.models[].
        dynamic_models: list[dict[str, Any]] = []
        if provider_obj is not None and hasattr(provider_obj, "list_models"):
            try:
                listed = provider_obj.list_models()
                if isinstance(listed, list):
                    dynamic_models = [m for m in listed if isinstance(m, dict)]
            except Exception as exc:
                logger.warning(
                    "providers/%s: Provider.list_models() raised %s — falling back to static catalog",
                    pid, exc,
                )

        models = dynamic_models or ((spec.get("spec") or {}).get("models") or [])

        for m in models:
            if not isinstance(m, dict):
                continue
            mid = m.get("id")
            if not isinstance(mid, str):
                continue
            out.append(
                ProviderModel(
                    provider_id=pid,
                    instance_name=primary.name,
                    model_id=mid,
                    family=m.get("family"),
                    kind=m.get("kind", "chat"),
                    context_window=m.get("contextWindow"),
                    supports=list(m.get("supports") or []),
                    extra={
                        k: v
                        for k, v in m.items()
                        if k not in {"id", "family", "kind", "contextWindow", "supports"}
                    },
                )
            )

        advertised.append(f"{pid} ({primary.name}, {len(models)} models)")

    if skipped:
        logger.info(
            "Provider catalog gated: %d provider(s) skipped (no configured instance): %s",
            len(skipped),
            ", ".join(skipped),
        )
    if advertised:
        logger.info("Active model providers: %s", "; ".join(advertised))

    return out


def provider_summary(store: ProviderStore | None = None) -> dict[str, int]:
    """Per-provider model counts (zero for providers without instances)."""
    summary: dict[str, int] = {}
    if store is None:
        store = ProviderStore()
    configured = store.configured_provider_ids()
    root = _bundle_root()
    manifest = _load_yaml(root / "manifest.yaml")
    for entry in manifest.get("providers") or []:
        if not isinstance(entry, dict):
            continue
        pid = entry.get("id")
        if not isinstance(pid, str):
            continue
        spec = _load_yaml((root / entry["path"]).resolve() / "provider.yaml")
        models = (spec.get("spec") or {}).get("models") or []
        summary[pid] = len(models) if pid in configured else 0
    return summary
