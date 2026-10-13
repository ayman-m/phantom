"""Tests for SqlitePersonalityStore — agent persona persistence.

Covers:
  - default-on-empty (get_or_default returns DEFAULT_PERSONALITY)
  - put bumps version, snapshots prior into history
  - history is capped at HISTORY_KEEP, oldest evicted first
  - reset_to_default produces the canonical seed doc
  - migration from legacy setup.json:values.personality runs once
  - migration is idempotent (second boot doesn't re-migrate)
  - put rejects non-dict input
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.usecase.personality_store import (
    DEFAULT_PERSONALITY,
    HISTORY_KEEP,
    SqlitePersonalityStore,
)


def test_empty_store_returns_default_via_get_or_default(tmp_path: Path) -> None:
    """Per Personality migration logic, the constructor seeds a default
    blob when no setup.json migration source exists. So a fresh store
    isn't actually empty — it has the default seeded. get() returns
    that, get_or_default() returns the same."""
    s = SqlitePersonalityStore(data_root=tmp_path)
    p = s.get()
    assert p is not None
    assert p.blob == DEFAULT_PERSONALITY
    assert s.get_or_default().blob == DEFAULT_PERSONALITY


def test_put_bumps_version_and_archives(tmp_path: Path) -> None:
    s = SqlitePersonalityStore(data_root=tmp_path)
    v1 = s.get()
    assert v1 is not None and v1.version == 1  # bootstrap seeded as v1

    new_blob = {**DEFAULT_PERSONALITY, "personalityMd": "# Concise\n"}
    v2 = s.put(new_blob, actor="user:operator")
    assert v2.version == 2
    assert v2.blob["personalityMd"] == "# Concise\n"
    assert v2.updated_by == "user:operator"

    # History should now contain v1 (the seeded default).
    hist = s.history(limit=10)
    assert len(hist) == 1
    assert hist[0].blob == DEFAULT_PERSONALITY


def test_history_caps_at_keep_window(tmp_path: Path) -> None:
    s = SqlitePersonalityStore(data_root=tmp_path)
    # Put HISTORY_KEEP + 5 versions; oldest 5 should fall off.
    for i in range(HISTORY_KEEP + 5):
        s.put(
            {**DEFAULT_PERSONALITY, "personalityMd": f"# v{i}\n"},
            actor=f"actor-{i}",
        )
    hist = s.history(limit=HISTORY_KEEP + 100)
    assert len(hist) == HISTORY_KEEP


def test_reset_to_default_returns_seed_doc(tmp_path: Path) -> None:
    s = SqlitePersonalityStore(data_root=tmp_path)
    s.put({**DEFAULT_PERSONALITY, "personalityMd": "# Edited\n"}, actor="op")
    p = s.reset_to_default(actor="user:operator")
    assert p.blob == DEFAULT_PERSONALITY
    assert p.updated_by == "user:operator"


def test_put_rejects_non_dict(tmp_path: Path) -> None:
    s = SqlitePersonalityStore(data_root=tmp_path)
    with pytest.raises(TypeError, match="must be a dict"):
        s.put("not a dict", actor="op")  # type: ignore[arg-type]


def test_migration_from_setup_json(tmp_path: Path) -> None:
    """Simulate the legacy state: agent UI saved personality into
    setup.json as a stringified JSON blob under values.personality.
    First boot of the store should pick that up and persist as v1."""
    legacy_blob = {**DEFAULT_PERSONALITY, "personalityMd": "# Legacy\n"}
    setup_path = tmp_path / "setup.json"
    setup_path.write_text(
        json.dumps({
            "values": {
                "personality": json.dumps(legacy_blob),
                "MCP_TOKEN": "abc",  # non-personality field, should not bleed through
            },
        }),
        encoding="utf-8",
    )

    s = SqlitePersonalityStore(data_root=tmp_path)
    p = s.get()
    assert p is not None
    assert p.blob == legacy_blob
    assert p.updated_by == "migration:setup.json"


def test_migration_is_idempotent(tmp_path: Path) -> None:
    """Second boot should NOT re-run migration (the row already
    exists). Test by constructing two stores back-to-back; the
    second's get() should still match what the first wrote."""
    legacy_blob = {**DEFAULT_PERSONALITY, "personalityMd": "# Legacy 42\n"}
    (tmp_path / "setup.json").write_text(
        json.dumps({"values": {"personality": json.dumps(legacy_blob)}}),
        encoding="utf-8",
    )
    s1 = SqlitePersonalityStore(data_root=tmp_path)
    v1_at_first_boot = s1.get().version  # type: ignore[union-attr]

    # Second store points at the same DB; constructor should not
    # re-migrate (would bump version) — the row is already populated.
    s2 = SqlitePersonalityStore(data_root=tmp_path)
    v2_at_second_boot = s2.get().version  # type: ignore[union-attr]
    assert v1_at_first_boot == v2_at_second_boot


