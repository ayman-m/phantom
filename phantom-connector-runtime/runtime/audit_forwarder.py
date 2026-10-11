"""Fire-and-forget audit-event forwarder for connector containers.

When a connector tool wants to write an audit row (e.g.
"agent_self_mod_executed", "tool_call_with_outcome"), it calls
`record_event()` here. The forwarder POSTs to the agent's
`/api/v1/audit` endpoint via the URL in `PHANTOM_AUDIT_URL`,
authenticating with `MCP_TOKEN`.

# Why fire-and-forget

Audit writes shouldn't block tool execution. If the agent is briefly
unreachable (rolling restart, network blip), the connector's main
job — answering the tool call — should still succeed. The forwarder
buffers up to N events in memory and retries with exponential
backoff in a background task; events that exhaust retries are
logged at WARN level (visible via `docker logs phantom-connector-X`)
and dropped.

# Why not write directly to audit_log.db

Two reasons:
  1. Single source of truth. The agent's audit_log is the operator-
     facing record; having connectors write directly to the same
     SQLite file would require write coordination across containers,
     which SQLite handles poorly under contention.
  2. Defense-in-depth. A compromised connector that can write
     arbitrary rows to audit_log.db could inject false trail entries.
     Forcing it through the agent's HTTP endpoint means the agent
     can validate, rate-limit, and (future) sign rows before they
     land in durable storage.

# Durability trade-off

This implementation uses a tiny in-memory queue + asyncio task. It's
not durable across container restarts. Events emitted in the brief
window between "tool finished" and "container received SIGTERM"
might be lost.

That's acceptable because:
  - Most audit-worthy tool outcomes are also visible in the agent's
    direct chat-turn audit (chat_turn_cost, agent_self_mod_executed)
    which never leaves the agent process.
  - The connector-side audit is "nice to have" (per-call diagnostic
    rows), not "load-bearing" (security/compliance attestation).
  - A small WAL-backed buffer could be added if the loss rate
    proves real in production.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Knobs — tune via env vars at container start if a deployment
# profile needs different defaults.
_AUDIT_URL_ENV = "PHANTOM_AUDIT_URL"
_MCP_TOKEN_ENV = "MCP_TOKEN"
_QUEUE_CAP = 1024  # events held in memory before drop-on-overflow
_RETRY_MAX = 5
_RETRY_BASE_DELAY_S = 1.0
_RETRY_MAX_DELAY_S = 30.0
_BACKGROUND_FLUSH_INTERVAL_S = 0.2


class _AuditForwarder:
    """Singleton forwarder. The runtime entrypoint creates one at boot
    and exposes `record_event()` to connector code via the module
    -level proxy below."""

    def __init__(self) -> None:
        self._url: str | None = os.getenv(_AUDIT_URL_ENV) or None
        self._token: str | None = os.getenv(_MCP_TOKEN_ENV) or None
        self._queue: asyncio.Queue[dict[str, Any]] | None = None
        self._task: asyncio.Task[None] | None = None
        self._dropped = 0  # cumulative count of overflow drops

    async def start(self) -> None:
        """Spin up the background flush task. Idempotent."""
        if self._task is not None:
            return
        self._queue = asyncio.Queue(maxsize=_QUEUE_CAP)
        self._task = asyncio.create_task(self._flush_loop())
        logger.info(
            "audit forwarder started (url=%s, queue_cap=%d)",
            self._url or "(disabled — no PHANTOM_AUDIT_URL)",
            _QUEUE_CAP,
        )

    async def stop(self) -> None:
        """Drain the queue + cancel the task. Called on SIGTERM."""
        if self._task is None:
            return
        # Give in-flight events ~2s to drain before we cut the cord.
        try:
            if self._queue is not None:
                deadline = time.monotonic() + 2.0
                while not self._queue.empty() and time.monotonic() < deadline:
                    await asyncio.sleep(0.05)
        finally:
            self._task.cancel()
            self._task = None
            if self._dropped:
                logger.warning(
                    "audit forwarder shutting down — dropped %d events "
                    "due to queue overflow during this container's lifetime",
                    self._dropped,
                )

    def record_event(
        self,
        action: str,
        target: str | None = None,
        status: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Enqueue an audit event for forwarding. Non-blocking; drops
        on overflow with a logged warning rather than raising into the
        connector's tool-call path."""
        if self._url is None or self._queue is None:
            # Audit URL not set — agent is running in a "no audit
            # forwarding" config. Drop silently; this is the dev/test
            # case where the connector container is started standalone.
            return
        event = {
            "action": action,
            "target": target,
            "status": status,
            "metadata": metadata or {},
        }
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            self._dropped += 1
            if self._dropped == 1 or self._dropped % 100 == 0:
                logger.warning(
                    "audit forwarder queue full — dropped %d events so far. "
                    "Agent /api/v1/audit may be unreachable or slow.",
                    self._dropped,
                )

    async def _flush_loop(self) -> None:
        """Pull events off the queue, POST them to the agent, retry
        with exponential backoff on transient errors."""
        assert self._queue is not None
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
            while True:
                try:
                    event = await self._queue.get()
                except asyncio.CancelledError:
                    break
                await self._send_with_retry(client, event)
                # Yield briefly so the queue doesn't starve other
                # async tasks under high event rates.
                await asyncio.sleep(_BACKGROUND_FLUSH_INTERVAL_S)

    async def _send_with_retry(
        self, client: httpx.AsyncClient, event: dict[str, Any],
    ) -> None:
        delay = _RETRY_BASE_DELAY_S
        for attempt in range(1, _RETRY_MAX + 1):
            try:
                headers = {"Content-Type": "application/json"}
                if self._token:
                    headers["Authorization"] = self._token
                resp = await client.post(self._url, json=event, headers=headers)
                if resp.status_code < 500:
                    # 2xx, 4xx — both terminal. 4xx means agent rejected
                    # the row (bad action name, etc.); we shouldn't keep
                    # retrying that. Log at DEBUG only when 4xx so the
                    # operator log isn't noisy.
                    if resp.status_code >= 400:
                        logger.debug(
                            "audit forwarder: agent rejected event "
                            "(status=%d, action=%s, body=%.200s)",
                            resp.status_code, event.get("action"),
                            resp.text,
                        )
                    return
                # 5xx → retry
                last_error = f"HTTP {resp.status_code}"
            except httpx.HTTPError as exc:
                last_error = str(exc)
            except Exception as exc:  # noqa: BLE001
                last_error = f"{type(exc).__name__}: {exc}"
            if attempt < _RETRY_MAX:
                await asyncio.sleep(delay)
                delay = min(delay * 2, _RETRY_MAX_DELAY_S)
        logger.warning(
            "audit forwarder: gave up on event after %d retries "
            "(action=%s, last_error=%s)",
            _RETRY_MAX, event.get("action"), last_error,
        )


# Module-level singleton. The entrypoint creates and starts this; the
# helper functions below are what connector code calls.
_forwarder: _AuditForwarder | None = None


def init_forwarder() -> _AuditForwarder:
    """Create + return the singleton. Called once by the entrypoint."""
    global _forwarder
    if _forwarder is None:
        _forwarder = _AuditForwarder()
    return _forwarder


def record_event(
    action: str,
    target: str | None = None,
    status: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Public API for connector code: record an audit event. Mirrors
    bundles/spark/mcp/src/usecase/audit_log.py:record_event so existing
    connector code that imports this name works unchanged."""
    if _forwarder is None:
        # Forwarder not yet initialized (early-boot path or test).
        # No-op rather than raise — connector code shouldn't be
        # required to handle "audit not ready" branches.
        return
    _forwarder.record_event(action, target, status, metadata)
