"""Round-trip tests for the YAML dual-write layer in
CroniterJobScheduler — per spark-agents spec §7.1, runtime job
definitions persist as YAML files at <data_root>/jobs/<name>.yaml
alongside the SQLite system-of-record.

These tests verify:
  - add_job() writes a YAML file matching the row
  - delete_job() removes the YAML file (runtime jobs only)
  - update_job() re-exports the YAML
  - load_yaml_jobs() reconciles a fresh DB from the YAML directory
    (boot replay)
  - Manifest jobs do NOT get a YAML mirror (their canonical def lives
    in manifest.yaml)
  - Path traversal in job names is rejected before touching disk

Tests use a fresh tempfile data root per case so concurrent runs
don't fight over /app/data/jobs/. The scheduler is constructed with
no manifest dispatcher (jobs that fire would fail; we only exercise
the storage layer, not _fire).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from usecase.job_scheduler import CroniterJobScheduler, JobDefinition


async def _noop_dispatcher(name, args):  # noqa: ANN001
    return {"ok": True, "called": name}


def _scheduler(
    tmp_path: Path, manifest_jobs: list[dict] | None = None,
) -> CroniterJobScheduler:
    """Build a scheduler rooted at tmp_path. Empty manifest by
    default; pass `manifest_jobs` (list of dicts) to seed boot
    reconciliation. We translate to JobDefinition shape here so the
    test fixtures stay readable."""
    defs = [
        JobDefinition(
            name=j["name"],
            cron=j["cron"],
            timezone=j.get("timezone", "UTC"),
            action=j["action"],
        )
        for j in (manifest_jobs or [])
    ]
    return CroniterJobScheduler(
        definitions=defs,
        dispatcher=_noop_dispatcher,
        data_root=tmp_path,
    )


# ─── Write path ──────────────────────────────────────────────────────


def test_add_job_creates_yaml_with_definition_only(tmp_path: Path) -> None:
    """Adding a runtime job writes a YAML mirror containing the
    DEFINITION fields (name, cron, timezone, enabled, run_once,
    action) — but NOT runtime state (last_fired_at, next_due_at,
    registered_at). State stays in SQLite to keep the YAML diff
    quiet across cron ticks."""
    s = _scheduler(tmp_path)
    s.add_job(
        name="nightly-summary",
        cron="0 9 * * *",
        timezone_name="UTC",
        action={"type": "chat", "message": "summary please"},
        enabled=True,
    )

    yaml_path = tmp_path / "jobs" / "nightly-summary.yaml"
    assert yaml_path.is_file(), f"expected YAML at {yaml_path}"

    body = yaml_path.read_text(encoding="utf-8")
    # Banner present
    assert "Phantom runtime job definition" in body
    # The actual payload parses cleanly (skip the banner — yaml.safe_load
    # tolerates the leading comment lines as blanks).
    doc = yaml.safe_load(body)
    assert doc["name"] == "nightly-summary"
    assert doc["cron"] == "0 9 * * *"
    assert doc["timezone"] == "UTC"
    assert doc["enabled"] is True
    assert doc["run_once"] is False
    assert doc["action"] == {"type": "chat", "message": "summary please"}
    # Runtime state must NOT leak into the YAML — it would create
    # spurious diffs on every cron tick.
    assert "next_due_at" not in doc
    assert "last_fired_at" not in doc
    assert "registered_at" not in doc


def test_add_job_run_once_persists_in_yaml(tmp_path: Path) -> None:
    """run_once=true is part of the definition; should round-trip."""
    s = _scheduler(tmp_path)
    s.add_job(
        name="oneshot",
        cron="0 0 1 1 *",
        action={"type": "tool_call", "name": "phantom_get_field_info", "args": {}},
        run_once=True,
    )
    doc = yaml.safe_load((tmp_path / "jobs" / "oneshot.yaml").read_text())
    assert doc["run_once"] is True


def test_update_job_rewrites_yaml(tmp_path: Path) -> None:
    s = _scheduler(tmp_path)
    s.add_job(
        name="weekly",
        cron="0 0 * * 0",
        action={"type": "chat", "message": "v1"},
    )
    s.update_job(
        "weekly",
        cron="0 12 * * 0",
        action={"type": "chat", "message": "v2"},
    )
    doc = yaml.safe_load((tmp_path / "jobs" / "weekly.yaml").read_text())
    assert doc["cron"] == "0 12 * * 0"
    assert doc["action"]["message"] == "v2"


def test_delete_runtime_job_removes_yaml(tmp_path: Path) -> None:
    s = _scheduler(tmp_path)
    s.add_job(
        name="ephemeral",
        cron="0 0 1 1 *",
        action={"type": "chat", "message": "hi"},
    )
    yaml_path = tmp_path / "jobs" / "ephemeral.yaml"
    assert yaml_path.is_file()

    assert s.delete_job("ephemeral") is True
    assert not yaml_path.exists(), "YAML should be removed after delete"


# ─── Manifest jobs do NOT get YAML mirrors ──────────────────────────


def test_manifest_job_does_not_create_yaml(tmp_path: Path) -> None:
    """Manifest jobs (source='manifest') are canonical in manifest.yaml;
    mirroring would create dueling sources of truth. Verify the YAML
    dir stays empty when only manifest jobs are registered."""
    manifest = [
        {
            "name": "from-manifest",
            "cron": "0 0 * * *",
            "action": {"type": "chat", "message": "manifest job"},
        }
    ]
    s = _scheduler(tmp_path, manifest_jobs=manifest)
    yaml_dir = tmp_path / "jobs"
    files = list(yaml_dir.glob("*.yaml")) if yaml_dir.is_dir() else []
    assert files == [], f"manifest job should NOT mirror to disk; found {files}"
    # Confirm SQLite has the row though
    assert s.get_job("from-manifest") is not None


# ─── Boot replay ─────────────────────────────────────────────────────


def test_load_yaml_jobs_reconciles_into_fresh_db(tmp_path: Path) -> None:
    """Simulate a deploy where SQLite was wiped but the YAML directory
    survived (e.g. the operator nuked phantom_mcp_data volume but kept
    /app/data/jobs/). The boot loader should re-create every YAML row
    in SQLite."""
    # First scheduler — write some jobs
    s1 = _scheduler(tmp_path)
    s1.add_job(
        name="alpha",
        cron="0 9 * * *",
        action={"type": "chat", "message": "α"},
    )
    s1.add_job(
        name="beta",
        cron="0 17 * * *",
        action={"type": "tool_call", "name": "phantom_get_field_info", "args": {}},
        enabled=False,
    )

    # Wipe SQLite; keep YAML
    db = tmp_path / "jobs.db"
    db.unlink()

    # New scheduler — boot reconciliation kicks in
    s2 = _scheduler(tmp_path)
    alpha = s2.get_job("alpha")
    beta = s2.get_job("beta")
    assert alpha is not None and alpha.cron == "0 9 * * *"
    assert beta is not None and beta.enabled is False
    assert beta.action == {
        "type": "tool_call",
        "name": "phantom_get_field_info",
        "args": {},
    }


def test_load_yaml_jobs_idempotent_on_repeat_boot(tmp_path: Path) -> None:
    """Running boot twice should NOT duplicate jobs — the ON CONFLICT
    clause in add_job's INSERT handles the idempotent case."""
    s1 = _scheduler(tmp_path)
    s1.add_job(
        name="repeat-me",
        cron="0 0 * * *",
        action={"type": "chat", "message": "x"},
    )
    count1 = len(s1.list_jobs())

    # Tear down + reload — both should still see exactly one job
    s2 = _scheduler(tmp_path)
    count2 = len(s2.list_jobs())
    assert count1 == count2 == 1