def test_migration_skips_when_setup_json_missing(tmp_path: Path) -> None:
    """No setup.json → store seeds with DEFAULT_PERSONALITY. The
    constructor's docstring promises this so the chat agent and UI
    have a coherent persona on day 1."""
    s = SqlitePersonalityStore(data_root=tmp_path)
    p = s.get()
    assert p is not None
    assert p.blob == DEFAULT_PERSONALITY
    assert p.updated_by == "bootstrap:default"


def test_to_dict_shape(tmp_path: Path) -> None:
    s = SqlitePersonalityStore(data_root=tmp_path)
    d = s.get().to_dict()  # type: ignore[union-attr]
    assert set(d.keys()) == {"personality", "updated_at", "updated_by", "version"}
    assert isinstance(d["personality"], dict)


# ─── Action policy (Phase-11.1) ──────────────────────────────────


def test_default_personality_includes_action_policy(tmp_path: Path) -> None:
    """Fresh stores seeded with DEFAULT_PERSONALITY must carry the
    actionPolicy block. The chat route relies on the field being
    present to build the routing rules in the system prompt."""
    s = SqlitePersonalityStore(data_root=tmp_path)
    p = s.get()
    assert p is not None
    policy = p.blob.get("actionPolicy")
    assert isinstance(policy, dict), "actionPolicy missing from default"
    assert "localCategories" in policy
    assert "externalCategories" in policy
    assert policy.get("askWhenUnsure") is True
    assert policy.get("confirmLocalActions") == "approve-card"
    assert policy.get("confirmExternalActions") == "off"
    # Sanity check on category contents.
    assert "jobs" in policy["localCategories"]
    assert "xlog" in policy["externalCategories"]


def test_action_policy_round_trips_through_put(tmp_path: Path) -> None:
    """Operators editing the policy via the personality page POST a
    full blob; round-trip must preserve every actionPolicy field
    (including custom category extensions)."""
    s = SqlitePersonalityStore(data_root=tmp_path)
    custom_policy = {
        **DEFAULT_PERSONALITY,
        "actionPolicy": {
            "localCategories": ["jobs", "settings", "custom-category"],
            "externalCategories": ["xlog", "third-party-api"],
            "askWhenUnsure": False,
            "confirmLocalActions": "approve-card",
            "confirmExternalActions": "approve-card",
        },
    }
    saved = s.put(custom_policy, actor="user:operator")
    fetched = s.get()
    assert fetched is not None
    assert fetched.blob["actionPolicy"] == custom_policy["actionPolicy"]
    assert fetched.blob["actionPolicy"]["localCategories"] == [
        "jobs",
        "settings",
        "custom-category",
    ]
    assert fetched.blob["actionPolicy"]["confirmExternalActions"] == "approve-card"


def test_personality_without_action_policy_round_trips(tmp_path: Path) -> None:
    """A personality blob saved before actionPolicy existed (or by a
    consumer that doesn't know about it) must round-trip cleanly
    without exploding. The field is additive — missing == use defaults
    at read time on the consumer side."""
    s = SqlitePersonalityStore(data_root=tmp_path)
    legacy_blob = {
        "personalityMd": "# Custom\n\nLegacy personality without policy.\n",
    }
    saved = s.put(legacy_blob, actor="user:operator")
    fetched = s.get()
    assert fetched is not None
    # The exact blob round-trips — no implicit injection of defaults
    # at storage time (only at read-with-default time on the consumer).
    assert "actionPolicy" not in fetched.blob
    assert fetched.blob["personalityMd"].startswith("# Custom")


# ─── personality_patch merge semantics ────────────────────


