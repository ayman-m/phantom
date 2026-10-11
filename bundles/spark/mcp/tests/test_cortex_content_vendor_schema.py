"""cortex-content/vendor schema extraction — unit tests.

The marketplace data-sources feature reverse-engineers each Cortex
ModelingRule into its raw vendor field inventory by reading
`Packs/<pack>/ModelingRules/<rule>/<rule>_schema.json`. Three tools
power this: extract one rule's schema, extract one pack's logo, and
roll both up across the entire content repo. These tests defend each
contract independently so a regression in any one of them fails loud.

# Path resolution + module loading

We reuse the synthetic-package loading trick from
`test_cortex_content_index_kb.py`: the connector lives under
`bundles/spark/connectors/cortex-content/src/` and uses a relative
import (`from ._github_client import ...`), but its `src/` dir name
collides with MCP's own `src/` already on sys.path. The workaround is
`importlib.util.spec_from_file_location` under a unique synthetic
package name (`_cortex_test_pkg`). Both test files share the cache
in sys.modules, so module loading is a no-op the second time.

# Mocking

GitHubClient is fully mocked via `_make_client_mock` — no network
during tests. Each test stubs the specific `list_dir` / `get_file` /
`get_file_json` paths it needs; missing paths raise
`GitHubNotFoundError` so we exercise the "missing files don't crash"
paths uniformly.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any
from unittest import mock

import pytest


# ─── Path resolution: load the connector via synthetic package ──────
# (Identical to test_cortex_content_index_kb.py. Sharing sys.modules
# cache means whichever test file loads first does the actual import
# work; the second one's _load_connector_module() returns the cached
# module immediately.)


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
    import importlib.util

    src = _resolve_connector_src()
    pkg_name = "_cortex_test_pkg"

    pkg = sys.modules.get(pkg_name)
    if pkg is None:
        spec_pkg = importlib.util.spec_from_loader(pkg_name, loader=None)
        pkg = importlib.util.module_from_spec(spec_pkg)
        pkg.__path__ = [str(src)]
        sys.modules[pkg_name] = pkg

    if f"{pkg_name}._github_client" not in sys.modules:
        spec_gh = importlib.util.spec_from_file_location(
            f"{pkg_name}._github_client",
            src / "_github_client.py",
        )
        gh = importlib.util.module_from_spec(spec_gh)
        sys.modules[f"{pkg_name}._github_client"] = gh
        spec_gh.loader.exec_module(gh)

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


# ─── GitHubClient mock builder (same as sibling test file) ──────────


def _make_client_mock(
    *,
    list_dir_returns: dict[str, list[dict[str, Any]]] | None = None,
    get_file_returns: dict[str, str] | None = None,
    get_file_json_returns: dict[str, Any] | None = None,
    list_dir_raises: dict[str, Exception] | None = None,
    get_file_raises: dict[str, Exception] | None = None,
    get_file_json_raises: dict[str, Exception] | None = None,
    owner: str = "demisto",
    repo: str = "content",
    branch: str = "master",
) -> mock.MagicMock:
    """Build a MagicMock imitating GitHubClient. Missing paths raise
    GitHubNotFoundError by default (real client behavior). Owner/repo/
    branch attrs are set so cortex_extract_vendor_logo can build the
    logo URL deterministically."""
    c = mock.MagicMock()
    c.owner = owner
    c.repo = repo
    c.branch = branch

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


# Common schema fixtures used across tests
_META_FIELD = {"type": "string", "is_array": False}

_STRUCTURED_SCHEMA = {
    "fortigate_raw": {
        "_id": _META_FIELD,
        "_time": {"type": "datetime", "is_array": False},
        "_raw_log": _META_FIELD,
        "_vendor": _META_FIELD,
        "_product": _META_FIELD,
        "_collector_name": _META_FIELD,
        "srcip": _META_FIELD,
        "dstip": _META_FIELD,
        "action": _META_FIELD,
        "user": _META_FIELD,
        "groups": {"type": "string", "is_array": True},
    },
}

_RAWLOG_ONLY_SCHEMA = {
    # F5APM-style: nothing but meta fields → extraction uses regex on _raw_log.
    "f5apm_raw": {
        "_id": _META_FIELD,
        "_time": {"type": "datetime", "is_array": False},
        "_raw_log": _META_FIELD,
        "_vendor": _META_FIELD,
        "_product": _META_FIELD,
        "_collector_name": _META_FIELD,
    },
}


# ───────────────────────────────────────────────────────────────────
# cortex_extract_vendor_schema
# ───────────────────────────────────────────────────────────────────


def test_extract_schema_empty_pack_rejected():
    """Empty pack_name → clean error envelope, no GitHub fetch."""
    out = asyncio.run(connector.cortex_extract_vendor_schema(
        pack_name="", rule_name="X",
    ))
    assert out["ok"] is False
    assert "pack_name and rule_name are required" in out["error"]


def test_extract_schema_empty_rule_rejected():
    out = asyncio.run(connector.cortex_extract_vendor_schema(
        pack_name="FortiGate", rule_name="",
    ))
    assert out["ok"] is False
    assert "pack_name and rule_name are required" in out["error"]


def test_extract_schema_missing_returns_clean_error(monkeypatch):
    """Schema.json missing → ok=False + remediation hint pointing at
    the exact path tried. Critical for the marketplace catalog when a
    pack ships a ModelingRules dir but no schema (rare but seen)."""
    client = _make_client_mock()  # all paths raise NotFound
    monkeypatch.setattr(connector, "_get_client", lambda: client)

    out = asyncio.run(connector.cortex_extract_vendor_schema(
        pack_name="FortiGate", rule_name="FortiGate_1_3",
    ))
    assert out["ok"] is False
    assert "not found" in out["error"]
    assert "Packs/FortiGate/ModelingRules/FortiGate_1_3/FortiGate_1_3_schema.json" in out["error"]


def test_extract_schema_non_dict_rejected(monkeypatch):
    """If the file exists but isn't a JSON object (e.g. ships as a
    list or string), the tool must not crash on .items() — it should
    return a structured error."""
    client = _make_client_mock(
        get_file_json_returns={
            "Packs/Pack/ModelingRules/Rule/Rule_schema.json": ["not", "an", "object"],
        },
    )
    monkeypatch.setattr(connector, "_get_client", lambda: client)

    out = asyncio.run(connector.cortex_extract_vendor_schema(
        pack_name="Pack", rule_name="Rule",
    ))
    assert out["ok"] is False
    assert "is not an object" in out["error"]


def test_extract_schema_structured_pack_has_vendor_fields(monkeypatch):
    """Happy path: FortiGate-style schema with srcip/dstip/action/user
    → is_structured=True; non_meta_field_count counts the 5 real
    vendor fields, ignoring the 6 meta fields."""
    client = _make_client_mock(
        get_file_json_returns={
            "Packs/FortiGate/ModelingRules/FortiGate_1_3/FortiGate_1_3_schema.json": _STRUCTURED_SCHEMA,
        },
    )
    monkeypatch.setattr(connector, "_get_client", lambda: client)

    out = asyncio.run(connector.cortex_extract_vendor_schema(
        pack_name="FortiGate", rule_name="FortiGate_1_3",
    ))
    assert out["ok"] is True
    assert out["pack_name"] == "FortiGate"
    assert out["rule_name"] == "FortiGate_1_3"
    assert out["is_structured"] is True
    assert "fortigate_raw" in out["datasets"]
    ds = out["datasets"]["fortigate_raw"]
    # 6 meta fields + 5 vendor fields = 11 total
    assert ds["field_count"] == 11
    assert ds["non_meta_field_count"] == 5
    assert ds["is_rawlog_only"] is False
    # Array field metadata preserved
    groups_entry = next(f for f in ds["fields"] if f["name"] == "groups")
    assert groups_entry["is_array"] is True
    assert groups_entry["type"] == "string"
    # Non-array fields default to is_array=False
    srcip_entry = next(f for f in ds["fields"] if f["name"] == "srcip")
    assert srcip_entry["is_array"] is False
    # Total field count rolls up across datasets (just one here)
    assert out["total_field_count"] == 11


def test_extract_schema_rawlog_only_pack(monkeypatch):
    """F5APM-style schema: meta fields only → is_rawlog_only=True per
    dataset + is_structured=False overall. This is the signal the
    marketplace UI uses to mark a pack as needing regex extraction."""
    client = _make_client_mock(
        get_file_json_returns={
            "Packs/F5APM/ModelingRules/F5APM/F5APM_schema.json": _RAWLOG_ONLY_SCHEMA,
        },
    )
    monkeypatch.setattr(connector, "_get_client", lambda: client)

    out = asyncio.run(connector.cortex_extract_vendor_schema(
        pack_name="F5APM", rule_name="F5APM",
    ))
    assert out["ok"] is True
    assert out["is_structured"] is False
    ds = out["datasets"]["f5apm_raw"]
    assert ds["field_count"] == 6
    assert ds["non_meta_field_count"] == 0
    assert ds["is_rawlog_only"] is True


def test_extract_schema_mixed_datasets_is_structured(monkeypatch):
    """One pack with multiple datasets where one is rawlog-only + one
    is structured → is_structured=True (any structured dataset wins).
    Counts surface per-dataset so the UI can render the mixed state."""
    mixed = {
        "ds_struct": {
            "_raw_log": _META_FIELD,
            "vendor_field": _META_FIELD,
        },
        "ds_rawlog": {
            "_raw_log": _META_FIELD,
            "_id": _META_FIELD,
        },
    }
    client = _make_client_mock(
        get_file_json_returns={
            "Packs/Multi/ModelingRules/Multi/Multi_schema.json": mixed,
        },
    )
    monkeypatch.setattr(connector, "_get_client", lambda: client)

    out = asyncio.run(connector.cortex_extract_vendor_schema(
        pack_name="Multi", rule_name="Multi",
    ))
    assert out["ok"] is True
    assert out["is_structured"] is True
    assert out["datasets"]["ds_struct"]["is_rawlog_only"] is False
    assert out["datasets"]["ds_rawlog"]["is_rawlog_only"] is True
    # Two datasets, 2 fields each = 4 total
    assert out["total_field_count"] == 4


def test_extract_schema_handles_string_type_legacy_form(monkeypatch):
    """Older pack schemas used a bare string as the field type instead
    of a `{type, is_array}` object. The extractor must still parse
    these — defaulting is_array=False — so we don't lose coverage on
    historical packs."""
    legacy = {
        "old_ds": {
            "src": "string",
            "count": "int",
            "_raw_log": "string",
        },
    }
    client = _make_client_mock(
        get_file_json_returns={
            "Packs/Old/ModelingRules/Old/Old_schema.json": legacy,
        },
    )
    monkeypatch.setattr(connector, "_get_client", lambda: client)

    out = asyncio.run(connector.cortex_extract_vendor_schema(
        pack_name="Old", rule_name="Old",
    ))
    assert out["ok"] is True
    fields = {f["name"]: f for f in out["datasets"]["old_ds"]["fields"]}
    assert fields["src"]["type"] == "string"
    assert fields["src"]["is_array"] is False
    assert fields["count"]["type"] == "int"
    # _raw_log is meta; src + count count as non-meta
    assert out["datasets"]["old_ds"]["non_meta_field_count"] == 2


def test_extract_schema_malformed_dataset_entry_skipped(monkeypatch):
    """Defensive: if one dataset's value is malformed (e.g. a string,
    not a dict), skip it rather than crashing on .items()."""
    malformed = {
        "good_ds": {"field_a": _META_FIELD},
        "bad_ds": "this should be a dict but isn't",
    }
    client = _make_client_mock(
        get_file_json_returns={
            "Packs/X/ModelingRules/X/X_schema.json": malformed,
        },
    )
    monkeypatch.setattr(connector, "_get_client", lambda: client)

    out = asyncio.run(connector.cortex_extract_vendor_schema(
        pack_name="X", rule_name="X",
    ))
    assert out["ok"] is True
    assert "good_ds" in out["datasets"]
    assert "bad_ds" not in out["datasets"]
    assert out["total_field_count"] == 1


# ───────────────────────────────────────────────────────────────────
# cortex_extract_vendor_logo
# ───────────────────────────────────────────────────────────────────


def test_extract_logo_empty_pack_rejected():
    out = asyncio.run(connector.cortex_extract_vendor_logo(pack_name=""))
    assert out["ok"] is False
    assert "pack_name is required" in out["error"]


def test_extract_logo_finds_svg_first(monkeypatch):
    """Preferred path: Packs/<pack>/Integrations/<int>/<int>_dark.svg.
    SVG wins over PNG even if both exist because SVG scales + is
    theme-friendly."""
    client = _make_client_mock(
        list_dir_returns={
            "Packs/FortiGate/Integrations": [
                {"name": "FortiGate", "type": "dir"},
            ],
        },
        get_file_returns={
            "Packs/FortiGate/Integrations/FortiGate/FortiGate_dark.svg": "<svg>...</svg>",
            # PNG exists too but should NOT be picked (SVG wins)
            "Packs/FortiGate/Integrations/FortiGate/FortiGate_image.png": "binary",
        },
    )
    monkeypatch.setattr(connector, "_get_client", lambda: client)

    out = asyncio.run(connector.cortex_extract_vendor_logo(pack_name="FortiGate"))
    assert out["ok"] is True
    assert out["logo_type"] == "svg"
    assert out["source_path"] == "Packs/FortiGate/Integrations/FortiGate/FortiGate_dark.svg"
    # Logo URL is always the Phantom-local serving route — bytes stream
    # via the agent's /api/agent/data-sources/logo/<pack> handler.
    assert out["logo_url"] == "/api/agent/data-sources/logo/FortiGate"
    # searched_paths should list the SVG (loop broke before trying PNG)
    assert "Packs/FortiGate/Integrations/FortiGate/FortiGate_dark.svg" in out["searched_paths"]


def test_extract_logo_falls_back_to_png(monkeypatch):
    """SVG missing → tool tries PNG next."""
    client = _make_client_mock(
        list_dir_returns={
            "Packs/FortiGate/Integrations": [{"name": "FortiGate", "type": "dir"}],
        },
        get_file_returns={
            # Only PNG exists
            "Packs/FortiGate/Integrations/FortiGate/FortiGate_image.png": "binary",
        },
    )
    monkeypatch.setattr(connector, "_get_client", lambda: client)

    out = asyncio.run(connector.cortex_extract_vendor_logo(pack_name="FortiGate"))
    assert out["ok"] is True
    assert out["logo_type"] == "png"
    assert out["source_path"].endswith("_image.png")
    # Both candidates appear in searched_paths
    assert any("_dark.svg" in p for p in out["searched_paths"])
    assert any("_image.png" in p for p in out["searched_paths"])


def test_extract_logo_falls_back_to_author_image(monkeypatch):
    """Modeling-rule-only pack (no Integrations dir): falls back to
    Packs/<pack>/Author_image.png. F5APM is the canonical example —
    no integrations because it just ships modeling rules for an
    external collector."""
    client = _make_client_mock(
        # Integrations dir doesn't exist (NotFound from mock)
        get_file_returns={
            "Packs/F5APM/Author_image.png": "binary",
        },
    )
    monkeypatch.setattr(connector, "_get_client", lambda: client)

    out = asyncio.run(connector.cortex_extract_vendor_logo(pack_name="F5APM"))
    assert out["ok"] is True
    assert out["logo_type"] == "png"
    assert out["source_path"] == "Packs/F5APM/Author_image.png"
    assert "Packs/F5APM/Author_image.png" in out["searched_paths"]


def test_extract_logo_not_found_returns_null(monkeypatch):
    """Pack with no SVG, no PNG, no Author_image — ok=True but
    logo_url=None. The UI shows a placeholder; we don't fail the
    whole pack just because there's no logo."""
    client = _make_client_mock(
        list_dir_returns={
            "Packs/NoLogo/Integrations": [{"name": "NoLogo", "type": "dir"}],
        },
        # No get_file_returns means everything 404s
    )
    monkeypatch.setattr(connector, "_get_client", lambda: client)

    out = asyncio.run(connector.cortex_extract_vendor_logo(pack_name="NoLogo"))
    assert out["ok"] is True
    assert out["logo_url"] is None
    assert out["logo_type"] is None
    assert out["source_path"] is None
    # We tried at least one path
    assert len(out["searched_paths"]) > 0


