"""Destination handler registry.

Imports the Python handler module sitting adjacent to each manifest's
spec.yaml (i.e. `<type_id>/handler.py`) and caches them keyed by
type_id. Provides a single `dispatch_probe()` / `dispatch_send()`
interface that the REST API + xlog bridge both call.

# File-path-based loading

The spec.yaml's `handler:` field is NOT resolved as a Python DOTTED
module path (e.g. `bundles.spark.destinations.syslog.handler`). That
would work locally where the repo root is the CWD, but the agent
container ships the destinations at `/app/bundle/destinations/<id>/`
with `/app/bundle` NOT on sys.path, so the import would fail with
`ModuleNotFoundError: No module named 'bundles'` at MCP boot.

Instead, each handler is loaded by FILE PATH via `importlib.util.spec_from_
file_location` against `<dest_root>/<type_id>/handler.py`. The
spec.yaml's `handler:` field is an informational reference (and
can be left as-is); the loader doesn't use it for resolution. This
makes the destination types relocatable — they work in any layout
where the loader's `resolve_destinations_root()` finds the spec.yaml.

The handler interface is structural (Python doesn't require ABC):

    async def probe(merged_config: dict[str, Any]) -> dict[str, Any]
    async def send(merged_config: dict[str, Any],
                   records: list[dict[str, Any]]) -> dict[str, Any]

Registry boot rule: every loaded manifest MUST resolve to a handler.py
file with both callables. Missing handler.py → MCP fails to boot
loudly (no silent fallback). CLAUDE.md § Canonical-state discipline
Rule 5 — fail loudly when the spec and the code disagree.
"""

from __future__ import annotations

import importlib
import importlib.util
import logging
from pathlib import Path
from types import ModuleType
from typing import Any

from .destination_types_loader import (
    get_destination_types_loader,
    resolve_destinations_root,
)

logger = logging.getLogger("Phantom MCP")


_handlers: dict[str, ModuleType] = {}
_initialized: bool = False


def _validate_handler_module(type_id: str, module: ModuleType) -> None:
    """Loud check: module must expose `probe` and `send` callables."""
    for fn_name in ("probe", "send"):
        fn = getattr(module, fn_name, None)
        if fn is None or not callable(fn):
            raise RuntimeError(
                f"destination type {type_id!r}: handler module "
                f"{module.__name__!r} is missing required callable "
                f"{fn_name!r}"
            )


def _load_handler_from_path(type_id: str, handler_path: Path) -> ModuleType:
    """Load handler.py by file path. Module name is unique per type_id
    so importlib's module cache doesn't collide between types.
    """
    spec = importlib.util.spec_from_file_location(
        f"phantom_destination_handler_{type_id}",
        handler_path,
    )
    if spec is None or spec.loader is None:
        raise ImportError(
            f"failed to build module spec for {handler_path}"
        )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def initialize() -> None:
    """Load every handler.py adjacent to its spec.yaml.

    Called once at MCP boot. Subsequent calls are no-ops unless
    `reload()` clears the registry first.

    Resolution: `<destinations_root>/<type_id>/handler.py`. The
    manifest's `handler:` field is informational; the loader picks
    the file by convention, not by dotted module path.
    """
    global _initialized
    if _initialized:
        return
    loader = get_destination_types_loader()
    manifests = loader.list_all()
    root = resolve_destinations_root()
    failures: list[str] = []
    for type_id, manifest in manifests.items():
        handler_path = root / type_id / "handler.py"
        try:
            if not handler_path.is_file():
                raise FileNotFoundError(
                    f"handler.py not found at {handler_path}"
                )
            module = _load_handler_from_path(type_id, handler_path)
            _validate_handler_module(type_id, module)
            _handlers[type_id] = module
        except Exception as e:  # noqa: BLE001
            failures.append(
                f"{type_id} ({handler_path}): {type(e).__name__}: {e}"
            )
            logger.error(
                "destination_handler_registry: failed to load %s: %s",
                handler_path, e,
            )
    if failures:
        # Fail loudly. The MCP should refuse to boot when destination
        # type manifests declare handlers that don't exist.
        raise RuntimeError(
            "destination handlers failed to import:\n  - "
            + "\n  - ".join(failures)
        )
    _initialized = True
    logger.info(
        "destination_handler_registry: initialized with %d handlers: %s",
        len(_handlers), sorted(_handlers.keys()),
    )


def get_handler(type_id: str) -> ModuleType | None:
    """Return the cached handler module for `type_id`, or None.

    Triggers initialize() lazily on first call so test-only flows that
    instantiate the store without going through main.py still work.
    """
    if not _initialized:
        initialize()
    return _handlers.get(type_id)


def list_registered() -> list[str]:
    """Return all type_ids with a wired handler."""
    if not _initialized:
        initialize()
    return sorted(_handlers.keys())


async def dispatch_probe(
    type_id: str, merged_config: dict[str, Any],
) -> dict[str, Any]:
    """Invoke the type's probe() implementation. Raises if no handler."""
    handler = get_handler(type_id)
    if handler is None:
        raise KeyError(
            f"no handler registered for destination type {type_id!r}"
        )
    return await handler.probe(merged_config)


async def dispatch_send(
    type_id: str,
    merged_config: dict[str, Any],
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    """Invoke the type's send() implementation. Raises if no handler."""
    handler = get_handler(type_id)
    if handler is None:
        raise KeyError(
            f"no handler registered for destination type {type_id!r}"
        )
    return await handler.send(merged_config, records)


def reset_for_tests() -> None:
    """Test-only hook — clear the registry between tests that need
    different loader state."""
    global _initialized
    _handlers.clear()
    _initialized = False
