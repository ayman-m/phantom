"""The active organization rendered into the read-only `organization` knowledge base."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.organization_fixtures import _small_org
from usecase import organization_kb as okb
from usecase import organization_model as om
from usecase.kb_store import SqliteKnowledgeBase
from usecase.organization_store import SqliteOrganizationStore

BUNDLE = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _bundle_root(monkeypatch):
    monkeypatch.setenv("BUNDLE_ROOT", str(BUNDLE))
    om.load_schema.cache_clear()


@pytest.fixture()
def world(tmp_path):
    return SqliteOrganizationStore(data_root=tmp_path / "o"), SqliteKnowledgeBase(data_root=tmp_path / "k")


def test_phantom_lab_renders_documents_for_every_section(world):
    store, kb = world
    docs = okb.render_docs("phantom-lab", 1, store.get_active().document)
    ids = {d["doc_id"] for d in docs}
    assert {"overview", "infrastructure", "networks", "accounts", "personas", "cloud-and-egress",
            "cortex-setup", "dept-finance", "dept-it", "workstations-ruh", "workstations-jed"} <= ids
    finance = next(d for d in docs if d["doc_id"] == "dept-finance")["content"]
    assert "nalharbi" in finance and "PHWS-001 10.20.16.20" in finance
    assert all(d["content"].startswith("Active organization: Phantom Lab") for d in docs)


def test_sync_indexes_then_is_idempotent(world):
    store, kb = world
    first = okb.sync(kb, store.get_active())
    assert first["insert"] > 10 and first["failed"] == 0
    assert kb.kb_summary()[okb.KB_NAME]["doc_count"] == first["insert"]
    second = okb.sync(kb, store.get_active())
    assert second["insert"] == 0 and second["unchanged"] == first["insert"]


def test_switching_replaces_documents_and_removes_the_old_ones(world):
    store, kb = world
    okb.sync(kb, store.get_active())
    store.create(_small_org(), activate=True)
    counts = okb.sync(kb, store.get_active())
    assert counts["removed"] > 0
    ids = kb.kb_doc_ids(okb.KB_NAME)
    assert "dept-finance" in ids and "dept-it" not in ids
    assert all("acme" in d.content.lower() or "Acme" in d.content for d in kb.list_docs(okb.KB_NAME, limit=50))


def test_search_finds_a_person_by_description(world):
    store, kb = world
    okb.sync(kb, store.get_active())
    hits = kb.search("who works in Finance and which workstation", kb_name=okb.KB_NAME, limit=3)
    assert hits and any("dept-finance" == doc.doc_id for doc, _ in hits)


def test_listener_keeps_the_kb_in_step(world):
    store, kb = world
    store.add_listener(lambda rec: okb.sync(kb, rec))
    store.create(_small_org(), activate=True)
    assert "dept-finance" in kb.kb_doc_ids(okb.KB_NAME) and "dept-it" not in kb.kb_doc_ids(okb.KB_NAME)


def test_sync_survives_a_failing_embedder(world):
    store, kb = world

    class _Broken:
        def upsert(self, **_):
            raise RuntimeError("no embedder")

        def kb_doc_ids(self, _):
            return set()

        def remove(self, *_):
            return False

    counts = okb.sync(_Broken(), store.get_active())
    assert counts["failed"] == 3  # stops after three, no exception