def test_extract_logo_tries_each_integration_in_order(monkeypatch):
    """Multi-integration packs (e.g. AzureLogAnalytics with several
    integrations under Integrations/): tries the first integration's
    SVG, then its PNG, then the next integration's SVG, ... until
    one matches."""
    client = _make_client_mock(
        list_dir_returns={
            "Packs/AzureLA/Integrations": [
                {"name": "AzureLAA", "type": "dir"},  # alphabetical first
                {"name": "AzureLAB", "type": "dir"},
            ],
        },
        get_file_returns={
            # First integration: nothing
            # Second integration: SVG present
            "Packs/AzureLA/Integrations/AzureLAB/AzureLAB_dark.svg": "<svg/>",
        },
    )
    monkeypatch.setattr(connector, "_get_client", lambda: client)

    out = asyncio.run(connector.cortex_extract_vendor_logo(pack_name="AzureLA"))
    assert out["ok"] is True
    assert out["logo_type"] == "svg"
    assert "AzureLAB_dark.svg" in out["source_path"]
    # Should have tried AzureLAA's SVG + PNG before landing on AzureLAB
    assert any("AzureLAA_dark.svg" in p for p in out["searched_paths"])
    assert any("AzureLAA_image.png" in p for p in out["searched_paths"])


# ───────────────────────────────────────────────────────────────────
# cortex_extract_vendor_catalog
# ───────────────────────────────────────────────────────────────────


