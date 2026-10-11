"""Plugin-contributed hook handler runner.

Entry-point discovery and lifecycle are visible at
/observability/plugins. This runner closes the loop: plugin-contributed handlers in the
`phantom.hooks` entry-point group become CALLABLE from the agent's
hook-runner via an HTTP bridge.

Handler contract for plugin authors:

    # pyproject.toml
    [project.entry-points."phantom.hooks"]
    my-handler = "my_pkg.hooks:my_handler"

    # my_pkg/hooks.py
    def my_handler(payload: dict, config: dict) -> dict | None:
        '''Receive a HookPayload + operator config; return a
        HookResult dict or None for no-op.

        payload shape mirrors lib/hooks.ts HookPayload (event +
        event-specific fields). config is whatever the operator
        configured for this hook instance in /settings/hooks.

        Return None → no-op (same as not registering anything).
        Return dict → parsed as HookResult:
          {"decision": "allow" | "deny" | "ask", "reason": "..."}.
        '''
        return None

Discovery happens once per MCP boot + on demand (after pip install).
Plugin handlers run in the MCP process with full agent privileges.
Operators install plugins with the same trust they'd extend to a
vendor library — review the source before pip install.

Safety:

  - Bearer-auth via MCP_TOKEN — only the agent can invoke plugin
    handlers. No direct operator → plugin call path.
  - Timeout: each invoke runs in a thread bounded by `timeout_s`
    (defaults to 5s). Hung plugins don't block the hook-runner.
  - Audit: every invoke writes a `plugin_hook_invoked` event with
    handler name + dist + return-shape category (allow/deny/no-op/error).
  - Exception isolation: plugin exceptions are caught + returned as
    `{"error": str(exc)}` so they surface in the agent's hook-runner
    failure-policy path rather than 500-ing the MCP.
"""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from dataclasses import dataclass
from importlib import metadata
from typing import Any, Callable

logger = logging.getLogger("Phantom MCP")


@dataclass(frozen=True)
class PluginHookHandler:
    """One resolved plugin hook handler. Cached after first import so
    repeat invocations don't pay import cost."""

    name: str
    dist_name: str
    dist_version: str
    target: str
    fn: Callable[..., Any]


# In-process cache. Resolved at first invoke; cleared via clear_cache()
# after install/uninstall (the lifecycle endpoints call this).
_HANDLER_CACHE: dict[str, PluginHookHandler] = {}
_CACHE_LOCK = threading.Lock()

# Thread pool for plugin-handler invocation. Shared across calls so
# we don't spawn a new thread per hook fire. 4 workers is plenty —
# hook handlers are short-lived and the agent fires them serially
# per event in practice.
_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="plugin-hook")


def _discover_handlers() -> dict[str, PluginHookHandler]:
    """Walk phantom.hooks entry-points and return name → handler.
    Imports each handler's module (resolving the entry-point) and
    caches the result.

    Plugin authors register via:
        [project.entry-points."phantom.hooks"]
        my-handler = "my_pkg.hooks:my_handler"
    """
    out: dict[str, PluginHookHandler] = {}
    try:
        eps = metadata.entry_points(group="phantom.hooks")
    except TypeError:
        # Older importlib.metadata API. Phantom ships 3.12 so this
        # path is defensive only.
        eps = metadata.entry_points().get("phantom.hooks", [])  # type: ignore[attr-defined]

    for ep in eps:
        dist = getattr(ep, "dist", None)
        dist_name = (dist and getattr(dist, "name", "")) or ""
        dist_version = (dist and getattr(dist, "version", "")) or ""
        try:
            fn = ep.load()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "plugin_hook_runner: failed to load handler %s = %s "
                "(from %s %s): %s",
                ep.name, ep.value, dist_name or "<unknown>",
                dist_version or "?", exc,
            )
            continue
        if not callable(fn):
            logger.warning(
                "plugin_hook_runner: %s = %s did not resolve to a "
                "callable; skipping",
                ep.name, ep.value,
            )
            continue
        out[ep.name] = PluginHookHandler(
            name=ep.name,
            dist_name=dist_name,
            dist_version=dist_version,
            target=ep.value,
            fn=fn,
        )
    return out


