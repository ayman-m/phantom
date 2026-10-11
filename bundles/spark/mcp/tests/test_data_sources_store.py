"""Tests for DataSourcesStore — install state.

Coverage:
  - schema initialization on a fresh tmp_path
  - install records the row + field rows + xdm_mapping rows
  - install is idempotent (re-installing replaces, doesn't duplicate)
  - foreign-key cascade: deleting a data source removes dependents
  - list returns ordered rows
  - list with filter does case-insensitive LIKE across pack/dataset/rule/desc
  - get returns a single row; get_with_schema returns the expanded form
  - get_with_schema returns None for missing id
  - pin/unpin updates the row + clears pinned_version on unpin
  - supported_modules JSON round-trips
  - rawlog-only data sources persist with field_count=1, non_meta=0
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.usecase.data_sources_store import (
    DataSource,
    DataSourceField,
    DataSourceXdmMapping,
    DataSourcesStore,
    compose_data_source_id,
)


# ── Helpers ───────────────────────────────────────────────────────


def _fortigate_data_source() -> DataSource:
    return DataSource(
        id=compose_data_source_id("FortiGate", "FortiGate_1_3", "fortinet_fortigate_raw"),
        pack_name="FortiGate",
        rule_name="FortiGate_1_3",
        dataset_name="fortinet_fortigate_raw",
        pack_version="1.2.0",
        is_rawlog_only=False,
        field_count=11,
        non_meta_field_count=5,
        supported_modules=["xsiam", "xsoar"],
        pack_description="FortiGate firewall logs",
        logo_url="https://raw.githubusercontent.com/demisto/content/master/Packs/FortiGate/Integrations/FortiGate/FortiGate_dark.svg",
        logo_type="svg",
        installed_by="user:operator",
        source_revision="abc1234",
    )


def _fortigate_fields() -> list[DataSourceField]:
    """Approximate FortiGate fields — meta + a few vendor fields."""
    return [
        DataSourceField(name="_id", type="string", is_array=False, is_meta=True),
        DataSourceField(name="_time", type="datetime", is_array=False, is_meta=True),
        DataSourceField(name="_raw_log", type="string", is_array=False, is_meta=True),
        DataSourceField(name="_vendor", type="string", is_array=False, is_meta=True),
        DataSourceField(name="_product", type="string", is_array=False, is_meta=True),
        DataSourceField(name="_collector_name", type="string", is_array=False, is_meta=True),
        DataSourceField(name="srcip", type="string", is_array=False, is_meta=False),
        DataSourceField(name="dstip", type="string", is_array=False, is_meta=False),
        DataSourceField(name="action", type="string", is_array=False, is_meta=False),
        DataSourceField(name="user", type="string", is_array=False, is_meta=False),
        DataSourceField(name="groups", type="string", is_array=True, is_meta=False),
    ]


def _f5apm_rawlog_data_source() -> DataSource:
    return DataSource(
        id=compose_data_source_id("F5APM", "F5APM", "f5_apm_raw"),
        pack_name="F5APM",
        rule_name="F5APM",
        dataset_name="f5_apm_raw",
        is_rawlog_only=True,
        field_count=1,
        non_meta_field_count=0,
        supported_modules=["xsiam"],
        installed_by="agent",
    )


# ── Schema init + lifecycle ───────────────────────────────────────


def test_init_creates_empty_tables(tmp_path: Path) -> None:
    """Fresh store has all 3 tables but zero rows."""
    s = DataSourcesStore(db_path=tmp_path / "ds.db")
    assert s.count() == 0
    assert s.list() == []


def test_install_returns_true_on_first_insert(tmp_path: Path) -> None:
    s = DataSourcesStore(db_path=tmp_path / "ds.db")
    ds = _fortigate_data_source()
    was_new = s.install(ds, fields=_fortigate_fields())
    assert was_new is True
    assert s.count() == 1
    assert s.is_installed(ds.id) is True


def test_install_returns_false_on_reinstall(tmp_path: Path) -> None:
    """Idempotent re-install: returns False (not new), still post-condition
    holds (the row + dependents reflect the new payload)."""
    s = DataSourcesStore(db_path=tmp_path / "ds.db")
    ds = _fortigate_data_source()
    s.install(ds, fields=_fortigate_fields())
    # Second install with slightly different metadata
    ds.pack_description = "FortiGate firewall logs (rev 2)"
    was_new = s.install(ds, fields=_fortigate_fields())
    assert was_new is False
    assert s.count() == 1  # NOT 2 — replaced not duplicated
    got = s.get(ds.id)
    assert got is not None
    assert got.pack_description == "FortiGate firewall logs (rev 2)"


# ── Fields persistence ────────────────────────────────────────────


def test_install_persists_all_fields(tmp_path: Path) -> None:
    """The 11 fields from _fortigate_fields land in data_source_fields
    and round-trip with is_array + is_meta preserved."""
    s = DataSourcesStore(db_path=tmp_path / "ds.db")
    ds = _fortigate_data_source()
    s.install(ds, fields=_fortigate_fields())

    expanded = s.get_with_schema(ds.id)
    assert expanded is not None
    assert len(expanded.fields) == 11
    # Meta fields first per ORDER BY is_meta ASC... wait, is_meta ASC means
    # is_meta=0 (non-meta) first. Let's grab by name instead.
    by_name = {f.name: f for f in expanded.fields}
    assert by_name["srcip"].is_meta is False
    assert by_name["groups"].is_array is True
    assert by_name["_raw_log"].is_meta is True


def test_xdm_mappings_persist_when_provided(tmp_path: Path) -> None:
    """The table schema and the install code path handle XDM mappings
    when they are provided, even though no extractor produces them."""
    s = DataSourcesStore(db_path=tmp_path / "ds.db")
    ds = _fortigate_data_source()
    mappings = [
        DataSourceXdmMapping(xdm_path="xdm.source.ipv4", raw_expr="srcip"),
        DataSourceXdmMapping(xdm_path="xdm.destination.ipv4", raw_expr="dstip"),
    ]
    s.install(ds, fields=_fortigate_fields(), xdm_mappings=mappings)

    expanded = s.get_with_schema(ds.id)
    assert expanded is not None
    paths = {m.xdm_path for m in expanded.xdm_mappings}
    assert paths == {"xdm.source.ipv4", "xdm.destination.ipv4"}


# ── Cascade delete ────────────────────────────────────────────────


def test_uninstall_cascade_removes_fields(tmp_path: Path) -> None:
    """The FK cascade on data_source_fields means a single DELETE on
    data_sources drops all dependent rows. Test by counting child
    rows via the expanded view before + after.

    PRAGMA foreign_keys must be ON each connection — the store sets
    it, this test would silently pass even if FK was OFF (and then
    leave orphans). We verify it via the public API instead of poking
    the DB directly."""
    s = DataSourcesStore(db_path=tmp_path / "ds.db")
    ds = _fortigate_data_source()
    s.install(ds, fields=_fortigate_fields())
    assert s.get_with_schema(ds.id) is not None  # has 11 field rows

    deleted = s.uninstall(ds.id)
    assert deleted is True
    assert s.is_installed(ds.id) is False
    # Re-install with NO fields and confirm the expanded view has zero
    # fields — if cascade hadn't fired, we'd see stale fields from the
    # previous install reappearing.
    s.install(ds, fields=None)
    expanded = s.get_with_schema(ds.id)
    assert expanded is not None
    assert len(expanded.fields) == 0


def test_uninstall_returns_false_for_missing_id(tmp_path: Path) -> None:
    s = DataSourcesStore(db_path=tmp_path / "ds.db")
    assert s.uninstall("nonexistent/path/foo") is False


def test_reinstall_clears_stale_fields(tmp_path: Path) -> None:
    """If an operator updates a data source schema (e.g. pack bumped
    from v1.2 to v1.3 and the field set changed), re-install should
    NOT leave stale fields from the old version."""
    s = DataSourcesStore(db_path=tmp_path / "ds.db")
    ds = _fortigate_data_source()
    s.install(ds, fields=_fortigate_fields())  # 11 fields
    # Re-install with a smaller field set — should drop the old 11
    smaller_fields = [
        DataSourceField(name="srcip", type="string"),
        DataSourceField(name="dstip", type="string"),
    ]
    ds.field_count = 2
    ds.non_meta_field_count = 2
    s.install(ds, fields=smaller_fields)
    expanded = s.get_with_schema(ds.id)
    assert expanded is not None
    assert len(expanded.fields) == 2
    assert {f.name for f in expanded.fields} == {"srcip", "dstip"}


# ── List + filter ─────────────────────────────────────────────────


def test_list_sorts_by_pack_then_dataset(tmp_path: Path) -> None:
    s = DataSourcesStore(db_path=tmp_path / "ds.db")
    s.install(_fortigate_data_source())
    s.install(_f5apm_rawlog_data_source())
    rows = s.list()
    assert len(rows) == 2
    # F5APM (alphabetical first) before FortiGate
    assert rows[0].pack_name == "F5APM"
    assert rows[1].pack_name == "FortiGate"


def test_list_filter_matches_pack_name_case_insensitive(tmp_path: Path) -> None:
    s = DataSourcesStore(db_path=tmp_path / "ds.db")
    s.install(_fortigate_data_source())
    s.install(_f5apm_rawlog_data_source())
    # Lowercase filter still matches uppercase pack_name
    rows = s.list(filter="fortigate")
    assert len(rows) == 1
    assert rows[0].pack_name == "FortiGate"


def test_list_filter_matches_description(tmp_path: Path) -> None:
    """Filter checks pack_description too — operators search by what they
    remember about the vendor, not by exact pack id."""
    s = DataSourcesStore(db_path=tmp_path / "ds.db")
    s.install(_fortigate_data_source())  # description: "FortiGate firewall logs"
    rows = s.list(filter="firewall")
    assert len(rows) == 1
    assert rows[0].pack_name == "FortiGate"


def test_list_filter_matches_dataset_name(tmp_path: Path) -> None:
    s = DataSourcesStore(db_path=tmp_path / "ds.db")
    s.install(_fortigate_data_source())
    rows = s.list(filter="fortinet_fortigate_raw")
    assert len(rows) == 1
    assert rows[0].dataset_name == "fortinet_fortigate_raw"


def test_list_filter_no_match_returns_empty(tmp_path: Path) -> None:
    s = DataSourcesStore(db_path=tmp_path / "ds.db")
    s.install(_fortigate_data_source())
    assert s.list(filter="zzz_no_match_zzz") == []


# ── get_with_schema edge cases ────────────────────────────────────


def test_get_with_schema_returns_none_for_missing_id(tmp_path: Path) -> None:
    s = DataSourcesStore(db_path=tmp_path / "ds.db")
    assert s.get_with_schema("missing/id/foo") is None


def test_get_returns_none_for_missing_id(tmp_path: Path) -> None:
    s = DataSourcesStore(db_path=tmp_path / "ds.db")
    assert s.get("missing/id/foo") is None


# ── Type round-tripping ───────────────────────────────────────────


def test_supported_modules_round_trips(tmp_path: Path) -> None:
    """supported_modules is stored as a JSON string but exposed as a
    Python list. Round-trip should preserve order + content."""
    s = DataSourcesStore(db_path=tmp_path / "ds.db")
    ds = _fortigate_data_source()
    ds.supported_modules = ["xsiam", "xsoar", "agentX"]
    s.install(ds)
    got = s.get(ds.id)
    assert got is not None
    assert got.supported_modules == ["xsiam", "xsoar", "agentX"]


def test_empty_supported_modules_stays_empty_list(tmp_path: Path) -> None:
    """Round-trip from [] → null in DB → [] on read. Tests we don't
    leak a JSON 'null' into the list contract."""
    s = DataSourcesStore(db_path=tmp_path / "ds.db")
    ds = _fortigate_data_source()
    ds.supported_modules = []
    s.install(ds)
    got = s.get(ds.id)
    assert got is not None
    assert got.supported_modules == []


def test_is_rawlog_only_round_trips(tmp_path: Path) -> None:
    """The rawlog-only classification persists correctly. The bool
    is stored as INTEGER in SQLite, so the round-trip is the only way
    to catch an int-vs-bool drift."""
    s = DataSourcesStore(db_path=tmp_path / "ds.db")
    s.install(_f5apm_rawlog_data_source())
    got = s.get("F5APM/F5APM/f5_apm_raw")
    assert got is not None
    assert got.is_rawlog_only is True
    assert got.field_count == 1
    assert got.non_meta_field_count == 0


# ── Pin/unpin ─────────────────────────────────────────────────────


def test_set_pinned_true_records_version(tmp_path: Path) -> None:
    s = DataSourcesStore(db_path=tmp_path / "ds.db")
    ds = _fortigate_data_source()
    s.install(ds)
    ok = s.set_pinned(ds.id, pinned=True, pinned_version="1.2.0")
    assert ok is True
    got = s.get(ds.id)
    assert got is not None
    assert got.is_pinned is True
    assert got.pinned_version == "1.2.0"


def test_set_pinned_false_clears_version(tmp_path: Path) -> None:
    """Unpinning should NULL the pinned_version — a stale version
    pinned-to-nothing would be confusing."""
    s = DataSourcesStore(db_path=tmp_path / "ds.db")
    ds = _fortigate_data_source()
    s.install(ds)
    s.set_pinned(ds.id, pinned=True, pinned_version="1.2.0")
    s.set_pinned(ds.id, pinned=False)
    got = s.get(ds.id)
    assert got is not None
    assert got.is_pinned is False
    assert got.pinned_version is None


def test_set_pinned_returns_false_for_missing_id(tmp_path: Path) -> None:
    s = DataSourcesStore(db_path=tmp_path / "ds.db")
    assert s.set_pinned("missing/id/foo", pinned=True) is False


# ── to_dict shape (for REST handler integration) ──────────────────


def test_to_dict_contains_all_marketplace_fields(tmp_path: Path) -> None:
    """The to_dict shape is the REST contract. If a UI consumer needs
    a field, it must be in to_dict — pin the contract."""
    s = DataSourcesStore(db_path=tmp_path / "ds.db")
    ds = _fortigate_data_source()
    s.install(ds, fields=_fortigate_fields())
    got = s.get(ds.id)
    assert got is not None
    d = got.to_dict()
    expected_keys = {
        "id", "pack_name", "rule_name", "dataset_name", "pack_version",
        "is_rawlog_only", "field_count", "non_meta_field_count",
        "supported_modules", "pack_description", "logo_url", "logo_type",
        "installed_at", "installed_by", "is_pinned", "pinned_version",
        "source_revision",
    }
    assert set(d.keys()) == expected_keys


def test_with_schema_to_dict_includes_fields_and_mappings(tmp_path: Path) -> None:
    s = DataSourcesStore(db_path=tmp_path / "ds.db")
    ds = _fortigate_data_source()
    mappings = [DataSourceXdmMapping(xdm_path="xdm.source.ipv4", raw_expr="srcip")]
    s.install(ds, fields=_fortigate_fields(), xdm_mappings=mappings)
    expanded = s.get_with_schema(ds.id)
    assert expanded is not None
    d = expanded.to_dict()
    assert "fields" in d
    # xdm_mappings are not part of the serialized payload.
    # The SQLite table + dataclass field remain (orphaned) for
    # compatibility, but to_dict() does not surface the key.
    assert "xdm_mappings" not in d
    assert len(d["fields"]) == 11
    # example is carried alongside description so the drawer can
    # render the Example column for both installed + preview paths.
    # is_gate + enum_values too: the compact schema keeps a gate's
    # example and an enum's values only when the payload carries them.
    assert d["fields"][0].keys() == {
        "name", "type", "is_array", "is_meta", "is_gate", "enum_values",
        "description", "example",
    }


# ── ID composition contract ───────────────────────────────────────


def test_compose_data_source_id_format(tmp_path: Path) -> None:
    """The id format is operator-facing; pin it so a future refactor
    doesn't silently change customer-visible identifiers."""
    assert (
        compose_data_source_id("FortiGate", "FortiGate_1_3", "fortinet_fortigate_raw")
        == "FortiGate/FortiGate_1_3/fortinet_fortigate_raw"
    )