def _make_catalog_client(
    *,
    pack_names: list[str],
    pack_metas: dict[str, dict[str, Any]],
    pack_rules: dict[str, list[str]],
    pack_schemas: dict[str, dict[str, Any]],
    pack_logos: dict[str, str] | None = None,
) -> mock.MagicMock:
    """Build a catalog-sized mock client. The catalog walks many
    paths; this helper consolidates the boilerplate so each test
    just declares its pack roster + metadata."""
    list_dir: dict[str, list[dict[str, Any]]] = {
        "Packs": [{"name": n, "type": "dir"} for n in pack_names],
    }
    get_file_json: dict[str, Any] = {}
    get_file: dict[str, str] = {}

    for p in pack_names:
        # pack metadata
        if p in pack_metas:
            get_file_json[f"Packs/{p}/pack_metadata.json"] = pack_metas[p]
        # modeling rules dir
        rules = pack_rules.get(p, [])
        if rules:
            list_dir[f"Packs/{p}/ModelingRules"] = [
                {"name": r, "type": "dir"} for r in rules
            ]
        # schema per rule
        for r in rules:
            key = (p, r)
            if key in pack_schemas:
                get_file_json[f"Packs/{p}/ModelingRules/{r}/{r}_schema.json"] = pack_schemas[key]
        # Logo: skip Integrations entirely + put a fake Author_image.png
        # so the catalog gets a non-null logo url per pack without
        # exercising the integration-listing branch.
        if pack_logos and p in pack_logos:
            get_file[f"Packs/{p}/Author_image.png"] = pack_logos[p]

    return _make_client_mock(
        list_dir_returns=list_dir,
        get_file_returns=get_file,
        get_file_json_returns=get_file_json,
    )


