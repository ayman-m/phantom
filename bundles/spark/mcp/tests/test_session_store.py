"""Tests for SqliteSessionStore.

`list_sessions` takes an `exclude_scheduled` filter. The
`scheduled_by`-tagged sessions are created by the recurring-job
dispatcher (chat-route writes `meta.scheduled_by=<job-name>` when
X-Phantom-Trigger is `job:*`). The chat sidebar uses the filter
so operator-driven sessions don't drown under scheduled-job churn
on busy installs.
"""

from __future__ import annotations

import pytest

from src.usecase.session_store import SqliteSessionStore


@pytest.fixture
def store(tmp_path) -> SqliteSessionStore:
    """Fresh session store rooted in tmp_path."""
    return SqliteSessionStore(data_root=tmp_path)


# ─── Baseline list_sessions behavior (no filter) ─────────────────────────────


def test_list_sessions_returns_all_when_no_filter(store: SqliteSessionStore):
    s_user = store.create_session(user="ayman", title="hi", meta={})
    s_job = store.create_session(
        user="agent", title="nightly run", meta={"scheduled_by": "nightly_coverage"}
    )
    rows = store.list_sessions()
    ids = {r.id for r in rows}
    assert s_user.id in ids
    assert s_job.id in ids
    assert len(rows) == 2


def test_list_sessions_user_filter_unchanged(store: SqliteSessionStore):
    """Backwards compat — the existing `user=` filter still works in
    isolation (no exclude_scheduled interaction)."""
    store.create_session(user="ayman", title="a", meta={})
    store.create_session(user="other", title="b", meta={})
    rows = store.list_sessions(user="ayman")
    assert len(rows) == 1
    assert rows[0].user == "ayman"


# ─── exclude_scheduled filter ───────────────────────────────


def test_exclude_scheduled_drops_sessions_with_scheduled_by(
    store: SqliteSessionStore,
):
    s_user = store.create_session(user="ayman", title="human", meta={})
    store.create_session(
        user="agent", title="job", meta={"scheduled_by": "nightly_coverage"}
    )
    rows = store.list_sessions(exclude_scheduled=True)
    assert len(rows) == 1
    assert rows[0].id == s_user.id


def test_exclude_scheduled_keeps_sessions_with_other_meta(
    store: SqliteSessionStore,
):
    """Only `scheduled_by` is the filter signal — other meta keys
    (approval_mode, model_override, etc.) must NOT cause a session to
    be hidden from the chat sidebar."""
    store.create_session(user="ayman", title="bypass-mode", meta={"approval_mode": "bypass"})
    store.create_session(user="ayman", title="model-pinned", meta={"model_override": "gemini-pro"})
    rows = store.list_sessions(exclude_scheduled=True)
    assert len(rows) == 2


def test_exclude_scheduled_keeps_sessions_with_empty_meta(
    store: SqliteSessionStore,
):
    """Sessions whose meta is `{}` (the default after create_session)
    must pass through — those are operator-driven sessions that simply
    haven't accrued any metadata yet."""
    store.create_session(user="ayman", title="brand-new", meta={})
    store.create_session(user="ayman", title="also-new", meta=None)
    rows = store.list_sessions(exclude_scheduled=True)
    assert len(rows) == 2


def test_exclude_scheduled_with_user_filter_combines(
    store: SqliteSessionStore,
):
    """The two filters must compose — `user=ayman AND not scheduled`
    returns ayman's human sessions only."""
    s_kept = store.create_session(user="ayman", title="ayman-human", meta={})
    store.create_session(user="ayman", title="ayman-job", meta={"scheduled_by": "j"})
    store.create_session(user="other", title="other-human", meta={})
    rows = store.list_sessions(user="ayman", exclude_scheduled=True)
    assert len(rows) == 1
    assert rows[0].id == s_kept.id


