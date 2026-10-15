"""The agent's organization tools: read sections, structured edits, switching, and their registration."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from tests.organization_fixtures import _small_org
from usecase import organization_model as om
from usecase.builtin_components import _approval_gate, self_mod_tools as t
from usecase.organization_store import SqliteOrganizationStore, set_organization_store

BUNDLE = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def world(tmp_path, monkeypatch):
    monkeypatch.setenv("BUNDLE_ROOT", str(BUNDLE))
    om.load_schema.cache_clear()
    _approval_gate._human_required_set.cache_clear()
    store = SqliteOrganizationStore(data_root=tmp_path)
    set_organization_store(store)
    yield store
    set_organization_store(None)


def test_get_overview_and_filtered_people():
    ov = t.organization_get()
    assert ov["organization"]["id"] == "phantom-lab" and ov["people"] == 50
    fin = t.organization_get(section="people", filter="department=Finance")
    assert fin["total"] == 7 and fin["rows"][0]["workstation_ip"]
    assert t.organization_get(section="personas")["vip"][0]["login"] in ("falqarni", "malessa")


def test_get_reports_truncation_and_errors():
    page = t.organization_get(section="hosts", filter="role=workstation", limit=5)
    assert page["total"] == 50 and page["truncated"] is True and len(page["rows"]) == 5
    assert "error" in t.organization_get(section="bogus")
    assert "error" in t.organization_get(organization_id="nope")


def test_list(world):
    world.create(_small_org())
    out = t.organization_list()
    assert out["count"] == 2 and out["active_id"] == "phantom-lab"


def test_update_adds_a_hire_to_a_copy_and_it_becomes_active(world):
    out = asyncio.run(t.organization_update(
        {"upsert": {"people": [{"given_name": "Amira", "family_name": "Alfarsi", "title": "Analyst",
                                "department": "Finance"}]}}, note="new hire"))
    assert out["forked_from"] == "phantom-lab" and out["organization"]["id"] == "phantom-lab-custom"
    again = t.organization_get(section="people", filter="aalfarsi")
    assert again["total"] == 1 and again["rows"][0]["workstation"] == "PHWS-051"
    assert t.organization_list()["active_id"] == "phantom-lab-custom"


def test_update_rejects_inconsistent_change_with_every_error(world):
    out = asyncio.run(t.organization_update({"upsert": {"hosts": [{"name": "PHSRV-FS01", "ip": "10.99.0.5"}]}}))
    assert "error" in out and any("outside network" in e for e in out["errors"])
    assert [r.id for r in world.list()] == ["phantom-lab"]


def test_update_rejects_empty_changes():
    assert "error" in asyncio.run(t.organization_update({}))


def test_activate_switch_and_back(world):
    world.create(_small_org())
    out = asyncio.run(t.organization_activate("acme"))
    assert out["organization"]["active"] is True
    assert t.organization_get()["organization"]["id"] == "acme"
    assert "error" in asyncio.run(t.organization_activate("missing"))
    asyncio.run(t.organization_activate("phantom-lab"))
    assert t.organization_get()["organization"]["id"] == "phantom-lab"


def test_tools_are_agent_registered_and_batchable_and_not_credentials():
    from usecase.connector_loader import _BUILTIN_LEGACY_TOOLS
    names = {n for n, _ in _BUILTIN_LEGACY_TOOLS}
    assert {"organization_get", "organization_list", "organization_update", "organization_activate"} <= names
    t._populate_batchable_tools()
    assert "organization_update" in t._BATCHABLE_TOOLS and "organization_activate" in t._BATCHABLE_TOOLS


def test_docstrings_teach_the_arguments():
    for fn in (t.organization_get, t.organization_update):
        doc = fn.__doc__ or ""
        assert "Args:" in doc and "Example" in doc
    assert "filter" in t.organization_get.__doc__ and "upsert" in t.organization_update.__doc__