def test_catalog_filters_to_xsiam_packs(monkeypatch):
    """xsiam_only=True (the default): packs whose supportedModules
    don't include 'xsiam' are skipped before scanning their rules.
    The catalog is limited to XSIAM-capable packs."""
    client = _make_catalog_client(
        pack_names=["FortiGate", "SoarOnly"],
        pack_metas={
            "FortiGate": {
                "name": "FortiGate",
                "supportedModules": ["xsiam", "xsoar"],
                "description": "FortiGate firewall logs",
                "currentVersion": "1.2.0",
            },
            "SoarOnly": {
                "name": "SoarOnly",
                "supportedModules": ["xsoar"],  # no xsiam → filtered out
                "description": "SOAR-only pack",
            },
        },
        pack_rules={
            "FortiGate": ["FortiGate_1_3"],
            "SoarOnly": ["SoarOnly"],
        },
        pack_schemas={
            ("FortiGate", "FortiGate_1_3"): _STRUCTURED_SCHEMA,
            ("SoarOnly", "SoarOnly"): _STRUCTURED_SCHEMA,
        },
        pack_logos={"FortiGate": "binary", "SoarOnly": "binary"},
    )
    monkeypatch.setattr(connector, "_get_client", lambda: client)

    out = asyncio.run(connector.cortex_extract_vendor_catalog(
        xsiam_only=True, include_rawlog=True, pack_limit=0,
    ))
    assert out["ok"] is True
    # Only FortiGate (xsiam-tagged) made the cut
    assert out["packs_scanned"] == 1
    assert all(r["pack_name"] == "FortiGate" for r in out["rows"])
    # supported_modules surfaces unchanged
    assert "xsiam" in out["rows"][0]["supported_modules"]


