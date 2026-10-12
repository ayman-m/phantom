"""A job's permission policy no longer carries `require_approval`.

The per-job Require approval list was removed (it was stored and never acted
on). The scheduler drops the key on create and update, so the REST routes and
the agent's jobs_create / jobs_update tools never store it. Rows stored with it
before are read as they are and not migrated.
"""
from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from api.jobs import register_job_routes
from config.config import config as _config
from usecase.job_scheduler import CroniterJobScheduler

ACTION = {"type": "prompt", "message": "summarise the backlog"}


async def _noop(name, args):  # noqa: ANN001
    return {"ok": True}


class _FakeMcp:
    def __init__(self):
        self.routes = {}

    def custom_route(self, path, methods=None, include_in_schema=True):
        def deco(fn):
            for m in methods or ["GET"]:
                self.routes[(path, m)] = fn
            return fn

        return deco


def _stored_policy(tmp_path: Path, name: str) -> str | None:
    with sqlite3.connect(tmp_path / "jobs.db") as c:
        return c.execute(
            "SELECT permission_policy_json FROM jobs WHERE name = ?", (name,)
        ).fetchone()[0]


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(_config, "mcp_token", "test-token")
    sched = CroniterJobScheduler(definitions=[], dispatcher=_noop, data_root=tmp_path)
    mcp = _FakeMcp()
    register_job_routes(mcp, sched)
    app = Starlette()
    for (path, method), fn in mcp.routes.items():
        app.add_route(path, fn, methods=[method])
    client = TestClient(app, headers={"Authorization": "Bearer test-token"})
    return client, sched, tmp_path


def test_post_does_not_store_the_legacy_key(world):
    client, _s, tmp = world
    r = client.post("/api/v1/jobs", json={
        "name": "p", "cron": "0 9 * * *", "action": ACTION,
        "permission_policy": {"allowed_tools": ["xlog_*"], "require_approval": ["jobs_*"]},
    })
    assert r.status_code == 201
    assert r.json()["job"]["permission_policy"] == {"allowed_tools": ["xlog_*"]}
    assert "require_approval" not in _stored_policy(tmp, "p")


def test_patch_does_not_store_the_legacy_key(world):
    client, _s, tmp = world
    client.post("/api/v1/jobs", json={"name": "p", "cron": "0 9 * * *", "action": ACTION})
    r = client.patch("/api/v1/jobs/p", json={
        "permission_policy": {"denied_tools": ["*_delete"], "require_approval": ["jobs_*"]},
    })
    assert r.status_code == 200
    assert r.json()["job"]["permission_policy"] == {"denied_tools": ["*_delete"]}
    assert "require_approval" not in _stored_policy(tmp, "p")


def test_agent_jobs_create_and_update_do_not_store_the_legacy_key(world, monkeypatch):
    from usecase import job_scheduler
    from usecase.builtin_components import self_mod_tools

    _c, sched, tmp = world
    monkeypatch.setattr(job_scheduler, "_scheduler", sched, raising=False)
    monkeypatch.setattr(job_scheduler, "scheduler", lambda: sched)

    async def passthrough(*, tool_name, args, risk_tier, executor, **kw):  # noqa: ANN001
        return executor()

    monkeypatch.setattr("usecase.builtin_components._approval_gate.gate_and_execute", passthrough)

    asyncio.run(self_mod_tools.jobs_create(
        name="t", cron="0 9 * * *", action=ACTION,
        permission_policy={"allowed_tools": ["a_*"], "require_approval": ["b_*"]},
    ))
    assert "require_approval" not in _stored_policy(tmp, "t")
    asyncio.run(self_mod_tools.jobs_update(
        name="t", permission_policy={"denied_tools": ["c_*"], "require_approval": ["b_*"]},
    ))
    assert "require_approval" not in _stored_policy(tmp, "t")
    assert sched.get_job("t").permission_policy == {"denied_tools": ["c_*"]}
