"""enum_values must survive every projection hop to the generator.

WHY THIS TEST EXISTS. The field-metadata chain runs
    data_source.yaml -> DataSourceField -> REST/compact projection
    -> connector pydantic model -> GraphQL input -> dynamic_schema
and every hop projects an EXPLICIT key list, so a key absent from any one of
them is silently dropped with no error. `is_gate` has the same shape: the flag
can reach the served schema and the generator can know how to honour it, yet
pinning does nothing if the key dies crossing one boundary in the middle.

`enum_values` has the same shape and the same failure mode. Without it a field
declared `type: enum` falls through to the random-token branch, so a firewall's
`act` emits something like 'PWnpgWwN' and `xdm.observer.action` populates with a
meaningless value — which reads as working, and is therefore worse than null.

These tests pin the two ends that are checkable in-process. The connector and
GraphQL hops live in other services; they are covered by the shape assertions in
their own suites.
"""

from __future__ import annotations

import pathlib

import pytest
import yaml

from src.usecase.data_sources_store import DataSourceField

FORTIGATE = (
    pathlib.Path(__file__).resolve().parents[3]
    / "spark" / "data-sources"
    / "FortiGate__FortiGate__fortinet_fortigate_raw" / "data_source.yaml"
)


def _compact():
    import src.api.data_sources as ds
    fn = getattr(ds, "_compact_schema_payload", None)
    assert callable(fn), "compact projection helper not found"
    return fn


def test_dataclass_carries_enum_values() -> None:
    assert "enum_values" in DataSourceField.__dataclass_fields__


def test_enum_values_default_is_none_not_empty_list() -> None:
    """A mutable default would be shared across every field instance."""
    assert DataSourceField(name="x", type="string").enum_values is None


def test_compact_projection_preserves_enum_values() -> None:
    """The compact payload is what the agent actually receives."""
    out = _compact()({
        "fields": [
            {"name": "act", "type": "enum", "enum_values": ["accept", "deny"]},
            {"name": "src", "type": "ipv4"},
        ]
    })
    act = next(f for f in out["fields"] if f["name"] == "act")
    assert act.get("enum_values") == ["accept", "deny"], (
        "enum_values dropped in compaction — the generator will emit a random "
        "token and the XDM target will carry a meaningless value"
    )


def test_compact_projection_omits_enum_values_when_absent() -> None:
    """Non-enum fields must not gain an empty key — compaction stays lean."""
    out = _compact()({"fields": [{"name": "src", "type": "ipv4"}]})
    assert "enum_values" not in out["fields"][0]


@pytest.mark.skipif(not FORTIGATE.is_file(), reason="FortiGate source not present")
def test_fortigate_act_is_a_real_enum_not_a_placeholder() -> None:
    """The FortiGate `act` field must be a real enum, not a placeholder.

    `act` feeds xdm.observer.action via coalesce(). Declared as
    `type: string_short` with the placeholder example "token_value", it
    would generate a random token forever and leave the XDM field null.
    """
    doc = yaml.safe_load(FORTIGATE.read_text())
    act = next(f for f in doc["fields"] if f["name"] == "act")
    assert act["type"] == "enum"
    vals = act.get("enum_values") or []
    assert "accept" in vals and "deny" in vals
    assert act.get("example") != "token_value"


@pytest.mark.skipif(not FORTIGATE.is_file(), reason="FortiGate source not present")
def test_fortigate_address_fields_are_typed_ipv4() -> None:
    """The generator is steered by TYPE alone; a correct example is inert.

    src/dst declared `type: string` with example 192.0.2.45 produced random
    tokens, which is why xdm.source.ipv4 was 100% null across 14,399 events.
    """
    doc = yaml.safe_load(FORTIGATE.read_text())
    fields = {f["name"]: f for f in doc["fields"]}
    for name in ("src", "dst"):
        assert fields[name]["type"] == "ipv4", (
            f"{name} must be typed ipv4 — a string-typed address field emits a "
            "random token that no modeling rule can parse"
        )


# --------------------------------------------------------------------------
# the store hop — added after an edit silently terminated the class body


def test_enum_values_round_trips_through_the_store(tmp_path) -> None:
    """install() -> sqlite -> get_with_schema() must preserve enum_values.

    The store had no enum_values column at all, so a field declared
    `type: enum` was persisted without its values and the generator fell
    back to a random token. Stored as a JSON array.
    """
    from src.usecase.data_sources_store import (
        DataSource, DataSourceField, DataSourcesStore,
    )
    st = DataSourcesStore(db_path=str(tmp_path / "ds.db"))
    ds = DataSource(id="P/R/D", pack_name="P", rule_name="R", dataset_name="D")
    st.install(ds, [
        DataSourceField(name="act", type="enum", enum_values=["accept", "deny"]),
        DataSourceField(name="src", type="ipv4"),
    ], [])
    got = {f.name: f for f in st.get_with_schema("P/R/D").fields}
    assert got["act"].enum_values == ["accept", "deny"]
    # A non-enum field must read back as None, not [] — callers distinguish
    # "no values" from "not an enum".
    assert got["src"].enum_values is None


def test_store_class_still_exposes_its_methods() -> None:
    """Guards against an edit that terminates the class body early.

    A module-level helper inserted inside the class turned every method
    below it into a module function; the class kept importing fine and
    only failed at call time with AttributeError.
    """
    from src.usecase.data_sources_store import DataSourcesStore
    for m in ("install", "get_with_schema", "uninstall", "list"):
        assert callable(getattr(DataSourcesStore, m, None)), f"{m} is not a method"
