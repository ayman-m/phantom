"""Process-wide tool-dispatcher singleton.

A small accessor pair (set/get) for the dispatcher the job scheduler
already constructs at boot. Exposed here so other code paths
(specifically `agent_batch_propose` for connector-tool
batching) can dispatch to any registered tool by name without
duplicating the fastmcp.Client wiring.

Same singleton pattern as `set_scheduler` / `get_scheduler` in
job_scheduler — module-level holder, main.py installs it at boot,
consumers `get_tool_dispatcher()` and either dispatch or return a
clean error if the runtime isn't fully wired.

# Why a singleton rather than passing the dispatcher around

Two consumers (the scheduler + agent_batch_propose) need it at runtime,
and threading the dispatcher through the entire MCP-tool callsite would
mean re-wiring every existing self_mod_tool. The singleton keeps the
dispatcher coupling local.

# Lifecycle

main.py async_main() constructs the dispatcher AFTER register_all_tools
populates the tool_registry. Tools registered by a later hot-reload
(api/admin.py /reload_tools, api/instances.py) re-use the same registry
dict (mutated in place), so the dispatcher closure stays current
without a re-set.
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

logger = logging.getLogger("Phantom MCP")

ToolDispatcher = Callable[[str, dict[str, Any]], Awaitable[Any]]

_tool_dispatcher: ToolDispatcher | None = None


def set_tool_dispatcher(d: ToolDispatcher | None) -> None:
    """Install the process-wide dispatcher. Called once at boot from
    main.py after register_all_tools + make_tool_dispatcher."""
    global _tool_dispatcher
    _tool_dispatcher = d
    if d is not None:
        logger.info("tool_dispatcher installed")
    else:
        logger.info("tool_dispatcher cleared")


def get_tool_dispatcher() -> ToolDispatcher | None:
    """Return the dispatcher, or None when the runtime hasn't wired it
    (e.g. test harness, partial boot). Consumers handle None with a
    clean error envelope rather than crashing."""
    return _tool_dispatcher
