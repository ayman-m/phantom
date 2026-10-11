"""Container-side shim that mimics phantom-agent's
`bundles/spark/mcp/src/config/config.py` interface.

Connector code (e.g. `bundles/spark/connectors/web/src/browser.py`)
imports from this module:

    from config.config import get_config

In phantom-agent, that resolves to a real Settings + ConfigProxy
backed by env vars + per-instance contextvar overrides. In a
connector container, the only thing that matters is "get the
instance-config blob" — there are no env-var Settings to fall back
to, because the container was started with all the per-instance
values already known. This shim provides that minimal surface.

# Public API (mirrored from the agent's config.config):

    get_config()               → returns _ConfigProxy with instance values
    set_current_instance(d)    → set the contextvar to dict d, returns token
    reset_current_instance(t)  → reset via the returned token

# What the agent's version does that this DOESN'T

  - No Settings class. The container has no env-var-derived defaults
    because everything per-instance was loaded into the contextvar
    by the runtime entrypoint at boot.
  - No reload_config(). Runtime config is fixed at container start;
    operators reconfigure by stopping + restarting the container
    (which is what phantom-updater does on edit-instance).
  - No `_ConfigProxy` fall-through to underlying Settings — if a key
    isn't in the instance overrides, attribute access raises.
    Connector code that needs a default should use
    `getattr(cfg, key, default)` (which the existing connectors
    already do; see browser.py:_instance_config).

Raising on missing-key is intentional: if a connector tries to read
`config.x` and `x` isn't in the instance row, that's a bug in the
connector or a stale instance. Better to surface it loudly than
silently fall through to None.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any


# Set by runtime/entrypoint.py at boot, after instance config + secrets
# are merged. Connector code reads it transparently via get_config().
_current_instance_overrides: ContextVar[dict[str, Any] | None] = ContextVar(
    "_current_instance_overrides", default=None,
)


class _ConfigProxy:
    """Read-only proxy over the instance overrides dict.

    Slot-based to keep the per-call attribute lookup cheap. No fall-
    through to a Settings layer (the container has none).
    """

    __slots__ = ("_overrides",)

    def __init__(self, overrides: dict[str, Any]) -> None:
        self._overrides = overrides

    def __getattr__(self, name: str) -> Any:
        if name in self._overrides:
            return self._overrides[name]
        raise AttributeError(
            f"config key {name!r} not set on this connector instance. "
            f"Either add it to the instance's config (via /connectors UI "
            f"on the agent) or use getattr(config, {name!r}, default) "
            f"in the connector code."
        )


def get_config() -> _ConfigProxy:
    """Return a proxy over the current instance's config. Connector code
    reads attributes off this object the same way it does in
    phantom-agent — the call site is unchanged across runtimes."""
    overrides = _current_instance_overrides.get()
    if overrides is None:
        # Should never happen in production: the entrypoint sets the
        # contextvar before importing the connector module + starting
        # FastMCP. Surface explicitly so the misuse is loud.
        raise RuntimeError(
            "config.get_config() called before runtime.entrypoint set the "
            "instance contextvar. This usually means connector code is "
            "running outside the runtime (a test harness?) or the "
            "entrypoint failed to load the instance row."
        )
    return _ConfigProxy(overrides)


def set_current_instance(overrides: dict[str, Any] | None) -> Any:
    """Set the per-instance config blob. Returns a token for
    `reset_current_instance` (paired with try/finally if you ever need
    to swap mid-call — typically the container is per-instance so this
    is set once at boot)."""
    return _current_instance_overrides.set(overrides)


def reset_current_instance(token: Any) -> None:
    """Reset the contextvar to its prior value."""
    _current_instance_overrides.reset(token)
