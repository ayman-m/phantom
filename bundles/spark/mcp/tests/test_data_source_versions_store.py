"""Unit tests for the data-source version store."""
from __future__ import annotations

import pytest

from usecase.data_source_versions_store import DataSourceVersionsStore

DS = "ServiceNow/ServiceNow/servicenow_servicenow_raw"


@pytest.fixture
def store(tmp_path):
    return DataSourceVersionsStore(db_path=tmp_path / "versions.db")


def test_first_edit_snapshots_baseline_then_edit(store):
    store.snapshot(DS, "vendor: ServiceNow\n", author="bundle-baseline", note="original")
    store.snapshot(DS, "vendor: ServiceNow\nhow_to_use: edited\n", author="operator", note="my edit")
    versions = store.list_versions(DS)
    assert [v["version"] for v in versions] == [1, 2]
    assert versions[0]["author"] == "bundle-baseline"
    cur = store.get_current(DS)
    assert cur["version"] == 2 and "edited" in cur["yaml_snapshot"]


def test_single_current_invariant(store):
    store.snapshot(DS, "a", author="bundle-baseline")
    store.snapshot(DS, "b", author="operator")
    store.snapshot(DS, "c", author="operator")
    currents = [v for v in store.list_versions(DS) if v["is_current"]]
    assert len(currents) == 1 and currents[0]["version"] == 3


def test_get_version_and_none_for_unknown(store):
    store.snapshot(DS, "a", author="bundle-baseline")
    assert store.get_version(DS, 1)["yaml_snapshot"] == "a"
    assert store.get_version(DS, 99) is None
    assert store.get_current("Nope/Nope/nope_raw") is None
    assert store.list_versions("Nope/Nope/nope_raw") == []


def test_rollback_non_destructive(store):
    store.snapshot(DS, "v1", author="bundle-baseline")
    store.snapshot(DS, "v2", author="operator")
    store.snapshot(DS, "v3", author="operator")
    new = store.rollback(DS, 1)
    assert new["version"] == 4 and new["yaml_snapshot"] == "v1"
    assert [v["version"] for v in store.list_versions(DS)] == [1, 2, 3, 4]
    assert store.get_current(DS)["version"] == 4


def test_rollback_unknown_version_raises(store):
    store.snapshot(DS, "v1", author="bundle-baseline")
    with pytest.raises(ValueError):
        store.rollback(DS, 99)


def test_has_versions(store):
    assert store.has_versions(DS) is False
    store.snapshot(DS, "v1", author="bundle-baseline")
    assert store.has_versions(DS) is True


def test_all_current_returns_one_per_source(store):
    store.snapshot(DS, "v1", author="bundle-baseline")
    store.snapshot(DS, "v2-current", author="operator")
    store.snapshot("Other/Other/other_raw", "o1-current", author="operator")
    cur = store.all_current()
    assert cur == {
        DS: "v2-current",
        "Other/Other/other_raw": "o1-current",
    }


def test_rollback_records_author(store):
    # Rollback takes an author so agent rollbacks are attributed.
    store.snapshot(DS, "v1", author="bundle-baseline")
    store.snapshot(DS, "v2", author="operator")
    new = store.rollback(DS, 1, author="agent")
    assert new["author"] == "agent" and new["version"] == 3
    assert new["yaml_snapshot"] == "v1" and new["note"] == "rolled back to v1"
    # default stays "operator"
    new2 = store.rollback(DS, 2)
    assert new2["author"] == "operator" and new2["version"] == 4
