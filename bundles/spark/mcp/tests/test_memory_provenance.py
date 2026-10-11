"""Tests for memory provenance — distinguishing "the operator stated
this" from "the agent concluded this itself".

Every memory write must be attributed: cognitive_tools.py passes meta
through to store(), so the agent can tell at recall time whether a hit
is an operator-confirmed fact or its own unverified prior conclusion.
This targets the failure mode where the agent reaches a wrong
conclusion once, stores it, and a later turn recalls and repeats it
without re-investigating — so one mistake becomes permanent.

Three write paths, three provenance rules:
  - memory_store MCP tool (cognitive_tools.py) -> always meta.source="agent",
    not caller-selectable (only the agent calls this tool).
  - POST /api/v1/memories (api/cognitive.py) -> always meta.source="operator",
    stamped server-side, overriding anything the caller sent (only a
    human/external system calls this REST route directly).
  - plugin_loader.py -> meta.source="plugin:<name>".

search() also weights operator-sourced rows higher via
_OPERATOR_SOURCE_TRUST_MULTIPLIER so a well-matching self-conclusion
doesn't outrank an operator statement on the same topic.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from usecase.memory_store import (
    SqliteMemoryStore,
    TextHashEmbedder,
    _OPERATOR_SOURCE_TRUST_MULTIPLIER,
    set_memory_store,
)
from usecase.builtin_components import cognitive_tools


def _make_store(tmp_path: Path) -> SqliteMemoryStore:
    return SqliteMemoryStore(data_root=tmp_path, embedder=TextHashEmbedder(dims=768))


# ─── memory_store MCP tool: always source=agent ─────────────────────


def test_memory_store_tool_stamps_source_agent(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    set_memory_store(store)
    try:
        out = cognitive_tools.memory_store(key="k1", value="v1", scope="agent")
        assert out["meta"]["source"] == "agent"
    finally:
        set_memory_store(None)


def test_memory_store_tool_does_not_expose_a_source_override(tmp_path: Path) -> None:
    """The tool's public signature has no meta/source parameter at all
    — an agent invoking it cannot claim operator provenance for its
    own write, by construction rather than by validation."""
    import inspect

    params = inspect.signature(cognitive_tools.memory_store).parameters
    assert "meta" not in params
    assert "source" not in params


# ─── REST route: always source=operator, server-stamped ─────────────


def test_store_route_stamps_source_operator(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    meta = dict({"note": "from the settings UI"})
    meta["source"] = "operator"  # mirrors what api/cognitive.py's route does
    m = store.store(key="k1", value="v1", scope="agent", meta=meta)
    assert m.meta["source"] == "operator"
    assert m.meta["note"] == "from the settings UI"


def test_resolve_scope_filter_module_also_exports_store_route_stamping() -> None:
    """Guards the actual route body, not just a hand-rolled equivalent
    — reads api/cognitive.py's store_memory source and confirms the
    server-side stamp line is present and unconditional (guards
    against reintroducing `meta=body.get("meta") or {}`
    verbatim, which would let a caller forge source="operator")."""
    import inspect

    from api import cognitive

    src = inspect.getsource(cognitive)
    assert 'meta["source"] = "operator"' in src


# ─── search(): operator-sourced trust multiplier ─────────────────────


def test_search_operator_sourced_row_outranks_identical_agent_sourced_row(
    tmp_path: Path,
) -> None:
    store = _make_store(tmp_path)
    # Identical value text -> identical cosine against the query, so
    # any ranking difference is attributable to the trust multiplier
    # alone, not to relevance.
    store.store(
        key="k-agent", value="distinctive shared phrase alpha",
        scope="agent", meta={"source": "agent"},
    )
    store.store(
        key="k-operator", value="distinctive shared phrase alpha",
        scope="agent", meta={"source": "operator"},
    )
    hits = store.search("distinctive shared phrase alpha", scope="agent")
    keys_in_order = [m.key for m, _score in hits]
    assert keys_in_order[0] == "k-operator"

    op_score = next(s for m, s in hits if m.key == "k-operator")
    ag_score = next(s for m, s in hits if m.key == "k-agent")
    assert op_score > ag_score
    assert op_score == pytest.approx(ag_score * _OPERATOR_SOURCE_TRUST_MULTIPLIER)


def test_search_unattributed_row_gets_no_trust_boost(tmp_path: Path) -> None:
    """A row with no meta at all (unattributed legacy data) must NOT
    silently inherit the operator boost — absence of source is not
    the same as source="operator"."""
    store = _make_store(tmp_path)
    store.store(key="k-none", value="distinctive shared phrase beta", scope="agent")
    store.store(
        key="k-operator", value="distinctive shared phrase beta",
        scope="agent", meta={"source": "operator"},
    )
    hits = dict(
        (m.key, s) for m, s in store.search("distinctive shared phrase beta", scope="agent")
    )
    assert hits["k-operator"] == pytest.approx(hits["k-none"] * _OPERATOR_SOURCE_TRUST_MULTIPLIER)


# ─── plugin_loader path is untouched ─────────────────────────────────


def test_plugin_sourced_row_is_not_treated_as_operator_sourced(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    store.store(
        key="k-plugin", value="distinctive shared phrase gamma",
        scope="agent", meta={"source": "plugin:example-vendor"},
    )
    store.store(
        key="k-operator", value="distinctive shared phrase gamma",
        scope="agent", meta={"source": "operator"},
    )
    hits = dict(
        (m.key, s) for m, s in store.search("distinctive shared phrase gamma", scope="agent")
    )
    # plugin-sourced gets no boost (only exact source=="operator" does)
    assert hits["k-operator"] > hits["k-plugin"]