def test_catalog_xsiam_only_false_includes_all(monkeypatch):
    """xsiam_only=False: SOAR-only packs are included too."""
    client = _make_catalog_client(
        pack_names=["FortiGate", "SoarOnly"],
        pack_metas={
            "FortiGate": {"name": "FortiGate", "supportedModules": ["xsiam"]},
            "SoarOnly": {"name": "SoarOnly", "supportedModules": ["xsoar"]},
        },
        pack_rules={
            "FortiGate": ["FortiGate_1_3"],
            "SoarOnly": ["SoarOnly"],
        },
        pack_schemas={
            ("FortiGate", "FortiGate_1_3"): _STRUCTURED_SCHEMA,
            ("SoarOnly", "SoarOnly"): _STRUCTURED_SCHEMA,
        },
    )
    monkeypatch.setattr(connector, "_get_client", lambda: client)

    out = asyncio.run(connector.cortex_extract_vendor_catalog(
        xsiam_only=False, include_rawlog=True, pack_limit=0,
    ))
    assert out["ok"] is True
    assert out["packs_scanned"] == 2
    pack_names_in_rows = {r["pack_name"] for r in out["rows"]}
    assert pack_names_in_rows == {"FortiGate", "SoarOnly"}


def test_catalog_include_rawlog_false_excludes_rawlog_rows(monkeypatch):
    """include_rawlog=False: rawlog-only datasets are counted in
    rawlog_rules but NOT emitted as rows. structured_rules counts
    structured ones regardless. The UI uses this to show only
    structured packs."""
    client = _make_catalog_client(
        pack_names=["FortiGate", "F5APM"],
        pack_metas={
            "FortiGate": {"name": "FortiGate", "supportedModules": ["xsiam"]},
            "F5APM": {"name": "F5APM", "supportedModules": ["xsiam"]},
        },
        pack_rules={
            "FortiGate": ["FortiGate_1_3"],
            "F5APM": ["F5APM"],
        },
        pack_schemas={
            ("FortiGate", "FortiGate_1_3"): _STRUCTURED_SCHEMA,
            ("F5APM", "F5APM"): _RAWLOG_ONLY_SCHEMA,
        },
    )
    monkeypatch.setattr(connector, "_get_client", lambda: client)

    out = asyncio.run(connector.cortex_extract_vendor_catalog(
        xsiam_only=True, include_rawlog=False, pack_limit=0,
    ))
    assert out["ok"] is True
    # Both packs scanned (had ModelingRules dirs); counts reflect both
    assert out["packs_scanned"] == 2
    assert out["structured_rules"] == 1
    assert out["rawlog_rules"] == 1
    # But only the structured row was emitted
    assert len(out["rows"]) == 1
    assert out["rows"][0]["pack_name"] == "FortiGate"
    assert out["rows"][0]["is_rawlog_only"] is False


