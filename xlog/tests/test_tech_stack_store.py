"""Tests for the technology-stack singleton in xlog/app/store.py.

The store is the source of truth for the org's vendor catalog; the
GraphQL resolvers and the MCP `phantom_get_technology_stack` /
`phantom_update_technology_stack` tools are thin wrappers around
these helpers, so getting the store right is the most important test.

Each test points the store at a fresh tempfile sqlite via the
`XLOG_DB_PATH` env var so they don't fight over the production
`/data/xlog.db` (or whichever path is set in the runtime env).
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest


@pytest.fixture
def fresh_store(monkeypatch, tmp_path):
    """Reload `app.store` with a tempfile DB. Each test gets its own
    sqlite file so the singleton row isn't shared across tests, and
    the env-var fallback can be set without touching the real env."""
    db = tmp_path / "xlog-test.db"
    monkeypatch.setenv("XLOG_DB_PATH", str(db))
    monkeypatch.delenv("TECHNOLOGY_STACK", raising=False)
    # store caches DB_PATH at import time, so we have to reload it
    # whenever XLOG_DB_PATH changes per-test.
    from app import store
    importlib.reload(store)
    return store


# ─── Read path ───────────────────────────────────────────────────────


def test_empty_returns_default_source(fresh_store):
    """No sqlite row, no env var → 'default' source + configured=False."""
    result = fresh_store.get_technology_stack()
    assert result["configured"] is False
    assert result["source"] == "default"
    assert result["vendors"] == []
    assert result["total_vendors"] == 0
    assert result["stack_name"] is None


def test_env_var_fallback(fresh_store, monkeypatch):
    """When sqlite is empty but TECHNOLOGY_STACK env var is set, the
    env-var content is returned with source='env'. This preserves
    backwards compat with deploys that haven't migrated to the
    mutation path yet."""
    monkeypatch.setenv(
        "TECHNOLOGY_STACK",
        '{"stack_name": "Legacy Stack", "vendors": ['
        '{"vendor": "Cisco", "product": "ASA", "category": "Firewall", '
        '"formats": ["SYSLOG"]}]}',
    )
    result = fresh_store.get_technology_stack()
    assert result["configured"] is True
    assert result["source"] == "env"
    assert result["stack_name"] == "Legacy Stack"
    assert result["total_vendors"] == 1
    assert result["vendors"][0]["vendor"] == "Cisco"


def test_env_var_invalid_json_falls_through(fresh_store, monkeypatch):
    """Garbage in the env var should NOT crash — it should be treated
    as if the env var weren't set, falling back to 'default'."""
    monkeypatch.setenv("TECHNOLOGY_STACK", "{ this is not json }")
    result = fresh_store.get_technology_stack()
    assert result["configured"] is False
    assert result["source"] == "default"


# ─── Write path ──────────────────────────────────────────────────────


def test_update_then_read_returns_manual_source(fresh_store):
    """After update_technology_stack, subsequent reads return the new
    payload with source='manual' (sqlite wins over env-var)."""
    new_stack = {
        "stack_name": "Test Stack",
        "log_destination": {
            "type": "syslog",
            "protocol": "udp",
            "host": "10.0.0.1",
            "port": 514,
            "full_address": "udp:10.0.0.1:514",
        },
        "vendors": [
            {
                "vendor": "Fortinet",
                "product": "FortiGate",
                "category": "Firewall",
                "formats": ["CEF", "SYSLOG"],
                "description": "NGFW",
            }
        ],
    }
    after_update = fresh_store.update_technology_stack(new_stack)
    assert after_update["source"] == "manual"
    assert after_update["stack_name"] == "Test Stack"
    assert after_update["configured"] is True
    assert after_update["updated_at"] is not None

    # Re-reading should return the same payload (no env-var override
    # even if one is set — sqlite is the higher-priority source).
    again = fresh_store.get_technology_stack()
    assert again["stack_name"] == "Test Stack"
    assert again["source"] == "manual"


def test_update_overwrites_existing(fresh_store):
    """Calling update twice replaces the stack — vendors list is NOT
    merged, it's the operator's job to compose the new full list."""
    fresh_store.update_technology_stack(
        {
            "stack_name": "First",
            "vendors": [
                {
                    "vendor": "A",
                    "product": "X",
                    "category": "Firewall",
                    "formats": ["JSON"],
                }
            ],
        }
    )
    second = fresh_store.update_technology_stack(
        {
            "stack_name": "Second",
            "vendors": [
                {
                    "vendor": "B",
                    "product": "Y",
                    "category": "EDR",
                    "formats": ["JSON"],
                }
            ],
        }
    )
    assert second["stack_name"] == "Second"
    assert second["total_vendors"] == 1
    assert second["vendors"][0]["vendor"] == "B"


def test_sqlite_overrides_env_var(fresh_store, monkeypatch):
    """When BOTH sqlite has a row AND TECHNOLOGY_STACK is set, sqlite
    wins — that's the whole point of the mutation path."""
    monkeypatch.setenv(
        "TECHNOLOGY_STACK",
        '{"stack_name": "Env", "vendors": ['
        '{"vendor": "EnvVendor", "product": "P", "category": "C", '
        '"formats": ["JSON"]}]}',
    )
    fresh_store.update_technology_stack(
        {
            "stack_name": "Operator-set",
            "vendors": [
                {
                    "vendor": "OperatorVendor",
                    "product": "P",
                    "category": "C",
                    "formats": ["JSON"],
                }
            ],
        }
    )
    result = fresh_store.get_technology_stack()
    assert result["stack_name"] == "Operator-set"
    assert result["source"] == "manual"


def test_clear_falls_back_to_env(fresh_store, monkeypatch):
    """clear_technology_stack drops the sqlite row; subsequent read
    falls back to env var (if set) or 'default'."""
    monkeypatch.setenv(
        "TECHNOLOGY_STACK",
        '{"stack_name": "EnvFallback", "vendors": []}',
    )
    fresh_store.update_technology_stack(
        {"stack_name": "Operator", "vendors": [
            {"vendor": "V", "product": "P", "category": "C", "formats": ["JSON"]}
        ]}
    )
    cleared = fresh_store.clear_technology_stack()
    assert cleared["stack_name"] == "EnvFallback"
    assert cleared["source"] == "env"


# ─── Normalization ───────────────────────────────────────────────────


def test_loose_input_is_coerced(fresh_store):
    """The store accepts loose inputs (missing log_destination, missing
    description on vendors) — strict validation belongs at the GraphQL
    layer. Here we just want to make sure bad shapes don't crash."""
    result = fresh_store.update_technology_stack(
        {
            "stack_name": "Loose",
            "vendors": [
                {
                    "vendor": "V",
                    "product": "P",
                    "category": "C",
                    "formats": ["JSON"],
                    # description omitted — should round-trip None
                }
            ],
            # log_destination omitted entirely
        }
    )
    assert result["log_destination"] is None
    assert result["vendors"][0]["vendor"] == "V"


def test_garbage_input_doesnt_crash(fresh_store):
    """Pass complete garbage — store normalizes to empty rather than
    raising. The GraphQL input type is the strict gate; the store is
    the lenient last-line."""
    result = fresh_store.update_technology_stack({"random": "garbage"})
    assert result["vendors"] == []
    assert result["stack_name"] is None
