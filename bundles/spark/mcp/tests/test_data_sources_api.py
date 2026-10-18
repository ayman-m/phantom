"""Tests for the data sources REST + MCP tool surface.

The REST handlers and the MCP tools share most of their logic via
`_extract_and_compose_data_sources`. These tests cover both surfaces
by exercising the MCP tool entry points (`data_sources_list`,
`data_sources_get_schema`, `data_sources_install`) since they're plain
async functions easy to await + the REST handlers are thin wrappers.

# Mocking the cortex-content connector

The install path dynamically loads the cortex-content connector module
via `_load_cortex_content()`. Tests substitute a fake module with the
needed extraction functions stubbed; this avoids hitting GitHub during
unit tests and makes the install behavior deterministic.

# Store lifecycle

Each test creates a fresh DataSourcesStore on tmp_path + wires it via
`set_data_sources_store` before invoking the tools. Teardown clears
the singleton so tests stay isolated.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

# IMPORTANT: import via `api.X` and `usecase.X` (no `src.` prefix) so the
# test sees the SAME module instances as the production code. Python
# caches modules by import name, so `src.usecase.data_sources_store` and
# `usecase.data_sources_store` are TWO different module objects with
# independent `_singleton` state — using the same path as production
# avoids that cross-module singleton bug.
from api import data_sources as ds_api
from usecase.data_sources_store import (
    DataSourceField,
    DataSourcesStore,
    compose_data_source_id,
    set_data_sources_store,
)


# ─── Fixtures ─────────────────────────────────────────────────────


@pytest.fixture
def store(tmp_path: Path) -> DataSourcesStore:
    """Fresh DataSourcesStore wired as the process-global singleton.

    Teardown clears the singleton so other test files don't see this
    test's store (the singleton is module-level state, not per-test)."""
    s = DataSourcesStore(db_path=tmp_path / "ds.db")
    set_data_sources_store(s)
    yield s
    set_data_sources_store(None)


def _stub_cortex_module(
    *,
    schema_response: dict[str, Any] | None = None,
    logo_response: dict[str, Any] | None = None,
    pack_metadata: dict[str, Any] | None = None,
    raise_on_pack_metadata: Exception | None = None,
) -> Any:
    """Build a minimal stub of the cortex-content connector module with
    just the surfaces the install path touches.

    `schema_response` is what `cortex_extract_vendor_schema` returns.
    `logo_response` is what `cortex_extract_vendor_logo` returns.
    `pack_metadata` is what the inner `_get_client().get_file_json(...)`
    returns for the pack_metadata.json read.
    """
    mod = mock.MagicMock(name="cortex_content_stub")
    # The META set the install path queries
    mod._META_SCHEMA_FIELDS = {
        "_id", "_product", "_raw_log", "_vendor", "_time", "_collector_name",
    }

    async def _schema(pack_name: str, rule_name: str):
        return schema_response or {"ok": False, "error": "stub"}

    async def _logo(pack_name: str):
        return logo_response or {"ok": True, "logo_url": None, "logo_type": None}

    mod.cortex_extract_vendor_schema = _schema
    mod.cortex_extract_vendor_logo = _logo

    client = mock.MagicMock(name="github_client_stub")
    if raise_on_pack_metadata is not None:
        client.get_file_json.side_effect = raise_on_pack_metadata
    else:
        client.get_file_json.return_value = pack_metadata or {}
    mod._get_client = mock.MagicMock(return_value=client)

    return mod


@pytest.fixture
def stub_cortex(monkeypatch):
    """Inject a stub cortex-content module into the data_sources API
    layer's lazy-loader cache, so `_load_cortex_content()` returns
    our stub instead of trying to read /app/bundle paths."""

    def _set(stub_module):
        # Reset the cached module so subsequent calls re-resolve
        monkeypatch.setattr(ds_api, "_cortex_content_module", stub_module)

    return _set


# ─── data_sources_list ────────────────────────────────────────────


def test_list_returns_empty_when_store_empty(store: DataSourcesStore) -> None:
    out = asyncio.run(ds_api.data_sources_list())
    assert out["ok"] is True
    assert out["data_sources"] == []
    assert out["count"] == 0


def test_list_returns_installed_rows(store: DataSourcesStore) -> None:
    from usecase.data_sources_store import DataSource

    store.install(
        DataSource(
            id=compose_data_source_id("FortiGate", "FortiGate_1_3", "fortinet_fortigate_raw"),
            pack_name="FortiGate",
            rule_name="FortiGate_1_3",
            dataset_name="fortinet_fortigate_raw",
            field_count=11,
            non_meta_field_count=5,
        )
    )
    out = asyncio.run(ds_api.data_sources_list())
    assert out["ok"] is True
    assert out["count"] == 1
    assert out["data_sources"][0]["pack_name"] == "FortiGate"


def test_list_passes_filter_through(store: DataSourcesStore) -> None:
    from usecase.data_sources_store import DataSource

    store.install(DataSource(
        id="FortiGate/X/y", pack_name="FortiGate", rule_name="X", dataset_name="y",
    ))
    store.install(DataSource(
        id="F5APM/X/y", pack_name="F5APM", rule_name="X", dataset_name="y",
    ))
    out = asyncio.run(ds_api.data_sources_list(filter="fortigate"))
    assert out["count"] == 1
    assert out["data_sources"][0]["pack_name"] == "FortiGate"
    assert out["filter"] == "fortigate"


