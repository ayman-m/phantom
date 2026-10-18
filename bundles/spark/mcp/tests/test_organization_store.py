"""SqliteOrganizationStore: bundled seed, one active organization, read-only bundled, forks, history, import/export."""

from __future__ import annotations

import copy
import sqlite3
from pathlib import Path

import pytest

from usecase import organization_model as om
from usecase.organization_store import OrganizationStoreError, SqliteOrganizationStore

from tests.organization_fixtures import _small_org

BUNDLE = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _bundle_root(monkeypatch):
    monkeypatch.setenv("BUNDLE_ROOT", str(BUNDLE))
    om.load_schema.cache_clear()


@pytest.fixture()
def store(tmp_path: Path) -> SqliteOrganizationStore:
    return SqliteOrganizationStore(data_root=tmp_path)


def test_first_boot_loads_phantom_lab_and_activates_it(store):
    orgs = store.list()
    assert [o.id for o in orgs] == ["phantom-lab"]
    lab = store.get_active()
    assert lab.id == "phantom-lab" and lab.source == "bundled" and lab.version == 1
    assert om.summary(lab.document)["people"] == 50


def test_boot_is_idempotent_and_keeps_the_active_choice(tmp_path):
    s1 = SqliteOrganizationStore(data_root=tmp_path)
    s1.create(_small_org(), actor="t", activate=True)
    s2 = SqliteOrganizationStore(data_root=tmp_path)
    assert s2.get_active().id == "acme"
    assert s2.get("phantom-lab").version == 1


def test_changed_bundled_file_refreshes_the_stored_copy(tmp_path):
    bundled = tmp_path / "bundled"
    bundled.mkdir()
    text = (BUNDLE / "organization" / "phantom-lab.yaml").read_text(encoding="utf-8")
    (bundled / "phantom-lab.yaml").write_text(text, encoding="utf-8")
    SqliteOrganizationStore(data_root=tmp_path / "d", bundled_dir=bundled)
    (bundled / "phantom-lab.yaml").write_text(text.replace("name: Phantom Lab", "name: Phantom Lab Two", 1),
                                              encoding="utf-8")
    s = SqliteOrganizationStore(data_root=tmp_path / "d", bundled_dir=bundled)
    lab = s.get("phantom-lab")
    assert lab.name == "Phantom Lab Two" and lab.version == 2


def test_bundled_is_read_only(store):
    doc = copy.deepcopy(store.get("phantom-lab").document)
    with pytest.raises(OrganizationStoreError) as e:
        store.put("phantom-lab", doc)
    assert e.value.code == "bundled_read_only"
    with pytest.raises(OrganizationStoreError):
        store.delete("phantom-lab")


def test_create_activate_and_switch_removes_nothing(store):
    store.create(_small_org(), actor="t")
    assert store.get_active().id == "phantom-lab"
    store.activate("acme", actor="t")
    assert store.get_active().id == "acme"
    assert {o.id for o in store.list()} == {"phantom-lab", "acme"}
    assert sum(1 for o in store.list() if o.active) == 1
    store.activate("phantom-lab")
    assert store.get("acme") is not None


def test_create_rejects_invalid_and_duplicate(store):
    bad = _small_org()
    bad["hosts"][0]["ip"] = "10.99.0.1"
    with pytest.raises(om.OrganizationError):
        store.create(bad)
    store.create(_small_org())
    with pytest.raises(OrganizationStoreError) as e:
        store.create(_small_org())
    assert e.value.code == "exists"


def test_put_bumps_version_and_snapshots_history(store):
    store.create(_small_org())
    doc = store.get("acme").document
    doc["name"] = "Acme Two"
    rec = store.put("acme", doc, actor="op", note="rename")
    assert rec.version == 2 and rec.name == "Acme Two" and rec.updated_by == "op"
    h = store.history("acme")
    # Version 1 had no note of its own (create() was called with none), so its history row is
    # unlabelled; "rename" describes how version 2 came to be, not how version 1 ended.
    assert len(h) == 1 and h[0]["version"] == 1 and h[0]["note"] is None


def test_history_row_is_labelled_with_its_own_origin_not_its_replacement(store):
    # Measured 2026-10-18 (F4): a history row used to read as "what replaced me" instead of "how
    # I was made" -- a restore's "restored history entry 1" note landed on the OLD version being
    # overwritten rather than on the new version the restore itself produced.
    store.create(_small_org())
    doc = store.get("acme").document
    doc["name"] = "Acme Two"
    store.put("acme", doc, actor="op", note="renamed to Acme Two")
    doc = store.get("acme").document
    doc["name"] = "Acme Three"
    store.put("acme", doc, actor="op", note="renamed to Acme Three")
    h = {row["version"]: row["note"] for row in store.history("acme")}
    assert h[1] is None  # version 1's own origin (create() passed no note)
    assert h[2] == "renamed to Acme Two"  # version 2's own origin, not version 3's
    current = store.get("acme")
    assert current.version == 3 and current.note == "renamed to Acme Three"


