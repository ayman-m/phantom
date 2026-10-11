"""Per-job model routing.

Anchors the schema migration + JobRow round-trip + dispatch body shape
+ update_job sentinel semantics for the model_id +
thinking_enabled fields. These tests should stay green for any future
refactor of the routing surface.
"""

from __future__ import annotations

import asyncio
import sqlite3
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from src.usecase.job_scheduler import (
    CroniterJobScheduler,
    JobDefinition,
    JobRow,
)


# ─── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def scheduler(tmp_path: Path) -> CroniterJobScheduler:
    """Fresh scheduler with empty data root + no manifest definitions.
    Tests build runtime jobs via add_job + assert behavior."""

    async def _noop_dispatcher(
        tool_name: str, args: dict[str, Any], **_kwargs: Any
    ) -> dict[str, Any]:
        return {"ok": True}

    return CroniterJobScheduler(
        definitions=[],
        dispatcher=_noop_dispatcher,
        data_root=tmp_path,
    )


# ─── Schema migration ───────────────────────────────────────────────


def test_jobs_table_has_model_id_column(scheduler: CroniterJobScheduler) -> None:
    """The schema has model_id TEXT (nullable, no default). Newly-
    created data roots have the column on first boot."""
    with sqlite3.connect(scheduler.db_path) as c:
        cols = {r[1] for r in c.execute("PRAGMA table_info(jobs)").fetchall()}
    assert "model_id" in cols


def test_jobs_table_has_thinking_enabled_column(
    scheduler: CroniterJobScheduler,
) -> None:
    """The schema has thinking_enabled INTEGER DEFAULT 0."""
    with sqlite3.connect(scheduler.db_path) as c:
        cols = {r[1] for r in c.execute("PRAGMA table_info(jobs)").fetchall()}
    assert "thinking_enabled" in cols


def test_pre_migration_jobs_db_gets_columns_on_boot(tmp_path: Path) -> None:
    """A jobs.db lacking the model-routing columns auto-migrates on
    next boot — no manual ALTER needed."""
    pre_migration = tmp_path / "jobs.db"
    with sqlite3.connect(pre_migration) as c:
        c.execute("""
            CREATE TABLE jobs (
                name           TEXT PRIMARY KEY,
                cron           TEXT NOT NULL,
                timezone       TEXT NOT NULL,
                action_json    TEXT NOT NULL,
                enabled        INTEGER NOT NULL DEFAULT 1,
                removed        INTEGER NOT NULL DEFAULT 0,
                last_fired_at  TEXT,
                last_status    TEXT,
                last_error     TEXT,
                next_due_at    TEXT,
                registered_at  TEXT NOT NULL,
                source         TEXT NOT NULL DEFAULT 'manifest',
                run_once       INTEGER NOT NULL DEFAULT 0
            )
        """)
        c.execute(
            "INSERT INTO jobs (name, cron, timezone, action_json, "
            "registered_at) VALUES (?, ?, ?, ?, ?)",
            ("legacy-job", "*/5 * * * *", "UTC", '{"type":"prompt","message":"x"}',
             "2026-01-01T00:00:00Z"),
        )

    # Booting a scheduler against the pre-migration db should run the
    # additive migration during _init_schema.
    async def _noop_dispatcher(
        tool_name: str, args: dict[str, Any], **_kwargs: Any
    ) -> dict[str, Any]:
        return {"ok": True}

    sched = CroniterJobScheduler(
        definitions=[], dispatcher=_noop_dispatcher, data_root=tmp_path,
    )
    with sqlite3.connect(sched.db_path) as c:
        cols = {r[1] for r in c.execute("PRAGMA table_info(jobs)").fetchall()}
    assert "model_id" in cols
    assert "thinking_enabled" in cols


# ─── JobRow round-trip ───────────────────────────────────────────────


def test_add_job_persists_model_id(scheduler: CroniterJobScheduler) -> None:
    row = scheduler.add_job(
        name="flash-job",
        cron="*/5 * * * *",
        action={"type": "prompt", "message": "hi"},
        model_id="gemini-2.5-flash",
    )
    assert row.model_id == "gemini-2.5-flash"
    assert row.thinking_enabled is False  # default off

    # Round-trip through get_job.
    fetched = scheduler.get_job("flash-job")
    assert fetched is not None
    assert fetched.model_id == "gemini-2.5-flash"


def test_add_job_persists_thinking_enabled(
    scheduler: CroniterJobScheduler,
) -> None:
    row = scheduler.add_job(
        name="thinking-job",
        cron="*/5 * * * *",
        action={"type": "prompt", "message": "hi"},
        model_id="gemini-3.1-pro-preview",
        thinking_enabled=True,
    )
    assert row.thinking_enabled is True
    fetched = scheduler.get_job("thinking-job")
    assert fetched is not None
    assert fetched.thinking_enabled is True


def test_add_job_default_no_override(scheduler: CroniterJobScheduler) -> None:
    """When the operator doesn't pass model_id, the row stores None
    (means 'use runtime default at dispatch time')."""
    row = scheduler.add_job(
        name="default-job",
        cron="*/5 * * * *",
        action={"type": "prompt", "message": "hi"},
    )
    assert row.model_id is None
    assert row.thinking_enabled is False


