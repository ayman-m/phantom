"""Installed data sources sync to their effective catalog schema at boot.

An install copies the schema into data_sources.db and upgrades keep that volume,
so without a sync a corrected bundled YAML would never reach a source that is
already installed, and an operator edit would reach the catalog overlay but not
the served rows. The boot pass syncs every installed bundled source — unedited
to the bundle, edited to its effective (overlay) schema — leaving only pinned
sources, which it reports.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path

import pytest

from api import data_sources as ds_api
from usecase import data_source_versions_store as vs
from usecase.audit_log import SqliteAuditLog, set_audit_log
from usecase.data_sources_store import (
    DataSourceField,
    DataSourcesStore,
    set_data_sources_store,
)
from usecase.data_sources_yaml_loader import get_data_sources_yaml_loader

ZS = ("Zscaler", "ZscalerModelingRule", "zscaler_nssweblog_raw")
ZS_ID = "/".join(ZS)
FW = ("FortinetFortiwebVM", "FortinetFortiwebVM", "fortinet_fortiweb_raw")
FW_ID = "/".join(FW)
OLD_INSTALL = "2026-08-30T09:23:21Z"


@pytest.fixture
def env(tmp_path: Path):
    store = DataSourcesStore(db_path=tmp_path / "ds.db")
    set_data_sources_store(store)
    versions = vs.DataSourceVersionsStore(db_path=tmp_path / "v.db")
    vs.set_data_source_versions_store(versions)
    audit = SqliteAuditLog(data_root=tmp_path)
    set_audit_log(audit)
    get_data_sources_yaml_loader().invalidate()
    yield store, versions, audit
    set_data_sources_store(None)
    vs.set_data_source_versions_store(None)
    set_audit_log(None)
    get_data_sources_yaml_loader().invalidate()


def _install(pack: str, rule: str, dataset: str) -> None:
    out = asyncio.run(ds_api.data_sources_install(
        pack_name=pack, rule_name=rule, dataset_name=dataset))
    assert out["ok"] is True, out


def _make_stale(store: DataSourcesStore, ds_id: str) -> None:
    """Re-write the installed row with an old schema, the way an install made
    before a bundle fix looks: a field the fix removed, none it added."""
    ds = store.get(ds_id)
    ds.installed_at = OLD_INSTALL
    ds.installed_by = "user:operator"
    store.install(ds, fields=[
        DataSourceField(name="action", type="string"),
        DataSourceField(name="act", type="string_short", example="token_value"),
    ])


def _field_names(store: DataSourcesStore, ds_id: str) -> set[str]:
    return {f.name for f in store.get_with_schema(ds_id).fields}


def _bundle_field_names(pack: str, rule: str, dataset: str) -> set[str]:
    y = get_data_sources_yaml_loader().get_by_3tuple(pack, rule, dataset)
    return {f["name"] for f in y.fields}


def _audit_events(audit: SqliteAuditLog) -> list[dict]:
    with sqlite3.connect(audit.db_path) as c:
        rows = c.execute(
            "SELECT action, status, actor, trigger, metadata_json FROM audit_events "
            "WHERE action = 'data_sources_refreshed'"
        ).fetchall()
    return [
        {"action": a, "status": s, "actor": ac, "trigger": t, "meta": json.loads(m)}
        for a, s, ac, t, m in rows
    ]


def test_stale_source_is_refreshed_and_keeps_its_install_record(env) -> None:
    store, _, audit = env
    _install(*ZS)
    _make_stale(store, ZS_ID)

    summary = ds_api.refresh_installed_from_bundle()

    assert summary["refreshed"] == [ZS_ID]
    assert _field_names(store, ZS_ID) == _bundle_field_names(*ZS)
    row = store.get(ZS_ID)
    assert (row.installed_at, row.installed_by) == (OLD_INSTALL, "user:operator")
    assert row.field_count == len(_bundle_field_names(*ZS))
    # the served schema is the bundle's, gates and enums included
    act = {f.name: f for f in store.get_with_schema(ZS_ID).fields}["act"]
    assert act.enum_values == ["Allowed", "Blocked"] and act.example == "Allowed"

    events = _audit_events(audit)
    assert len(events) == 1
    assert events[0]["status"] == "success" and events[0]["trigger"] == "boot"
    assert events[0]["meta"]["refreshed"] == [ZS_ID]


def test_up_to_date_sources_are_left_alone_and_record_nothing(env) -> None:
    store, _, audit = env
    _install(*ZS)
    _install(*FW)

    summary = ds_api.refresh_installed_from_bundle()

    assert summary["refreshed"] == [] and summary["unchanged"] == 2
    assert "skipped_edited" not in summary  # edited sources are synced, not skipped
    assert _audit_events(audit) == []


def test_refresh_is_idempotent(env) -> None:
    store, _, audit = env
    _install(*ZS)
    _make_stale(store, ZS_ID)
    ds_api.refresh_installed_from_bundle()

    second = ds_api.refresh_installed_from_bundle()

    assert second["refreshed"] == [] and second["unchanged"] == 1
    assert len(_audit_events(audit)) == 1


def test_editing_an_installed_source_syncs_the_boot_pass_then_sees_it_current(env) -> None:
    # An edit that changes only how_to_use resyncs the installed rows at
    # edit time (to the full effective schema), so the boot pass sees it current.
    store, versions, audit = env
    _install(*FW)
    _make_stale(store, FW_ID)
    out = ds_api._apply_edit(*FW, how_to_use="OPERATOR NOTES", author="operator")
    assert out["ok"] and out["installed_schema_synced"] is True
    assert _field_names(store, FW_ID) == _bundle_field_names(*FW)  # synced by the edit

    summary = ds_api.refresh_installed_from_bundle()
    assert summary["refreshed"] == [] and summary["unchanged"] == 1
    assert _audit_events(audit) == []


def test_source_with_unsynced_edit_is_synced_by_the_boot_pass(env) -> None:
    # A source whose install rows diverge from its effective (edited) YAML —
    # an edit that never resynced — is synced to the edit by the boot pass, not skipped.
    store, versions, audit = env
    _install(*ZS)
    # edit the fields via the version store directly (no edit-time resync), then
    # make the installed rows stale, i.e. as if the edit never resynced them.
    out = ds_api._apply_edit(
        *ZS, fields=[{"name": "act", "type": "enum", "enum_values": ["Allowed"], "example": "Allowed"},
                     {"name": "suser", "type": "user", "example": "jdoe"}],
        author="operator")
    assert out["ok"]
    _make_stale(store, ZS_ID)  # divergence: installed != effective

    summary = ds_api.refresh_installed_from_bundle()

    assert summary["refreshed"] == [ZS_ID]
    assert _field_names(store, ZS_ID) == {"act", "suser"}  # the edited effective schema
    ev = _audit_events(audit)[0]["meta"]
    assert ev["refreshed"] == [ZS_ID] and "skipped_edited" not in ev


def test_pinned_source_is_skipped_and_reported(env) -> None:
    store, _, audit = env
    _install(*ZS)
    _make_stale(store, ZS_ID)
    store.set_pinned(ZS_ID, True, "1.5.8")

    summary = ds_api.refresh_installed_from_bundle()

    assert summary["skipped_pinned"] == [ZS_ID] and summary["refreshed"] == []
    assert _field_names(store, ZS_ID) == {"action", "act"}
    assert store.get(ZS_ID).is_pinned is True


def test_one_failure_does_not_stop_the_others(env, monkeypatch) -> None:
    store, _, audit = env
    _install(*ZS)
    _install(*FW)
    _make_stale(store, ZS_ID)
    _make_stale(store, FW_ID)
    real = ds_api._compose_from_user_yaml

    def flaky(yaml_ds, installed_by="user:operator"):
        if yaml_ds.dataset_name == ZS[2]:
            raise RuntimeError("boom")
        return real(yaml_ds, installed_by=installed_by)

    monkeypatch.setattr(ds_api, "_compose_from_user_yaml", flaky)

    summary = ds_api.refresh_installed_from_bundle()

    assert summary["failed"] == [ZS_ID]
    assert summary["refreshed"] == [FW_ID]
    assert _audit_events(audit)[0]["status"] == "failure"


def test_non_bundled_source_is_ignored(env) -> None:
    store, _, _ = env
    from usecase.data_sources_store import DataSource

    store.install(
        DataSource(id="TestVendor/TestVendor_1_0/testvendor_raw", pack_name="TestVendor",
                   rule_name="TestVendor_1_0", dataset_name="testvendor_raw"),
        fields=[DataSourceField(name="srcip", type="string")],
    )

    summary = ds_api.refresh_installed_from_bundle()

    assert summary == {"refreshed": [], "skipped_pinned": [], "failed": [], "unchanged": 0}
    assert _field_names(store, "TestVendor/TestVendor_1_0/testvendor_raw") == {"srcip"}


def test_replace_schema_refuses_an_uninstalled_source(env) -> None:
    store, _, _ = env
    from usecase.data_sources_store import DataSource

    ok = store.replace_schema(
        DataSource(id="Nope/Nope/nope_raw", pack_name="Nope", rule_name="Nope",
                   dataset_name="nope_raw"),
        [DataSourceField(name="x")],
    )
    assert ok is False
    assert store.get_with_schema("Nope/Nope/nope_raw") is None


# ── an edit/rollback reaches the served (installed) schema ──


def _served_fields(ds_id: str) -> dict:
    out = asyncio.run(ds_api.data_sources_get_schema(ds_id))
    assert out["ok"], out
    return {f["name"]: f for f in out["data_source"]["fields"]}


def test_edit_reaches_the_served_schema_immediately(env) -> None:
    store, _, _ = env
    _install(*ZS)
    out = ds_api._apply_edit(
        *ZS, fields=[{"name": "act", "type": "enum", "enum_values": ["Allowed", "Blocked", "Caution"], "example": "Allowed"},
                     {"name": "newcol", "type": "string", "example": "x"}],
        author="operator")
    assert out["ok"] and out["installed_schema_synced"] is True
    served = _served_fields(ZS_ID)
    assert set(served) == {"act", "newcol"}
    assert served["act"]["enum_values"] == ["Allowed", "Blocked", "Caution"]


def test_rollback_reaches_the_served_schema(env) -> None:
    store, _, _ = env
    _install(*ZS)
    ds_api._apply_edit(*ZS, fields=[{"name": "onlyone", "type": "string"}], author="operator")  # v2
    assert set(_served_fields(ZS_ID)) == {"onlyone"}
    out = ds_api._apply_rollback(*ZS, version=1, author="operator")  # back to bundle baseline
    assert out["ok"] and out["installed_schema_synced"] is True
    assert set(_served_fields(ZS_ID)) == _bundle_field_names(*ZS)


def test_edit_of_an_uninstalled_source_does_not_sync(env) -> None:
    store, _, _ = env  # ZS not installed
    out = ds_api._apply_edit(*ZS, how_to_use="notes", author="operator")
    assert out["ok"] and out["installed_schema_synced"] is False
    assert store.is_installed(ZS_ID) is False


def test_edit_syncs_even_when_pinned(env) -> None:
    # A pin gates only the automatic boot sync; an explicit edit outranks it.
    store, _, _ = env
    _install(*ZS)
    store.set_pinned(ZS_ID, True, "1.5.8")
    out = ds_api._apply_edit(*ZS, fields=[{"name": "act", "type": "string"}], author="operator")
    assert out["ok"] and out["installed_schema_synced"] is True
    assert set(_served_fields(ZS_ID)) == {"act"}
    assert store.get(ZS_ID).is_pinned is True  # pin preserved


def test_how_to_use_edit_reaches_installed_get_schema(env) -> None:
    # The store has no how_to_use column; get_schema enriches it from the
    # effective overlay so a guidance edit reaches an installed source too.
    store, _, _ = env
    _install(*ZS)
    out = ds_api._apply_edit(*ZS, how_to_use="OPERATOR-SPECIFIC BROKER NOTES", author="operator")
    assert out["ok"]
    got = asyncio.run(ds_api.data_sources_get_schema(ZS_ID))
    assert got["ok"] and got["data_source"]["how_to_use"] == "OPERATOR-SPECIFIC BROKER NOTES"


def test_installed_get_schema_carries_how_to_use_without_edits(env) -> None:
    store, _, _ = env
    _install(*ZS)
    got = asyncio.run(ds_api.data_sources_get_schema(ZS_ID))
    assert got["ok"] and got["data_source"].get("how_to_use")  # from the bundled YAML