def test_personality_patch_merges_shallowly(tmp_path: Path) -> None:
    """personality_patch (in self_mod_tools.py) does a read-modify-write
    where `updates` shallow-merges over the current blob:

        merged = {**current, **updates}
        store.put(merged, actor="agent")

    This test mirrors that operation directly on the store (skipping
    the approval gate) and verifies the merge:
      - keys present in `updates` overwrite the current value
      - keys absent from `updates` pass through unchanged

    The bug this protects against is the agent doing a naive
    personality_update({"personalityMd": "..."}) and wiping
    actionPolicy.
    """
    s = SqlitePersonalityStore(data_root=tmp_path)
    initial = {
        "personalityMd": "# Original\n",
        "actionPolicy": {"askWhenUnsure": True},
        "operatorNote": "kept",
    }
    s.put(initial, actor="user:operator")

    # Simulate personality_patch's _apply(): read, merge, write.
    current = s.get_or_default().blob
    updates = {"personalityMd": "# Updated by agent\n"}
    merged = {**current, **updates}
    s.put(merged, actor="agent")

    final = s.get_or_default().blob
    # Patched key updated.
    assert final["personalityMd"] == "# Updated by agent\n"
    # Untouched keys preserved (would be wiped by a naive PUT).
    assert final["actionPolicy"] == {"askWhenUnsure": True}
    assert final["operatorNote"] == "kept"


def test_personality_patch_overwrites_nested_fields_at_top_level(
    tmp_path: Path,
) -> None:
    """Shallow merge means a top-level key in `updates` REPLACES the
    same-named key, even if it's a dict — we don't recursively merge
    into nested dicts. Operators relying on patch to tweak a single
    actionPolicy field need to send the full actionPolicy dict.

    Documented behavior (matches personality_patch's docstring); this
    test pins it so a future "deep merge" refactor doesn't silently
    change semantics.
    """
    s = SqlitePersonalityStore(data_root=tmp_path)
    s.put(
        {
            "actionPolicy": {
                "askWhenUnsure": True,
                "confirmLocalActions": "approve-card",
            },
            "personalityMd": "# Hi\n",
        },
        actor="user:operator",
    )

    # Patch with a partial actionPolicy dict.
    current = s.get_or_default().blob
    updates = {"actionPolicy": {"askWhenUnsure": False}}
    merged = {**current, **updates}
    s.put(merged, actor="agent")

    final = s.get_or_default().blob
    # The whole actionPolicy got REPLACED (shallow merge at top level).
    assert final["actionPolicy"] == {"askWhenUnsure": False}
    # personalityMd untouched — outside the patch.
    assert final["personalityMd"] == "# Hi\n"


# ─── Dead keys from earlier releases ─────────────────────────────

DEAD_KEYS = (
    "permissionLevel",
    "defaultModel",
    "fallbackModel",
    "maxConcurrentRuns",
    "dailySummary",
    "summaryTime",
    "escalationThreshold",
    "responseStyle",
    "proactivity",
    "confidence",
    "logicDepth",
    "planningDepth",
    "delegationStyle",
)


def test_default_personality_carries_only_consumed_keys() -> None:
    """Nothing reads the keys earlier releases stored for permission
    level, models, concurrency, notifications or tone. The seed must
    not recreate them."""
    for key in DEAD_KEYS:
        assert key not in DEFAULT_PERSONALITY, key
    assert {"personalityMd", "actionPolicy"} <= set(DEFAULT_PERSONALITY)


def test_blob_with_dead_keys_loads_and_round_trips(tmp_path: Path) -> None:
    """An install upgraded from an earlier release has a stored blob
    with the dead keys. It must load without error (the store never
    validates keys), keep the live fields intact, and still accept a
    put that drops the dead keys."""
    legacy = {
        "permissionLevel": 40,
        "defaultModel": "gemini-3.1-pro-preview",
        "fallbackModel": "gemini-2.5-flash",
        "maxConcurrentRuns": 3,
        "dailySummary": True,
        "summaryTime": "09:00",
        "escalationThreshold": 60,
        "responseStyle": "balanced",
        "personalityMd": "# Kept\n",
        "actionPolicy": DEFAULT_PERSONALITY["actionPolicy"],
    }
    (tmp_path / "setup.json").write_text(
        json.dumps({"values": {"personality": json.dumps(legacy)}}),
        encoding="utf-8",
    )
    s = SqlitePersonalityStore(data_root=tmp_path)
    loaded = s.get_or_default()
    assert loaded.blob == legacy
    assert loaded.blob["personalityMd"] == "# Kept\n"

    cleaned = {k: v for k, v in loaded.blob.items() if k not in DEAD_KEYS}
    saved = s.put(cleaned, actor="user:operator")
    assert not set(DEAD_KEYS) & set(saved.blob)
    assert s.get_or_default().blob == cleaned