def get_handlers(refresh: bool = False) -> dict[str, PluginHookHandler]:
    """Return name → handler. Discovers + caches on first call;
    `refresh=True` re-walks entry-points (used after pip install)."""
    with _CACHE_LOCK:
        if refresh or not _HANDLER_CACHE:
            _HANDLER_CACHE.clear()
            _HANDLER_CACHE.update(_discover_handlers())
        return dict(_HANDLER_CACHE)


def clear_cache() -> None:
    """Drop the resolved-handler cache. Called by the install/uninstall
    endpoints so the next invoke walks fresh entry-points."""
    with _CACHE_LOCK:
        _HANDLER_CACHE.clear()


def list_handlers() -> list[dict[str, Any]]:
    """Return JSON-safe handler descriptors for the agent's UI
    dropdown. Doesn't include the callable itself."""
    out: list[dict[str, Any]] = []
    for h in get_handlers().values():
        out.append(
            {
                "name": h.name,
                "dist_name": h.dist_name,
                "dist_version": h.dist_version,
                "target": h.target,
            }
        )
    out.sort(key=lambda d: d["name"])
    return out


def invoke_handler(
    name: str,
    payload: dict[str, Any],
    config: dict[str, Any] | None = None,
    timeout_s: float = 5.0,
) -> dict[str, Any]:
    """Invoke the named plugin hook handler with payload + config.

    Returns a JSON-safe dict:
      - On success: {"ok": True, "result": <handler return>, "duration_ms": ...}
      - On unknown name: {"ok": False, "error": "unknown handler ...", "duration_ms": 0}
      - On exception inside the handler: {"ok": False, "error": "...", "duration_ms": ...}
      - On timeout: {"ok": False, "error": "timeout after Ns", "duration_ms": ...}

    The agent's hook-runner translates this into the standard
    HookResult shape (or the failure policy if `ok=False`).
    """
    started_at = time.time()
    handlers = get_handlers()
    if name not in handlers:
        # Try one refresh in case a recent install added it.
        handlers = get_handlers(refresh=True)
    if name not in handlers:
        return {
            "ok": False,
            "error": f"unknown plugin hook handler: {name!r}. "
                     f"Discovered handlers: {sorted(handlers.keys())[:10]}",
            "duration_ms": 0,
        }
    handler = handlers[name]

    def _call() -> Any:
        # Pass config as a separate arg so plugin handlers have a
        # clean signature. Plugin authors who only need payload can
        # accept config=None or use **kwargs.
        return handler.fn(payload, config or {})

    try:
        future = _EXECUTOR.submit(_call)
        result = future.result(timeout=timeout_s)
    except TimeoutError:
        return {
            "ok": False,
            "error": f"plugin handler {name!r} timed out after {timeout_s}s",
            "duration_ms": int((time.time() - started_at) * 1000),
            "handler": handler.target,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "error": f"plugin handler {name!r} raised: {type(exc).__name__}: {exc}",
            "duration_ms": int((time.time() - started_at) * 1000),
            "handler": handler.target,
        }

    # Result shape: plugin returned None → no-op, dict → HookResult.
    duration_ms = int((time.time() - started_at) * 1000)
    if result is None:
        return {
            "ok": True,
            "result": None,
            "duration_ms": duration_ms,
            "handler": handler.target,
        }
    if not isinstance(result, dict):
        return {
            "ok": False,
            "error": (
                f"plugin handler {name!r} returned non-dict "
                f"({type(result).__name__}); expected dict | None"
            ),
            "duration_ms": duration_ms,
            "handler": handler.target,
        }
    return {
        "ok": True,
        "result": result,
        "duration_ms": duration_ms,
        "handler": handler.target,
    }
