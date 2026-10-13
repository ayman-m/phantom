"""Bearer for the embedded MCP's own calls into the agent's /api/chat.

The agent middleware gates /api/chat on a session cookie or a
``phantom_ak_`` API key. Server-side callers inside the container (the job
scheduler, the benchmark runner) carry neither, so they present the
container's MCP_TOKEN, the same loopback trust the agent's
/api/agent/internal/* routes use. One helper, one source (pydantic-settings),
so a new in-container caller cannot forget it.
"""

from __future__ import annotations


def internal_chat_bearer() -> str:
    """The MCP_TOKEN as an Authorization header value, or "" when unset."""
    from config.config import get_config  # noqa: PLC0415

    token = (get_config().mcp_token or "").strip()
    return f"Bearer {token}" if token else ""
