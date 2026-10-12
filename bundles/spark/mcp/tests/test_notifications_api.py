"""HTTP surface the /notifications page uses: paging, date filter, mark-all-read."""
from __future__ import annotations

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from api.notifications import register_notification_routes
from config.config import config as _config
from usecase.notifications import SqliteNotificationStore, TopicSpec

TOPICS = [
    TopicSpec(name="simulation-complete", severity="info", target="user:operator"),
    TopicSpec(name="detection-miss", severity="warning", target="channel:soc"),
]


class _FakeMcp:
    def __init__(self):
        self.routes = {}

    def custom_route(self, path, methods=None, include_in_schema=True):
        def deco(fn):
            for m in methods or ["GET"]:
                self.routes[(path, m)] = fn
            return fn

        return deco


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(_config, "mcp_token", "test-token")
    store = SqliteNotificationStore(topics=TOPICS, data_root=tmp_path)
    mcp = _FakeMcp()
    register_notification_routes(mcp, store)
    app = Starlette()
    for (path, method), fn in mcp.routes.items():
        app.add_route(path, fn, methods=[method])
    return store, TestClient(app, headers={"Authorization": "Bearer test-token"})


def test_list_pages_and_reports_the_total(world):
    store, api = world
    ids = [store.publish("simulation-complete").id for _ in range(5)]
    page1 = api.get("/api/v1/notifications?limit=2").json()
    page2 = api.get("/api/v1/notifications?limit=2&offset=2").json()
    assert page1["total"] == page2["total"] == 5
    assert [n["id"] for n in page1["notifications"] + page2["notifications"]] == list(reversed(ids))[:4]
    assert page1["count"] == 2


def test_list_since_filters_and_total_follows_it(world):
    store, api = world
    store.publish("simulation-complete")
    body = api.get("/api/v1/notifications?since=2999-01-01T00:00:00.000000Z").json()
    assert body["notifications"] == [] and body["total"] == 0
    assert api.get("/api/v1/notifications?since=2000-01-01T00:00:00.000000Z").json()["total"] == 1


@pytest.mark.parametrize(
    "since",
    ["yesterday", "2026-13-45T00:00:00Z", "2026-10-12", "2026-10-12T00:00:00", "12345", "Z", "%20%20",
     "0001-01-01T00:00:00+01:00", "9999-12-31T23:59:59-01:00"],
)
def test_a_malformed_since_is_a_400_not_a_silent_filter(world, since):
    store, api = world
    store.publish("simulation-complete")
    r = api.get("/api/v1/notifications", params={"since": since})
    assert r.status_code == 400, since
    body = r.json()
    assert body["code"] == "bad_since" and "since" in body["error"]


def test_since_is_normalised_to_the_stores_timestamp_format():
    from api.notifications import _normalize_since

    assert _normalize_since("2026-10-12T05:06:07Z") == "2026-10-12T05:06:07.000000Z"
    assert _normalize_since("2026-10-12T09:06:07.5+04:00") == "2026-10-12T05:06:07.500000Z"
    assert _normalize_since("0099-01-01T00:00:00Z") == "0099-01-01T00:00:00.000000Z"


def test_since_accepts_z_offsets_and_whole_seconds_and_compares_as_time(world):
    store, api = world
    n = store.publish("simulation-complete")
    # Whole seconds with Z: the row created within that second still matches.
    stamp = n.created_at[:19]
    assert api.get("/api/v1/notifications", params={"since": stamp + "Z"}).json()["total"] == 1
    # The same instant written with a +04:00 offset is the same filter.
    from datetime import datetime, timedelta, timezone

    dt = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    local = dt.astimezone(timezone(timedelta(hours=4))).isoformat()
    assert api.get("/api/v1/notifications", params={"since": local}).json()["total"] == 1
    later = (dt + timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    assert api.get("/api/v1/notifications", params={"since": later}).json()["total"] == 0


def test_bad_offset_falls_back_to_the_first_page(world):
    store, api = world
    store.publish("simulation-complete")
    assert api.get("/api/v1/notifications?offset=abc").json()["count"] == 1


def test_ack_all_marks_everything_read(world):
    store, api = world
    store.publish("simulation-complete")
    store.publish("detection-miss")
    r = api.post("/api/v1/notifications/ack_all")
    assert r.status_code == 200 and r.json() == {"acked": 2}
    assert store.unread_count() == 0
    rows = api.get("/api/v1/notifications").json()["notifications"]
    assert all(n["read_at"] for n in rows)


def test_ack_all_with_a_target_only_touches_that_target(world):
    store, api = world
    store.publish("simulation-complete")
    store.publish("detection-miss")
    assert api.post("/api/v1/notifications/ack_all", json={"target": "channel:soc"}).json() == {"acked": 1}
    assert store.unread_count(target="user:operator") == 1


def test_ack_all_requires_the_bearer(world):
    _, api = world
    r = api.post("/api/v1/notifications/ack_all", headers={"Authorization": "Bearer nope"})
    assert r.status_code in (401, 403)


def test_single_ack_still_works_next_to_ack_all(world):
    store, api = world
    n = store.publish("simulation-complete")
    assert api.post(f"/api/v1/notifications/{n.id}/ack").json()["acked"] is True


def test_agent_dismiss_all_tool_goes_through_the_same_store_call(world, tmp_path, monkeypatch):
    """notifications_dismiss_all and the page's Mark All Read share store.ack_all."""
    import asyncio

    from usecase import notifications as notifications_mod
    from usecase.builtin_components import _approval_gate, self_mod_tools

    store, _api = world
    store.publish("simulation-complete")
    store.publish("detection-miss")

    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "manifest.yaml").write_text("approvals:\n  policy: hybrid\n  humanRequired: []\n", encoding="utf-8")
    monkeypatch.setenv("BUNDLE_ROOT", str(bundle))
    _approval_gate._human_required_set.cache_clear()
    notifications_mod.set_notification_store(store)
    try:
        out = asyncio.run(self_mod_tools.notifications_dismiss_all(target="channel:soc"))
        assert out == {"dismissed": 1}
        assert store.unread_count(target="user:operator") == 1
        assert asyncio.run(self_mod_tools.notifications_dismiss_all()) == {"dismissed": 1}
        assert store.unread_count() == 0
    finally:
        notifications_mod.set_notification_store(None)
        _approval_gate._human_required_set.cache_clear()
