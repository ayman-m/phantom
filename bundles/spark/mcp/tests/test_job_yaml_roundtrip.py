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
    # Replaying the mirror is not an error: a job that already exists with
    # the same definition used to be reported as "already exists" on every
    # boot, filling the yaml-issues list.
    assert s2.yaml_load_issues == []


def test_repeated_boots_leave_issues_empty_and_state_alone(tmp_path: Path) -> None:
    """Every runtime job is replayed on every boot. None of them may turn
    into a load issue, and the replay must not disturb live state."""
    s1 = _scheduler(tmp_path)
    for i in range(5):
        s1.add_job(
            name=f"job-{i}", cron="*/5 * * * *",
            action={"type": "prompt", "message": f"m{i}"},
            description=f"note {i}" if i % 2 else None,
        )
    before = {j.name: (j.id, j.registered_at, j.next_due_at) for j in s1.list_jobs()}
    for _ in range(3):
        s = _scheduler(tmp_path)
        assert s.yaml_load_issues == []
    after = {j.name: (j.id, j.registered_at, j.next_due_at) for j in s.list_jobs()}
    assert after == before


def test_description_round_trips_set_cleared_and_omitted(tmp_path: Path) -> None:
    s = _scheduler(tmp_path)
    s.add_job(name="a", cron="0 9 * * *", action={"type": "chat", "message": "x"},
              description="first note")
    s.add_job(name="b", cron="0 9 * * *", action={"type": "chat", "message": "x"})
    s.add_job(name="c", cron="0 9 * * *", action={"type": "chat", "message": "x"},
              description="to be cleared")
    s.update_job("c", description="")
    s2 = _scheduler(tmp_path)
    assert s2.yaml_load_issues == []
    assert s2.get_job("a").description == "first note"
    assert s2.get_job("b").description == ""
    assert s2.get_job("c").description == ""
    # And once more through a database wipe: the mirror alone restores it.
    (tmp_path / "jobs.db").unlink()
    s3 = _scheduler(tmp_path)
    assert s3.yaml_load_issues == []
    assert [s3.get_job(n).description for n in "abc"] == ["first note", "", ""]


def test_edited_yaml_definition_is_applied_on_reboot(tmp_path: Path) -> None:
    """The mirror is the operator-editable definition: cron, timezone,
    action, run_once and description edits apply on restart."""
    s1 = _scheduler(tmp_path)
    s1.add_job(name="edit-me", cron="0 9 * * *", action={"type": "chat", "message": "old"},
               description="old note")
    path = tmp_path / "jobs" / "edit-me.yaml"
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    doc.update(cron="30 6 * * *", timezone="Asia/Riyadh", description="new note",
               run_once=True, action={"type": "chat", "message": "new"})
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")

    s2 = _scheduler(tmp_path)
    assert s2.yaml_load_issues == []
    row = s2.get_job("edit-me")
    assert (row.cron, row.timezone, row.description, row.run_once) == (
        "30 6 * * *", "Asia/Riyadh", "new note", True,
    )
    assert row.action == {"type": "chat", "message": "new"}
    assert row.enabled is True and row.next_due_at is not None


def test_edited_yaml_with_a_bad_cron_is_a_load_issue_and_keeps_the_job(tmp_path: Path) -> None:
    s1 = _scheduler(tmp_path)
    s1.add_job(name="keep", cron="0 9 * * *", action={"type": "chat", "message": "x"})
    path = tmp_path / "jobs" / "keep.yaml"
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    doc["cron"] = "not a cron"
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")

    s2 = _scheduler(tmp_path)
    assert [i["basename"] for i in s2.yaml_load_issues] == ["keep.yaml"]
    assert s2.get_job("keep").cron == "0 9 * * *"


def test_yaml_with_a_manifest_job_name_is_a_load_issue_not_an_overwrite(tmp_path: Path) -> None:
    manifest = [{"name": "shared", "cron": "0 0 * * *",
                 "action": {"type": "chat", "message": "manifest wins"}}]
    yaml_dir = tmp_path / "jobs"
    yaml_dir.mkdir(parents=True)
    (yaml_dir / "shared.yaml").write_text(
        "name: shared\ncron: '5 5 * * *'\ntimezone: UTC\n"
        "action: { type: chat, message: from yaml }\n",
        encoding="utf-8",
    )
    s = _scheduler(tmp_path, manifest_jobs=manifest)
    assert [i["basename"] for i in s.yaml_load_issues] == ["shared.yaml"]
    assert "manifest" in s.yaml_load_issues[0]["error"]
    row = s.get_job("shared")
    assert row.source == "manifest" and row.cron == "0 0 * * *"


def test_paused_job_stays_paused_across_reboot_and_database_wipe(tmp_path: Path) -> None:
    """set_enabled used to leave the mirror saying enabled: true."""
    s1 = _scheduler(tmp_path)
    s1.add_job(name="paused", cron="*/5 * * * *", action={"type": "chat", "message": "x"})
    s1.set_enabled("paused", False)
    assert yaml.safe_load((tmp_path / "jobs" / "paused.yaml").read_text())["enabled"] is False

    s2 = _scheduler(tmp_path)
    assert s2.yaml_load_issues == []
    assert s2.get_job("paused").enabled is False
    assert s2.get_job("paused").next_due_at is None

    (tmp_path / "jobs.db").unlink()
    s3 = _scheduler(tmp_path)
    assert s3.get_job("paused").enabled is False

    # Resume is mirrored too.
    s3.set_enabled("paused", True)
    s4 = _scheduler(tmp_path)
    assert s4.get_job("paused").enabled is True
    assert s4.yaml_load_issues == []


def test_stale_enabled_in_an_old_mirror_does_not_resume_a_paused_job(tmp_path: Path) -> None:
    """Mirrors written before pause was mirrored still say enabled: true.
    A restart must not resume a job SQLite has paused."""
    s1 = _scheduler(tmp_path)
    s1.add_job(name="old-mirror", cron="*/5 * * * *", action={"type": "chat", "message": "x"})
    s1.set_enabled("old-mirror", False)
    path = tmp_path / "jobs" / "old-mirror.yaml"
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    doc["enabled"] = True
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")

    s2 = _scheduler(tmp_path)
    assert s2.yaml_load_issues == []
    assert s2.get_job("old-mirror").enabled is False


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