def test_catalog_pack_limit_caps_processing(monkeypatch):
    """pack_limit > 0: caps the number of packs walked. Tests pass
    pack_limit=1 so only the first (alphabetically) lands."""
    client = _make_catalog_client(
        pack_names=["AAA_first", "ZZZ_last"],
        pack_metas={
            "AAA_first": {"name": "AAA_first", "supportedModules": ["xsiam"]},
            "ZZZ_last": {"name": "ZZZ_last", "supportedModules": ["xsiam"]},
        },
        pack_rules={
            "AAA_first": ["AAA_first"],
            "ZZZ_last": ["ZZZ_last"],
        },
        pack_schemas={
            ("AAA_first", "AAA_first"): _STRUCTURED_SCHEMA,
            ("ZZZ_last", "ZZZ_last"): _STRUCTURED_SCHEMA,
        },
    )
    monkeypatch.setattr(connector, "_get_client", lambda: client)

    out = asyncio.run(connector.cortex_extract_vendor_catalog(
        xsiam_only=True, include_rawlog=True, pack_limit=1,
    ))
    assert out["ok"] is True
    assert out["packs_scanned"] == 1
    assert out["rows"][0]["pack_name"] == "AAA_first"
    # filter dict echoes back the params for debug
    assert out["filter"]["pack_limit"] == 1


