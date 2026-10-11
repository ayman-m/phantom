"""Plugin loader.

Plugins are filesystem-discovered directories under
`bundles/spark/plugins/<name>/`. Each plugin ships a `manifest.yaml`
declaring its contributions:

    name: example-vendor
    version: 1.0.0
    description: Example plugin demonstrating contributions.
    enabled: true

    skills:
      - skills/example-skill.md

    scenarios:
      - scenarios/example-scenario.json

    memory_seeds:
      # Each entry is a key/value/scope/meta that the loader writes
      # to the memory store on first boot. Seeds with the same key
      # are not re-applied — operator edits to a memory survive
      # plugin reloads.
      - key: example-vendor.notable-event-types
        scope: agent
        value: |
          - foo: indicates X
          - bar: indicates Y
        meta:
          source: plugin:example-vendor
          version: 1.0.0

The loader runs at MCP boot AFTER the core stores are initialized.
For each plugin where `enabled: true`:
  1. Skill files are copied to `/app/skills/plugins/<plugin>/` so
     the existing skill loader picks them up.
  2. Scenario files are copied to `scenarios/ready/`.
  3. Memory seeds are checked against the memory store; missing
     keys (per scope) are written; existing keys are left alone.

Disabled plugins are still discovered but their contributions are
skipped. Operators can toggle via /api/v1/plugins.

Why filesystem-discovered (vs API-installed):

  Phantom is an internal SOC platform deployed once per org. There's
  no marketplace, no install flow. "Drop a folder, restart, the
  plugin's contributions are live" is the right shape. SnowAgent's
  full plugin lifecycle (download / install / version-pin) is
  appropriate for a public-marketplace tool but overkill here.
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger("Phantom MCP")


@dataclass
class PluginInfo:
    """One discovered plugin's metadata + contribution counts."""

    name: str
    version: str
    description: str
    enabled: bool
    path: Path
    skills_count: int
    scenarios_count: int
    memory_seeds_count: int
    seeded_count: int  # how many seeds were ACTUALLY written
    error: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "enabled": self.enabled,
            "path": str(self.path),
            "skills_count": self.skills_count,
            "scenarios_count": self.scenarios_count,
            "memory_seeds_count": self.memory_seeds_count,
            "seeded_count": self.seeded_count,
            "error": self.error,
        }