def test_exclude_scheduled_default_false_preserves_old_behavior(
    store: SqliteSessionStore,
):
    """Calling list_sessions() without the filter parameter must return
    scheduled rows alongside human rows, so callers that need to see
    EVERY session (jobs page, audit views) are unaffected."""
    store.create_session(user="ayman", title="human", meta={})
    store.create_session(user="agent", title="job", meta={"scheduled_by": "j"})
    rows = store.list_sessions()  # default exclude_scheduled=False
    assert len(rows) == 2


def test_exclude_scheduled_keeps_human_sessions_visible_under_scheduled_churn(
    store: SqliteSessionStore,
):
    """End-to-end: 50 scheduled sessions can saturate the default
    50-row window and hide human sessions entirely (the default list
    returns 50 scheduled and a client-side filter drops them all →
    empty sidebar). With exclude_scheduled=true, the server skips the
    scheduled rows in the SQL WHERE clause and the 50-row window fills
    with human sessions instead."""
    # 50 scheduled sessions (most recent — would saturate the window)
    for i in range(50):
        store.create_session(
            user="agent",
            title=f"scheduled-{i}",
            meta={"scheduled_by": "recurring_job"},
        )
    # 5 human sessions (older — would be evicted from the window without the filter)
    human_ids = []
    for i in range(5):
        s = store.create_session(user="ayman", title=f"human-{i}", meta={})
        human_ids.append(s.id)

    # Without filter, default 50-row response is dominated by the most
    # recent scheduled sessions. (Order: started_at DESC; humans were
    # created last so they're actually at the top of an unbounded list,
    # but the test verifies the filter shape regardless of insertion
    # order.)
    rows_unfiltered = store.list_sessions(limit=50)
    scheduled_count = sum(
        1 for r in rows_unfiltered if "scheduled_by" in (r.meta or {})
    )
    # Order is deterministic by started_at — humans come last, so the
    # 50-row window picks up 50 humans (5) + scheduled (45) = 50 rows.
    # The point: scheduled sessions OCCUPY a chunk of the window.
    assert scheduled_count > 0

    # With the filter, the 50-row window is 100% human regardless of
    # how many scheduled rows exist before/after.
    rows_filtered = store.list_sessions(limit=50, exclude_scheduled=True)
    assert len(rows_filtered) == 5
    assert {r.id for r in rows_filtered} == set(human_ids)
    for r in rows_filtered:
        assert "scheduled_by" not in (r.meta or {})


# ─── fork metadata on the session payload ────────────────────────────────────


def test_forked_session_exposes_parent_id_in_list_and_to_dict(store: SqliteSessionStore):
    """The sidebar nests a fork under its parent from `parent_id`. The column
    was always written by fork_session but never read, so the list payload
    carried no parent and every fork rendered as a root."""
    parent = store.create_session(user="ayman", title="root", meta={})
    store.append_message(parent.id, role="user", content="hello")
    fork = store.fork_session(from_session_id=parent.id)
    assert fork is not None

    by_id = {s.id: s for s in store.list_sessions()}
    assert by_id[fork.id].parent_id == parent.id
    assert by_id[fork.id].to_dict()["parent_id"] == parent.id
    assert store.get_session(fork.id).to_dict()["parent_id"] == parent.id


def test_non_fork_session_has_null_parent_id(store: SqliteSessionStore):
    root = store.create_session(user="ayman", title="root", meta={})
    assert root.to_dict()["parent_id"] is None
    assert root.to_dict()["fork_point_message_id"] is None
    assert store.list_sessions()[0].parent_id is None


def test_fork_from_message_records_fork_point(store: SqliteSessionStore):
    parent = store.create_session(user="ayman", title="root", meta={})
    first = store.append_message(parent.id, role="user", content="one")
    store.append_message(parent.id, role="assistant", content="two")
    fork = store.fork_session(from_session_id=parent.id, from_message_id=first.id)
    assert fork is not None
    assert fork.to_dict()["fork_point_message_id"] == first.id