def test_load_yaml_jobs_ignores_malformed_files(tmp_path: Path, caplog) -> None:
    """A garbage YAML file shouldn't break boot — log + skip + continue."""
    yaml_dir = tmp_path / "jobs"
    yaml_dir.mkdir(parents=True, exist_ok=True)
    (yaml_dir / "bad.yaml").write_text("this is: : not [valid] yaml: [", encoding="utf-8")
    (yaml_dir / "good.yaml").write_text(
        "name: good\ncron: '0 9 * * *'\ntimezone: UTC\nenabled: true\nrun_once: false\n"
        "action: { type: chat, message: hi }\n",
        encoding="utf-8",
    )

    s = _scheduler(tmp_path)
    # Bad file skipped; good file loaded
    assert s.get_job("good") is not None
    assert s.get_job("bad") is None


def test_yaml_load_issues_collected(tmp_path: Path) -> None:
    """Malformed YAMLs are captured into scheduler.yaml_load_issues
    (instead of WARN-per-file log noise) so the /jobs page can render a
    banner and the /api/v1/jobs/yaml-issues endpoint can surface details."""
    yaml_dir = tmp_path / "jobs"
    yaml_dir.mkdir(parents=True, exist_ok=True)
    # Two distinct failure modes — both should land in the issues list.
    (yaml_dir / "bad-yaml.yaml").write_text(
        "this is: : not [valid] yaml: [", encoding="utf-8",
    )
    (yaml_dir / "bad-action.yaml").write_text(
        # Valid YAML, but action.type='log' is rejected by add_job's
        # validator.
        "name: bad-action\ncron: '0 9 * * *'\ntimezone: UTC\n"
        "action: { type: log, payload: hi }\n",
        encoding="utf-8",
    )
    (yaml_dir / "good.yaml").write_text(
        "name: good\ncron: '0 9 * * *'\ntimezone: UTC\nenabled: true\n"
        "action: { type: chat, message: hi }\n",
        encoding="utf-8",
    )

    s = _scheduler(tmp_path)
    # Good job loaded, bad ones skipped.
    assert s.get_job("good") is not None
    assert s.get_job("bad-yaml") is None
    assert s.get_job("bad-action") is None

    # Both failures should be captured in the issues list.
    issues = s.yaml_load_issues
    assert len(issues) == 2
    bad_names = sorted(i["basename"] for i in issues)
    assert bad_names == ["bad-action.yaml", "bad-yaml.yaml"]
    # Each entry must have the contract fields the UI banner reads.
    for issue in issues:
        assert "path" in issue
        assert "basename" in issue
        assert "error" in issue
        assert "mtime" in issue


