"""At boot every runtime job's YAML mirror is brought in line with SQLite.

Mirrors written by an older build said `enabled: true` for a run-once job that
had since completed, and carried an older banner. The boot pass rewrites a file
only when its text differs from the live state, so the second boot writes
nothing, and a file that failed to load is left alone (it may hold an edit that
has not been applied).
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

import yaml

from usecase.job_scheduler import CroniterJobScheduler

ACTION = {"type": "prompt", "message": "once"}
RUN_AT = "0 9 11 10 *"


async def _noop(name, args, **_k):  # noqa: ANN001
    return {"ok": True}


def _boot(tmp_path: Path) -> CroniterJobScheduler:
    return CroniterJobScheduler(definitions=[], dispatcher=_noop, data_root=tmp_path)


def _mirror(tmp_path: Path, name: str) -> Path:
    return tmp_path / "jobs" / f"{name}.yaml"


def _doc(tmp_path: Path, name: str) -> dict:
    return yaml.safe_load(_mirror(tmp_path, name).read_text())


def _stale(tmp_path: Path, name: str) -> None:
    """Make the mirror look like an older build wrote it."""
    doc = _doc(tmp_path, name)
    doc["enabled"] = True
    _mirror(tmp_path, name).write_text(
        "# Phantom runtime job definition (source='runtime').\n"
        "# Edit cron, timezone, action or run_once and restart.\n"
        + yaml.safe_dump(doc, sort_keys=False)
    )


def test_a_stale_enabled_true_mirror_of_a_completed_run_once_job_is_rewritten(tmp_path):
    s = _boot(tmp_path)
    s.add_job(name="once", cron=RUN_AT, action=ACTION, run_once=True)
    asyncio.run(s.trigger_now("once"))
    assert s.get_job("once").enabled is False
    _stale(tmp_path, "once")
    assert _doc(tmp_path, "once")["enabled"] is True

    again = _boot(tmp_path)

    assert _doc(tmp_path, "once")["enabled"] is False
    text = _mirror(tmp_path, "once").read_text()
    assert text.startswith("# Phantom runtime job definition (source='runtime').\n")
    assert "kept in SQLite" in text, "the current banner replaces the old one"
    row = again.get_job("once")
    assert row.enabled is False and row.next_due_at is None, "the job stays disabled"


def test_the_pass_is_idempotent_a_second_boot_writes_nothing(tmp_path):
    s = _boot(tmp_path)
    s.add_job(name="daily", cron="0 9 * * *", action=ACTION)
    s.add_job(name="paused", cron="0 10 * * *", action=ACTION, enabled=False)
    _stale(tmp_path, "daily")
    path = _mirror(tmp_path, "daily")
    old_ns = 1_000_000_000_000_000_000
    os.utime(path, ns=(old_ns, old_ns))
    paused_before = _mirror(tmp_path, "paused").read_text()

    first = _boot(tmp_path)
    assert first.converge_job_mirrors() == 0, "the first boot already converged everything"
    assert path.stat().st_mtime_ns != old_ns, "the stale file was rewritten at that boot"
    after_first = path.stat().st_mtime_ns

    _boot(tmp_path)
    assert path.stat().st_mtime_ns == after_first, "an up-to-date mirror is not rewritten"
    assert _mirror(tmp_path, "paused").read_text() == paused_before


def test_a_missing_mirror_is_written(tmp_path):
    s = _boot(tmp_path)
    s.add_job(name="daily", cron="0 9 * * *", action=ACTION)
    _mirror(tmp_path, "daily").unlink()

    _boot(tmp_path)

    assert _doc(tmp_path, "daily")["cron"] == "0 9 * * *"


def test_a_file_that_failed_to_load_is_left_as_the_operator_wrote_it(tmp_path):
    s = _boot(tmp_path)
    s.add_job(name="daily", cron="0 9 * * *", action=ACTION)
    path = _mirror(tmp_path, "daily")
    path.write_text("name: daily\ncron: not a cron\ntimezone: UTC\naction: {type: prompt, message: hi}\n")
    edited = path.read_text()

    again = _boot(tmp_path)

    assert [i["basename"] for i in again.yaml_load_issues] == ["daily.yaml"]
    assert path.read_text() == edited, "an unapplied edit is not overwritten"
    assert again.get_job("daily").cron == "0 9 * * *"


def test_manifest_jobs_get_no_mirror(tmp_path):
    from usecase.job_scheduler import JobDefinition

    defs = [JobDefinition(name="m", cron="0 9 * * *", timezone="UTC", action=ACTION)]
    CroniterJobScheduler(definitions=defs, dispatcher=_noop, data_root=tmp_path)
    assert not _mirror(tmp_path, "m").exists()
