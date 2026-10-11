"""Tests for `_get_webhook_headers` + the store-driven webhook fields on
`DataWorkerCreateInput`.

The XSIAM_WEBHOOK branch of `create_data_worker` prefers a per-destination
endpoint + auth key injected by the MCP log-destination resolver (the
xsiam_http destination type), falling back to the container-wide
WEBHOOK_ENDPOINT / WEBHOOK_KEY env defaults when absent.

The single most important invariant under test: the Authorization header
carries the RAW key, never "Bearer <key>" (see xlog/CLAUDE.md "Webhook
sender — non-Bearer auth header"). These tests call the pure helper +
inspect the Strawberry input class directly — no rosetta, no sockets.
"""
from __future__ import annotations

import pytest

import app.schema as schema
from app.types.sender import DataWorkerCreateInput


def test_env_default_header_is_raw_authorization(monkeypatch):
    monkeypatch.setattr(schema, "WEBHOOK_KEY", "ENVKEY")
    headers = schema._get_webhook_headers()
    # RAW key — NOT "Bearer ENVKEY".
    assert headers["Authorization"] == "ENVKEY"
    assert headers["Content-Type"] == "application/json"


def test_key_override_wins_and_stays_raw(monkeypatch):
    monkeypatch.setattr(schema, "WEBHOOK_KEY", "ENVKEY")
    headers = schema._get_webhook_headers("STORE_RESOLVED_KEY")
    assert headers["Authorization"] == "STORE_RESOLVED_KEY"
    assert not headers["Authorization"].startswith("Bearer ")


def test_override_works_even_when_env_key_absent(monkeypatch):
    # A store xsiam_http destination must work on an install that never set
    # the WEBHOOK_KEY env default.
    monkeypatch.setattr(schema, "WEBHOOK_KEY", None)
    headers = schema._get_webhook_headers("ONLY_STORE_KEY")
    assert headers["Authorization"] == "ONLY_STORE_KEY"


def test_raises_when_no_key_anywhere(monkeypatch):
    monkeypatch.setattr(schema, "WEBHOOK_KEY", None)
    with pytest.raises(ValueError):
        schema._get_webhook_headers()


def test_data_worker_input_carries_optional_webhook_fields():
    ann = DataWorkerCreateInput.__annotations__
    assert "webhook_url" in ann
    assert "webhook_key" in ann
    # Both default to None so omitting them preserves legacy env-fallback.
    # Strawberry inputs are dataclasses under the hood — inspect the field
    # defaults directly (avoids constructing one, which needs a live enum).
    fields = DataWorkerCreateInput.__dataclass_fields__
    assert fields["webhook_url"].default is None
    assert fields["webhook_key"].default is None
