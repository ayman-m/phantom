"""Tests for SqliteSettingsStore (manifest.settings runtime overrides)."""

from __future__ import annotations

from typing import Any

import pytest

from src.usecase.settings_store import SqliteSettingsStore


@pytest.fixture
def store(tmp_path) -> SqliteSettingsStore:
    """Fresh store rooted in tmp_path with the bundle's actual settings shape."""
    return SqliteSettingsStore(
        defaults={
            "defaultModel": "vertex/gemini-3.1-pro-preview",
            "defaultLogDestination": "XSIAM_WEBHOOK",
            "requireHumanApprovalForOperations": True,
            "coverageReportFormat": "json",
        },
        overridable=[
            "defaultModel",
            "defaultLogDestination",
            "requireHumanApprovalForOperations",
            "coverageReportFormat",
        ],
        data_root=tmp_path,
    )


def test_get_returns_default_when_no_override(store: SqliteSettingsStore) -> None:
    assert store.get("defaultModel") == "vertex/gemini-3.1-pro-preview"


def test_set_persists_override_and_overrides_default(store: SqliteSettingsStore) -> None:
    row = store.set("defaultModel", "vertex/gemini-2.5-flash", actor="ayman")
    assert row.value == "vertex/gemini-2.5-flash"
    assert row.default_value == "vertex/gemini-3.1-pro-preview"
    assert row.updated_by == "ayman"
    assert store.get("defaultModel") == "vertex/gemini-2.5-flash"


def test_effective_merges_defaults_with_overrides(store: SqliteSettingsStore) -> None:
    store.set("coverageReportFormat", "csv", actor="ayman")
    eff = store.effective()
    assert eff["coverageReportFormat"] == "csv"          # overridden
    assert eff["defaultModel"] == "vertex/gemini-3.1-pro-preview"  # untouched default


def test_set_rejects_non_overridable_keys(store: SqliteSettingsStore) -> None:
    # Attempting to set a key that ISN'T in the manifest's overridable
    # list must raise — the bundle author marked it as build-time only.
    with pytest.raises(PermissionError):
        store.set("setupUiUser", "phantom-admin")


def test_set_rejects_keys_completely_unknown_to_manifest(store: SqliteSettingsStore) -> None:
    with pytest.raises(PermissionError):
        store.set("totally_invented_key", "value")


def test_clear_removes_override(store: SqliteSettingsStore) -> None:
    store.set("defaultModel", "vertex/gemini-2.5-flash")
    assert store.is_overridden("defaultModel") is True
    removed = store.clear("defaultModel")
    assert removed is True
    assert store.is_overridden("defaultModel") is False
    # After clear, the default should resurface.
    assert store.get("defaultModel") == "vertex/gemini-3.1-pro-preview"


def test_clear_returns_false_when_no_override(store: SqliteSettingsStore) -> None:
    assert store.clear("defaultModel") is False


def test_overrides_lists_only_explicit_settings(store: SqliteSettingsStore) -> None:
    store.set("defaultModel", "x")
    store.set("requireHumanApprovalForOperations", False)
    rows = store.overrides()
    keys = {r.key for r in rows}
    assert keys == {"defaultModel", "requireHumanApprovalForOperations"}


def test_describe_shape(store: SqliteSettingsStore) -> None:
    store.set("defaultModel", "x", actor="ayman")
    snapshot = store.describe()
    assert "defaults" in snapshot
    assert "overridable" in snapshot
    assert "effective" in snapshot
    assert "overrides" in snapshot
    assert snapshot["effective"]["defaultModel"] == "x"
    assert "defaultModel" in snapshot["overridable"]


def test_audit_log_called_on_set(store: SqliteSettingsStore, tmp_path) -> None:
    """The store must record settings_changed via the wired audit log,
    with target=setting:<key> for filterability."""

    class _SpyAudit:
        def __init__(self) -> None:
            self.events: list[dict[str, Any]] = []

        def record(
            self, action: str, *, target: str | None = None,
            status: str | None = None, actor: str | None = None,
            duration_ms: int | None = None, metadata: dict[str, Any] | None = None,
        ) -> str:
            self.events.append(
                {"action": action, "target": target, "actor": actor, "metadata": metadata}
            )
            return "row-id"

    spy = _SpyAudit()
    s = SqliteSettingsStore(
        defaults={"defaultModel": "default-model"},
        overridable=["defaultModel"],
        data_root=tmp_path / "audit-test",
        audit_log=spy,
    )
    s.set("defaultModel", "x", actor="ayman")
    s.clear("defaultModel", actor="ayman")
    assert [e["action"] for e in spy.events] == ["settings_changed", "settings_changed"]
    assert spy.events[0]["target"] == "setting:defaultModel"
    assert spy.events[0]["actor"] == "ayman"
    assert spy.events[0]["metadata"]["new"] == "x"
    assert spy.events[1]["metadata"].get("cleared") is True


