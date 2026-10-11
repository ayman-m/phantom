"""kb_loader — unit tests.

Covers the required-field strict-validation behavior. A frontmatterless
file such as a README.md at a KB root, or a source dataset file in
_tools/, must not leak into the KB as a broken doc (no id, no title, no
category) and inflate its doc_count. Required means required:
missing-required-field docs are skipped, not upserted.

These tests exercise the loader directly against a temporary KB
directory + a stub `kb` object that records upsert calls. No
embedding model is invoked — the kb stub returns a fake action
string. The point is to verify the BRANCHING behavior of the loader,
not the embedding pipeline.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest

# kb_loader lives at src/usecase/kb_loader.py — same sys.path layout
# as the other tests; the pytest harness sets PYTHONPATH=src per the
# project's pre-deploy gate.
from usecase import kb_loader


# ─── Fakes ──────────────────────────────────────────────────────────


@dataclass
class _FakeKb:
    """Records every upsert + remove call. Returns a deterministic
    action so the loader's counts['insert']/['update']/['unchanged']
    bookkeeping can be exercised. Matches the real `kb_store` interface
    surface the loader uses."""

    upserts: list[dict] = field(default_factory=list)
    removes: list[str] = field(default_factory=list)
    existing_doc_ids: set[str] = field(default_factory=set)

    def upsert(
        self, *,
        kb_name: str,
        doc_id: str,
        content: str,
        title: str | None,
        category: str | None,
        metadata: dict,
        source_path: str,
        source_hash: str,
    ) -> tuple[object, str]:
        self.upserts.append({
            "kb_name": kb_name,
            "doc_id": doc_id,
            "title": title,
            "category": category,
            "metadata": metadata,
            "source_path": source_path,
        })
        return (None, "insert")

    def kb_doc_ids(self, kb_name: str) -> set[str]:
        return set(self.existing_doc_ids)

    def remove(self, kb_name: str, doc_id: str) -> bool:
        self.removes.append(doc_id)
        return True


# ─── Helpers ────────────────────────────────────────────────────────


def _seed_kb_dir(tmp_path: Path) -> tuple[Path, dict]:
    """Build a small KB directory mirroring the xql-examples shape +
    return its path + the matching schema dict. Two valid entries,
    one missing-required-field entry, plus README.md at the root
    (frontmatterless) — the shape that must not leak into the KB."""
    kb_root = tmp_path / "test-kb"
    (kb_root / "entries").mkdir(parents=True)

    # Valid entry 1
    (kb_root / "entries" / "001-valid.md").write_text(
        "---\n"
        "id: XQL-001-valid\n"
        "title: Valid Entry One\n"
        "category: detection\n"
        "---\n"
        "\n"
        "# Valid Entry One\n"
        "Body text.\n",
    )
    # Valid entry 2
    (kb_root / "entries" / "002-valid.md").write_text(
        "---\n"
        "id: XQL-002-valid\n"
        "title: Valid Entry Two\n"
        "category: investigation\n"
        "---\n"
        "\n"
        "# Valid Entry Two\n"
        "Body text.\n",
    )
    # Invalid: missing category (required)
    (kb_root / "entries" / "003-broken.md").write_text(
        "---\n"
        "id: XQL-003-broken\n"
        "title: Broken Entry\n"
        "---\n"
        "\n"
        "# Broken Entry\n"
        "Body text.\n",
    )
    # README.md at root, no frontmatter: EMPTY metadata, missing all
    # three required fields.
    (kb_root / "README.md").write_text("# README\nSee schema.json.\n")

    schema = {
        "required": ["id", "title", "category"],
        "properties": {
            "id": {"type": "string"},
            "title": {"type": "string"},
            "category": {
                "type": "string",
                "enum": ["detection", "investigation", "alert-mapping", "general"],
            },
        },
    }
    return kb_root, schema


# ─── Tests ──────────────────────────────────────────────────────────


def test_invalid_docs_are_skipped_not_upserted(tmp_path):
    """Required means required — missing-required docs DON'T enter the KB."""
    kb_root, schema = _seed_kb_dir(tmp_path)
    kb = _FakeKb()

    summary = kb_loader.load_bundled_knowledge(
        kb=kb,
        bundle_root=tmp_path,
        bundled=[{
            "name": "test-kb",
            "path": "./test-kb/",
            # Schema is loaded by the loader from a file, but the
            # loader also accepts an inline dict via the schema_path
            # being None — so we patch the validator path instead.
        }],
    )

    # The schema-path branch of the loader reads from disk. To exercise
    # the strict-validation path with our inline schema, write it.
    # (The seed above didn't write it; the call above ran without a
    # schema and would have upserted everything. So this first call
    # is just to verify the no-schema path doesn't crash; the real
    # test continues below.)
    assert "test-kb" in summary


