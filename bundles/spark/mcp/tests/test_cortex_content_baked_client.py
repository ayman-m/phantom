"""Tests for cortex-content/_baked_client — offline backend.

Covers the drop-in replacement for GitHubClient that reads from the
pre-fetched baked/ directory committed to the repo. The shape of
BakedClient's three public methods (list_dir, get_file, get_file_json)
must match GitHubClient's exactly + the error semantics (raise
GitHubNotFoundError on missing path) must match too — these are the
behaviors the connector + the API layer depend on.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


# Reuse the synthetic-package loader from the existing cortex-content tests
def _resolve_connector_src() -> Path:
    here = Path(__file__).resolve().parent
    candidates = [
        here.parent.parent / "connectors" / "cortex-content" / "src",
        Path("/app/bundle/connectors/cortex-content/src"),
    ]
    for c in candidates:
        if c.is_dir():
            return c
    raise ImportError("cortex-content/src not found")


def _load_baked_client():
    """Load _baked_client.py as a synthetic-package member so its
    relative import (`from ._github_client import ...`) resolves."""
    import importlib.util
    import types

    src = _resolve_connector_src()
    pkg_name = "_cortex_test_pkg"

    pkg = sys.modules.get(pkg_name)
    if pkg is None:
        pkg = types.ModuleType(pkg_name)
        pkg.__path__ = [str(src)]
        sys.modules[pkg_name] = pkg

    # _github_client must be available for _baked_client's relative import
    gh_key = f"{pkg_name}._github_client"
    if gh_key not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            gh_key, src / "_github_client.py"
        )
        gh = importlib.util.module_from_spec(spec)
        sys.modules[gh_key] = gh
        spec.loader.exec_module(gh)

    bc_key = f"{pkg_name}._baked_client"
    if bc_key not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            bc_key, src / "_baked_client.py"
        )
        bc = importlib.util.module_from_spec(spec)
        sys.modules[bc_key] = bc
        spec.loader.exec_module(bc)
    return sys.modules[bc_key], sys.modules[gh_key]


baked_mod, github_mod = _load_baked_client()
BakedClient = baked_mod.BakedClient
GitHubNotFoundError = github_mod.GitHubNotFoundError


# ── Fixtures ──────────────────────────────────────────────────────


@pytest.fixture
def baked_root(tmp_path: Path) -> Path:
    """Build a tiny baked tree on disk that mirrors the production layout."""
    root = tmp_path / "baked"
    # Manifest
    (root / "Packs").mkdir(parents=True)
    (root / "_manifest.json").write_text(
        json.dumps({"upstream_sha": "abc123", "packs_baked": 1})
    )
    (root / "catalog.json").write_text(
        json.dumps({"ok": True, "rows": [], "packs_scanned": 1})
    )
    # FortiGate pack with one modeling rule + one logo
    pack = root / "Packs" / "FortiGate"
    pack.mkdir()
    (pack / "pack_metadata.json").write_text(
        json.dumps(
            {
                "name": "FortiGate",
                "currentVersion": "1.2.3",
                "supportedModules": ["xsiam"],
                "description": "FortiGate firewall logs",
            }
        )
    )
    mr_dir = pack / "ModelingRules" / "FortiGate_1_3"
    mr_dir.mkdir(parents=True)
    (mr_dir / "FortiGate_1_3_schema.json").write_text(
        json.dumps(
            {
                "fortinet_fortigate_raw": {
                    "_raw_log": {"type": "string", "is_array": False},
                    "srcip": {"type": "string", "is_array": False},
                    "dstip": {"type": "string", "is_array": False},
                }
            }
        )
    )
    int_dir = pack / "Integrations" / "FortiGate"
    int_dir.mkdir(parents=True)
    (int_dir / "FortiGate_dark.svg").write_text("<svg/>")
    return root


# ── Behavior: list_dir ───────────────────────────────────────────


def test_list_dir_returns_pack_children(baked_root: Path) -> None:
    c = BakedClient(baked_root)
    entries = c.list_dir("Packs/FortiGate")
    names = {e["name"]: e["type"] for e in entries}
    assert names["pack_metadata.json"] == "file"
    assert names["ModelingRules"] == "dir"
    assert names["Integrations"] == "dir"


def test_list_dir_returns_entries_sorted(baked_root: Path) -> None:
    """Deterministic ordering — same contract as the GitHub contents API
    (which is alphabetical) so consumers can rely on it."""
    c = BakedClient(baked_root)
    entries = c.list_dir("Packs/FortiGate")
    names = [e["name"] for e in entries]
    assert names == sorted(names)


def test_list_dir_raises_not_found_for_missing_path(baked_root: Path) -> None:
    c = BakedClient(baked_root)
    with pytest.raises(GitHubNotFoundError) as exc_info:
        c.list_dir("Packs/NonexistentPack")
    assert "directory not found" in str(exc_info.value)


def test_list_dir_raises_not_found_when_path_is_a_file(baked_root: Path) -> None:
    """list_dir on a file path must raise (matches GitHub API behavior)."""
    c = BakedClient(baked_root)
    with pytest.raises(GitHubNotFoundError):
        c.list_dir("Packs/FortiGate/pack_metadata.json")


# ── Behavior: get_file ───────────────────────────────────────────


def test_get_file_returns_text_contents(baked_root: Path) -> None:
    c = BakedClient(baked_root)
    text = c.get_file("Packs/FortiGate/Integrations/FortiGate/FortiGate_dark.svg")
    assert text == "<svg/>"


def test_get_file_raises_not_found_for_missing_file(baked_root: Path) -> None:
    c = BakedClient(baked_root)
    with pytest.raises(GitHubNotFoundError) as exc_info:
        c.get_file("Packs/FortiGate/missing_file.txt")
    assert "file not found" in str(exc_info.value)


def test_get_file_raises_not_found_for_binary(baked_root: Path) -> None:
    """PNG/binary content can't be returned as text — surface a clean
    error rather than emit garbled bytes. Callers use the
    /logo/<pack> route for binary content."""
    binary_path = baked_root / "Packs" / "FortiGate" / "Integrations" / "FortiGate" / "FortiGate_image.png"
    binary_path.write_bytes(b"\x89PNG\r\n\x1a\n\x00")  # bare PNG magic + bytes
    c = BakedClient(baked_root)
    with pytest.raises(GitHubNotFoundError) as exc_info:
        c.get_file("Packs/FortiGate/Integrations/FortiGate/FortiGate_image.png")
    assert "binary" in str(exc_info.value).lower()


# ── Behavior: get_file_json ─────────────────────────────────────


def test_get_file_json_parses_metadata(baked_root: Path) -> None:
    c = BakedClient(baked_root)
    meta = c.get_file_json("Packs/FortiGate/pack_metadata.json")
    assert meta["name"] == "FortiGate"
    assert meta["currentVersion"] == "1.2.3"
    assert meta["supportedModules"] == ["xsiam"]


def test_get_file_json_parses_schema(baked_root: Path) -> None:
    c = BakedClient(baked_root)
    schema = c.get_file_json(
        "Packs/FortiGate/ModelingRules/FortiGate_1_3/FortiGate_1_3_schema.json"
    )
    assert "fortinet_fortigate_raw" in schema
    fields = schema["fortinet_fortigate_raw"]
    assert "srcip" in fields
    assert "dstip" in fields


def test_get_file_json_raises_not_found_for_missing_path(baked_root: Path) -> None:
    c = BakedClient(baked_root)
    with pytest.raises(GitHubNotFoundError):
        c.get_file_json("Packs/FortiGate/no_such_json.json")


def test_get_file_json_propagates_json_decode_error(baked_root: Path) -> None:
    """Malformed JSON should propagate up rather than be masked as
    not-found — matches GitHub client's behavior for genuinely-broken
    content."""
    (baked_root / "Packs" / "FortiGate" / "broken.json").write_text(
        "{ this is not valid json"
    )
    c = BakedClient(baked_root)
    with pytest.raises(json.JSONDecodeError):
        c.get_file_json("Packs/FortiGate/broken.json")


# ── Path traversal defense ───────────────────────────────────────


def test_traversal_with_dotdot_rejected(baked_root: Path, tmp_path: Path) -> None:
    """A `..` in the path that would escape the baked root must raise
    NotFound rather than serve the escaped file. Defense in depth."""
    # Write a file outside the baked tree the test could plausibly reach
    outside = tmp_path / "outside_secret.txt"
    outside.write_text("secret")
    c = BakedClient(baked_root)
    with pytest.raises(GitHubNotFoundError) as exc_info:
        c.get_file("../outside_secret.txt")
    assert "escapes root" in str(exc_info.value)


def test_absolute_path_rejected(baked_root: Path) -> None:
    c = BakedClient(baked_root)
    with pytest.raises(GitHubNotFoundError):
        c.get_file("/etc/passwd")


def test_empty_path_rejected(baked_root: Path) -> None:
    c = BakedClient(baked_root)
    with pytest.raises(GitHubNotFoundError):
        c.get_file("")


# ── owner/repo/branch sentinel values ───────────────────────────


def test_sentinel_attributes_present(baked_root: Path) -> None:
    """Legacy callers (logo URL construction) read owner/repo/
    branch from the client. BakedClient sets sentinel values; production
    flow always rewrites logo URLs to /api/agent/.../logo/<pack> so the
    sentinel values never reach operator browsers."""
    c = BakedClient(baked_root)
    assert c.owner == "local"
    assert c.repo == "cortex-content"
    assert c.branch == "local"


# ── is_baked_available helper ───────────────────────────────────


def test_is_baked_available_false_when_dir_missing(tmp_path: Path, monkeypatch) -> None:
    """When the baked root doesn't exist (e.g., dev workstation that
    hasn't run the refresh script), the helper returns False so
    callers fall back to GitHubClient."""
    # Point baked_root_path() at an empty tmp dir
    monkeypatch.setattr(baked_mod, "baked_root_path", lambda: tmp_path / "nope")
    assert baked_mod.is_baked_available() is False


def test_is_baked_available_false_when_manifest_missing(tmp_path: Path, monkeypatch) -> None:
    """An empty baked/ dir without _manifest.json doesn't count — the
    refresh script writes the manifest last, so its absence means the
    bake is incomplete OR was never run."""
    fake_root = tmp_path / "baked"
    fake_root.mkdir()
    monkeypatch.setattr(baked_mod, "baked_root_path", lambda: fake_root)
    assert baked_mod.is_baked_available() is False


def test_is_baked_available_true_when_manifest_present(tmp_path: Path, monkeypatch) -> None:
    fake_root = tmp_path / "baked"
    fake_root.mkdir()
    (fake_root / "_manifest.json").write_text("{}")
    monkeypatch.setattr(baked_mod, "baked_root_path", lambda: fake_root)
    assert baked_mod.is_baked_available() is True
