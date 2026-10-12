"""WebhookDispatcher — channel:* notification fanout to operator-supplied URLs.

SqliteNotificationStore.publish() accepts a DispatchHook callable for
channel:* targets; main.py wires this dispatcher in as that hook, so
publish("detection-miss", ...) (target=channel:soc) reaches
Slack/PagerDuty/whatever the operator configured.

# Configuration

Each channel's webhook URL is read from an env var at startup.
The naming convention:

    target              env var
    channel:soc         PHANTOM_NOTIFICATION_CHANNEL_SOC
    channel:purple-team PHANTOM_NOTIFICATION_CHANNEL_PURPLE_TEAM
                        (hyphens become underscores in the var name)

Channels with no configured URL skip cleanly — the notification
still persists (dispatch_status="stored"), just without an outbound
call. Operators can fill missing URLs later without losing prior
notifications.

# Why env vars, not the SecretStore

Webhook URLs ARE credentials (Slack incoming-webhook tokens are
bearer-equivalent). Two reasons env vars are the right surface for
this iteration:

  1. Operators already manage env-style config via .env (MCP_TOKEN,
     PHANTOM_SECRET_KEK live there). Adding more env vars matches
     the existing operational model.
  2. The SecretStore is the right home for connector secrets — those
     flow through the /connectors instance form. Notification webhooks are a
     deployment-time config, not part of the connector instance
     model. Different surface, different lifecycle.

A future improvement could add a settings section for channel
URLs that writes them to the SecretStore at paths like
`/agents/phantom/notifications/channels/<name>/webhook_url`. Until
then, env-var config keeps the surface small and the
configurable-without-rebuild story intact.

# Payload shape

The default dispatcher sends a generic JSON payload:

    POST <webhook_url>
    Content-Type: application/json
    {
      "topic":     "detection-miss",
      "severity":  "warning",
      "target":    "channel:soc",
      "id":        "<notification uuid>",
      "created_at": "<iso8601>",
      "payload":   {...the application's own payload...}
    }

This works as-is for any webhook receiver that accepts arbitrary JSON
(generic SOAR, internal services). For Slack incoming webhooks the
operator can chain through a thin adapter (the `text`/`blocks` shape
Slack expects). Future improvement: per-channel formatter selection
based on URL host (slack.com → Slack-shaped, events.pagerduty.com →
PagerDuty Events API v2, etc.).

# Failure handling

The hook raises on dispatch failure. SqliteNotificationStore.publish()
catches that and records dispatch_status="failed" + dispatch_error.
The notification still persists — the operator sees what didn't
reach where via /api/v1/notifications, even when the upstream is
down.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

import httpx

logger = logging.getLogger("Phantom MCP")

CHANNEL_PREFIX = "channel:"
ENV_PREFIX = "PHANTOM_NOTIFICATION_CHANNEL_"
DEFAULT_TIMEOUT_S = 10.0


def env_var_for(channel: str) -> str:
    """Map a channel name like 'soc' or 'purple-team' to its env var.

    Replaces hyphens with underscores and uppercases. Stable mapping
    so operators can predict the env var from the manifest.
    """
    sanitized = re.sub(r"[^A-Za-z0-9]", "_", channel).upper()
    return f"{ENV_PREFIX}{sanitized}"


class WebhookDispatcher:
    """Channel:* fanout via outbound HTTP POST.

    Designed to be plugged in as the SqliteNotificationStore's
    `dispatch_hook` parameter:

        store = SqliteNotificationStore(
            ..., dispatch_hook=WebhookDispatcher(),
        )
    """

    def __init__(
        self,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        env: dict[str, str] | None = None,
    ) -> None:
        # Capture os.environ at construction (or accept an injected
        # dict for testing). Reading at __init__ rather than per-call
        # makes the configured channel set deterministic for the
        # process lifetime — operators set URLs in .env and restart
        # to add a new channel, same lifecycle as other env config.
        self._env: dict[str, str] = dict(env if env is not None else os.environ)
        self._timeout = timeout_s

    def __call__(self, notification: Any) -> None:
        """Required signature: takes a Notification, returns None.
        Raises on dispatch failure so the caller (publish) can record
        dispatch_status=failed."""
        target = getattr(notification, "target", "") or ""
        if not target.startswith(CHANNEL_PREFIX):
            return  # not a channel target — do nothing
        channel = target[len(CHANNEL_PREFIX):]
        url = self._env.get(env_var_for(channel))
        if not url:
            # No URL configured for this channel. Log and return —
            # the publish() caller treats "no exception" as
            # dispatched, so we want this to NOT count as
            # dispatched. Raise a specific exception so the row
            # gets dispatch_status=failed with a clear reason.
            raise RuntimeError(
                f"no webhook URL configured for {target!r} "
                f"(set {env_var_for(channel)} in .env)"
            )

        body = {
            "topic":      getattr(notification, "topic", None),
            "severity":   getattr(notification, "severity", None),
            "target":     target,
            "id":         getattr(notification, "id", None),
            "created_at": getattr(notification, "created_at", None),
            "payload":    getattr(notification, "payload", None) or {},
        }
        try:
            with httpx.Client(timeout=self._timeout) as client:
                resp = client.post(
                    url,
                    json=body,
                    headers={"Content-Type": "application/json"},
                )
        except httpx.HTTPError as exc:
            raise RuntimeError(
                f"webhook POST to {target} failed: {type(exc).__name__}: {exc}"
            )
        if resp.status_code >= 400:
            # Slack returns 200 with body "invalid_payload" sometimes;
            # operators can read the error in the dispatch_error column.
            body_preview = resp.text[:200] if resp.text else "(empty)"
            raise RuntimeError(
                f"webhook POST to {target} → {resp.status_code}: {body_preview}"
            )
        logger.info(
            "Notification webhook dispatched: target=%s topic=%s status=%d",
            target, body["topic"], resp.status_code,
        )
