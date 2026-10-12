"""`next_due_at` semantics for jobs that are not schedulable.

A job only has a next run while it is enabled and not removed. Pausing
it, creating it disabled, or completing a run-once job must leave
`next_due_at` empty so the UI never shows a stale "next run 4h ago" for
a paused job. Resuming recomputes from now (never replays a stale past
value as an immediate catch-up fire).
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any

import pytest

from src.usecase.job_scheduler import CroniterJobScheduler

PROMPT = {"type": "prompt", "message": "hi"}


@pytest.fixture
def scheduler(tmp_path: Path) -> CroniterJobScheduler:
    async def _noop(tool_name: str, args: dict[str, Any], **_k: Any) -> dict[str, Any]:
        return {"ok": True}

    return CroniterJobScheduler(
        definitions=[], dispatcher=_noop, data_root=tmp_path,
    )


def _iso_to_epoch(iso: str) -> float:
    return time.mktime(time.strptime(iso, "%Y-%m-%dT%H:%M:%SZ")) - time.timezone


def _raw_next_due(sched: CroniterJobScheduler, name: str) -> str | None:
    with sqlite3.connect(sched.db_path) as c:
        return c.execute(
            "SELECT next_due_at FROM jobs WHERE name = ?", (name,)
        ).fetchone()[0]


def test_enabled_job_has_a_future_next_due(scheduler: CroniterJobScheduler) -> None:
    row = scheduler.add_job(name="live", cron="*/5 * * * *", action=PROMPT)
    assert row.next_due_at is not None
    assert _iso_to_epoch(row.next_due_at) > time.time() - 1


def test_add_job_disabled_has_no_next_due(scheduler: CroniterJobScheduler) -> None:
    row = scheduler.add_job(
        name="born-paused", cron="*/5 * * * *", action=PROMPT, enabled=False,
    )
    assert row.enabled is False
    assert row.next_due_at is None
    assert _raw_next_due(scheduler, "born-paused") is None


def test_update_job_pause_clears_next_due(scheduler: CroniterJobScheduler) -> None:
    scheduler.add_job(name="p", cron="*/5 * * * *", action=PROMPT)
    row = scheduler.update_job("p", enabled=False)
    assert row is not None
    assert row.enabled is False
    assert row.next_due_at is None
    assert _raw_next_due(scheduler, "p") is None


def test_update_job_resume_recomputes_from_now(scheduler: CroniterJobScheduler) -> None:
    scheduler.add_job(name="r", cron="*/5 * * * *", action=PROMPT)
    scheduler.update_job("r", enabled=False)
    # Simulate the stale value an older build left behind on a paused job.
    with sqlite3.connect(scheduler.db_path) as c:
        c.execute(
            "UPDATE jobs SET next_due_at = '2020-01-01T00:00:00Z' WHERE name = 'r'"
        )
    row = scheduler.update_job("r", enabled=True)
    assert row is not None and row.enabled is True
    assert row.next_due_at is not None
    assert _iso_to_epoch(row.next_due_at) > time.time() - 1


def test_update_job_edit_while_paused_stays_unscheduled(
    scheduler: CroniterJobScheduler,
) -> None:
    scheduler.add_job(name="e", cron="*/5 * * * *", action=PROMPT, enabled=False)
    row = scheduler.update_job("e", cron="0 9 * * *")
    assert row is not None
    assert row.cron == "0 9 * * *"
    assert row.next_due_at is None


def test_set_enabled_false_clears_and_true_recomputes(
    scheduler: CroniterJobScheduler,
) -> None:
    scheduler.add_job(name="s", cron="*/5 * * * *", action=PROMPT)
    paused = scheduler.set_enabled("s", False)
    assert paused is not None and paused.next_due_at is None
    assert _raw_next_due(scheduler, "s") is None

    resumed = scheduler.set_enabled("s", True)
    assert resumed is not None and resumed.enabled is True
    assert resumed.next_due_at is not None
    assert _iso_to_epoch(resumed.next_due_at) > time.time() - 1


def test_resume_does_not_replay_a_stale_past_due(scheduler: CroniterJobScheduler) -> None:
    """A paused job whose stored next_due_at slid into the past used to
    fire immediately on resume (the tick sees next_due_at <= now)."""
    scheduler.add_job(name="stale", cron="0 9 * * *", action=PROMPT, enabled=False)
    with sqlite3.connect(scheduler.db_path) as c:
        c.execute(
            "UPDATE jobs SET next_due_at = '2020-01-01T00:00:00Z' WHERE name = 'stale'"
        )
    scheduler.set_enabled("stale", True)
    assert scheduler._read_due_jobs(time.time()) == []


def test_paused_completed_run_once_job_stays_unscheduled(
    scheduler: CroniterJobScheduler,
) -> None:
    """Run-once jobs are disabled after their fire. Pausing one again
    (the menu offers Pause on it) must not schedule anything."""
    scheduler.add_job(
        name="once", cron="30 4 12 10 *", action=PROMPT, run_once=True,
    )
    with sqlite3.connect(scheduler.db_path) as c:
        c.execute(
            "UPDATE jobs SET enabled = 0, next_due_at = NULL, "
            "last_fired_at = '2026-10-12T04:30:00Z', last_status = 'success' "
            "WHERE name = 'once'"
        )
    row = scheduler.update_job("once", enabled=False)
    assert row is not None
    assert row.enabled is False
    assert row.next_due_at is None
    assert row.to_dict()["next_due_at"] is None
    assert _raw_next_due(scheduler, "once") is None


def test_legacy_stale_next_due_on_a_paused_row_is_not_reported(
    scheduler: CroniterJobScheduler,
) -> None:
    """Rows paused by an older build keep a stale stored next_due_at; the
    read path must not surface it."""
    scheduler.add_job(name="legacy", cron="*/5 * * * *", action=PROMPT)
    with sqlite3.connect(scheduler.db_path) as c:
        c.execute(
            "UPDATE jobs SET enabled = 0, next_due_at = '2020-01-01T00:00:00Z' "
            "WHERE name = 'legacy'"
        )
    got = scheduler.get_job("legacy")
    assert got is not None
    assert got.next_due_at is None
    listed = {j.name: j for j in scheduler.list_jobs()}
    assert listed["legacy"].next_due_at is None
    assert listed["legacy"].to_dict()["next_due_at"] is None


# ─── Completed run-once jobs are never re-armed by Resume ──────────────────
#
# A run-once job stores its Run-at time as `M H D Mo *`. After it fires
# the job is disabled; arming it again from that cron would pick the same
# date NEXT YEAR and fire unattended. Resume therefore refuses; editing the
# Run-at time (a new cron) or duplicating the job are the ways back.


def _fire_once(scheduler: CroniterJobScheduler, name: str) -> None:
    import asyncio

    scheduler.add_job(
        name=name, cron="0 9 11 10 *", timezone_name="UTC",
        action=PROMPT, run_once=True,
    )
    asyncio.run(scheduler.trigger_now(name))
    row = scheduler.get_job(name)
    assert row is not None
    assert row.enabled is False and row.last_fired_at is not None
    assert row.next_due_at is None


def test_set_enabled_refuses_a_completed_run_once_job(
    scheduler: CroniterJobScheduler,
) -> None:
    from src.usecase.job_scheduler import CompletedRunOnceError

    _fire_once(scheduler, "done")
    with pytest.raises(CompletedRunOnceError) as exc:
        scheduler.set_enabled("done", True)
    assert "Run-at" in str(exc.value) or "Duplicate" in str(exc.value)
    row = scheduler.get_job("done")
    assert row is not None
    assert row.enabled is False
    assert row.next_due_at is None
    assert _raw_next_due(scheduler, "done") is None


def test_update_job_enable_refuses_a_completed_run_once_job(
    scheduler: CroniterJobScheduler,
) -> None:
    from src.usecase.job_scheduler import CompletedRunOnceError

    _fire_once(scheduler, "done2")
    with pytest.raises(CompletedRunOnceError):
        scheduler.update_job("done2", enabled=True)
    # An edit that changes nothing about the schedule but re-sends the
    # same cron with enabled=True is still a re-arm of last year's date.
    with pytest.raises(CompletedRunOnceError):
        scheduler.update_job("done2", cron="0 9 11 10 *", enabled=True)
    assert _raw_next_due(scheduler, "done2") is None


def test_completed_run_once_can_be_rearmed_with_a_new_run_at_time(
    scheduler: CroniterJobScheduler,
) -> None:
    _fire_once(scheduler, "done3")
    row = scheduler.update_job("done3", cron="30 4 12 10 *", enabled=True)
    assert row is not None
    assert row.enabled is True
    assert row.next_due_at is not None


def test_set_enabled_still_arms_a_run_once_job_that_never_fired(
    scheduler: CroniterJobScheduler,
) -> None:
    scheduler.add_job(
        name="fresh-once", cron="0 9 11 10 *", action=PROMPT,
        run_once=True, enabled=False,
    )
    row = scheduler.set_enabled("fresh-once", True)
    assert row is not None and row.enabled is True
    assert row.next_due_at is not None


def test_pausing_a_completed_run_once_job_is_still_allowed(
    scheduler: CroniterJobScheduler,
) -> None:
    _fire_once(scheduler, "done4")
    row = scheduler.set_enabled("done4", False)
    assert row is not None and row.enabled is False and row.next_due_at is None