def test_list_returns_error_when_store_not_wired() -> None:
    """If main.py hasn't run yet (early-boot path), the tool fails
    gracefully with an ok=False envelope rather than crashing."""
    set_data_sources_store(None)
    out = asyncio.run(ds_api.data_sources_list())
    assert out["ok"] is False
    assert "not initialized" in out["error"]


# ─── data_sources_get_schema ──────────────────────────────────────


def test_get_schema_returns_not_found(store: DataSourcesStore) -> None:
    out = asyncio.run(ds_api.data_sources_get_schema(data_source_id="missing/id/foo"))
    assert out["ok"] is False
    assert out["error"] == "not found"
    assert out["data_source_id"] == "missing/id/foo"


def test_get_schema_returns_expanded(store: DataSourcesStore) -> None:
    from usecase.data_sources_store import DataSource

    ds = DataSource(
        id="F5APM/F5APM/f5_apm_raw",
        pack_name="F5APM", rule_name="F5APM", dataset_name="f5_apm_raw",
        is_rawlog_only=True, field_count=1, non_meta_field_count=0,
    )
    store.install(ds, fields=[DataSourceField(name="_raw_log", is_meta=True)])

    out = asyncio.run(ds_api.data_sources_get_schema(data_source_id=ds.id))
    assert out["ok"] is True
    body = out["data_source"]
    assert body["pack_name"] == "F5APM"
    assert body["is_rawlog_only"] is True
    assert "fields" in body and len(body["fields"]) == 1
    # xdm_mappings are not part of the serialized payload.
    # Data sources are vendor-neutral specs; XDM is Cortex-specific
    # and lives downstream of the wire format. The SQLite table is
    # still in place (orphaned) but nothing reads or writes it.
    assert "xdm_mappings" not in body


def test_get_schema_compact_strips_descriptions(store: DataSourcesStore) -> None:
    """compact=True returns only name/type/is_array/is_meta per field — the
    keys schema_override consumes — dropping verbose description + example so
    a 100+-field schema fits the agent's tool-result cap. Verbose
    (default) keeps descriptions for the UI."""
    from usecase.data_sources_store import DataSource

    ds = DataSource(
        id="S1/S1/sentinelone_xdr_raw",
        pack_name="S1", rule_name="S1", dataset_name="sentinelone_xdr_raw",
        is_rawlog_only=False, field_count=4, non_meta_field_count=3,
    )
    store.install(ds, fields=[
        DataSourceField(
            name="agentDetectionInfo", type="json", is_array=False,
            is_meta=False,
            description="A long verbose vendor description. " * 12,
            example="{}",
        ),
        DataSourceField(
            name="eventType", type="string", is_array=False, is_meta=False,
            description="Modeling-rule GATE — must equal Threat.",
            example="Threat",
        ),
        DataSourceField(
            name="tags", type="string", is_array=True, is_meta=False,
            description="an array field", example="a",
        ),
        DataSourceField(
            name="_log_type", type="string", is_array=False, is_meta=True,
            description="a meta field", example="x",
        ),
    ])

    # Default (verbose) keeps per-field descriptions.
    verbose = asyncio.run(ds_api.data_sources_get_schema(data_source_id=ds.id))
    assert verbose["ok"] is True
    vfields = verbose["data_source"]["fields"]
    assert any(f.get("description") for f in vfields)

    # compact=True strips description/example, keeps name/type, and
    # OMITS is_array/is_meta when False — only emitting them when True.
    compact = asyncio.run(
        ds_api.data_sources_get_schema(data_source_id=ds.id, compact=True)
    )
    assert compact["ok"] is True
    cfields = compact["data_source"]["fields"]
    assert len(cfields) == len(vfields)
    for f in cfields:
        assert set(f.keys()) <= {"name", "type", "is_array", "is_meta"}
        assert "description" not in f
        assert "example" not in f
    by_name = {f["name"]: f for f in cfields}
    assert {*by_name} == {"agentDetectionInfo", "eventType", "tags", "_log_type"}
    assert by_name["agentDetectionInfo"]["type"] == "json"
    assert by_name["eventType"]["type"] == "string"
    # Falsy is_array/is_meta are omitted entirely (lossless — the worker
    # defaults them False); truthy ones are preserved.
    assert "is_array" not in by_name["agentDetectionInfo"]
    assert "is_meta" not in by_name["agentDetectionInfo"]
    assert by_name["tags"]["is_array"] is True
    assert by_name["_log_type"]["is_meta"] is True


def test_get_schema_unknown_id_returns_not_found() -> None:
    # The tool does not hard-fail when the installed store is
    # unwired; it falls back to the YAML loader (source of truth). An id
    # that resolves to no YAML returns a clean "not found".
    set_data_sources_store(None)
    out = asyncio.run(ds_api.data_sources_get_schema(data_source_id="x/y/z"))
    assert out["ok"] is False
    assert "not found" in out["error"]


# ─── data_sources_install ─────────────────────────────────────────


def test_install_rejects_missing_args(store: DataSourcesStore) -> None:
    out = asyncio.run(
        ds_api.data_sources_install(pack_name="", rule_name="X")
    )
    assert out["ok"] is False
    assert "required" in out["error"]