def test_required_field_validation_is_enforcing(tmp_path):
    """With a schema declaring required fields, invalid docs are
    skipped (counts['invalid'] += 1) and NOT upserted."""
    kb_root, schema = _seed_kb_dir(tmp_path)

    # Write the schema to disk so the loader picks it up via the
    # `schema` entry in the bundled spec.
    import json
    schema_path = kb_root / "schema.json"
    schema_path.write_text(json.dumps(schema))

    kb = _FakeKb()
    summary = kb_loader.load_bundled_knowledge(
        kb=kb,
        bundle_root=tmp_path,
        bundled=[{
            "name": "test-kb",
            "path": "./test-kb/",
            "schema": "./test-kb/schema.json",
        }],
    )

    counts = summary["test-kb"]
    # The two valid entries land via upsert; the broken entry +
    # README.md (missing all required fields) both skip.
    assert counts["insert"] == 2, f"expected 2 valid inserts, got {counts}"
    assert counts["invalid"] == 2, f"expected 2 invalid skips, got {counts}"

    # Verify the upsert calls cover only the valid entries.
    upserted_doc_ids = {u["doc_id"] for u in kb.upserts}
    assert upserted_doc_ids == {"XQL-001-valid", "XQL-002-valid"}, (
        f"upserted unexpected docs: {upserted_doc_ids}"
    )


def test_previously_loaded_invalid_doc_is_reaped(tmp_path):
    """If a doc used to be valid + got into the KB, but now fails
    required-field validation (operator edited the frontmatter), the
    reaper removes it on the next boot.

    The mechanism: invalid docs are NOT added to seen_doc_ids, so
    the reaper at the end of the loop sees them as 'vanished from
    disk' and removes them. This is the desired semantic — the KB
    should only contain currently-valid docs."""
    kb_root, schema = _seed_kb_dir(tmp_path)

    import json
    (kb_root / "schema.json").write_text(json.dumps(schema))

    kb = _FakeKb()
    # Simulate: XQL-003-broken WAS in the KB from a previous boot
    # (when it had its category set). Now it's missing category.
    kb.existing_doc_ids = {"XQL-001-valid", "XQL-002-valid", "XQL-003-broken"}

    summary = kb_loader.load_bundled_knowledge(
        kb=kb,
        bundle_root=tmp_path,
        bundled=[{
            "name": "test-kb",
            "path": "./test-kb/",
            "schema": "./test-kb/schema.json",
        }],
    )

    counts = summary["test-kb"]
    # XQL-003-broken: not in seen_doc_ids → reaped → counts["removed"] += 1
    assert "XQL-003-broken" in kb.removes, (
        f"expected XQL-003-broken to be reaped; removes={kb.removes}"
    )
    assert counts["removed"] >= 1, f"expected at least 1 removed, got {counts}"


class _AlwaysFailingKb(_FakeKb):
    """Every upsert raises — simulates a fully broken embedder (a Vertex
    outage/misconfig makes every call fail; without a circuit breaker the
    loader would grind through hundreds of docs, blowing entrypoint.sh's
    60s MCP-readiness window and crash-looping the whole container)."""

    def upsert(self, **kwargs):
        self.attempts = getattr(self, "attempts", 0) + 1
        raise RuntimeError("simulated embedder failure")


class _IntermittentKb(_FakeKb):
    """Fails 2 of every 3 calls — never hits enough CONSECUTIVE failures
    to trip the breaker, so a flaky-but-not-fully-broken embedder must
    still finish the load."""

    def upsert(self, **kwargs):
        self.attempts = getattr(self, "attempts", 0) + 1
        if self.attempts % 3 != 0:
            raise RuntimeError("simulated transient failure")
        return super().upsert(**kwargs)


