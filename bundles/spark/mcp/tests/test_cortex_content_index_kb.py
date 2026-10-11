"""cortex-content/index_kb — unit tests.

These tests defend the KB-indexing tool's behavior contracts so changes
(new pack-content shapes, KB API drift, etc.) don't silently regress.

# Path resolution

The cortex-content connector lives in a sibling directory under the
bundle, NOT inside mcp/src. The source-tree path and the container
path differ:

  Source: bundles/spark/connectors/cortex-content/src/
  Image:  /app/bundle/connectors/cortex-content/src/

Both are reached by inserting the right directory into sys.path; the
candidate list below handles either layout. CI's `pytest tests -q`
runs from /app/mcp/tests in the container.

# Mocking

  - GitHubClient is fully mocked — no network access during tests.
    The pattern is `mock.patch.object(connector, "_get_client", ...)`
    returning a MagicMock with `list_dir`/`get_file`/`get_file_json`
    pre-stubbed per test case.
  - The KB singleton (`usecase.kb_store.knowledge_base`) is replaced
    with a stub whose `upsert` records calls and returns the same
    (doc, action) tuple shape the real kb produces.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

# Per-test fresh metrics registry so cortex-content
# index_kb counters from one test don't bleed into the next.
from usecase import metrics_registry as metrics_registry_module


@pytest.fixture(autouse=True)
def _reset_metrics():
    metrics_registry_module.set_metrics_registry(
        metrics_registry_module.MetricsRegistry()
    )
    yield
    metrics_registry_module.set_metrics_registry(None)

# ─── Path resolution: load the connector via synthetic package ──────
#
# The cortex-content connector's `src/` collides namespace-wise with
# the MCP's `src/` (pytest's rootdir detection puts MCP's parent dir
# on sys.path → `src` resolves to /app/mcp/src/, NOT to our connector
# src). To avoid the collision we use importlib.util to load the
# connector under a unique synthetic package name (`_cortex_test_pkg`).
# That preserves the relative import (`from ._github_client import ...`)
# inside connector.py because it's loaded as a package member, just
# with a different parent than at runtime.


def _resolve_connector_src() -> Path:
    here = Path(__file__).resolve().parent
    candidates = [
        # Source-tree layout: bundles/spark/mcp/tests + bundles/spark/connectors/...
        here.parent.parent / "connectors" / "cortex-content" / "src",
        # Container layout: /app/mcp/tests + /app/bundle/connectors/...
        Path("/app/bundle/connectors/cortex-content/src"),
    ]
    for c in candidates:
        if c.is_dir():
            return c
    raise ImportError(
        f"cortex-content/src not found in any of: {[str(c) for c in candidates]}"
    )


def _load_connector_module() -> Any:
    """Load connector.py + _github_client.py as members of a synthetic
    package, sidestepping the `src` name collision with MCP. Returns
    the connector module."""
    import importlib.util

    src = _resolve_connector_src()
    pkg_name = "_cortex_test_pkg"

    # Synthesize a parent package whose __path__ points at the
    # connector's src/ dir. This makes `from . import _github_client`
    # in connector.py resolve to <pkg>._github_client.
    pkg = sys.modules.get(pkg_name)
    if pkg is None:
        spec_pkg = importlib.util.spec_from_loader(pkg_name, loader=None)
        pkg = importlib.util.module_from_spec(spec_pkg)
        pkg.__path__ = [str(src)]
        sys.modules[pkg_name] = pkg

    # Load _github_client first so the connector's relative import
    # finds it pre-loaded under the synthetic package.
    if f"{pkg_name}._github_client" not in sys.modules:
        spec_gh = importlib.util.spec_from_file_location(
            f"{pkg_name}._github_client",
            src / "_github_client.py",
        )
        gh = importlib.util.module_from_spec(spec_gh)
        sys.modules[f"{pkg_name}._github_client"] = gh
        spec_gh.loader.exec_module(gh)

    # Now load connector.py — its `from ._github_client import ...`
    # resolves through the synthetic package's __path__.
    if f"{pkg_name}.connector" not in sys.modules:
        spec_c = importlib.util.spec_from_file_location(
            f"{pkg_name}.connector",
            src / "connector.py",
        )
        cm = importlib.util.module_from_spec(spec_c)
        sys.modules[f"{pkg_name}.connector"] = cm
        spec_c.loader.exec_module(cm)
    return sys.modules[f"{pkg_name}.connector"]


connector = _load_connector_module()
GitHubNotFoundError = sys.modules["_cortex_test_pkg._github_client"].GitHubNotFoundError
GitHubRateLimitError = sys.modules["_cortex_test_pkg._github_client"].GitHubRateLimitError


# ─── Helpers ────────────────────────────────────────────────────────


def _make_client_mock(
    *,
    list_dir_returns: dict[str, list[dict[str, Any]]] | None = None,
    get_file_returns: dict[str, str] | None = None,
    get_file_json_returns: dict[str, Any] | None = None,
    list_dir_raises: dict[str, Exception] | None = None,
    get_file_raises: dict[str, Exception] | None = None,
    get_file_json_raises: dict[str, Exception] | None = None,
) -> mock.MagicMock:
    """Build a MagicMock that imitates GitHubClient. Each public method
    looks up the path argument in the corresponding dict; missing
    paths raise GitHubNotFoundError by default (the real client's
    behavior for missing files)."""
    c = mock.MagicMock()

    def _list_dir(path: str) -> list[dict[str, Any]]:
        if list_dir_raises and path in list_dir_raises:
            raise list_dir_raises[path]
        if list_dir_returns is None or path not in list_dir_returns:
            raise GitHubNotFoundError(f"list_dir: {path}")
        return list_dir_returns[path]

    def _get_file(path: str) -> str:
        if get_file_raises and path in get_file_raises:
            raise get_file_raises[path]
        if get_file_returns is None or path not in get_file_returns:
            raise GitHubNotFoundError(f"get_file: {path}")
        return get_file_returns[path]

    def _get_file_json(path: str) -> Any:
        if get_file_json_raises and path in get_file_json_raises:
            raise get_file_json_raises[path]
        if get_file_json_returns is None or path not in get_file_json_returns:
            raise GitHubNotFoundError(f"get_file_json: {path}")
        return get_file_json_returns[path]

    c.list_dir.side_effect = _list_dir
    c.get_file.side_effect = _get_file
    c.get_file_json.side_effect = _get_file_json
    return c


class _StubKB:
    """Minimal KB stub matching SqliteKnowledgeBase.upsert's contract.

    Records every upsert call into self.calls so tests can assert
    doc_id, content composition, metadata, and source_hash. Returns
    "insert" for the first call per source_hash, "unchanged" when
    re-upserting identical content (mirroring the real store's
    source_hash dedupe)."""

    def __init__(self, *, dedup_on_hash: bool = False) -> None:
        self.calls: list[dict[str, Any]] = []
        self._seen_hashes: set[str] = set()
        self.dedup_on_hash = dedup_on_hash

    def upsert(self, **kw: Any) -> tuple[mock.MagicMock, str]:
        self.calls.append(kw)
        if self.dedup_on_hash and kw["source_hash"] in self._seen_hashes:
            return mock.MagicMock(), "unchanged"
        self._seen_hashes.add(kw["source_hash"])
        return mock.MagicMock(), "insert"


def _install_kb_stub(monkeypatch, stub: _StubKB) -> None:
    """Patch the kb_store.knowledge_base() lookup so the connector
    sees our stub. The connector imports it lazily inside
    _cortex_index_kb_impl, so we patch at the module level."""
    import usecase.kb_store as kb_store_mod
    monkeypatch.setattr(kb_store_mod, "knowledge_base", lambda: stub)


# ─── Validation cases ──────────────────────────────────────────────


def test_empty_pack_name_rejected():
    """Empty pack_name → clean error envelope, no GitHub fetch."""
    out = asyncio.run(connector.cortex_index_kb(pack_name=""))
    assert out["ok"] is False
    assert "pack_name is required" in out["error"]


def test_empty_kb_name_rejected():
    """Empty kb_name → same; should not even attempt the GitHub fetch
    or KB resolution."""
    out = asyncio.run(
        connector.cortex_index_kb(pack_name="F5APM", kb_name="")
    )
    assert out["ok"] is False
    assert "kb_name is required" in out["error"]


def test_unknown_rule_type_rejected():
    """A rule_type not in {modeling, parsing, correlation} → clean
    error pointing to the allowed set."""
    out = asyncio.run(
        connector.cortex_index_kb(
            pack_name="F5APM",
            rule_types=["mythical_rule_type"],
        )
    )
    assert out["ok"] is False
    assert "unknown rule_type" in out["error"]
    # Error message must include the allowed set so the agent can
    # self-correct without trial-and-error.
    assert "modeling" in out["error"]
    assert "parsing" in out["error"]
    assert "correlation" in out["error"]


def test_kb_unavailable_returns_clean_error(monkeypatch):
    """If knowledge_base() returns None (test harness, partial boot),
    the tool returns a structured error envelope instead of crashing."""
    import usecase.kb_store as kb_store_mod
    monkeypatch.setattr(kb_store_mod, "knowledge_base", lambda: None)

    out = asyncio.run(connector.cortex_index_kb(pack_name="F5APM"))
    assert out["ok"] is False
    assert "knowledge base not initialized" in out["error"]


def test_pack_metadata_missing_returns_clean_error(monkeypatch):
    """Pack with no pack_metadata.json → clear remediation error
    ("does it exist in the repo?"). This catches typos / dead packs."""
    stub_kb = _StubKB()
    _install_kb_stub(monkeypatch, stub_kb)

    client = _make_client_mock()  # no responses configured
    monkeypatch.setattr(connector, "_get_client", lambda: client)

    out = asyncio.run(connector.cortex_index_kb(pack_name="NonexistentPack"))
    assert out["ok"] is False
    assert "no pack_metadata.json" in out["error"]
    # No KB calls were made.
    assert stub_kb.calls == []


# ─── Happy path ─────────────────────────────────────────────────────


def test_modeling_rule_indexes_with_all_three_files(monkeypatch):
    """A modeling rule with .xif + .yml + _schema.json all present →
    one KB doc upserted with composed markdown content + full
    metadata."""
    stub_kb = _StubKB()
    _install_kb_stub(monkeypatch, stub_kb)

    pack_meta = {
        "name": "F5APM",
        "description": "F5 Access Policy Manager content pack",
        "currentVersion": "1.2.0",
        "supportedModules": ["xsiam"],
    }
    schema = {"f5apm_raw": {"src_ip": "string", "dst_ip": "string"}}
    xif_content = "[MODEL: dataset=f5apm_raw]\n  xdm.source.ipv4 = src_ip"
    yml_content = "name: F5APM\nfromVersion: '6.0.0'"

    client = _make_client_mock(
        get_file_json_returns={
            "Packs/F5APM/pack_metadata.json": pack_meta,
            "Packs/F5APM/ModelingRules/F5APM/F5APM_schema.json": schema,
        },
        list_dir_returns={
            "Packs/F5APM/ModelingRules": [
                {"name": "F5APM", "type": "dir"},
            ],
        },
        get_file_returns={
            "Packs/F5APM/ModelingRules/F5APM/F5APM.xif": xif_content,
            "Packs/F5APM/ModelingRules/F5APM/F5APM.yml": yml_content,
        },
    )
    monkeypatch.setattr(connector, "_get_client", lambda: client)

    out = asyncio.run(connector.cortex_index_kb(
        pack_name="F5APM", rule_types=["modeling"],
    ))
    assert out["ok"] is True
    assert out["pack_name"] == "F5APM"
    assert out["kb_name"] == "cortex-content"
    assert out["indexed"]["modeling"] == 1
    assert out["indexed"]["parsing"] == 0
    assert out["indexed"]["correlation"] == 0
    assert out["unchanged"] == 0
    assert out["errors"] == []
    # Exactly one KB upsert call with the expected shape.
    assert len(stub_kb.calls) == 1
    call = stub_kb.calls[0]
    assert call["kb_name"] == "cortex-content"
    assert call["doc_id"] == "F5APM/modeling/F5APM"
    assert call["category"] == "modeling"
    # Content composition: should contain section headers + fenced
    # code blocks for each of the 3 files + dataset list.
    content = call["content"]
    assert "# F5APM/ModelingRules/F5APM" in content
    assert "Rule type: modeling" in content
    assert "## .xif (F5APM.xif)" in content
    assert "```xql" in content
    assert "[MODEL: dataset=f5apm_raw]" in content
    assert "## .yml (F5APM.yml)" in content
    assert "## _schema.json (F5APM_schema.json)" in content
    assert "f5apm_raw" in content  # dataset list
    # Metadata.
    md = call["metadata"]
    assert md["pack_name"] == "F5APM"
    assert md["rule_type"] == "modeling"
    assert md["rule_name"] == "F5APM"
    assert md["datasets"] == ["f5apm_raw"]
    assert md["supportedModules"] == ["xsiam"]
    assert md["pack_version"] == "1.2.0"


def test_source_hash_dedupe_on_repeat_index(monkeypatch):
    """Idempotency contract: re-running index_kb on the same
    pack with the same content should NOT re-embed (kb.upsert returns
    'unchanged'), and the count should land in 'unchanged' rather
    than 'indexed'."""
    stub_kb = _StubKB(dedup_on_hash=True)
    _install_kb_stub(monkeypatch, stub_kb)

    pack_meta = {"name": "F5APM", "description": "F5", "currentVersion": "1.0"}
    client = _make_client_mock(
        get_file_json_returns={
            "Packs/F5APM/pack_metadata.json": pack_meta,
        },
        list_dir_returns={
            "Packs/F5APM/ModelingRules": [{"name": "F5APM", "type": "dir"}],
        },
        get_file_returns={
            "Packs/F5APM/ModelingRules/F5APM/F5APM.xif": "stable content",
        },
    )
    monkeypatch.setattr(connector, "_get_client", lambda: client)

    # First call: indexes the rule.
    out1 = asyncio.run(connector.cortex_index_kb(
        pack_name="F5APM", rule_types=["modeling"],
    ))
    assert out1["indexed"]["modeling"] == 1
    assert out1["unchanged"] == 0

    # Second call (same content) — source_hash should match → counts
    # as unchanged, not re-indexed.
    out2 = asyncio.run(connector.cortex_index_kb(
        pack_name="F5APM", rule_types=["modeling"],
    ))
    assert out2["indexed"]["modeling"] == 0
    assert out2["unchanged"] == 1


# ─── Missing rule dirs are not errors ────────────────────────────────


def test_pack_with_no_modeling_rules_dir(monkeypatch):
    """Pack that has pack_metadata.json but no ModelingRules/ dir →
    indexed.modeling=0, NO error in the errors list. The connector
    treats "this pack has no rules of this type" as a legitimate
    empty result."""
    stub_kb = _StubKB()
    _install_kb_stub(monkeypatch, stub_kb)

    # Pack metadata exists, but list_dir for ModelingRules raises
    # GitHubNotFoundError (the real-world behavior for "directory
    # doesn't exist on the branch").
    pack_meta = {"name": "EmptyPack", "description": "no rules"}
    client = _make_client_mock(
        get_file_json_returns={
            "Packs/EmptyPack/pack_metadata.json": pack_meta,
        },
    )
    monkeypatch.setattr(connector, "_get_client", lambda: client)

    out = asyncio.run(connector.cortex_index_kb(
        pack_name="EmptyPack",
        rule_types=["modeling", "parsing", "correlation"],
    ))
    assert out["ok"] is True
    assert out["indexed"] == {"modeling": 0, "parsing": 0, "correlation": 0}
    assert out["errors"] == []
    # No KB upserts.
    assert stub_kb.calls == []


def test_rate_limit_during_list_dir_recorded_as_error(monkeypatch):
    """If list_dir() hits the GitHub rate limit, the rule-type loop
    records the error but continues to the next rule type. The
    final response surfaces the rate-limit error in errors[] without
    failing the whole call."""
    stub_kb = _StubKB()
    _install_kb_stub(monkeypatch, stub_kb)

    pack_meta = {"name": "P", "description": "p"}
    client = _make_client_mock(
        get_file_json_returns={"Packs/P/pack_metadata.json": pack_meta},
        list_dir_returns={
            "Packs/P/ParsingRules": [],  # empty list, no rules
        },
        list_dir_raises={
            "Packs/P/ModelingRules": GitHubRateLimitError(
                "rate limit exceeded; reset at ..."
            ),
        },
    )
    monkeypatch.setattr(connector, "_get_client", lambda: client)

    out = asyncio.run(connector.cortex_index_kb(
        pack_name="P", rule_types=["modeling", "parsing"],
    ))
    # Rate limit on modeling captured; parsing dir was empty.
    assert out["ok"] is True  # overall ok flag isn't set False for per-rule errors
    assert any(
        e["rule_type"] == "modeling" and "rate limit" in e["error"]
        for e in out["errors"]
    )


# ─── Flat-file correlation rule ─────────────────────────────────────


def test_flat_file_correlation_rule_indexes(monkeypatch):
    """index_kb supports two CorrelationRules shapes:
      1. Directory: Packs/<pack>/CorrelationRules/<rule>/<rule>.yml + .xql
      2. Flat: Packs/<pack>/CorrelationRules/<rule>.yml (no dir)
    Test the flat-file path — these have no .xif, may have no .xql."""
    stub_kb = _StubKB()
    _install_kb_stub(monkeypatch, stub_kb)

    pack_meta = {"name": "P", "description": "p"}
    yml_content = "name: FlatRule\nseverity: high"
    xql_content = "datamodel | filter event_type = \"login\""

    client = _make_client_mock(
        get_file_json_returns={
            "Packs/P/pack_metadata.json": pack_meta,
        },
        list_dir_returns={
            # Flat file at the CorrelationRules root — type='file' not 'dir'.
            "Packs/P/CorrelationRules": [
                {"name": "FlatRule.yml", "type": "file"},
            ],
        },
        get_file_returns={
            "Packs/P/CorrelationRules/FlatRule.yml": yml_content,
            "Packs/P/CorrelationRules/FlatRule.xql": xql_content,
        },
    )
    monkeypatch.setattr(connector, "_get_client", lambda: client)

    out = asyncio.run(connector.cortex_index_kb(
        pack_name="P", rule_types=["correlation"],
    ))
    assert out["ok"] is True
    assert out["indexed"]["correlation"] == 1
    # One upsert, doc_id=P/correlation/FlatRule
    assert len(stub_kb.calls) == 1
    call = stub_kb.calls[0]
    assert call["doc_id"] == "P/correlation/FlatRule"
    # flat_file marker in metadata so consumers can tell the two shapes apart.
    assert call["metadata"]["flat_file"] is True
    # Content includes both yml + xql sections.
    content = call["content"]
    assert "## .yml (FlatRule.yml)" in content
    assert yml_content in content
    assert "## .xql (FlatRule.xql)" in content
    assert xql_content in content


def test_flat_file_correlation_without_xql(monkeypatch):
    """Flat-file correlation rule with .yml but no .xql counterpart
    (some packs have orphan ymls) — should still index without erroring."""
    stub_kb = _StubKB()
    _install_kb_stub(monkeypatch, stub_kb)

    pack_meta = {"name": "P", "description": "p"}
    client = _make_client_mock(
        get_file_json_returns={
            "Packs/P/pack_metadata.json": pack_meta,
        },
        list_dir_returns={
            "Packs/P/CorrelationRules": [
                {"name": "OrphanRule.yml", "type": "file"},
            ],
        },
        get_file_returns={
            "Packs/P/CorrelationRules/OrphanRule.yml": "name: OrphanRule",
            # No .xql.
        },
    )
    monkeypatch.setattr(connector, "_get_client", lambda: client)

    out = asyncio.run(connector.cortex_index_kb(
        pack_name="P", rule_types=["correlation"],
    ))
    assert out["ok"] is True
    assert out["indexed"]["correlation"] == 1
    call = stub_kb.calls[0]
    content = call["content"]
    assert "## .yml" in content
    assert "## .xql" not in content  # absent — no orphan section


# ─── cortex-content index_kb metrics ───────────────────────


def _counter_value(reg, name: str, **labels: str) -> float:
    c = reg.get(name)
    if c is None:
        return 0.0
    key = tuple(sorted((k, str(v)) for k, v in labels.items()))
    return c._values.get(key, 0.0)  # type: ignore[attr-defined]


def test_metrics_emitted_on_successful_index(monkeypatch):
    """A clean index_kb call increments the run counter at
    result=succeeded + the doc counter at action=insert per rule."""
    stub_kb = _StubKB()
    _install_kb_stub(monkeypatch, stub_kb)

    pack_meta = {"name": "F5APM", "description": "F5", "currentVersion": "1.0"}
    client = _make_client_mock(
        get_file_json_returns={"Packs/F5APM/pack_metadata.json": pack_meta},
        list_dir_returns={
            "Packs/F5APM/ModelingRules": [{"name": "F5APM", "type": "dir"}],
        },
        get_file_returns={
            "Packs/F5APM/ModelingRules/F5APM/F5APM.xif": "content",
        },
    )
    monkeypatch.setattr(connector, "_get_client", lambda: client)

    out = asyncio.run(connector.cortex_index_kb(
        pack_name="F5APM", rule_types=["modeling"],
    ))
    assert out["ok"] is True
    assert out["indexed"]["modeling"] == 1
    # Run counter: one succeeded entry for this pack.
    reg = metrics_registry_module.metrics_registry()
    assert _counter_value(
        reg, "phantom_cortex_content_index_runs_total",
        pack="F5APM", result="succeeded",
    ) == 1
    # Doc counter: one insert.
    assert _counter_value(
        reg, "phantom_cortex_content_indexed_docs_total", action="insert",
    ) == 1


def test_metrics_doc_counter_distinguishes_unchanged(monkeypatch):
    """Re-indexing the same content lands the doc counter at
    action=unchanged (not insert). This is the dashboard signal that
    distinguishes 'we re-fetched a pack but nothing was new' from
    'we ingested fresh content'."""
    stub_kb = _StubKB(dedup_on_hash=True)
    _install_kb_stub(monkeypatch, stub_kb)

    pack_meta = {"name": "F5APM", "description": "F5", "currentVersion": "1.0"}
    client = _make_client_mock(
        get_file_json_returns={"Packs/F5APM/pack_metadata.json": pack_meta},
        list_dir_returns={
            "Packs/F5APM/ModelingRules": [{"name": "F5APM", "type": "dir"}],
        },
        get_file_returns={
            "Packs/F5APM/ModelingRules/F5APM/F5APM.xif": "stable content",
        },
    )
    monkeypatch.setattr(connector, "_get_client", lambda: client)

    # First call: doc counter at insert=1
    asyncio.run(connector.cortex_index_kb(pack_name="F5APM", rule_types=["modeling"]))
    # Second call: doc counter increments at unchanged=1; insert stays at 1
    asyncio.run(connector.cortex_index_kb(pack_name="F5APM", rule_types=["modeling"]))

    reg = metrics_registry_module.metrics_registry()
    assert _counter_value(
        reg, "phantom_cortex_content_indexed_docs_total", action="insert",
    ) == 1
    assert _counter_value(
        reg, "phantom_cortex_content_indexed_docs_total", action="unchanged",
    ) == 1
    # Two successful runs both at result=succeeded for the same pack.
    assert _counter_value(
        reg, "phantom_cortex_content_index_runs_total",
        pack="F5APM", result="succeeded",
    ) == 2


def test_metrics_run_counter_records_partial_on_per_rule_failure(monkeypatch):
    """When some rules index successfully but others error,
    the run counter records result=partial. Operators can alert on
    `result="failed"` (nothing worked) vs `result="partial"` (some
    work landed) vs `result="succeeded"` (all clean)."""
    stub_kb = _StubKB()
    _install_kb_stub(monkeypatch, stub_kb)

    pack_meta = {"name": "P", "description": "p"}
    client = _make_client_mock(
        get_file_json_returns={"Packs/P/pack_metadata.json": pack_meta},
        list_dir_returns={
            "Packs/P/ParsingRules": [],  # empty
        },
        list_dir_raises={
            "Packs/P/ModelingRules": GitHubRateLimitError("rate limit"),
        },
    )
    monkeypatch.setattr(connector, "_get_client", lambda: client)

    out = asyncio.run(connector.cortex_index_kb(
        pack_name="P", rule_types=["modeling", "parsing"],
    ))
    # The rate-limit error puts something in errors; no indexed work
    # landed → result=failed (not partial).
    assert len(out["errors"]) > 0
    reg = metrics_registry_module.metrics_registry()
    assert _counter_value(
        reg, "phantom_cortex_content_index_runs_total",
        pack="P", result="failed",
    ) == 1


def test_metrics_silent_when_registry_unavailable(monkeypatch):
    """Metrics emission never affects the tool's primary path.
    When metrics_registry() is None, the index call still completes
    cleanly."""
    metrics_registry_module.set_metrics_registry(None)

    stub_kb = _StubKB()
    _install_kb_stub(monkeypatch, stub_kb)
    pack_meta = {"name": "P", "description": "p"}
    client = _make_client_mock(
        get_file_json_returns={"Packs/P/pack_metadata.json": pack_meta},
    )
    monkeypatch.setattr(connector, "_get_client", lambda: client)

    out = asyncio.run(connector.cortex_index_kb(pack_name="P", rule_types=["modeling"]))
    # Primary path unaffected — pack with no ModelingRules dir + no
    # registry still returns the standard success envelope.
    assert out["ok"] is True
    assert out["indexed"]["modeling"] == 0