def test_persistence_survives_reopen(tmp_path) -> None:
    """Override written by one instance must be visible to a fresh
    instance pointing at the same data_root — proves we're really
    going through sqlite, not in-memory state."""
    s1 = SqliteSettingsStore(
        defaults={"defaultModel": "old"},
        overridable=["defaultModel"],
        data_root=tmp_path,
    )
    s1.set("defaultModel", "new", actor="ayman")

    s2 = SqliteSettingsStore(
        defaults={"defaultModel": "old"},
        overridable=["defaultModel"],
        data_root=tmp_path,
    )
    assert s2.get("defaultModel") == "new"


def test_value_types_round_trip(store: SqliteSettingsStore, tmp_path) -> None:
    """JSON round-trip preserves bool/list/dict values, not just strings, as long as
    the value has the same type as the setting's default."""
    store.set("requireHumanApprovalForOperations", False)
    assert store.get("requireHumanApprovalForOperations") is False
    structured = SqliteSettingsStore(
        defaults={"report": {"format": "json"}, "tags": ["a"]},
        overridable=["report", "tags"],
        data_root=tmp_path / "structured",
    )
    structured.set("report", {"format": "yaml", "include_meta": True})
    structured.set("tags", ["x", "y"])
    assert structured.get("report") == {"format": "yaml", "include_meta": True}
    assert structured.get("tags") == ["x", "y"]


# ---- a value must have the same type as the setting's default -------------------

import pytest as _pytest


@_pytest.fixture
def typed_store(tmp_path):
    return SqliteSettingsStore(
        defaults={"model": "gemini-x", "flag": True, "limit": 5, "ratio": 0.5},
        overridable=["model", "flag", "limit", "ratio"],
        data_root=tmp_path,
    )


@_pytest.mark.parametrize("key,value", [
    ("model", 12345), ("model", True), ("model", None), ("model", ["a"]),
    ("flag", "false"), ("flag", "true"), ("flag", 1), ("flag", None),
    ("limit", "5"), ("limit", True), ("limit", None),
    ("ratio", "0.5"),
])
def test_a_value_of_the_wrong_type_is_refused(typed_store, key, value):
    with _pytest.raises(ValueError):
        typed_store.set(key, value, actor="t")
    assert typed_store.get(key) == typed_store._defaults[key]


@_pytest.mark.parametrize("key,value", [
    ("model", "other"), ("model", ""), ("flag", False), ("limit", 7), ("limit", 7.5), ("ratio", 1),
])
def test_a_value_of_the_right_type_is_stored(typed_store, key, value):
    typed_store.set(key, value, actor="t")
    assert typed_store.get(key) == value


def test_the_rest_api_lists_a_wrong_typed_value_as_rejected_and_applies_the_rest(tmp_path):
    from starlette.applications import Starlette
    from starlette.testclient import TestClient
    from src.usecase.settings_store import set_settings_store
    from api.settings import register_settings_routes

    class _Mcp:
        def __init__(self): self.routes = {}
        def custom_route(self, path, methods=None, include_in_schema=True):
            def deco(fn):
                for m in methods or ["GET"]: self.routes[(path, m)] = fn
                return fn
            return deco

    from config.config import config as _config
    _config.mcp_token = "t"
    store = SqliteSettingsStore(defaults={"a": "x", "b": True}, overridable=["a", "b"], data_root=tmp_path)
    set_settings_store(store)
    try:
        mcp = _Mcp(); register_settings_routes(mcp, store)
        app = Starlette()
        for (path, method), fn in mcp.routes.items(): app.add_route(path, fn, methods=[method])
        r = TestClient(app).put("/api/v1/settings", json={"updates": {"a": 5, "b": False}},
                                headers={"Authorization": "Bearer t"})
        body = r.json()
        assert [x["key"] for x in body["rejected"]] == ["a"] and "takes a str" in body["rejected"][0]["reason"]
        assert [x["key"] for x in body["applied"]] == ["b"]
        assert store.get("a") == "x" and store.get("b") is False
    finally:
        set_settings_store(None)