def test_install_persists_extraction_to_store(
    store: DataSourcesStore, stub_cortex
) -> None:
    """Happy path: stub cortex-content returns a 2-dataset schema; install
    persists both datasets + their fields to the store.

    Uses a synthetic pack name (TestVendor) that has no bundled YAML on
    disk so the install path falls back to cortex-extracted fields. The
    YAML-canonical happy path is covered by
    `test_install_uses_yaml_when_present`.
    """
    stub = _stub_cortex_module(
        pack_metadata={
            "currentVersion": "1.2.0",
            "description": "TestVendor firewall logs",
            "supportedModules": ["xsiam"],
        },
        logo_response={
            "ok": True,
            "logo_url": "https://example.com/fg.svg",
            "logo_type": "svg",
        },
        schema_response={
            "ok": True,
            "pack_name": "TestVendor",
            "rule_name": "TestVendor_1_0",
            "datasets": {
                "testvendor_raw": {
                    "field_count": 3,
                    "non_meta_field_count": 2,
                    "is_rawlog_only": False,
                    "fields": [
                        {"name": "_raw_log", "type": "string", "is_array": False},
                        {"name": "srcip", "type": "string", "is_array": False},
                        {"name": "dstip", "type": "string", "is_array": False},
                    ],
                },
            },
        },
    )
    stub_cortex(stub)

    out = asyncio.run(
        ds_api.data_sources_install(pack_name="TestVendor", rule_name="TestVendor_1_0")
    )
    assert out["ok"] is True
    assert out["datasets_installed"] == 1
    assert out["fields_count"] == 3
    assert out["pack_version"] == "1.2.0"
    # Verify persistence
    assert store.count() == 1
    ds_id = "TestVendor/TestVendor_1_0/testvendor_raw"
    got = store.get(ds_id)
    assert got is not None
    assert got.installed_by == "agent"  # MCP tool path attribution
    assert got.logo_url == "https://example.com/fg.svg"
    assert got.pack_version == "1.2.0"
    assert got.supported_modules == ["xsiam"]


def test_install_with_specific_dataset_filters(
    store: DataSourcesStore, stub_cortex
) -> None:
    """When the rule has multiple datasets and dataset_name is provided,
    only that dataset is installed."""
    stub = _stub_cortex_module(
        pack_metadata={"description": "Multi-DS pack"},
        schema_response={
            "ok": True,
            "datasets": {
                "ds_one": {
                    "field_count": 2, "non_meta_field_count": 1,
                    "is_rawlog_only": False,
                    "fields": [
                        {"name": "_raw_log", "type": "string", "is_array": False},
                        {"name": "field_a", "type": "string", "is_array": False},
                    ],
                },
                "ds_two": {
                    "field_count": 2, "non_meta_field_count": 1,
                    "is_rawlog_only": False,
                    "fields": [
                        {"name": "_raw_log", "type": "string", "is_array": False},
                        {"name": "field_b", "type": "string", "is_array": False},
                    ],
                },
            },
        },
    )
    stub_cortex(stub)

    out = asyncio.run(ds_api.data_sources_install(
        pack_name="MultiPack", rule_name="MultiRule", dataset_name="ds_two",
    ))
    assert out["ok"] is True
    assert out["datasets_installed"] == 1
    assert out["datasets_in_rule"] == 2
    assert out["data_source_ids"] == ["MultiPack/MultiRule/ds_two"]
    # Confirm only ds_two persisted
    assert store.is_installed("MultiPack/MultiRule/ds_one") is False
    assert store.is_installed("MultiPack/MultiRule/ds_two") is True


def test_install_rejects_unknown_dataset(
    store: DataSourcesStore, stub_cortex
) -> None:
    """dataset_name not in the rule's schema → ok=False with the
    available list spelled out (helps the agent self-correct)."""
    stub = _stub_cortex_module(
        pack_metadata={},
        schema_response={
            "ok": True,
            "datasets": {
                "real_dataset": {
                    "field_count": 1, "non_meta_field_count": 0,
                    "is_rawlog_only": True, "fields": [],
                },
            },
        },
    )
    stub_cortex(stub)

    out = asyncio.run(ds_api.data_sources_install(
        pack_name="X", rule_name="X", dataset_name="nonexistent_dataset",
    ))
    assert out["ok"] is False
    assert "nonexistent_dataset" in out["error"]
    assert "real_dataset" in out["error"]
    assert store.count() == 0


def test_install_is_idempotent(store: DataSourcesStore, stub_cortex) -> None:
    """Re-installing the same data source replaces (count stays 1)."""
    stub = _stub_cortex_module(
        pack_metadata={"currentVersion": "1.0"},
        schema_response={
            "ok": True,
            "datasets": {
                "ds": {
                    "field_count": 1, "non_meta_field_count": 0,
                    "is_rawlog_only": True,
                    "fields": [{"name": "_raw_log", "type": "string", "is_array": False}],
                },
            },
        },
    )
    stub_cortex(stub)

    asyncio.run(ds_api.data_sources_install(pack_name="P", rule_name="R"))
    asyncio.run(ds_api.data_sources_install(pack_name="P", rule_name="R"))
    assert store.count() == 1