def test_catalog_skips_pack_without_modeling_rules_dir(monkeypatch):
    """A pack with pack_metadata.json but no ModelingRules/ dir is
    skipped — doesn't count in packs_scanned, no rows emitted, no
    error raised. Many SOAR packs have no modeling rules; this is
    not a failure mode."""
    client = _make_catalog_client(
        pack_names=["FortiGate", "NoRules"],
        pack_metas={
            "FortiGate": {"name": "FortiGate", "supportedModules": ["xsiam"]},
            "NoRules": {"name": "NoRules", "supportedModules": ["xsiam"]},
        },
        pack_rules={"FortiGate": ["FortiGate_1_3"]},  # NoRules → empty list = no dir
        pack_schemas={("FortiGate", "FortiGate_1_3"): _STRUCTURED_SCHEMA},
    )
    monkeypatch.setattr(connector, "_get_client", lambda: client)

    out = asyncio.run(connector.cortex_extract_vendor_catalog(
        xsiam_only=True, include_rawlog=True, pack_limit=0,
    ))
    assert out["ok"] is True
    assert out["packs_scanned"] == 1
    pack_names_in_rows = {r["pack_name"] for r in out["rows"]}
    assert pack_names_in_rows == {"FortiGate"}


def test_catalog_row_shape_contains_all_marketplace_fields(monkeypatch):
    """Each row must carry every field the marketplace UI needs:
    pack/rule/dataset names, counts, rawlog flag, logo, modules,
    description, version. If any of these drift the UI silently
    breaks; the test pins the contract."""
    client = _make_catalog_client(
        pack_names=["FortiGate"],
        pack_metas={
            "FortiGate": {
                "name": "FortiGate",
                "supportedModules": ["xsiam"],
                "description": "FortiGate firewall logs",
                "currentVersion": "1.2.0",
            },
        },
        pack_rules={"FortiGate": ["FortiGate_1_3"]},
        pack_schemas={("FortiGate", "FortiGate_1_3"): _STRUCTURED_SCHEMA},
        pack_logos={"FortiGate": "binary"},
    )
    monkeypatch.setattr(connector, "_get_client", lambda: client)

    out = asyncio.run(connector.cortex_extract_vendor_catalog(
        xsiam_only=True, include_rawlog=True, pack_limit=0,
    ))
    assert out["ok"] is True
    assert len(out["rows"]) == 1
    row = out["rows"][0]
    # Every key the UI consumes
    assert row["pack_name"] == "FortiGate"
    assert row["rule_name"] == "FortiGate_1_3"
    assert row["dataset_name"] == "fortigate_raw"
    assert row["field_count"] == 11
    assert row["non_meta_field_count"] == 5
    assert row["is_rawlog_only"] is False
    assert row["logo_url"] == "/api/agent/data-sources/logo/FortiGate"
    assert row["logo_type"] == "png"
    assert row["supported_modules"] == ["xsiam"]
    assert row["pack_description"] == "FortiGate firewall logs"
    assert row["pack_version"] == "1.2.0"