# ─── geminiModel -> defaultModel rename ──────────────────────────


class _SpyAudit:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def record(self, action: str, *, target=None, status=None, actor=None,
               duration_ms=None, metadata=None) -> str:
        self.events.append(
            {"action": action, "target": target, "actor": actor, "metadata": metadata}
        )
        return "row-id"


def _legacy_db(tmp_path, key="geminiModel", value='"gemini-2.5-flash"',
               by="ayman", at="2026-01-01T00:00:00.000000Z"):
    """A settings.db as a pre-rename install left it."""
    import sqlite3

    with sqlite3.connect(tmp_path / "settings.db") as c:
        c.execute(
            "CREATE TABLE setting_overrides (key TEXT PRIMARY KEY, "
            "value_json TEXT NOT NULL, updated_at TEXT NOT NULL, updated_by TEXT)"
        )
        c.execute("INSERT INTO setting_overrides VALUES (?, ?, ?, ?)", (key, value, at, by))


def _reopen(tmp_path, audit=None):
    return SqliteSettingsStore(
        defaults={"defaultModel": "vertex/gemini-3.1-pro-preview"},
        overridable=["defaultModel"],
        data_root=tmp_path,
        audit_log=audit,
    )


def test_stored_gemini_model_override_moves_to_default_model_with_a_vertex_prefix(tmp_path) -> None:
    _legacy_db(tmp_path)
    s = _reopen(tmp_path)
    assert s.get("defaultModel") == "vertex/gemini-2.5-flash"
    assert s.is_overridden("defaultModel")
    assert not s.is_overridden("geminiModel")
    [row] = s.overrides()
    assert row.key == "defaultModel"
    # Who set it and when survives the rename.
    assert row.updated_by == "ayman"
    assert row.updated_at == "2026-01-01T00:00:00.000000Z"


def test_a_value_that_already_names_a_provider_is_not_prefixed_twice(tmp_path) -> None:
    _legacy_db(tmp_path, value='"anthropic/claude-opus-5-5"')
    assert _reopen(tmp_path).get("defaultModel") == "anthropic/claude-opus-5-5"


def test_the_rename_is_idempotent(tmp_path) -> None:
    _legacy_db(tmp_path)
    _reopen(tmp_path)
    s = _reopen(tmp_path)
    assert s.get("defaultModel") == "vertex/gemini-2.5-flash"
    assert [o.key for o in s.overrides()] == ["defaultModel"]


def test_an_existing_default_model_override_is_never_overwritten_by_the_rename(tmp_path) -> None:
    import sqlite3

    _legacy_db(tmp_path)
    with sqlite3.connect(tmp_path / "settings.db") as c:
        c.execute(
            "INSERT INTO setting_overrides VALUES ('defaultModel', ?, '2026-02-01T00:00:00.000000Z', 'op')",
            ('"anthropic/claude-opus-5-5"',),
        )
    s = _reopen(tmp_path)
    assert s.get("defaultModel") == "anthropic/claude-opus-5-5"
    assert [o.key for o in s.overrides()] == ["defaultModel"]


def test_no_override_means_the_manifest_default_and_no_audit_row(tmp_path) -> None:
    spy = _SpyAudit()
    s = _reopen(tmp_path, audit=spy)
    assert s.get("defaultModel") == "vertex/gemini-3.1-pro-preview"
    assert spy.events == []


def test_the_rename_is_audited_once(tmp_path) -> None:
    _legacy_db(tmp_path)
    spy = _SpyAudit()
    _reopen(tmp_path, audit=spy)
    _reopen(tmp_path, audit=spy)
    assert len(spy.events) == 1
    ev = spy.events[0]
    assert ev["target"] == "setting:defaultModel"
    assert ev["metadata"]["old"] == "gemini-2.5-flash"
    assert ev["metadata"]["new"] == "vertex/gemini-2.5-flash"
    assert ev["metadata"]["migrated_from"] == "geminiModel"