def test_install_classifies_meta_fields_correctly(
    store: DataSourcesStore, stub_cortex
) -> None:
    """The install path should mark the 6 meta fields as is_meta=True
    + vendor fields as is_meta=False, using the connector's
    _META_SCHEMA_FIELDS as the source of truth."""
    stub = _stub_cortex_module(
        pack_metadata={},
        schema_response={
            "ok": True,
            "datasets": {
                "ds": {
                    "field_count": 4, "non_meta_field_count": 1,
                    "is_rawlog_only": False,
                    "fields": [
                        {"name": "_id", "type": "string", "is_array": False},
                        {"name": "_raw_log", "type": "string", "is_array": False},
                        {"name": "_vendor", "type": "string", "is_array": False},
                        {"name": "srcip", "type": "string", "is_array": False},
                    ],
                },
            },
        },
    )
    stub_cortex(stub)

    asyncio.run(ds_api.data_sources_install(pack_name="P", rule_name="R"))
    expanded = store.get_with_schema("P/R/ds")
    assert expanded is not None
    by_name = {f.name: f for f in expanded.fields}
    assert by_name["_id"].is_meta is True
    assert by_name["_raw_log"].is_meta is True
    assert by_name["_vendor"].is_meta is True
    assert by_name["srcip"].is_meta is False  # vendor field


def test_install_returns_clean_error_on_extraction_failure(
    store: DataSourcesStore, stub_cortex
) -> None:
    stub = _stub_cortex_module(
        pack_metadata={},
        schema_response={"ok": False, "error": "schema.json not found"},
    )
    stub_cortex(stub)

    out = asyncio.run(ds_api.data_sources_install(pack_name="X", rule_name="Y"))
    assert out["ok"] is False
    assert "schema extraction failed" in out["error"]
    assert "schema.json not found" in out["error"]
    assert store.count() == 0


def test_install_handles_missing_pack_metadata(
    store: DataSourcesStore, stub_cortex
) -> None:
    """If pack_metadata.json is missing → ValueError → ok=False envelope."""
    from api.data_sources import _load_cortex_content  # noqa: F401

    stub = _stub_cortex_module(
        raise_on_pack_metadata=Exception("404 not found"),
    )
    stub_cortex(stub)

    out = asyncio.run(ds_api.data_sources_install(pack_name="X", rule_name="Y"))
    assert out["ok"] is False
    assert "pack_metadata.json" in out["error"]
    assert store.count() == 0


def test_install_returns_error_when_store_not_wired(stub_cortex) -> None:
    set_data_sources_store(None)
    out = asyncio.run(ds_api.data_sources_install(pack_name="P", rule_name="R"))
    assert out["ok"] is False
    assert "not initialized" in out["error"]


def test_install_empty_dataset_list_errors_clean(
    store: DataSourcesStore, stub_cortex
) -> None:
    stub = _stub_cortex_module(
        pack_metadata={},
        schema_response={"ok": True, "datasets": {}},
    )
    stub_cortex(stub)

    out = asyncio.run(ds_api.data_sources_install(pack_name="X", rule_name="Y"))
    assert out["ok"] is False
    assert "no datasets" in out["error"]


# ── field-count scalars always match the payload's fields[] ──


def test_sync_field_counts_matches_fields_array() -> None:
    """The stat-tile scalars must be derived from the payload's own fields[],
    so the drawer tile can never disagree with the table below it."""
    payload = {
        # Stale scalars from a different source — must be overwritten.
        "field_count": 7,
        "non_meta_field_count": 7,
        "fields": [
            {"name": "a", "is_meta": False},
            {"name": "b", "is_meta": False},
            {"name": "_time", "is_meta": True},
            {"name": "c"},  # missing is_meta → treated as non-meta
        ],
    }
    ds_api._sync_field_counts_to_fields(payload)
    assert payload["field_count"] == 4  # len(fields)
    assert payload["non_meta_field_count"] == 3  # a, b, c (not _time)


def test_sync_field_counts_empty_fields() -> None:
    payload = {"field_count": 99, "non_meta_field_count": 42, "fields": []}
    ds_api._sync_field_counts_to_fields(payload)
    assert payload["field_count"] == 0
    assert payload["non_meta_field_count"] == 0


def test_sync_field_counts_missing_fields_key() -> None:
    payload: dict = {"field_count": 99}
    ds_api._sync_field_counts_to_fields(payload)
    assert payload["field_count"] == 0
    assert payload["non_meta_field_count"] == 0


def test_live_field_counts_keyed_by_composite_id() -> None:
    """Field-count overlay keys must match the installed rows' ids.

    `_live_field_counts_by_id()` must key by the COMPOSITE id
    ("pack/rule/dataset", == the store's r.id), NOT the loader's SHORT id
    ("ServiceNow"). Keyed by the short id, the overlay map would never match
    any installed row and the InstalledCard badge + vendor enrichment would
    silently fall back to the stale snapshot. Reads the real bundle tree
    (ServiceNow, unversioned).
    """
    counts = ds_api._live_field_counts_by_id()
    composite = compose_data_source_id(
        "ServiceNow", "ServiceNow", "servicenow_servicenow_raw"
    )
    # Composite key present (matches the store id format)...
    assert composite in counts, "counts must be keyed by the composite id"
    fc, nm = counts[composite]
    assert fc > 1 and nm > 1  # real ServiceNow YAML has dozens of fields
    # ...and the SHORT id must NOT be a key.
    assert "ServiceNow" not in counts


# ── _apply_edit: baseline + version + validation ──

SN = "ServiceNow/ServiceNow/servicenow_servicenow_raw"