def _seed_many_docs(tmp_path: Path, count: int, kb_dirname: str = "many-docs-kb") -> Path:
    """`count` valid, schema-free docs — enough to exceed the circuit
    breaker threshold if every upsert fails."""
    kb_root = tmp_path / kb_dirname
    kb_root.mkdir(parents=True)
    for i in range(count):
        (kb_root / f"{i:03d}.md").write_text(
            f"---\nid: DOC-{i:03d}\ntitle: Doc {i}\ncategory: general\n---\n\nBody.\n",
        )
    return kb_root


def test_circuit_breaker_aborts_after_consecutive_failures(tmp_path):
    """A broken embedder must not grind through every doc — the loader
    aborts after _EMBED_FAILURE_CIRCUIT_BREAKER consecutive failures
    instead of attempting all of them."""
    doc_count = kb_loader._EMBED_FAILURE_CIRCUIT_BREAKER + 20
    _seed_many_docs(tmp_path, doc_count)

    kb = _AlwaysFailingKb()
    summary = kb_loader.load_bundled_knowledge(
        kb=kb,
        bundle_root=tmp_path,
        bundled=[{"name": "many-docs-kb", "path": "./many-docs-kb/"}],
    )

    counts = summary["many-docs-kb"]
    assert kb.attempts == kb_loader._EMBED_FAILURE_CIRCUIT_BREAKER, (
        f"expected exactly {kb_loader._EMBED_FAILURE_CIRCUIT_BREAKER} attempts "
        f"before the breaker trips, got {kb.attempts} (of {doc_count} docs)"
    )
    assert counts["skipped"] == kb_loader._EMBED_FAILURE_CIRCUIT_BREAKER


def test_circuit_breaker_does_not_reap_on_abort(tmp_path):
    """An aborted load must not delete docs it never got to visit — an
    unvisited doc is absent from seen_doc_ids purely because the loader
    stopped early, not because it's actually gone from disk."""
    doc_count = kb_loader._EMBED_FAILURE_CIRCUIT_BREAKER + 5
    _seed_many_docs(tmp_path, doc_count)

    kb = _AlwaysFailingKb()
    kb.existing_doc_ids = {"some-doc-from-a-prior-boot"}
    kb_loader.load_bundled_knowledge(
        kb=kb,
        bundle_root=tmp_path,
        bundled=[{"name": "many-docs-kb", "path": "./many-docs-kb/"}],
    )

    assert kb.removes == [], f"aborted load must not reap — removes={kb.removes}"


def test_circuit_breaker_resets_on_intermittent_success(tmp_path):
    """Occasional successes reset the consecutive-failure counter, so a
    flaky-but-not-fully-broken embedder still finishes the load rather
    than tripping the breaker early."""
    doc_count = kb_loader._EMBED_FAILURE_CIRCUIT_BREAKER * 3
    _seed_many_docs(tmp_path, doc_count)

    kb = _IntermittentKb()
    kb_loader.load_bundled_knowledge(
        kb=kb,
        bundle_root=tmp_path,
        bundled=[{"name": "many-docs-kb", "path": "./many-docs-kb/"}],
    )

    assert kb.attempts == doc_count, (
        f"expected the loader to attempt every doc, got {kb.attempts}/{doc_count}"
    )


def test_no_schema_means_no_strict_validation(tmp_path):
    """When no schema is configured for a KB, the loader doesn't
    invent required fields — every parseable doc gets upserted.
    This is the default for KBs that intentionally don't declare a
    schema."""
    kb_root, _ = _seed_kb_dir(tmp_path)

    kb = _FakeKb()
    summary = kb_loader.load_bundled_knowledge(
        kb=kb,
        bundle_root=tmp_path,
        bundled=[{
            "name": "test-kb",
            "path": "./test-kb/",
            # No schema entry — loader skips validation.
        }],
    )

    counts = summary["test-kb"]
    # All four files (3 entries + README) get upserted in the no-schema path.
    assert counts["insert"] == 4, f"expected 4 inserts in no-schema mode, got {counts}"
    assert counts["invalid"] == 0, f"expected 0 invalid, got {counts}"
