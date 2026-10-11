"""Per-job permission policy.

Anchors the schema migration + JobRow round-trip + dispatch body shape
+ update_job sentinel semantics for the permission_policy
field. The TS-side evaluator (lib/permission-policy.ts) lives in the
agent and is exercised at runtime; this test suite focuses on the
storage + dispatch path the MCP owns.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest

from src.usecase.job_scheduler import (
    CroniterJobScheduler,
    JobRow,
)


@pytest.fixture
def scheduler(tmp_path: Path) -> CroniterJobScheduler:
    async def _noop_dispatcher(
        tool_name: str, args: dict[str, Any], **_kwargs: Any
    ) -> dict[str, Any]:
        return {"ok": True}

    return CroniterJobScheduler(
        definitions=[], dispatcher=_noop_dispatcher, data_root=tmp_path,
    )


# ─── Schema migration ───────────────────────────────────────────────


def test_jobs_table_has_permission_policy_column(
    scheduler: CroniterJobScheduler,
) -> None:
    with sqlite3.connect(scheduler.db_path) as c:
        cols = {r[1] for r in c.execute("PRAGMA table_info(jobs)").fetchall()}
    assert "permission_policy_json" in cols


def test_pre_migration_db_gets_column(tmp_path: Path) -> None:
    """A jobs.db without the permission_policy column auto-migrates
    (additive ALTER TABLE) on boot. Verifies the migration probe in _init_schema."""
    pre = tmp_path / "jobs.db"
    with sqlite3.connect(pre) as c:
        c.execute("""
            CREATE TABLE jobs (
                name           TEXT PRIMARY KEY,
                cron           TEXT NOT NULL,
                timezone       TEXT NOT NULL,
                action_json    TEXT NOT NULL,
                enabled        INTEGER NOT NULL DEFAULT 1,
                removed        INTEGER NOT NULL DEFAULT 0,
                last_fired_at  TEXT, last_status TEXT, last_error TEXT,
                next_due_at    TEXT,
                registered_at  TEXT NOT NULL,
                source         TEXT NOT NULL DEFAULT 'manifest',
                run_once       INTEGER NOT NULL DEFAULT 0
            )
        """)
    async def _noop(tool_name: str, args: dict[str, Any], **_k: Any) -> dict[str, Any]:
        return {"ok": True}
    sched = CroniterJobScheduler(
        definitions=[], dispatcher=_noop, data_root=tmp_path,
    )
    with sqlite3.connect(sched.db_path) as c:
        cols = {r[1] for r in c.execute("PRAGMA table_info(jobs)").fetchall()}
    assert "permission_policy_json" in cols


# ─── JobRow round-trip ───────────────────────────────────────────────


def test_add_job_persists_policy(scheduler: CroniterJobScheduler) -> None:
    policy = {
        "allowed_tools": ["xlog_*"],
        "denied_tools": ["*_delete"],
        "require_approval": ["xsiam_write_*"],
    }
    row = scheduler.add_job(
        name="restricted-job", cron="*/5 * * * *",
        action={"type": "prompt", "message": "hi"},
        permission_policy=policy,
    )
    assert row.permission_policy == policy
    fetched = scheduler.get_job("restricted-job")
    assert fetched is not None
    assert fetched.permission_policy == policy


def test_add_job_default_no_policy(scheduler: CroniterJobScheduler) -> None:
    row = scheduler.add_job(
        name="open-job", cron="*/5 * * * *",
        action={"type": "prompt", "message": "hi"},
    )
    assert row.permission_policy is None


def test_to_dict_includes_policy(scheduler: CroniterJobScheduler) -> None:
    policy = {"allowed_tools": ["xlog_*"]}
    row = scheduler.add_job(
        name="dict-job", cron="*/5 * * * *",
        action={"type": "prompt", "message": "hi"},
        permission_policy=policy,
    )
    d = row.to_dict()
    assert d["permission_policy"] == policy


# ─── update_job sentinel semantics ───────────────────────────────────


def test_update_preserves_policy_when_none(
    scheduler: CroniterJobScheduler,
) -> None:
    """None = operator did not touch this field."""
    scheduler.add_job(
        name="job-a", cron="*/5 * * * *",
        action={"type": "prompt", "message": "hi"},
        permission_policy={"allowed_tools": ["xlog_*"]},
    )
    updated = scheduler.update_job("job-a", cron="*/10 * * * *")
    assert updated is not None
    assert updated.permission_policy == {"allowed_tools": ["xlog_*"]}


def test_update_clears_policy_with_empty_dict(
    scheduler: CroniterJobScheduler,
) -> None:
    """{} = operator explicitly cleared. Distinguishes from None
    (preserve) which the dict-typed field can't express via simple
    falsy check."""
    scheduler.add_job(
        name="job-b", cron="*/5 * * * *",
        action={"type": "prompt", "message": "hi"},
        permission_policy={"denied_tools": ["*_delete"]},
    )
    updated = scheduler.update_job("job-b", permission_policy={})
    assert updated is not None
    assert updated.permission_policy is None


def test_update_sets_policy(scheduler: CroniterJobScheduler) -> None:
    scheduler.add_job(
        name="job-c", cron="*/5 * * * *",
        action={"type": "prompt", "message": "hi"},
    )
    new_policy = {"allowed_tools": ["scenarios_*", "skills_*"]}
    updated = scheduler.update_job("job-c", permission_policy=new_policy)
    assert updated is not None
    assert updated.permission_policy == new_policy


# ─── Defensive read (malformed JSON safety) ──────────────────────────


def test_malformed_policy_json_degrades_to_none(tmp_path: Path) -> None:
    """A corrupt permission_policy_json should NOT crash the row read.
    The defensive parse in _row_to_jobrow catches the JSONDecodeError
    and degrades to None + warning log."""
    async def _noop(tool_name: str, args: dict[str, Any], **_k: Any) -> dict[str, Any]:
        return {"ok": True}
    sched = CroniterJobScheduler(
        definitions=[], dispatcher=_noop, data_root=tmp_path,
    )
    # Insert a row with corrupt policy json directly.
    with sqlite3.connect(sched.db_path) as c:
        c.execute(
            "INSERT INTO jobs (name, id, cron, timezone, action_json, "
            "enabled, removed, registered_at, source, run_once, "
            "permission_policy_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("corrupt-job", "u-1", "*/5 * * * *", "UTC",
             '{"type":"prompt","message":"x"}', 1, 0,
             "2026-01-01T00:00:00Z", "runtime", 0,
             "{not-valid-json"),
        )
    row = sched.get_job("corrupt-job")
    assert row is not None
    assert row.permission_policy is None  # degraded silently
