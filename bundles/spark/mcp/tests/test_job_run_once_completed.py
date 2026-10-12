"""A run-once job that already fired is not re-armed by anything but a new
Run-at time: not by Resume (API: 409 on /enable, 400 on PATCH enabled), and
not by a boot replay of the YAML mirror, with or without the database.

The stored cron has no year (`M H D Mo *`), so re-arming the old time would
fire the job again on the same date next year.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import yaml
from starlette.applications import Starlette
from starlette.testclient import TestClient

from api.jobs import register_job_routes
from config.config import config as _config
from usecase.job_scheduler import CompletedRunOnceError, CroniterJobScheduler

ACTION = {"type": "prompt", "message": "once"}
RUN_AT = "0 9 11 10 *"


async def _noop(name, args, **_k):  # noqa: ANN001
    return {"ok": True}


def _scheduler(tmp_path: Path) -> CroniterJobScheduler:
    return CroniterJobScheduler(definitions=[], dispatcher=_noop, data_root=tmp_path)


def _fired_run_once(s: CroniterJobScheduler, name: str = "once") -> None:
    s.add_job(name=name, cron=RUN_AT, action=ACTION, run_once=True)
    asyncio.run(s.trigger_now(name))
    row = s.get_job(name)
    assert row.enabled is False and row.last_fired_at is not None


# ─── API: Resume is refused ──────────────────────────────────────────


class _FakeMcp:
    def __init__(self):
        self.routes = {}

    def custom_route(self, path, methods=None, include_in_schema=True):
        def deco(fn):
            for m in methods or ["GET"]:
                self.routes[(path, m)] = fn
            return fn

        return deco


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setattr(_config, "mcp_token", "test-token")
    sched = _scheduler(tmp_path)
    mcp = _FakeMcp()
    register_job_routes(mcp, sched)
    app = Starlette()
    for (path, method), fn in mcp.routes.items():
        app.add_route(path, fn, methods=[method])
    client = TestClient(app, headers={"Authorization": "Bearer test-token"})
    return sched, client


def test_enable_route_refuses_a_completed_run_once_job_with_409(api):
    sched, client = api
    _fired_run_once(sched)
    r = client.post("/api/v1/jobs/once/enable")
    assert r.status_code == 409
    assert "Run-at" in r.json()["error"]
    row = sched.get_job("once")
    assert row.enabled is False and row.next_due_at is None


def test_patch_enable_refuses_a_completed_run_once_job_with_400(api):
    sched, client = api
    _fired_run_once(sched)
    r = client.patch("/api/v1/jobs/once", json={"enabled": True})
    assert r.status_code == 400
    assert sched.get_job("once").enabled is False


def test_a_new_run_at_time_rearms_a_completed_run_once_job(api):
    sched, client = api
    _fired_run_once(sched)
    r = client.patch(
        "/api/v1/jobs/once", json={"enabled": True, "cron": "0 9 12 10 *"},
    )
    assert r.status_code == 200
    assert r.json()["job"]["enabled"] is True
    assert r.json()["job"]["next_due_at"] is not None


def test_a_paused_run_once_job_that_never_fired_can_be_resumed(api):
    """The refusal is for COMPLETED run-once jobs only."""
    sched, client = api
    sched.add_job(name="not-yet", cron="0 9 11 10 *", action=ACTION, run_once=True, enabled=False)
    r = client.post("/api/v1/jobs/not-yet/enable")
    assert r.status_code == 200
    assert r.json()["job"]["enabled"] is True


# ─── Boot replay never re-enables it ─────────────────────────────────


def test_fire_writes_the_disabled_state_to_the_mirror(tmp_path):
    s = _scheduler(tmp_path)
    _fired_run_once(s)
    assert yaml.safe_load((tmp_path / "jobs" / "once.yaml").read_text())["enabled"] is False


def test_boot_replay_keeps_a_completed_run_once_job_disabled(tmp_path):
    s1 = _scheduler(tmp_path)
    _fired_run_once(s1)
    fired_at = s1.get_job("once").last_fired_at

    s2 = _scheduler(tmp_path)
    assert s2.yaml_load_issues == []
    row = s2.get_job("once")
    assert row.enabled is False and row.next_due_at is None
    assert row.last_fired_at == fired_at
    with pytest.raises(CompletedRunOnceError):
        s2.set_enabled("once", True)


def test_boot_replay_ignores_a_stale_enabled_true_in_the_mirror(tmp_path):
    """Mirrors written before the fire was mirrored say enabled: true."""
    s1 = _scheduler(tmp_path)
    _fired_run_once(s1)
    path = tmp_path / "jobs" / "once.yaml"
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    doc["enabled"] = True
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")

    s2 = _scheduler(tmp_path)
    assert s2.yaml_load_issues == []
    row = s2.get_job("once")
    assert row.enabled is False and row.next_due_at is None


def test_boot_replay_into_a_wiped_database_does_not_arm_a_fired_run_once_job(tmp_path):
    s1 = _scheduler(tmp_path)
    _fired_run_once(s1)
    (tmp_path / "jobs.db").unlink()

    s2 = _scheduler(tmp_path)
    assert s2.yaml_load_issues == []
    row = s2.get_job("once")
    assert row.enabled is False and row.next_due_at is None
