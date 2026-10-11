"""`_migrate_action_types` rewrites legacy `type: "log"` job rows into a
working tool_call.

The migration (chat→prompt, log→tool_call) must rewrite `type: "log"`
rows to call the connector-namespaced tool name
(`xlog.create_data_worker`) with its parameters flat, not wrapped in a
`{"request": ...}` key. A row migrated to `phantom_create_data_worker`
or to wrapped args would be permanently broken — "Unknown tool:
'phantom_create_data_worker'" at every fire.

These tests insert a legacy row directly (bypassing jobs_create, which
does not accept this shape — the row stands in for legacy stored state)
and construct a fresh CroniterJobScheduler against the same data_root,
which re-runs _init_schema → _migrate_action_types on every boot.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from src.usecase.job_scheduler import CroniterJobScheduler


@pytest.fixture
def data_root(tmp_path: Path) -> Path:
    async def _noop(tool_name: str, args: dict[str, Any], **_k: Any) -> dict[str, Any]:
        return {"ok": True}

    # Boot once to create the schema, then insert the legacy row
    # directly — jobs_create does not accept type="log";
    # this row stands in for legacy stored state.
    CroniterJobScheduler(definitions=[], dispatcher=_noop, data_root=tmp_path)
    return tmp_path


def _insert_legacy_log_job(db_path: Path, name: str, action: dict[str, Any]) -> None:
    with sqlite3.connect(db_path) as c:
        c.execute(
            "INSERT INTO jobs (name, cron, timezone, action_json, "
            "registered_at, source) VALUES (?, '* * * * *', 'UTC', ?, "
            "'2020-01-01T00:00:00Z', 'runtime')",
            (name, json.dumps(action)),
        )


def _reboot_and_fetch_action(data_root: Path, name: str) -> dict[str, Any]:
    async def _noop(tool_name: str, args: dict[str, Any], **_k: Any) -> dict[str, Any]:
        return {"ok": True}

    CroniterJobScheduler(definitions=[], dispatcher=_noop, data_root=data_root)
    with sqlite3.connect(data_root / "jobs.db") as c:
        c.row_factory = sqlite3.Row
        row = c.execute("SELECT action_json FROM jobs WHERE name = ?", (name,)).fetchone()
    return json.loads(row["action_json"])


def test_migrates_log_action_to_namespaced_tool_call(data_root: Path) -> None:
    _insert_legacy_log_job(data_root / "jobs.db", "legacy-log-job", {
        "type": "log",
        "format": "CEF",
        "count": 5,
        "destination": "udp:10.0.0.8:514",
        "vendor": "Fortinet",
        "product": "FortiGate",
    })

    action = _reboot_and_fetch_action(data_root, "legacy-log-job")

    assert action["type"] == "tool_call"
    assert action["name"] == "xlog.create_data_worker"
    # args must be flat (no "request" wrapper) — the tool takes its
    # parameters directly.
    assert "request" not in action["args"]
    assert action["args"]["type"] == "CEF"  # format renamed to type
    assert action["args"]["count"] == 5
    assert action["args"]["destination"] == "udp:10.0.0.8:514"
    assert action["args"]["vendor"] == "Fortinet"


def test_migration_is_idempotent(data_root: Path) -> None:
    _insert_legacy_log_job(data_root / "jobs.db", "legacy-log-job-2", {
        "type": "log", "format": "JSON", "count": 1,
    })

    first = _reboot_and_fetch_action(data_root, "legacy-log-job-2")
    second = _reboot_and_fetch_action(data_root, "legacy-log-job-2")

    assert first == second
    assert second["type"] == "tool_call"
    assert second["name"] == "xlog.create_data_worker"
