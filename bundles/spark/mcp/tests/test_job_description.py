"""A job's `description` is stored, round-trips, and reaches the API.

The /jobs/new form has always had a Description field, but the backend ignored
it (POST dropped `meta`, to_dict and the YAML mirror had no such field), so a
description typed by the operator vanished on save. It is a first-class column
now. Rows stored before the column existed read as empty.
"""
from __future__ import annotations

import sqlite3
import asyncio
from pathlib import Path

import pytest
import yaml
from starlette.applications import Starlette
from starlette.testclient import TestClient

from api.jobs import register_job_routes
from config.config import config as _config
from usecase.job_scheduler import CroniterJobScheduler

ACTION = {"type": "prompt", "message": "summarise the backlog"}


async def _noop(name, args):  # noqa: ANN001
    return {"ok": True}


def _scheduler(tmp_path: Path) -> CroniterJobScheduler:
    return CroniterJobScheduler(definitions=[], dispatcher=_noop, data_root=tmp_path)


def _yaml(tmp_path: Path, name: str) -> dict:
    return yaml.safe_load((tmp_path / "jobs" / f"{name}.yaml").read_text())


# ─── store / to_dict / YAML mirror ───────────────────────────────────


def test_description_is_stored_and_returned(tmp_path):
    s = _scheduler(tmp_path)
    row = s.add_job(name="digest", cron="0 9 * * *", action=ACTION, description="Morning digest for the SOC lead")
    assert row.description == "Morning digest for the SOC lead"
    assert row.to_dict()["description"] == "Morning digest for the SOC lead"
    assert s.get_job("digest").description == "Morning digest for the SOC lead"


def test_a_job_without_a_description_reads_as_empty(tmp_path):
    s = _scheduler(tmp_path)
    row = s.add_job(name="plain", cron="0 9 * * *", action=ACTION)
    assert row.description == "" and row.to_dict()["description"] == ""
    assert "description" not in _yaml(tmp_path, "plain")


def test_description_is_mirrored_to_yaml_and_survives_a_boot_replay(tmp_path):
    s = _scheduler(tmp_path)
    s.add_job(name="digest", cron="0 9 * * *", action=ACTION, description="Morning digest")
    assert _yaml(tmp_path, "digest")["description"] == "Morning digest"

    # Boot replay onto a fresh database: the YAML directory is the source.
    (tmp_path / "jobs.db").unlink()
    fresh = _scheduler(tmp_path)
    assert fresh.get_job("digest").description == "Morning digest"


def test_update_none_keeps_empty_string_clears_text_sets(tmp_path):
    s = _scheduler(tmp_path)
    s.add_job(name="digest", cron="0 9 * * *", action=ACTION, description="first")

    assert s.update_job("digest", cron="0 10 * * *").description == "first", "None preserves"
    assert s.update_job("digest", description="second").description == "second"
    assert _yaml(tmp_path, "digest")["description"] == "second"
    cleared = s.update_job("digest", description="")
    assert cleared.description == ""
    assert "description" not in _yaml(tmp_path, "digest")


def test_rows_stored_before_the_column_existed_are_migrated_and_read_empty(tmp_path):
    s = _scheduler(tmp_path)
    s.add_job(name="old", cron="0 9 * * *", action=ACTION)
    db = tmp_path / "jobs.db"
    c = sqlite3.connect(db)
    c.execute("ALTER TABLE jobs DROP COLUMN description")
    c.commit()
    c.close()

    reopened = _scheduler(tmp_path)
    assert reopened.get_job("old").description == ""
    assert reopened.update_job("old", description="now has one").description == "now has one"


# ─── REST API ────────────────────────────────────────────────────────


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
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(_config, "mcp_token", "test-token")
    mcp = _FakeMcp()
    register_job_routes(mcp, _scheduler(tmp_path))
    app = Starlette()
    for (path, method), fn in mcp.routes.items():
        app.add_route(path, fn, methods=[method])
    return TestClient(app, headers={"Authorization": "Bearer test-token"})


def test_post_stores_description_and_get_returns_it(client):
    r = client.post(
        "/api/v1/jobs",
        json={"name": "digest", "cron": "0 9 * * *", "action": ACTION, "description": "Morning digest"},
    )
    assert r.status_code == 201 and r.json()["job"]["description"] == "Morning digest"
    listed = client.get("/api/v1/jobs").json()["jobs"]
    assert [j["description"] for j in listed if j["name"] == "digest"] == ["Morning digest"]


def test_patch_sets_clears_and_preserves_description(client):
    client.post("/api/v1/jobs", json={"name": "digest", "cron": "0 9 * * *", "action": ACTION, "description": "a"})
    assert client.patch("/api/v1/jobs/digest", json={"description": "b"}).json()["job"]["description"] == "b"
    assert client.patch("/api/v1/jobs/digest", json={"enabled": True}).json()["job"]["description"] == "b"
    assert client.patch("/api/v1/jobs/digest", json={"description": ""}).json()["job"]["description"] == ""


def test_a_non_string_description_is_a_400(client):
    r = client.post("/api/v1/jobs", json={"name": "x", "cron": "0 9 * * *", "action": ACTION, "description": {"a": 1}})
    assert r.status_code == 400 and "description" in r.json()["error"]


# ─── agent tools ─────────────────────────────────────────────────────


def test_jobs_create_and_update_tools_carry_the_description(tmp_path, monkeypatch):
    from usecase.builtin_components import self_mod_tools
    from usecase import job_scheduler

    s = _scheduler(tmp_path)
    monkeypatch.setattr(job_scheduler, "_scheduler", s, raising=False)
    monkeypatch.setattr(job_scheduler, "scheduler", lambda: s)

    async def passthrough(*, tool_name, args, risk_tier, executor, **kw):  # noqa: ANN001
        return executor()

    monkeypatch.setattr("usecase.builtin_components._approval_gate.gate_and_execute", passthrough)

    made = asyncio.run(self_mod_tools.jobs_create(name="t", cron="0 9 * * *", action=ACTION, description="from the agent"))
    assert made["job"]["description"] == "from the agent"
    changed = asyncio.run(self_mod_tools.jobs_update(name="t", description="edited"))
    assert changed["job"]["description"] == "edited"
    kept = asyncio.run(self_mod_tools.jobs_update(name="t", enabled=False))
    assert kept["job"]["description"] == "edited"