@pytest.fixture
def vstore(tmp_path):
    """Wire a fresh version store + invalidate the (real) loader so its
    overlay picks up edits. Teardown unwires + invalidates."""
    from usecase import data_source_versions_store as vs
    from usecase.data_sources_yaml_loader import get_data_sources_yaml_loader

    s = vs.DataSourceVersionsStore(db_path=tmp_path / "v.db")
    vs.set_data_source_versions_store(s)
    get_data_sources_yaml_loader().invalidate()
    yield s
    vs.set_data_source_versions_store(None)
    get_data_sources_yaml_loader().invalidate()


def test_apply_edit_baseline_then_version(vstore):
    out = ds_api._apply_edit(
        "ServiceNow", "ServiceNow", "servicenow_servicenow_raw",
        how_to_use="EDITED VIA TEST", note="t", author="operator",
    )
    assert out["ok"] and out["version"] == 2
    versions = vstore.list_versions(SN)
    assert len(versions) == 2 and versions[0]["author"] == "bundle-baseline"
    # loader overlay now serves the edit
    from usecase.data_sources_yaml_loader import get_data_sources_yaml_loader
    ds = get_data_sources_yaml_loader().get_by_3tuple(
        "ServiceNow", "ServiceNow", "servicenow_servicenow_raw"
    )
    assert ds.how_to_use == "EDITED VIA TEST"


def test_apply_edit_rejects_duplicate_fields(vstore):
    out = ds_api._apply_edit(
        "ServiceNow", "ServiceNow", "servicenow_servicenow_raw",
        fields=[{"name": "a", "type": "string"}, {"name": "a", "type": "string"}],
        author="operator",
    )
    assert out["ok"] is False and "duplicate" in out["error"].lower()
    assert vstore.list_versions(SN) == []  # no snapshot on rejection


def test_apply_edit_unknown_source(vstore):
    out = ds_api._apply_edit("Nope", "Nope", "nope_raw", how_to_use="x", author="operator")
    assert out["ok"] is False and "not found" in out["error"].lower()


def test_apply_edit_second_edit_increments(vstore):
    ds_api._apply_edit("ServiceNow", "ServiceNow", "servicenow_servicenow_raw",
                       how_to_use="E1", author="operator")
    out = ds_api._apply_edit("ServiceNow", "ServiceNow", "servicenow_servicenow_raw",
                             how_to_use="E2", author="agent")
    assert out["version"] == 3  # v1 baseline, v2 E1, v3 E2


# ── data_sources_edit agent tool (author="agent") ──


def test_data_sources_edit_tool_records_agent_author(vstore):
    out = asyncio.run(ds_api.data_sources_edit(
        pack_name="ServiceNow", rule_name="ServiceNow",
        dataset_name="servicenow_servicenow_raw", how_to_use="AGENT EDIT",
    ))
    assert out["ok"] and out["version"] == 2
    versions = vstore.list_versions(SN)
    assert versions[0]["author"] == "bundle-baseline"
    assert versions[1]["author"] == "agent"  # the tool fixes author=agent


def test_data_sources_edit_tool_rejects_duplicate_fields(vstore):
    out = asyncio.run(ds_api.data_sources_edit(
        pack_name="ServiceNow", rule_name="ServiceNow",
        dataset_name="servicenow_servicenow_raw",
        fields=[{"name": "x", "type": "string"}, {"name": "x", "type": "string"}],
    ))
    assert out["ok"] is False and "duplicate" in out["error"].lower()


# ── _apply_rollback: non-destructive version restore ──


def test_apply_rollback_non_destructive(vstore):
    ds_api._apply_edit("ServiceNow", "ServiceNow", "servicenow_servicenow_raw",
                       how_to_use="E1", author="operator")
    ds_api._apply_edit("ServiceNow", "ServiceNow", "servicenow_servicenow_raw",
                       how_to_use="E2", author="operator")
    out = ds_api._apply_rollback("ServiceNow", "ServiceNow", "servicenow_servicenow_raw",
                                 version=1, author="operator")
    assert out["ok"] and out["version"] == 4  # v1 base, v2 E1, v3 E2, v4 = rollback-to-v1
    versions = vstore.list_versions(SN)
    assert [v["version"] for v in versions] == [1, 2, 3, 4]  # history preserved
    # v4 content == v1 (the pristine baseline)
    assert vstore.get_version(SN, 4)["yaml_snapshot"] == vstore.get_version(SN, 1)["yaml_snapshot"]


def test_apply_rollback_unknown_version(vstore):
    ds_api._apply_edit("ServiceNow", "ServiceNow", "servicenow_servicenow_raw",
                       how_to_use="E1", author="operator")
    out = ds_api._apply_rollback("ServiceNow", "ServiceNow", "servicenow_servicenow_raw",
                                 version=99, author="operator")
    assert out["ok"] is False and "not found" in out["error"].lower()


def test_apply_rollback_no_versions(vstore):
    # never edited → nothing to roll back to
    out = ds_api._apply_rollback("ServiceNow", "ServiceNow", "servicenow_servicenow_raw",
                                 version=1, author="operator")
    assert out["ok"] is False and "no versions" in out["error"].lower()


# ── list_versions + rollback agent tools ──


def test_list_versions_tool(vstore):
    ds_api._apply_edit("ServiceNow", "ServiceNow", "servicenow_servicenow_raw",
                       how_to_use="E1", author="operator")
    out = asyncio.run(ds_api.data_sources_list_versions(
        pack_name="ServiceNow", rule_name="ServiceNow",
        dataset_name="servicenow_servicenow_raw"))
    assert out["ok"] and [v["version"] for v in out["versions"]] == [1, 2]
    assert out["versions"][0]["author"] == "bundle-baseline"
    assert out["versions"][1]["is_current"] is True
    # metadata-only: yaml_snapshot is NOT in the list payload
    assert "yaml_snapshot" not in out["versions"][0]