def test_put_rejects_invalid_document_and_leaves_the_stored_one(store):
    store.create(_small_org())
    doc = store.get("acme").document
    doc["people"][0]["manager"] = "ghost"
    with pytest.raises(om.OrganizationError):
        store.put("acme", doc)
    assert store.get("acme").version == 1


def test_fork_makes_an_editable_copy_with_a_unique_id(store):
    a = store.fork("phantom-lab")
    b = store.fork("phantom-lab")
    assert a.id == "phantom-lab-custom" and a.source == "operator"
    assert b.id == "phantom-lab-custom-2"
    assert a.document["id"] == a.id and om.validate_document(a.document) == []


def test_fork_with_a_name_slugifies_it_instead_of_chaining_dash_custom(store):
    # Measured 2026-10-18 (F3): the Duplicate dialog only collects a name, so `new_id` is always
    # None; forking a copy of a copy ("phantom-lab-custom") with no new_name produced
    # "phantom-lab-custom-custom" -- the typed name was ignored entirely. A name should slugify
    # to its own id regardless of what the source organization's id happens to be.
    a = store.fork("phantom-lab", new_name="Test Copy A")
    assert a.id == "test-copy-a" and a.name == "Test Copy A"
    b = store.fork(a.id, new_name="Test Copy B")
    assert b.id == "test-copy-b"  # not "test-copy-a-custom" or any suffix of a's id
    # Forking a SECOND copy under the same name is still made unique.
    c = store.fork("phantom-lab", new_name="Test Copy A")
    assert c.id == "test-copy-a-2"


def test_apply_changes_on_bundled_forks_and_keeps_it_active(store):
    rec, notes, forked_from = store.apply_changes("phantom-lab", {"upsert": {"people": [
        {"given_name": "Amira", "family_name": "Alfarsi", "title": "Analyst", "department": "Finance"}]}}, actor="agent")
    assert forked_from == "phantom-lab" and rec.id == "phantom-lab-custom"
    assert store.get_active().id == "phantom-lab-custom"
    assert om.summary(rec.document)["people"] == 51
    assert om.summary(store.get("phantom-lab").document)["people"] == 50  # the bundled one is untouched
    assert any("bundled" in n for n in notes)


def test_apply_changes_on_operator_org_edits_in_place(store):
    store.create(_small_org())
    rec, _, forked_from = store.apply_changes("acme", {"set": {"description": "hello"}})
    assert forked_from is None and rec.id == "acme" and rec.document["description"] == "hello" and rec.version == 2


def test_bad_change_to_bundled_leaves_no_fork(store):
    with pytest.raises(om.OrganizationError):
        store.apply_changes("phantom-lab", {"upsert": {"people": [{"login": "falqarni", "manager": "ghost"}]}})
    assert [o.id for o in store.list()] == ["phantom-lab"]


def test_delete_rules(store):
    store.create(_small_org())
    store.activate("acme")
    with pytest.raises(OrganizationStoreError) as e:
        store.delete("acme")
    assert e.value.code == "active"
    store.activate("phantom-lab")
    store.delete("acme")
    assert store.get("acme") is None and store.history("acme") == []


def test_restore_brings_back_an_earlier_document(store):
    store.create(_small_org())
    doc = store.get("acme").document
    doc["description"] = "changed"
    store.put("acme", doc)
    seq = store.history("acme")[0]["seq"]
    rec = store.restore("acme", seq)
    assert "description" not in rec.document and rec.version == 3


def test_import_export_round_trip_and_replace_rules(store):
    text = om.to_yaml(_small_org())
    rec = store.import_text(text, "yaml", activate=True)
    assert rec.id == "acme" and store.get_active().id == "acme"
    with pytest.raises(OrganizationStoreError):
        store.import_text(text, "yaml")
    again = store.import_text(text.replace("Acme Example", "Acme Again"), "yaml", replace=True)
    assert again.name == "Acme Again" and again.version == 2
    assert om.parse_document(store.export_text("acme", "json"))["id"] == "acme"
    lab_text = store.export_text("phantom-lab")
    with pytest.raises(OrganizationStoreError):
        store.import_text(lab_text, "yaml")  # a bundled id is never replaced


def test_listener_sees_the_active_organization(store):
    seen = []
    store.add_listener(lambda rec: seen.append(rec.id if rec else None))
    store.create(_small_org())
    store.activate("acme")
    assert seen[-1] == "acme"


def test_database_is_not_in_wal_mode(store):
    """A connector container opens organization.db mode=ro on a read-only mount; WAL would need a writable -shm."""
    c = sqlite3.connect(store.db_path)
    try:
        assert c.execute("PRAGMA journal_mode").fetchone()[0].lower() != "wal"
    finally:
        c.close()
