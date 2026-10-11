"""An uploaded (user) connector's container must be stoppable, observable and
restartable by phantom-updater.

`start` accepts user connectors through an explicit `image_ref`, and `stop`, `status`
and `restart` accept every connector id, not only the bundle-only KNOWN_CONNECTORS set,
so deleting an instance never leaves its container running.
These tests drive the real endpoints against a fake docker client.
"""

import os

os.environ.setdefault("MCP_TOKEN", "test-mcp-token")

import pytest  # noqa: E402
from docker.errors import NotFound  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src import main as updater_main  # noqa: E402

AUTH = {"Authorization": "Bearer test-mcp-token"}
USER_IMAGE = "ghcr.io/ayman-m/phantom-connector-acme-feed-oss:0.1.0"


class FakeImage:
    tags = [USER_IMAGE]
    id = "sha256:img"


class FakeContainer:
    def __init__(self, name, *, labels=None, config_image=USER_IMAGE, status="running"):
        self.name = name
        self.labels = labels if labels is not None else {}
        self.attrs = {
            "Config": {"Image": config_image, "Env": []},
            "State": {"Health": {"Status": "healthy"}},
            "RestartCount": 0,
        }
        self.status = status
        self.id = "cid123"
        self.image = FakeImage()
        self.calls = []

    def stop(self, timeout=None):
        self.calls.append("stop")

    def remove(self, force=False):
        self.calls.append("remove")


def managed(connector_id, instance, **kw):
    return FakeContainer(
        f"phantom-connector-{connector_id}-{instance}",
        labels={
            "phantom.role": "connector-runtime",
            "phantom.connector_id": connector_id,
            "phantom.instance_name": instance,
            "phantom.instance_id": "iid-1",
        },
        **kw,
    )


class FakeDocker:
    def __init__(self, *containers):
        self.containers = self
        self._by_name = {c.name: c for c in containers}

    def get(self, name):
        try:
            return self._by_name[name]
        except KeyError:
            raise NotFound(f"no such container: {name}")


@pytest.fixture
def api(monkeypatch):
    notified = []

    async def fake_set_url(instance_id, url):
        notified.append((instance_id, url))

    def make(*containers):
        monkeypatch.setattr(updater_main, "_docker_client", lambda: FakeDocker(*containers))
        monkeypatch.setattr(updater_main, "_agent_set_container_url", fake_set_url)
        return TestClient(updater_main.app)

    make.notified = notified
    return make


BASE = "/api/v1/connectors/acme-feed/instances/ds-1"


def test_stop_removes_a_user_connectors_container(api):
    c = managed("acme-feed", "ds-1")
    r = api(c).post(f"{BASE}/stop", headers=AUTH)
    assert r.status_code == 200 and r.json()["status"] == "stopped"
    assert c.calls == ["stop", "remove"]
    assert api.notified == [("iid-1", None)], "the agent's routing entry must be cleared"


def test_stop_with_nothing_running_is_idempotent(api):
    r = api().post(f"{BASE}/stop", headers=AUTH)
    assert r.status_code == 200 and r.json()["status"] == "not_running"


def test_stop_refuses_a_container_that_is_not_a_managed_connector(api):
    # Same name, but not ours: no phantom.* labels and not a bundle connector id.
    impostor = FakeContainer("phantom-connector-acme-feed-ds-1", labels={"app": "other"})
    r = api(impostor).post(f"{BASE}/stop", headers=AUTH)
    assert r.status_code == 409 and impostor.calls == []


def test_stop_refuses_a_managed_container_of_another_connector(api):
    other = managed("xlog", "ds-1")
    other.name = "phantom-connector-acme-feed-ds-1"  # collides by name only
    r = api(other).post(f"{BASE}/stop", headers=AUTH)
    assert r.status_code == 409 and other.calls == []


def test_a_bundle_container_from_an_older_updater_without_labels_still_stops(api):
    legacy = FakeContainer("phantom-connector-cortex-xdr-Cortex_XDR", labels={})
    r = api(legacy).post("/api/v1/connectors/cortex-xdr/instances/Cortex_XDR/stop", headers=AUTH)
    assert r.status_code == 200 and legacy.calls == ["stop", "remove"]


def test_status_reports_a_user_connector_healthy(api):
    r = api(managed("acme-feed", "ds-1")).get(f"{BASE}/status", headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "healthy" and body["container_url"] == "http://phantom-connector-acme-feed-ds-1:9000"


def test_status_with_nothing_running(api):
    r = api().get(f"{BASE}/status", headers=AUTH)
    assert r.status_code == 200 and r.json()["status"] == "not_running"


@pytest.fixture
def started(monkeypatch):
    """Capture what restart hands to the start handler."""
    seen = {}

    async def fake_start(connector_id, instance_name, request):
        seen["connector_id"], seen["instance_name"], seen["body"] = connector_id, instance_name, await request.json()
        return {"status": "started"}

    monkeypatch.setattr(updater_main, "start_connector_instance", fake_start)
    return seen


def test_restart_reuses_the_image_a_user_connector_was_running(api, started):
    r = api(managed("acme-feed", "ds-1")).post(f"{BASE}/restart", headers=AUTH, json={})
    assert r.status_code == 200
    assert started["body"] == {"instance_id": "iid-1", "image_ref": USER_IMAGE}


def test_restart_of_a_bundle_connector_still_derives_its_image_from_the_pin(api, started):
    r = api(managed("xlog", "Xlog")).post(
        "/api/v1/connectors/xlog/instances/Xlog/restart", headers=AUTH, json={},
    )
    assert r.status_code == 200
    assert started["body"] == {"instance_id": "iid-1"}, "bundle connectors must not be given an image_ref"


def test_restart_with_nothing_running_takes_instance_id_and_image_from_the_caller(api, started):
    r = api().post(f"{BASE}/restart", headers=AUTH, json={"instance_id": "iid-9", "image_ref": USER_IMAGE})
    assert r.status_code == 200
    assert started["body"] == {"instance_id": "iid-9", "image_ref": USER_IMAGE}


def test_restart_with_nothing_running_and_no_instance_id_is_a_clear_400(api, started):
    r = api().post(f"{BASE}/restart", headers=AUTH, json={})
    assert r.status_code == 400 and "instance_id" in r.json()["detail"]
