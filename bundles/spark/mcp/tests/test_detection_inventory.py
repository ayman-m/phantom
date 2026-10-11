"""Tests for SqliteDetectionInventory and the coverage_tools surface.

Covers:
  - upsert_fires: inserts new rows, dedups on issue_id (idempotency),
    skips malformed payloads, persists technique_ids correctly across
    XSIAM's mixed shapes (list-of-strings, list-of-objects, comma-strings).
  - list_rules: aggregates fires per rule, computes 24h/7d/30d windows,
    unions techniques, sorts by recent.
  - rule_summary: fetches the per-rule rollup.
  - list_fires: filters by rule_id + since.
  - technique_coverage: per-MITRE-T-code rollup.
  - The detections_list / detections_get / detections_recent_fires
    / technique_coverage tool wrappers return clean shapes when the
    inventory singleton is wired.
  - detections_sync (the ingest-only tool) handles non-list input
    gracefully + reports counts.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from usecase.detection_inventory import (
    SqliteDetectionInventory,
    set_detection_inventory,
)
from usecase.builtin_components import coverage_tools


def _now_ms() -> int:
    return int(time.time() * 1000)


def _issue(
    *,
    issue_id: str,
    rule_id: str = "rule-A",
    rule_name: str = "Rule A",
    severity: str = "HIGH",
    techniques: object = None,
    minutes_ago: int = 0,
) -> dict:
    """Build a minimal XSIAM-like issue dict for tests."""
    fired_at_ms = _now_ms() - (minutes_ago * 60 * 1000)
    out: dict = {
        "issue_id": issue_id,
        "correlation_rule_id": rule_id,
        "rule_name": rule_name,
        "severity": severity,
        "detection_method": "correlation",
        "_insert_time": fired_at_ms,
    }
    if techniques is not None:
        out["mitre_technique_id_and_name"] = techniques
    return out


# ─── Upsert path ──────────────────────────────────────────────────


def test_upsert_inserts_new_fires(tmp_path: Path) -> None:
    inv = SqliteDetectionInventory(data_root=tmp_path)
    issues = [
        _issue(issue_id="i1", rule_id="r1", techniques=["T1078"]),
        _issue(issue_id="i2", rule_id="r1", techniques=["T1078", "T1059.001"]),
        _issue(issue_id="i3", rule_id="r2", techniques=["T1059"]),
    ]
    result = inv.upsert_fires(issues)
    assert result == {"inserted": 3, "skipped": 0, "total": 3}


def test_upsert_dedups_on_issue_id(tmp_path: Path) -> None:
    inv = SqliteDetectionInventory(data_root=tmp_path)
    issues = [_issue(issue_id="dup", rule_id="r1", techniques=["T1078"])]
    inv.upsert_fires(issues)
    second = inv.upsert_fires(issues)
    assert second["inserted"] == 0
    assert second["total"] == 1


def test_upsert_skips_missing_required_fields(tmp_path: Path) -> None:
    inv = SqliteDetectionInventory(data_root=tmp_path)
    bad = [
        {},                               # no issue_id, no rule_id
        {"issue_id": "x"},                 # missing rule_id
        {"correlation_rule_id": "r1"},     # missing issue_id
        "not a dict",                      # type-broken
    ]
    result = inv.upsert_fires(bad)
    assert result["inserted"] == 0
    assert result["skipped"] == 4


def test_technique_extraction_handles_mixed_shapes(tmp_path: Path) -> None:
    """XSIAM's MITRE attachment shape varies. Our extractor should
    cope with: list-of-strings, list-of-objects (with id/name keys),
    and comma-separated strings."""
    inv = SqliteDetectionInventory(data_root=tmp_path)
    inv.upsert_fires([
        _issue(issue_id="s1", techniques=["T1078", "T1059.001"]),
        _issue(issue_id="s2", techniques=[
            {"id": "T1110", "name": "Brute Force"},
            {"id": "T1078"},
        ]),
        _issue(issue_id="s3", techniques="T1190, T1133"),
    ])
    fires = inv.list_fires(limit=10)
    by_id = {f.issue_id: f.technique_ids for f in fires}
    assert by_id["s1"] == ["T1078", "T1059.001"]
    assert by_id["s2"] == ["T1110", "T1078"]
    assert by_id["s3"] == ["T1190", "T1133"]


# ─── Aggregations ─────────────────────────────────────────────────


def test_list_rules_aggregates_with_window_counts(tmp_path: Path) -> None:
    inv = SqliteDetectionInventory(data_root=tmp_path)
    # rule-A: 2 fires recent (within 24h), 1 older (40 days)
    # rule-B: 1 fire recent
    inv.upsert_fires([
        _issue(issue_id="a1", rule_id="rule-A", techniques=["T1078"], minutes_ago=10),
        _issue(issue_id="a2", rule_id="rule-A", techniques=["T1078", "T1059"], minutes_ago=120),
        _issue(issue_id="a3", rule_id="rule-A", techniques=["T1078"], minutes_ago=40 * 24 * 60),
        _issue(issue_id="b1", rule_id="rule-B", techniques=["T1110"], minutes_ago=30),
    ])
    rules = inv.list_rules()
    by_id = {r.rule_id: r for r in rules}

    assert by_id["rule-A"].fires_total == 3
    assert by_id["rule-A"].fires_24h == 2
    assert by_id["rule-A"].fires_7d == 2
    assert by_id["rule-A"].fires_30d == 2  # 40-day-old fire excluded
    assert set(by_id["rule-A"].technique_ids) == {"T1078", "T1059"}

    assert by_id["rule-B"].fires_total == 1
    assert by_id["rule-B"].fires_24h == 1


def test_rule_summary_returns_none_for_unknown_rule(tmp_path: Path) -> None:
    inv = SqliteDetectionInventory(data_root=tmp_path)
    inv.upsert_fires([_issue(issue_id="a", rule_id="exists")])
    assert inv.rule_summary("not-here") is None
    assert inv.rule_summary("exists") is not None


def test_list_fires_filter_by_rule(tmp_path: Path) -> None:
    inv = SqliteDetectionInventory(data_root=tmp_path)
    inv.upsert_fires([
        _issue(issue_id="a1", rule_id="rule-A"),
        _issue(issue_id="a2", rule_id="rule-A"),
        _issue(issue_id="b1", rule_id="rule-B"),
    ])
    a_fires = inv.list_fires(rule_id="rule-A")
    assert len(a_fires) == 2
    assert all(f.rule_id == "rule-A" for f in a_fires)


def test_technique_coverage_per_t_code(tmp_path: Path) -> None:
    inv = SqliteDetectionInventory(data_root=tmp_path)
    inv.upsert_fires([
        _issue(issue_id="x1", rule_id="rule-A", techniques=["T1078"]),
        _issue(issue_id="x2", rule_id="rule-B", techniques=["T1078"]),
        _issue(issue_id="y1", rule_id="rule-A", techniques=["T1059"]),
    ])
    cov = inv.technique_coverage()
    assert cov["T1078"]["rules_count"] == 2
    assert cov["T1078"]["fires_24h"] == 2
    assert cov["T1059"]["rules_count"] == 1


# ─── Tool wrappers ────────────────────────────────────────────────


def test_detections_sync_tool_rejects_non_list(tmp_path: Path) -> None:
    inv = SqliteDetectionInventory(data_root=tmp_path)
    set_detection_inventory(inv)
    try:
        out = coverage_tools.detections_sync(issues="not a list")  # type: ignore[arg-type]
        assert "error" in out
        assert "list" in out["error"].lower()
    finally:
        set_detection_inventory(None)


def test_detections_sync_tool_returns_counts(tmp_path: Path) -> None:
    inv = SqliteDetectionInventory(data_root=tmp_path)
    set_detection_inventory(inv)
    try:
        out = coverage_tools.detections_sync(issues=[
            _issue(issue_id="t1", rule_id="rA"),
            _issue(issue_id="t2", rule_id="rA"),
        ])
        assert out["ok"] is True
        assert out["inserted"] == 2
        assert out["total"] == 2
    finally:
        set_detection_inventory(None)


def test_detections_list_tool_returns_empty_when_no_data(tmp_path: Path) -> None:
    inv = SqliteDetectionInventory(data_root=tmp_path)
    set_detection_inventory(inv)
    try:
        out = coverage_tools.detections_list()
        assert out == {"rules": [], "count": 0}
    finally:
        set_detection_inventory(None)


def test_detections_list_tool_filters_by_severity(tmp_path: Path) -> None:
    inv = SqliteDetectionInventory(data_root=tmp_path)
    set_detection_inventory(inv)
    try:
        inv.upsert_fires([
            _issue(issue_id="h1", rule_id="rH", severity="HIGH"),
            _issue(issue_id="l1", rule_id="rL", severity="LOW"),
        ])
        high = coverage_tools.detections_list(severity="high")
        assert high["count"] == 1
        assert high["rules"][0]["rule_id"] == "rH"
    finally:
        set_detection_inventory(None)


def test_detections_get_tool_returns_error_for_unknown(tmp_path: Path) -> None:
    inv = SqliteDetectionInventory(data_root=tmp_path)
    set_detection_inventory(inv)
    try:
        out = coverage_tools.detections_get("ghost-rule")
        assert "error" in out
        assert "not found" in out["error"]
    finally:
        set_detection_inventory(None)


def test_technique_coverage_tool_shape(tmp_path: Path) -> None:
    inv = SqliteDetectionInventory(data_root=tmp_path)
    set_detection_inventory(inv)
    try:
        inv.upsert_fires([
            _issue(issue_id="a", rule_id="r", techniques=["T1078"]),
        ])
        out = coverage_tools.technique_coverage()
        assert out["total_techniques"] == 1
        assert "T1078" in out["techniques"]
        assert out["techniques"]["T1078"]["rules_count"] == 1
    finally:
        set_detection_inventory(None)


# ─── Tools fail closed when inventory not wired ────────────────────


def test_tools_error_when_inventory_not_wired() -> None:
    set_detection_inventory(None)
    out = coverage_tools.detections_list()
    assert "error" in out
    assert "not initialized" in out["error"]