def test_the_rename_is_skipped_when_the_new_key_is_not_overridable(tmp_path) -> None:
    _legacy_db(tmp_path)
    s = SqliteSettingsStore(
        defaults={"other": "x"}, overridable=["other"], data_root=tmp_path,
    )
    assert s.get("defaultModel") is None


def test_the_manifest_declares_default_model_as_a_canonical_ref() -> None:
    from pathlib import Path

    import yaml

    manifest = yaml.safe_load(
        (Path(__file__).resolve().parents[2] / "manifest.yaml").read_text(encoding="utf-8")
    )
    settings = manifest["settings"]
    assert "geminiModel" not in settings["defaults"]
    assert "geminiModel" not in settings["overridable"]
    assert settings["defaults"]["defaultModel"] == "vertex/gemini-3.1-pro-preview"
    assert "defaultModel" in settings["overridable"]


# ─── geminiModel values the catalog does not serve ───────────────


def test_an_unknown_gemini_id_is_not_carried_over_and_the_default_stays(tmp_path) -> None:
    _legacy_db(tmp_path, value='"gemini-1.0-nonesuch"')
    s = _reopen(tmp_path)
    assert s.get("defaultModel") == "vertex/gemini-3.1-pro-preview"
    assert not s.is_overridden("defaultModel")
    assert not s.is_overridden("geminiModel")


def test_a_dropped_gemini_id_is_logged_and_audited_once(tmp_path, caplog) -> None:
    _legacy_db(tmp_path, value='"my-tuned-gemini"')
    spy = _SpyAudit()
    with caplog.at_level("WARNING", logger="Phantom MCP"):
        _reopen(tmp_path, audit=spy)
        _reopen(tmp_path, audit=spy)
    assert len(spy.events) == 1
    md = spy.events[0]["metadata"]
    assert spy.events[0]["actor"] == "migration"
    assert md["old"] == "my-tuned-gemini" and md["new"] is None and md["cleared"] is True
    assert md["migrated_from"] == "geminiModel"
    assert any("my-tuned-gemini" in r.getMessage() for r in caplog.records)


@pytest.mark.parametrize("value", ['""', '"   "', "42", "null"])
def test_a_blank_or_non_string_gemini_model_is_dropped_not_migrated(tmp_path, value) -> None:
    _legacy_db(tmp_path, value=value)
    s = _reopen(tmp_path)
    assert not s.is_overridden("defaultModel")
    assert not s.is_overridden("geminiModel")


def test_a_vertex_prefixed_unknown_id_is_dropped_but_a_known_one_and_other_providers_migrate(tmp_path) -> None:
    cases = {
        "vertex/gemini-1.0-nonesuch": None,
        "vertex/gemini-2.5-flash": "vertex/gemini-2.5-flash",
        "anthropic/claude-opus-5-5": "anthropic/claude-opus-5-5",
    }
    for i, (value, expected) in enumerate(cases.items()):
        d = tmp_path / str(i)
        d.mkdir()
        _legacy_db(d, value=f'"{value}"')
        s = _reopen(d)
        assert s.is_overridden("defaultModel") is (expected is not None), value
        if expected is not None:
            assert s.get("defaultModel") == expected


def test_every_known_vertex_id_still_migrates(tmp_path) -> None:
    from usecase.settings_store import KNOWN_VERTEX_CHAT_MODEL_IDS

    for model_id in KNOWN_VERTEX_CHAT_MODEL_IDS:
        d = tmp_path / model_id
        d.mkdir()
        _legacy_db(d, value=f'"{model_id}"')
        assert _reopen(d).get("defaultModel") == f"vertex/{model_id}"


def test_the_known_id_list_matches_the_agent_catalog() -> None:
    """The Python list is a copy of the catalog's Gemini chat ids; keep them equal."""
    import re
    from pathlib import Path

    from usecase.settings_store import KNOWN_VERTEX_CHAT_MODEL_IDS

    path = (
        Path(__file__).resolve().parents[4] / "mcp" / "agent" / "lib" / "providers" / "registry" / "catalog-vertex.ts"
    )
    if not path.exists():
        pytest.skip("agent catalog is not in this checkout")
    catalog = path.read_text(encoding="utf-8")
    ids = [m for m in re.findall(r"model: '(gemini-[^']+)'", catalog) if "embedding" not in m]
    assert sorted(ids) == sorted(KNOWN_VERTEX_CHAT_MODEL_IDS)