def test_list_versions_tool_empty(vstore):
    out = asyncio.run(ds_api.data_sources_list_versions(
        pack_name="ServiceNow", rule_name="ServiceNow",
        dataset_name="servicenow_servicenow_raw"))
    assert out["ok"] and out["versions"] == []


def test_rollback_tool_records_agent(vstore):
    ds_api._apply_edit("ServiceNow", "ServiceNow", "servicenow_servicenow_raw",
                       how_to_use="E1", author="operator")
    out = asyncio.run(ds_api.data_sources_rollback(
        pack_name="ServiceNow", rule_name="ServiceNow",
        dataset_name="servicenow_servicenow_raw", version=1))
    assert out["ok"] and out["version"] == 3
    assert vstore.list_versions(SN)[-1]["author"] == "agent"


# ── _resolve_export_content: export by version ──


def test_export_content_current_after_edit(vstore):
    ds_api._apply_edit("ServiceNow", "ServiceNow", "servicenow_servicenow_raw",
                       how_to_use="EXPORT-CUR", author="operator")
    content, fname, err = ds_api._resolve_export_content(
        "ServiceNow", "ServiceNow", "servicenow_servicenow_raw", version=None)
    assert err is None and content is not None and "EXPORT-CUR" in content
    assert fname == "servicenow_servicenow_raw.yaml"


def test_export_content_specific_version(vstore):
    ds_api._apply_edit("ServiceNow", "ServiceNow", "servicenow_servicenow_raw",
                       how_to_use="V2TEXT", author="operator")
    # v1 = baseline (pristine original), v2 = the edit
    content, fname, err = ds_api._resolve_export_content(
        "ServiceNow", "ServiceNow", "servicenow_servicenow_raw", version=1)
    assert err is None and content is not None and "V2TEXT" not in content
    assert fname == "servicenow_servicenow_raw.v1.yaml"


def test_export_content_unknown_version(vstore):
    ds_api._apply_edit("ServiceNow", "ServiceNow", "servicenow_servicenow_raw",
                       how_to_use="X", author="operator")
    content, fname, err = ds_api._resolve_export_content(
        "ServiceNow", "ServiceNow", "servicenow_servicenow_raw", version=99)
    assert content is None and err == "version_not_found"


def test_export_content_unedited_reads_file(vstore):
    content, fname, err = ds_api._resolve_export_content(
        "ServiceNow", "ServiceNow", "servicenow_servicenow_raw", version=None)
    assert err is None and content is not None and "ServiceNow" in content
    assert fname == "servicenow_servicenow_raw.yaml"


# ── schema surfaces fall back to the bundled YAML ──
# okta_sso_raw has a bundled YAML but cortex-content's Okta pack only
# enumerates okta_okta_raw; uninstalled, its drawer would 404 without the
# fallback. The schema surfaces must resolve it via the YAML loader (source of truth, like the
# catalog), not just installed-store → cortex.


def test_yaml_ds_to_schema_payload_shape():
    from usecase.data_sources_yaml_loader import get_data_sources_yaml_loader

    yaml_ds = get_data_sources_yaml_loader().get_by_3tuple(
        "Okta", "OktaModelingRules", "okta_sso_raw")
    assert yaml_ds is not None, "okta_sso_raw bundled YAML must exist"
    payload = ds_api._yaml_ds_to_schema_payload(
        yaml_ds, "Okta/OktaModelingRules/okta_sso_raw", is_preview=True)
    assert payload["id"] == "Okta/OktaModelingRules/okta_sso_raw"
    assert payload["dataset_name"] == "okta_sso_raw"
    assert payload["is_preview"] is True
    assert payload["fields"] and len(payload["fields"]) == payload["field_count"]
    assert all("name" in f and "type" in f for f in payload["fields"])


def test_get_schema_yaml_fallback_for_uninstalled_dataset():
    out = asyncio.run(
        ds_api.data_sources_get_schema("Okta/OktaModelingRules/okta_sso_raw"))
    assert out["ok"], out
    ds = out["data_source"]
    assert ds["dataset_name"] == "okta_sso_raw"
    assert len(ds["fields"]) > 0
    # sibling primary dataset still resolves
    out2 = asyncio.run(
        ds_api.data_sources_get_schema("Okta/OktaModelingRules/okta_okta_raw"))
    assert out2["ok"] and len(out2["data_source"]["fields"]) > 0


# ── install persists every YAML field attribute ──
# A gate field's `example` is the only value its rule accepts, so the YAML
# install path must persist it; otherwise a freshly installed gated source
# would serve an empty gate until the next boot's backfill.


def _stored(store: DataSourcesStore, ds_id: str) -> dict[str, DataSourceField]:
    got = store.get_with_schema(ds_id)
    assert got is not None, ds_id
    return {f.name: f for f in got.fields}


