"""Tests for WebhookDispatcher — channel:* notification fanout."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from usecase.notification_dispatcher import (
    CHANNEL_PREFIX,
    ENV_PREFIX,
    WebhookDispatcher,
    env_var_for,
)


@dataclass
class FakeNotification:
    """Mimics the SqliteNotificationStore.Notification shape (the
    dispatcher only reads attributes; doesn't call any methods)."""
    id: str = "abc"
    topic: str = "detection-miss"
    severity: str = "warning"
    target: str = "channel:soc"
    payload: dict | None = None
    created_at: str = "2026-04-29T00:00:00Z"


# ─── env var mapping ──────────────────────────────────────────────


def test_env_var_for_simple_channel() -> None:
    assert env_var_for("soc") == "PHANTOM_NOTIFICATION_CHANNEL_SOC"


def test_env_var_for_hyphenated_channel() -> None:
    assert env_var_for("purple-team") == "PHANTOM_NOTIFICATION_CHANNEL_PURPLE_TEAM"


def test_env_var_for_strips_special_chars() -> None:
    assert env_var_for("a.b/c") == "PHANTOM_NOTIFICATION_CHANNEL_A_B_C"


# ─── target gating ────────────────────────────────────────────────


def test_user_target_is_skipped() -> None:
    """user:operator targets are never fanned out — they're operator
    notifications consumed via the agent UI, not external webhooks."""
    d = WebhookDispatcher(env={})
    n = FakeNotification(target="user:operator")
    # Returns None without raising; nothing was supposed to dispatch.
    assert d(n) is None


def test_unconfigured_channel_raises_clear_error() -> None:
    """Channel target with no env var configured: raise so the
    publish() caller marks dispatch_status=failed with a useful reason."""
    d = WebhookDispatcher(env={})
    n = FakeNotification(target="channel:soc")
    with pytest.raises(RuntimeError, match="no webhook URL configured for 'channel:soc'"):
        d(n)


# ─── successful dispatch ──────────────────────────────────────────


def test_successful_post(monkeypatch) -> None:
    """Configured channel + 200 response: dispatcher returns None
    (success), having posted the right JSON body."""

    captured: dict[str, Any] = {}

    class _StubResponse:
        status_code = 200
        text = "ok"

    class _StubClient:
        def __init__(self, *_, **__):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def post(self, url: str, *, json=None, headers=None):
            captured["url"] = url
            captured["json"] = json
            captured["headers"] = headers
            return _StubResponse()

    import usecase.notification_dispatcher as mod
    monkeypatch.setattr(mod.httpx, "Client", _StubClient)

    d = WebhookDispatcher(env={
        "PHANTOM_NOTIFICATION_CHANNEL_SOC": "https://example/webhook",
    })
    n = FakeNotification(target="channel:soc", payload={"detection_id": "X"})
    assert d(n) is None
    assert captured["url"] == "https://example/webhook"
    assert captured["json"]["topic"] == "detection-miss"
    assert captured["json"]["target"] == "channel:soc"
    assert captured["json"]["payload"] == {"detection_id": "X"}
    assert captured["headers"]["Content-Type"] == "application/json"


def test_4xx_response_raises(monkeypatch) -> None:
    """Webhook returning 4xx → raise so dispatch_status records the failure."""

    class _StubResponse:
        status_code = 400
        text = "invalid_payload"

    class _StubClient:
        def __init__(self, *_, **__):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def post(self, *_, **__):
            return _StubResponse()

    import usecase.notification_dispatcher as mod
    monkeypatch.setattr(mod.httpx, "Client", _StubClient)

    d = WebhookDispatcher(env={
        "PHANTOM_NOTIFICATION_CHANNEL_SOC": "https://example/webhook",
    })
    with pytest.raises(RuntimeError, match="400.*invalid_payload"):
        d(FakeNotification(target="channel:soc"))


def test_network_error_raises_with_context(monkeypatch) -> None:
    """httpx.HTTPError wraps in a RuntimeError with the upstream type
    in the message — operators see "ConnectError" not just a generic failure."""
    import httpx

    class _StubClient:
        def __init__(self, *_, **__):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def post(self, *_, **__):
            raise httpx.ConnectError("nope")

    import usecase.notification_dispatcher as mod
    monkeypatch.setattr(mod.httpx, "Client", _StubClient)

    d = WebhookDispatcher(env={
        "PHANTOM_NOTIFICATION_CHANNEL_SOC": "https://example/webhook",
    })
    with pytest.raises(RuntimeError, match="ConnectError.*nope"):
        d(FakeNotification(target="channel:soc"))


# ─── integration with SqliteNotificationStore ─────────────────────


def test_integration_with_store(tmp_path) -> None:
    """End-to-end: WebhookDispatcher plugs into SqliteNotificationStore
    as dispatch_hook. Successful dispatch → status=dispatched. Failure
    → status=failed + dispatch_error captured."""
    from usecase.notifications import SqliteNotificationStore, TopicSpec

    captures: list[dict] = []

    def fake_dispatch(notif):
        captures.append({"target": notif.target, "topic": notif.topic})
        # Simulate one success, one failure.
        if notif.topic == "fail-me":
            raise RuntimeError("simulated webhook 503")

    topics = [
        TopicSpec(name="ok-topic", severity="info", target="channel:ok"),
        TopicSpec(name="fail-me", severity="warning", target="channel:bad"),
    ]
    store = SqliteNotificationStore(
        topics=topics, data_root=tmp_path, dispatch_hook=fake_dispatch,
    )

    n_ok = store.publish("ok-topic", payload={"x": 1})
    assert n_ok.dispatch_status == "dispatched"
    assert n_ok.dispatch_error is None

    n_bad = store.publish("fail-me", payload={"x": 2})
    assert n_bad.dispatch_status == "failed"
    assert n_bad.dispatch_error and "simulated webhook 503" in n_bad.dispatch_error

    assert [c["target"] for c in captures] == ["channel:ok", "channel:bad"]
