"""Reference connector — minimal demo_echo tool.

Demonstrates the runtime contract:
  * Public function in connector.py exposed via __all__.
  * Reads per-instance config via `from config.config import get_config`
    (the runtime's contextvar shim — same API as in-process loader).
  * Returns a dict that flows back through the agent's MCP proxy
    unchanged.
  * Uses async (FastMCP supports both sync + async; async is the
    convention in Phantom's connector code).

Naming: function is `phantom__runtime_demo_echo`. The runtime
entrypoint strips the `phantom__runtime_` prefix at registration
time, so the agent's MCP proxy sees the tool as `demo_echo`. This
matches how xlog uses `phantom_<id>_<tool>` and how web uses
`phantom_web_<tool>`. Either prefix style works; the runtime
handles them all.
"""

from __future__ import annotations

from typing import Any

from config.config import get_config


__all__ = ["phantom__runtime_demo_echo"]


async def phantom__runtime_demo_echo(message: str, **extra: Any) -> dict[str, Any]:
    """Return {greeting, message} where greeting comes from instance config.

    Args:
        message: the text to echo back.
        **extra: any additional keyword args; included verbatim in
                 the response so callers can verify proxy round-trip.

    Returns:
        {"greeting": <from instance config or "Hello">,
         "message": <the input>,
         "extra": <any other kwargs>}
    """
    cfg = get_config()
    # getattr-with-default handles the case where the instance config
    # didn't set `greeting` — the connector.yaml's configSchema lists
    # a default but the operator might not have explicitly set it
    # in the form, in which case it just isn't on the proxy.
    greeting = getattr(cfg, "greeting", "Hello")
    return {
        "greeting": greeting,
        "message": message,
        "extra": extra,
    }
