"""The connector-runtime reader against the real store: the two ends of the shared-volume contract."""

from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

import pytest

from tests.organization_fixtures import _small_org
from usecase import organization_model as om
from usecase.organization_store import SqliteOrganizationStore

REPO = Path(__file__).resolve().parents[4]
BUNDLE = REPO / "bundles" / "spark"


def _reader_module():
    path = REPO / "phantom-connector-runtime" / "runtime" / "organization_reader.py"
    spec = importlib.util.spec_from_file_location("organization_reader_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(autouse=True)
def _bundle_root(monkeypatch):
    monkeypatch.setenv("BUNDLE_ROOT", str(BUNDLE))
    om.load_schema.cache_clear()


@pytest.fixture()
def pair(tmp_path):
    store = SqliteOrganizationStore(data_root=tmp_path)
    mod = _reader_module()
    return store, mod, mod.OrganizationReader(store.db_path)


def test_reads_the_active_organization(pair):
    store, _, reader = pair
    doc = reader.load()
    assert doc["id"] == "phantom-lab" and len(doc["people"]) == 50


def test_follows_a_switch_and_a_save_without_a_restart(pair):
    store, _, reader = pair
    assert reader.load()["id"] == "phantom-lab"
    store.create(_small_org(), activate=True)
    assert reader.load()["id"] == "acme"
    doc = store.get("acme").document
    doc["description"] = "changed"
    store.put("acme", doc)
    assert reader.load()["description"] == "changed"


def test_pinned_organization_ignores_the_active_one(pair):
    store, _, reader = pair
    store.create(_small_org(), activate=True)
    assert reader.load("phantom-lab")["id"] == "phantom-lab"
    assert reader.load("")["id"] == "acme"


def test_caches_until_the_version_changes(pair, monkeypatch):
    store, _, reader = pair
    first = reader.load()
    assert reader.load() is first  # same object: not re-parsed
    doc = store.get("phantom-lab-custom") or store.fork("phantom-lab").document
    store.activate("phantom-lab-custom")
    assert reader.load() is not first


def test_explicit_errors(pair, tmp_path):
    store, mod, reader = pair
    with pytest.raises(mod.OrganizationUnavailable, match="no organization with id"):
        reader.load("missing")
    with pytest.raises(mod.OrganizationUnavailable, match="not found"):
        mod.OrganizationReader(tmp_path / "nope.db").load()
    c = sqlite3.connect(store.db_path)
    c.execute("UPDATE organizations SET active = 0")
    c.commit()
    c.close()
    with pytest.raises(mod.OrganizationUnavailable, match="no organization is active"):
        reader.load()


def test_opens_a_read_only_copy_of_the_file(pair, tmp_path):
    """The container's view: the same file, read-only. A write must fail and a read must still work."""
    store, mod, _ = pair
    ro = tmp_path / "ro.db"
    ro.write_bytes(store.db_path.read_bytes())
    ro.chmod(0o444)
    try:
        assert mod.OrganizationReader(ro).load()["id"] == "phantom-lab"
        conn = sqlite3.connect(f"file:{ro}?mode=ro", uri=True)
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("UPDATE organizations SET active = 0")
        conn.close()
    finally:
        ro.chmod(0o644)
