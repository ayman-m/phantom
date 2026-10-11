"""Fire-and-forget hook callback to the agent.

The hook dispatcher (lib/hook-runner.ts) lives TS-side, so MCP-side
code paths (notification publish, approval request) need a way to
trigger hook dispatch. The agent exposes an internal endpoint,
`/api/agent/internal/fire-hook`, that MCP calls when a
hook-eligible event happens.

Constraints:

  - Best-effort: a failed callback must NOT break the notification /
    approval creation that triggered it. Errors get logged and
    swallowed.
  - Non-blocking: notifications/approvals are sync code paths;
    blocking them on an HTTP round-trip would slow every event.
    Fire the callback in a background thread so the caller returns
    immediately.
  - Loopback only: the agent's internal endpoint lives at
    `PHANTOM_AGENT_INTERNAL_URL` (default `https://phantom-agent:8080`
    inside the compose network), gated by `MCP_TOKEN` bearer.

Recursion caveat: if an operator installs a Notification hook whose
handler creates more notifications, we'll fire another callback,
which fires the hook again, etc. There is no recursion defense;
it is a known caveat for Notification hook authors. A cleaner defense
(header-based source tagging) is possible if the caveat bites in
practice.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any

logger = logging.getLogger("Phantom MCP")


# Sentinel for the agent's internal URL. Read at call time (not at
# module import) so a late env-var change (e.g. test setup) is
# respected.
def _agent_internal_url() -> str:
    return os.environ.get(
        "PHANTOM_AGENT_INTERNAL_URL", "https://phantom-agent:8080"
    ).rstrip("/")


def _mcp_token() -> str:
    return os.environ.get("MCP_TOKEN", "")


def fire_hook_event_async(event: str, payload: dict[str, Any]) -> None:
    """Fire `event` with `payload` against the agent's hook dispatcher.
    Returns immediately; the HTTP call happens on a background thread.

    Args:
        event: One of the HOOK_EVENTS values the agent recognizes.
            Wired events: Notification, PermissionRequest.
        payload: Event-specific shape — see lib/hooks.ts HookPayload.
            Must be JSON-serializable. Caller's responsibility to
            shape it correctly.
    """
    token = _mcp_token()
    if not token:
        logger.debug(
            "hook_dispatch_callback: MCP_TOKEN empty; skipping %s callback",
            event,
        )
        return

    url = f"{_agent_internal_url()}/api/agent/internal/fire-hook"
    body = {"event": event, "payload": payload}

    def _send() -> None:
        try:
            # httpx is the project's standard HTTP client (already used
            # by job_scheduler._dispatch_chat). Import inside the
            # thread so a missing dep doesn't crash module import.
            import httpx

            # The agent's TLS proxy is self-signed inside the compose
            # network; verify=False matches the existing internal
            # loopback pattern in job_scheduler.py.
            with httpx.Client(
                timeout=httpx.Timeout(5.0), verify=False,
            ) as client:
                resp = client.post(
                    url,
                    json=body,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                    },
                )
                if resp.status_code >= 400:
                    logger.debug(
                        "hook_dispatch_callback: agent returned %s on %s callback: %s",
                        resp.status_code, event,
                        resp.text[:200] if resp.text else "<empty>",
                    )
        except Exception as exc:  # noqa: BLE001
            # Don't even WARN-log — operators don't need to see this
            # noise. The agent endpoint is best-effort; missing it
            # just means hooks didn't fire for this event, which is
            # the behavior without this callback anyway.
            logger.debug(
                "hook_dispatch_callback: %s callback to %s failed: %s",
                event, url, exc,
            )

    # Daemon thread so it doesn't block process shutdown if the
    # agent's endpoint is hung.
    t = threading.Thread(target=_send, name=f"hook-cb-{event}", daemon=True)
    t.start()
