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


def test_value_types_round_trip(store: SqliteSettingsStore) -> None:
    """JSON round-trip preserves bool/int/list/dict values, not just strings."""
    store.set("requireHumanApprovalForOperations", False)
    assert store.get("requireHumanApprovalForOperations") is False
    # The store doesn't constrain types — overridable keys can hold whatever
    # JSON-serializable shape the bundle author intended.
    store.set("coverageReportFormat", {"format": "json", "include_meta": True})
    assert store.get("coverageReportFormat") == {"format": "json", "include_meta": True}