@pytest.mark.parametrize("pack,rule,dataset", [
    # gated: `cat` picks the modeling block
    ("FortinetFortiwebVM", "FortinetFortiwebVM", "fortinet_fortiweb_raw"),
    # enum-heavy: act / app / requestMethod / outcome
    ("Zscaler", "ZscalerModelingRule", "zscaler_nssweblog_raw"),
])
def test_yaml_install_persists_example_gate_and_enum(
    store: DataSourcesStore, pack: str, rule: str, dataset: str,
) -> None:
    from usecase.data_sources_yaml_loader import get_data_sources_yaml_loader

    yaml_ds = get_data_sources_yaml_loader().get_by_3tuple(pack, rule, dataset)
    assert yaml_ds is not None
    out = asyncio.run(ds_api.data_sources_install(
        pack_name=pack, rule_name=rule, dataset_name=dataset))
    assert out["ok"] is True, out

    stored = _stored(store, compose_data_source_id(pack, rule, dataset))
    for f in yaml_ds.fields:
        row = stored[f["name"]]
        want_example = "" if f.get("example") is None else str(f["example"])
        assert row.example == want_example, f["name"]
        assert row.is_gate == bool(f.get("is_gate")), f["name"]
        assert row.enum_values == (list(f["enum_values"]) if f.get("enum_values") else None), f["name"]


def test_yaml_install_serves_the_gate_example(store: DataSourcesStore) -> None:
    """The observed failure, end to end: FortiWeb's `cat` gate served empty."""
    asyncio.run(ds_api.data_sources_install(
        pack_name="FortinetFortiwebVM", rule_name="FortinetFortiwebVM",
        dataset_name="fortinet_fortiweb_raw"))
    cat = _stored(store, "FortinetFortiwebVM/FortinetFortiwebVM/fortinet_fortiweb_raw")["cat"]
    assert cat.is_gate is True
    assert cat.example == "trafficlog"


def test_cortex_path_yaml_branch_persists_gate_and_enum(
    store: DataSourcesStore, stub_cortex, monkeypatch,
) -> None:
    """The cortex-extraction path's YAML branch dropped is_gate/enum_values."""
    stub_cortex(_stub_cortex_module(
        pack_metadata={"currentVersion": "1.0.0", "supportedModules": ["xsiam"]},
        schema_response={
            "ok": True, "pack_name": "TestVendor", "rule_name": "TestVendor_1_0",
            "datasets": {"testvendor_raw": {
                "field_count": 1, "non_meta_field_count": 1, "is_rawlog_only": False,
                "fields": [{"name": "kind", "type": "string", "is_array": False}],
            }},
        },
    ))
    monkeypatch.setattr(ds_api, "_yaml_field_records", lambda *_: [
        {"name": "kind", "type": "string", "is_gate": True, "example": "traffic"},
        {"name": "verdict", "type": "enum", "enum_values": ["allow", "deny"], "example": "allow"},
        {"name": "_raw_log", "type": "string"},
    ])

    out = asyncio.run(ds_api.data_sources_install(
        pack_name="TestVendor", rule_name="TestVendor_1_0"))
    assert out["ok"] is True, out

    stored = _stored(store, "TestVendor/TestVendor_1_0/testvendor_raw")
    assert (stored["kind"].is_gate, stored["kind"].example) == (True, "traffic")
    assert stored["verdict"].enum_values == ["allow", "deny"]
    assert stored["verdict"].example == "allow"
    assert stored["_raw_log"].is_meta is True  # cortex classifier still applies


# ── installed sources serve gates + enums ──
# to_dict() must carry both, so the compact schema the agent passes as
# schema_override keeps every gate and enum.


@pytest.mark.parametrize("compact", [True, False])
def test_installed_schema_serves_gate_and_enum(store: DataSourcesStore, compact: bool) -> None:
    for pack, rule, dataset in [
        ("FortinetFortiwebVM", "FortinetFortiwebVM", "fortinet_fortiweb_raw"),
        ("Zscaler", "ZscalerModelingRule", "zscaler_nssweblog_raw"),
    ]:
        asyncio.run(ds_api.data_sources_install(
            pack_name=pack, rule_name=rule, dataset_name=dataset))
        assert store.is_installed(compose_data_source_id(pack, rule, dataset))

    fw = asyncio.run(ds_api.data_sources_get_schema(
        "FortinetFortiwebVM/FortinetFortiwebVM/fortinet_fortiweb_raw", compact=compact))
    cat = {f["name"]: f for f in fw["data_source"]["fields"]}["cat"]
    assert cat["is_gate"] is True
    assert cat["example"] == "trafficlog"

    zs = asyncio.run(ds_api.data_sources_get_schema(
        "Zscaler/ZscalerModelingRule/zscaler_nssweblog_raw", compact=compact))
    act = {f["name"]: f for f in zs["data_source"]["fields"]}["act"]
    assert act["enum_values"] == ["Allowed", "Blocked"]


def test_installed_and_yaml_payloads_agree_on_field_keys(store: DataSourcesStore) -> None:
    """The two paths feed the same consumers; their field shapes must match."""
    ds_id = "Zscaler/ZscalerModelingRule/zscaler_nssweblog_raw"
    before = asyncio.run(ds_api.data_sources_get_schema(ds_id))  # uninstalled → YAML path
    asyncio.run(ds_api.data_sources_install(
        pack_name="Zscaler", rule_name="ZscalerModelingRule", dataset_name="zscaler_nssweblog_raw"))
    after = asyncio.run(ds_api.data_sources_get_schema(ds_id))   # installed → store path
    yaml_keys = set(before["data_source"]["fields"][0])
    store_keys = set(after["data_source"]["fields"][0])
    assert {"is_gate", "enum_values", "example"} <= yaml_keys & store_keys