class PluginLoader:
    """Discovers and loads plugins from a filesystem root.

    Stateless / idempotent: load_all() can be called multiple times.
    Memory seeds are deduped by (scope, key); skill / scenario
    files are copied with `shutil.copy2` (no-op when source is
    older or identical).
    """

    def __init__(
        self,
        plugins_root: Path,
        skills_dest_root: Path,
        scenarios_dest_root: Path,
    ) -> None:
        self.plugins_root = plugins_root
        self.skills_dest_root = skills_dest_root
        self.scenarios_dest_root = scenarios_dest_root

    # ─── Discovery ──────────────────────────────────────────────

    def discover(self) -> list[Path]:
        """Return paths to plugin directories. Each must contain a
        manifest.yaml. Non-directory entries and dirs without
        manifest are skipped silently."""
        if not self.plugins_root.exists():
            return []
        out: list[Path] = []
        for entry in sorted(self.plugins_root.iterdir()):
            if not entry.is_dir():
                continue
            if not (entry / "manifest.yaml").exists():
                continue
            out.append(entry)
        return out

    def list_loaded(self) -> list[PluginInfo]:
        """Read manifests + count contributions WITHOUT applying
        them. For the /plugins UI (operator browses without
        side effects)."""
        infos: list[PluginInfo] = []
        for plugin_dir in self.discover():
            try:
                manifest = self._read_manifest(plugin_dir)
                infos.append(
                    PluginInfo(
                        name=manifest.get("name") or plugin_dir.name,
                        version=str(manifest.get("version") or "0.0.0"),
                        description=str(manifest.get("description") or ""),
                        enabled=bool(manifest.get("enabled", True)),
                        path=plugin_dir,
                        skills_count=len(manifest.get("skills") or []),
                        scenarios_count=len(manifest.get("scenarios") or []),
                        memory_seeds_count=len(
                            manifest.get("memory_seeds") or []
                        ),
                        seeded_count=0,
                        error=None,
                    ),
                )
            except Exception as exc:
                infos.append(
                    PluginInfo(
                        name=plugin_dir.name,
                        version="?",
                        description="",
                        enabled=False,
                        path=plugin_dir,
                        skills_count=0,
                        scenarios_count=0,
                        memory_seeds_count=0,
                        seeded_count=0,
                        error=str(exc),
                    ),
                )
        return infos

    # ─── Application ────────────────────────────────────────────

    def apply_all(
        self,
        *,
        memory_store: Any,  # SqliteMemoryStore (avoid cyclic import)
        agent_definition_store: Any = None,
    ) -> list[PluginInfo]:
        """Discover + apply contributions for every enabled plugin.
        Returns per-plugin results (count of seeded memories etc).
        Skill / scenario file copies are idempotent; memory seeds
        skip already-present keys.
        """
        results: list[PluginInfo] = []
        for plugin_dir in self.discover():
            try:
                manifest = self._read_manifest(plugin_dir)
                enabled = bool(manifest.get("enabled", True))
                if not enabled:
                    results.append(
                        PluginInfo(
                            name=manifest.get("name") or plugin_dir.name,
                            version=str(manifest.get("version") or "0.0.0"),
                            description=str(
                                manifest.get("description") or ""
                            ),
                            enabled=False,
                            path=plugin_dir,
                            skills_count=0,
                            scenarios_count=0,
                            memory_seeds_count=0,
                            seeded_count=0,
                            error=None,
                        )
                    )
                    continue
                info = self._apply_one(
                    plugin_dir,
                    manifest,
                    memory_store,
                    agent_definition_store,
                )
                results.append(info)
            except Exception as exc:
                logger.warning(
                    "plugin_loader: %s failed: %s", plugin_dir.name, exc,
                )
                results.append(
                    PluginInfo(
                        name=plugin_dir.name,
                        version="?",
                        description="",
                        enabled=False,
                        path=plugin_dir,
                        skills_count=0,
                        scenarios_count=0,
                        memory_seeds_count=0,
                        seeded_count=0,
                        error=str(exc),
                    )
                )
        return results

    def _apply_one(
        self,
        plugin_dir: Path,
        manifest: dict[str, Any],
        memory_store: Any,
        agent_definition_store: Any = None,
    ) -> PluginInfo:
        name = manifest.get("name") or plugin_dir.name
        version = str(manifest.get("version") or "0.0.0")
        description = str(manifest.get("description") or "")

        skills = manifest.get("skills") or []
        scenarios = manifest.get("scenarios") or []
        seeds = manifest.get("memory_seeds") or []

        # Skills — copy each into the mounted skills dir under a
        # plugin-namespaced subdir so they don't collide with bundle
        # defaults.
        skill_dest = self.skills_dest_root / "plugins" / name
        skill_dest.mkdir(parents=True, exist_ok=True)
        for rel in skills:
            src = (plugin_dir / rel).resolve()
            if not src.exists() or not src.is_file():
                logger.warning(
                    "plugin_loader[%s]: skill %s missing", name, rel,
                )
                continue
            dst = skill_dest / src.name
            shutil.copy2(src, dst)

        # Scenarios — copy into scenarios/ready/. We prefix the
        # filename with the plugin name to avoid collisions with
        # bundle scenarios.
        self.scenarios_dest_root.mkdir(parents=True, exist_ok=True)
        for rel in scenarios:
            src = (plugin_dir / rel).resolve()
            if not src.exists() or not src.is_file():
                logger.warning(
                    "plugin_loader[%s]: scenario %s missing", name, rel,
                )
                continue
            prefix = f"{name}__"
            dst_name = (
                src.name if src.name.startswith(prefix)
                else f"{prefix}{src.name}"
            )
            dst = self.scenarios_dest_root / dst_name
            shutil.copy2(src, dst)

        # Memory seeds — write each to the memory store IF the
        # (scope, key) doesn't already exist. Operator edits
        # survive plugin reloads.
        seeded = 0
        for seed in seeds:
            try:
                ok = self._apply_one_seed(seed, name, memory_store)
                if ok:
                    seeded += 1
            except Exception as exc:
                logger.warning(
                    "plugin_loader[%s]: seed %s failed: %s",
                    name, seed.get("key", "?"), exc,
                )

        # Agent definitions contributed by the
        # plugin. Each entry is either an inline dict (matching
        # AgentDefinition shape) OR a path to a YAML file under
        # the plugin dir. Definitions are upserted with origin
        # `plugin:<name>` so the /agents UI surfaces provenance.
        agents = manifest.get("agents") or []
        for entry in agents:
            try:
                self._apply_one_agent(
                    entry, plugin_dir, name, agent_definition_store,
                )
            except Exception as exc:
                logger.warning(
                    "plugin_loader[%s]: agent %s failed: %s",
                    name,
                    (
                        entry.get("name") if isinstance(entry, dict)
                        else str(entry)
                    ),
                    exc,
                )

        return PluginInfo(
            name=name,
            version=version,
            description=description,
            enabled=True,
            path=plugin_dir,
            skills_count=len(skills),
            scenarios_count=len(scenarios),
            memory_seeds_count=len(seeds),
            seeded_count=seeded,
            error=None,
        )

    @staticmethod
    def _apply_one_seed(
        seed: dict[str, Any], plugin_name: str, memory_store: Any
    ) -> bool:
        """Apply one memory seed. Returns True iff a new memory was
        written (existing keys are skipped — operator edits win)."""
        key = seed.get("key")
        value = seed.get("value")
        scope = seed.get("scope") or "agent"
        meta = seed.get("meta") or {}
        ttl = seed.get("ttl_seconds")
        if not isinstance(key, str) or not key.strip():
            return False
        if not isinstance(value, str):
            return False
        # Check existence by listing within scope and matching key.
        # SqliteMemoryStore exposes list_all(scope=...) we can use.
        try:
            existing = memory_store.list_all(scope=scope, limit=10000)
        except Exception:
            existing = []
        for m in existing:
            if getattr(m, "key", None) == key:
                return False  # already present; operator-owned
        # Tag meta with provenance so the operator can see which
        # plugin contributed each memory.
        meta = {
            **meta,
            "source": meta.get("source") or f"plugin:{plugin_name}",
        }
        try:
            memory_store.store(
                key=key,
                value=value,
                scope=scope,
                ttl_seconds=ttl,
                meta=meta,
            )
            return True
        except Exception as exc:
            logger.warning(
                "plugin_loader[%s]: store failed for key=%s: %s",
                plugin_name, key, exc,
            )
            return False

    @staticmethod
    def _apply_one_agent(
        entry: Any,
        plugin_dir: Path,
        plugin_name: str,
        agent_definition_store: Any,
    ) -> bool:
        """Apply one agent definition contribution. The entry can be:
          - a relative path string ("agents/red-team-emulator.yaml")
            pointing to a YAML file under the plugin dir
          - an inline dict matching the AgentDefinition shape

        Returns True iff a definition was upserted. Operator edits
        to a plugin-contributed agent (origin='plugin:<name>') ARE
        overwritten on reload — operators wanting persistent edits
        should clone the definition under origin='operator'."""
        if agent_definition_store is None:
            return False
        body: dict[str, Any]
        if isinstance(entry, str):
            full_path = (plugin_dir / entry).resolve()
            if not full_path.exists() or not full_path.is_file():
                logger.warning(
                    "plugin_loader[%s]: agent file %s missing",
                    plugin_name, entry,
                )
                return False
            try:
                body = yaml.safe_load(full_path.read_text()) or {}
            except Exception as exc:
                logger.warning(
                    "plugin_loader[%s]: agent file %s malformed: %s",
                    plugin_name, entry, exc,
                )
                return False
        elif isinstance(entry, dict):
            body = dict(entry)
        else:
            logger.warning(
                "plugin_loader[%s]: agent entry must be a string path "
                "or inline dict; got %s",
                plugin_name, type(entry).__name__,
            )
            return False
        if not isinstance(body, dict):
            return False
        # Tag origin BEFORE the upsert so the store records
        # provenance correctly.
        try:
            agent_definition_store.upsert(
                body, origin=f"plugin:{plugin_name}"
            )
            return True
        except ValueError as exc:
            logger.warning(
                "plugin_loader[%s]: agent definition rejected: %s",
                plugin_name, exc,
            )
            return False

    @staticmethod
    def _read_manifest(plugin_dir: Path) -> dict[str, Any]:
        path = plugin_dir / "manifest.yaml"
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise ValueError(
                f"manifest read failed: {exc}"
            ) from exc
        if not isinstance(data, dict):
            raise ValueError("manifest must be a YAML mapping")
        return data