def test_yaml_load_issues_empty_when_all_load_cleanly(tmp_path: Path) -> None:
    """No malformed files → empty issues list. The UI banner suppression
    contract depends on this being [] (falsy), not None."""
    yaml_dir = tmp_path / "jobs"
    yaml_dir.mkdir(parents=True, exist_ok=True)
    (yaml_dir / "ok.yaml").write_text(
        "name: ok\ncron: '0 9 * * *'\ntimezone: UTC\n"
        "action: { type: chat, message: hi }\n",
        encoding="utf-8",
    )
    s = _scheduler(tmp_path)
    assert s.yaml_load_issues == []
    assert len(s.yaml_load_issues) == 0


# ─── Defense in depth ───────────────────────────────────────────────


def test_path_traversal_in_name_rejected(tmp_path: Path) -> None:
    """A crafted name like '../escape' must not write outside
    <data_root>/jobs/. Validation is on add_job() (the YAML helper
    raises ValueError too — belt and suspenders)."""
    s = _scheduler(tmp_path)
    # add_job's name validation kicks in at the cron-validate stage;
    # _job_yaml_path also rejects independently. We exercise the path
    # builder directly to prove the second layer.
    with pytest.raises(ValueError, match="filesystem-safe"):
        s._job_yaml_path("../escape")
    with pytest.raises(ValueError, match="filesystem-safe"):
        s._job_yaml_path("a/b")