# ── `delivery` (syslog | http) reaches the API surfaces ──


def test_yaml_ds_to_schema_payload_carries_delivery():
    from usecase.data_sources_yaml_loader import get_data_sources_yaml_loader

    ldr = get_data_sources_yaml_loader()
    http = ldr.get_by_3tuple("Okta", "OktaHttpCollector", "okta_sso_raw")
    sysl = ldr.get_by_3tuple("Okta", "OktaModelingRules", "okta_sso_raw")
    assert http is not None and sysl is not None
    p_http = ds_api._yaml_ds_to_schema_payload(
        http, "Okta/OktaHttpCollector/okta_sso_raw", is_preview=True)
    p_sys = ds_api._yaml_ds_to_schema_payload(
        sysl, "Okta/OktaModelingRules/okta_sso_raw", is_preview=True)
    assert p_http["delivery"] == "http"
    assert p_sys["delivery"] == "syslog"
    # compact mode keeps it (agent reads the compact payload)
    assert ds_api._compact_schema_payload(p_http)["delivery"] == "http"


def test_get_schema_yaml_path_exposes_delivery():
    out = asyncio.run(
        ds_api.data_sources_get_schema("Okta/OktaHttpCollector/okta_sso_raw", compact=True))
    assert out["ok"], out
    assert out["data_source"]["delivery"] == "http"
    out2 = asyncio.run(
        ds_api.data_sources_get_schema("Okta/OktaModelingRules/okta_sso_raw", compact=True))
    assert out2["data_source"]["delivery"] == "syslog"


def test_installed_schema_overlays_delivery_from_yaml(store: DataSourcesStore) -> None:
    # Install the HTTP YAML, then read the schema through the store path:
    # the store has no `delivery` column, so it must be overlaid from the YAML.
    inst = asyncio.run(ds_api.data_sources_install(
        "Okta", "OktaHttpCollector", "okta_sso_raw"))
    assert inst["ok"], inst
    out = asyncio.run(ds_api.data_sources_get_schema(
        "Okta/OktaHttpCollector/okta_sso_raw"))
    assert out["ok"], out
    assert out["data_source"]["delivery"] == "http"


def test_installed_as_vendors_exposes_delivery(store: DataSourcesStore) -> None:
    for rule in ("OktaHttpCollector", "OktaModelingRules"):
        inst = asyncio.run(ds_api.data_sources_install("Okta", rule, "okta_sso_raw"))
        assert inst["ok"], inst
    out = asyncio.run(ds_api.data_sources_installed_as_vendors())
    assert out["ok"], out
    by_id = {v["data_source_id"]: v for v in out["vendors"]}
    http = by_id["Okta/OktaHttpCollector/okta_sso_raw"]
    sysl = by_id["Okta/OktaModelingRules/okta_sso_raw"]
    assert http["delivery"] == "http"
    assert http["formats"] == ["JSON"]
    assert sysl["delivery"] == "syslog"
    assert sysl["formats"] == ["SYSLOG", "CEF", "JSON"]


def test_installed_as_vendors_exposes_wec_delivery(store: DataSourcesStore) -> None:
    for rule in ("MicrosoftWindowsEventsWEC", "MicrosoftWindowsEvents"):
        inst = asyncio.run(
            ds_api.data_sources_install(
                "MicrosoftWindowsEvents", rule, "microsoft_windows_raw"
            )
        )
        assert inst["ok"], inst
    out = asyncio.run(ds_api.data_sources_installed_as_vendors())
    assert out["ok"], out
    by_id = {v["data_source_id"]: v for v in out["vendors"]}
    wec = by_id["MicrosoftWindowsEvents/MicrosoftWindowsEventsWEC/microsoft_windows_raw"]
    sysl = by_id["MicrosoftWindowsEvents/MicrosoftWindowsEvents/microsoft_windows_raw"]
    assert wec["delivery"] == "wec"
    assert wec["formats"] == ["WINEVENT"]
    assert sysl["delivery"] == "syslog"
    assert sysl["formats"] == ["SYSLOG", "CEF", "JSON"]


def test_get_schema_yaml_path_exposes_wec_delivery():
    out = asyncio.run(
        ds_api.data_sources_get_schema(
            "MicrosoftADFS/MicrosoftADFSWEC/microsoft_adfs_raw", compact=True
        )
    )
    assert out["ok"], out
    assert out["data_source"]["delivery"] == "wec"
    out2 = asyncio.run(
        ds_api.data_sources_get_schema(
            "MicrosoftADFS/MicrosoftADFS/microsoft_adfs_raw", compact=True
        )
    )
    assert out2["data_source"]["delivery"] == "syslog"


def test_apply_edit_preserves_delivery(vstore):
    out = ds_api._apply_edit(
        "Okta", "OktaHttpCollector", "okta_sso_raw",
        how_to_use="EDITED VIA TEST", note="t", author="operator",
    )
    assert out["ok"], out
    from usecase.data_sources_yaml_loader import get_data_sources_yaml_loader
    ds = get_data_sources_yaml_loader().get_by_3tuple(
        "Okta", "OktaHttpCollector", "okta_sso_raw")
    assert ds.how_to_use == "EDITED VIA TEST"
    assert ds.delivery == "http"
    # the stored version's content carries the key too
    content = ds_api._resolve_export_content(
        "Okta", "OktaHttpCollector", "okta_sso_raw", version=out["version"])[0]
    assert content is not None and "delivery: http" in content