def test_to_dict_includes_model_fields(
    scheduler: CroniterJobScheduler,
) -> None:
    """The to_dict() shape is what the agent UI / MCP API consumes;
    both fields must be present."""
    row = scheduler.add_job(
        name="dict-job",
        cron="*/5 * * * *",
        action={"type": "prompt", "message": "hi"},
        model_id="gemini-2.5-flash",
        thinking_enabled=False,
    )
    d = row.to_dict()
    assert d["model_id"] == "gemini-2.5-flash"
    assert d["thinking_enabled"] is False


# ─── update_job sentinel semantics ───────────────────────────────────


def test_update_job_preserves_model_id_when_none(
    scheduler: CroniterJobScheduler,
) -> None:
    """update_job with model_id=None should leave the existing value
    untouched (operator didn't touch this field)."""
    scheduler.add_job(
        name="job-a", cron="*/5 * * * *",
        action={"type": "prompt", "message": "hi"},
        model_id="gemini-2.5-flash",
    )
    # Update something else; model_id should NOT change.
    updated = scheduler.update_job(
        "job-a", cron="*/10 * * * *",
        # model_id explicitly omitted (None default)
    )
    assert updated is not None
    assert updated.model_id == "gemini-2.5-flash"


def test_update_job_clears_model_id_with_empty_string(
    scheduler: CroniterJobScheduler,
) -> None:
    """update_job with model_id='' should clear the override (revert to
    runtime default)."""
    scheduler.add_job(
        name="job-b", cron="*/5 * * * *",
        action={"type": "prompt", "message": "hi"},
        model_id="gemini-2.5-flash",
    )
    updated = scheduler.update_job("job-b", model_id="")
    assert updated is not None
    assert updated.model_id is None


def test_update_job_sets_model_id_to_new_value(
    scheduler: CroniterJobScheduler,
) -> None:
    """update_job with model_id='<new-id>' sets the override."""
    scheduler.add_job(
        name="job-c", cron="*/5 * * * *",
        action={"type": "prompt", "message": "hi"},
    )
    updated = scheduler.update_job("job-c", model_id="gemini-3.1-pro-preview")
    assert updated is not None
    assert updated.model_id == "gemini-3.1-pro-preview"


def test_update_job_preserves_thinking_when_none(
    scheduler: CroniterJobScheduler,
) -> None:
    scheduler.add_job(
        name="job-d", cron="*/5 * * * *",
        action={"type": "prompt", "message": "hi"},
        thinking_enabled=True,
    )
    updated = scheduler.update_job("job-d", enabled=False)
    assert updated is not None
    assert updated.thinking_enabled is True


def test_update_job_toggles_thinking(
    scheduler: CroniterJobScheduler,
) -> None:
    scheduler.add_job(
        name="job-e", cron="*/5 * * * *",
        action={"type": "prompt", "message": "hi"},
        thinking_enabled=False,
    )
    updated = scheduler.update_job("job-e", thinking_enabled=True)
    assert updated is not None
    assert updated.thinking_enabled is True

    re_updated = scheduler.update_job("job-e", thinking_enabled=False)
    assert re_updated is not None
    assert re_updated.thinking_enabled is False


# ─── Defensive read (pre-migration row safety) ───────────────────────


def test_row_to_jobrow_defensive_read_missing_columns(tmp_path: Path) -> None:
    """If a row is fetched mid-flight before _init_schema's migration
    completed, _row_to_jobrow should default to None / False rather
    than crash. We simulate this with a sqlite3.Row that lacks the
    columns."""
    async def _noop_dispatcher(
        tool_name: str, args: dict[str, Any], **_kwargs: Any
    ) -> dict[str, Any]:
        return {"ok": True}

    sched = CroniterJobScheduler(
        definitions=[], dispatcher=_noop_dispatcher, data_root=tmp_path,
    )
    # Build a sqlite3.Row that lacks model_id / thinking_enabled — this
    # is the pre-migration shape.
    with sqlite3.connect(sched.db_path) as c:
        c.row_factory = sqlite3.Row
        # Build a row by selecting from a CTE that names exactly the
        # pre-migration columns.
        row = c.execute("""
            SELECT
              'x' as name, 'x' as id, '*/5 * * * *' as cron, 'UTC' as timezone,
              '{}' as action_json, 1 as enabled, 0 as removed,
              NULL as last_fired_at, NULL as last_status, NULL as last_error,
              NULL as next_due_at, '2026-01-01' as registered_at,
              'runtime' as source, 0 as run_once, 0 as bypass_approvals,
              0 as run_count
        """).fetchone()
    # _row_to_jobrow is a staticmethod, call it directly to verify the
    # defensive try/except blocks.
    jobrow = CroniterJobScheduler._row_to_jobrow(row)  # noqa: SLF001
    assert jobrow.model_id is None
    assert jobrow.thinking_enabled is False
