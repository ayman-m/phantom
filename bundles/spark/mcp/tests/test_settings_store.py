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
            "geminiModel": "gemini-3.1-pro-preview",
            "defaultLogDestination": "XSIAM_WEBHOOK",
            "requireHumanApprovalForOperations": True,
            "coverageReportFormat": "json",
        },
        overridable=[
            "geminiModel",
            "defaultLogDestination",
            "requireHumanApprovalForOperations",
            "coverageReportFormat",
        ],
        data_root=tmp_path,
    )


def test_get_returns_default_when_no_override(store: SqliteSettingsStore) -> None:
    assert store.get("geminiModel") == "gemini-3.1-pro-preview"


def test_set_persists_override_and_overrides_default(store: SqliteSettingsStore) -> None:
    row = store.set("geminiModel", "gemini-2.5-flash", actor="ayman")
    assert row.value == "gemini-2.5-flash"
    assert row.default_value == "gemini-3.1-pro-preview"
    assert row.updated_by == "ayman"
    assert store.get("geminiModel") == "gemini-2.5-flash"


def test_effective_merges_defaults_with_overrides(store: SqliteSettingsStore) -> None:
    store.set("coverageReportFormat", "csv", actor="ayman")
    eff = store.effective()
    assert eff["coverageReportFormat"] == "csv"          # overridden
    assert eff["geminiModel"] == "gemini-3.1-pro-preview"  # untouched default


def test_set_rejects_non_overridable_keys(store: SqliteSettingsStore) -> None:
    # Attempting to set a key that ISN'T in the manifest's overridable
    # list must raise — the bundle author marked it as build-time only.
    with pytest.raises(PermissionError):
        store.set("setupUiUser", "phantom-admin")


def test_set_rejects_keys_completely_unknown_to_manifest(store: SqliteSettingsStore) -> None:
    with pytest.raises(PermissionError):
        store.set("totally_invented_key", "value")


def test_clear_removes_override(store: SqliteSettingsStore) -> None:
    store.set("geminiModel", "gemini-2.5-flash")
    assert store.is_overridden("geminiModel") is True
    removed = store.clear("geminiModel")
    assert removed is True
    assert store.is_overridden("geminiModel") is False
    # After clear, the default should resurface.
    assert store.get("geminiModel") == "gemini-3.1-pro-preview"


def test_clear_returns_false_when_no_override(store: SqliteSettingsStore) -> None:
    assert store.clear("geminiModel") is False


def test_overrides_lists_only_explicit_settings(store: SqliteSettingsStore) -> None:
    store.set("geminiModel", "x")
    store.set("requireHumanApprovalForOperations", False)
    rows = store.overrides()
    keys = {r.key for r in rows}
    assert keys == {"geminiModel", "requireHumanApprovalForOperations"}


def test_describe_shape(store: SqliteSettingsStore) -> None:
    store.set("geminiModel", "x", actor="ayman")
    snapshot = store.describe()
    assert "defaults" in snapshot
    assert "overridable" in snapshot
    assert "effective" in snapshot
    assert "overrides" in snapshot
    assert snapshot["effective"]["geminiModel"] == "x"
    assert "geminiModel" in snapshot["overridable"]


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
        defaults={"geminiModel": "default-model"},
        overridable=["geminiModel"],
        data_root=tmp_path / "audit-test",
        audit_log=spy,
    )
    s.set("geminiModel", "x", actor="ayman")
    s.clear("geminiModel", actor="ayman")
    assert [e["action"] for e in spy.events] == ["settings_changed", "settings_changed"]
    assert spy.events[0]["target"] == "setting:geminiModel"
    assert spy.events[0]["actor"] == "ayman"
    assert spy.events[0]["metadata"]["new"] == "x"
    assert spy.events[1]["metadata"].get("cleared") is True


def test_persistence_survives_reopen(tmp_path) -> None:
    """Override written by one instance must be visible to a fresh
    instance pointing at the same data_root — proves we're really
    going through sqlite, not in-memory state."""
    s1 = SqliteSettingsStore(
        defaults={"geminiModel": "old"},
        overridable=["geminiModel"],
        data_root=tmp_path,
    )
    s1.set("geminiModel", "new", actor="ayman")

    s2 = SqliteSettingsStore(
        defaults={"geminiModel": "old"},
        overridable=["geminiModel"],
        data_root=tmp_path,
    )
    assert s2.get("geminiModel") == "new"


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
