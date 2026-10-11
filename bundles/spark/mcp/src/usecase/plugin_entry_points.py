"""Entry-point plugin discovery (scoped).

Phantom already has a filesystem-based plugin loader at
`plugin_loader.py` (directory-discovered plugins
under `bundles/spark/plugins/<name>/`). This module adds the DISTRIBUTABLE
side: Python entry-point discovery, mirroring Octagon's
`Registry(entry_point_group="octagon.hooks")` pattern. Third-party
packages declare contributions via setup.py / pyproject.toml entry
points and ship as pip-installable wheels.

A full plugin lifecycle (marketplace UI for pip-installing, hot-reload
on install, plugin detail pages, safety warnings, sandboxed execution)
is NOT implemented; it would carry real security implications (plugins
run with agent privileges). This module is the DISCOVERY SCAFFOLDING:

  - `discover_plugins(group)` walks `importlib.metadata.entry_points`
    for a named group and returns refs.
  - Five group names reserved: phantom.skills, phantom.connectors,
    phantom.hooks, phantom.scanners, phantom.providers.
  - At MCP boot, `log_discovery()` walks all five and logs counts —
    fresh installs see zero plugins (no third-party packages target
    these groups yet); the contract is in place for future packages.

The registries that CONSUME entry-point-contributed plugins (skill
registry, hook store, etc.) are NOT yet wired to read from this
loader's results yet; that wiring waits for at least one third-party
plugin package to validate the integration end-to-end.

This module establishes the contract third-party developers can
target.

# Contract for third-party packages

In your `pyproject.toml`:

    [project.entry-points."phantom.skills"]
    my-skill = "my_pkg.skills:my_skill_factory"

The agent walks these at boot via `discover_plugins("phantom.skills")`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from importlib import metadata
from typing import Any

logger = logging.getLogger("Phantom MCP")


# Reserved entry-point group names. Third-party packages contribute
# via `entry_points={"phantom.X": [...]}` in their setup.py /
# pyproject.toml.
SUPPORTED_GROUPS: tuple[str, ...] = (
    "phantom.skills",
    "phantom.connectors",
    "phantom.hooks",
    "phantom.scanners",
    "phantom.providers",
)


@dataclass(frozen=True)
class PluginRef:
    """One discovered entry-point. Identifies the distribution + the
    target callable; resolution (importing + invoking) happens in the
    consumer-side wiring."""

    group: str
    name: str
    dist_name: str
    dist_version: str
    target: str  # "package.module:callable"

    def to_dict(self) -> dict[str, Any]:
        return {
            "group": self.group,
            "name": self.name,
            "dist_name": self.dist_name,
            "dist_version": self.dist_version,
            "target": self.target,
        }


def discover_plugins(group: str) -> list[PluginRef]:
    """Walk importlib.metadata.entry_points for the named group.
    Returns one PluginRef per entry-point. Safe on systems with no
    plugins installed — returns empty list.

    Modern keyword form (Python 3.10+); Phantom's agent container
    runs 3.12 so this is always supported.
    """
    if group not in SUPPORTED_GROUPS:
        raise ValueError(
            f"unknown plugin group {group!r}; supported: {SUPPORTED_GROUPS}"
        )
    out: list[PluginRef] = []
    try:
        eps = metadata.entry_points(group=group)
    except TypeError:
        # Defensive: older importlib.metadata API. Phantom doesn't
        # ship on a Python where this path would actually trigger; it's
        # here so test environments with stripped-down stdlib don't
        # blow up.
        eps = metadata.entry_points().get(group, [])  # type: ignore[attr-defined]
    for ep in eps:
        dist = getattr(ep, "dist", None)
        dist_name = ""
        dist_version = ""
        if dist is not None:
            dist_name = getattr(dist, "name", "") or ""
            dist_version = getattr(dist, "version", "") or ""
        out.append(
            PluginRef(
                group=group,
                name=ep.name,
                dist_name=dist_name,
                dist_version=dist_version,
                target=ep.value,
            )
        )
    return out


def discover_all() -> dict[str, list[PluginRef]]:
    """Walk every supported group. Returns {group: [PluginRef, ...]}.
    Called by the MCP boot path for the one-time startup discovery
    log entry."""
    out: dict[str, list[PluginRef]] = {}
    for group in SUPPORTED_GROUPS:
        try:
            out[group] = discover_plugins(group)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "plugin_entry_points: discovery for %s failed: %s", group, exc
            )
            out[group] = []
    return out


def log_discovery() -> dict[str, int]:
    """Log + return per-group counts. Wired into MCP startup so the
    operator sees plugin discovery in the boot log. Returns counts
    for downstream telemetry (audit row, /observability metric)."""
    counts: dict[str, int] = {}
    for group, refs in discover_all().items():
        counts[group] = len(refs)
        if refs:
            logger.info(
                "plugin_entry_points: discovered %d plugin(s) in group %s:",
                len(refs), group,
            )
            for ref in refs:
                logger.info(
                    "  - %s = %s  (from %s %s)",
                    ref.name, ref.target,
                    ref.dist_name or "<unknown-dist>",
                    ref.dist_version or "?",
                )
        else:
            logger.debug("plugin_entry_points: no plugins in group %s", group)
    total = sum(counts.values())
    logger.info(
        "plugin_entry_points: discovery complete — %d total plugin(s) across %d groups",
        total, len(SUPPORTED_GROUPS),
    )
    return counts
