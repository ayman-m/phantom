"""Connector containers must be recreated when they drift from their pin,
and a denied registry pull must be said out loud.

The drift reconcile has three blind spots to cover: a container whose image was
pruned must not abort the whole sweep, containers pulled under a different
registry owner must still produce a digest to compare, and hyphenated ids
(`cortex-xdr`) must be parsed whole rather than as `cortex`.
These tests use fake docker objects shaped like what docker-py returns.
"""

import asyncio
import os

os.environ.setdefault("MCP_TOKEN", "test-mcp-token")

import httpx  # noqa: E402
import pytest  # noqa: E402
from docker.errors import APIError, DockerException, ImageNotFound, NotFound  # noqa: E402

from src import main as updater_main  # noqa: E402

OWNER = updater_main.OWNER
# An owner that is NOT the current one, whatever PHANTOM_OWNER is in this environment.
LEGACY = "other-owner" if OWNER == "ayman-m" else "ayman-m"
NEW = "sha256:" + "n" * 64
OLD = "sha256:" + "o" * 64


class FakeImage:
    def __init__(self, repo_digests):
        self.attrs = {"RepoDigests": repo_digests}
        self.tags = []
        self.id = "sha256:img"


class FakeContainer:
    def __init__(self, name, *, labels=None, repo_digests=None, config_image="", env=None, image_gone=False):
        self.name = name
        self.labels = labels or {}
        self.attrs = {"Config": {"Image": config_image, "Env": env or []}}
        self._image = FakeImage(repo_digests or [])
        self._gone = image_gone

    @property
    def image(self):
        if self._gone:
            raise ImageNotFound("404 Client Error: No such image")
        return self._image


def labelled(connector_id, instance, iid="iid-" + "x", **kw):
    return FakeContainer(
        f"phantom-connector-{connector_id}-{instance}",
        labels={
            "phantom.role": "connector-runtime",
            "phantom.connector_id": connector_id,
            "phantom.instance_name": instance,
            "phantom.instance_id": iid,
            **kw.pop("labels", {}),
        },
        **kw,
    )


def digest_of(owner, connector_id, digest):
    return f"ghcr.io/{owner}/phantom-connector-{connector_id}-oss@{digest}"


# ── identity ────────────────────────────────────────────────────────────

def test_identity_reads_a_hyphenated_id_from_labels():
    c = labelled("cortex-xdr", "Cortex_XDR", "abc")
    assert updater_main._identify_connector_container(c) == ("cortex-xdr", "Cortex_XDR", "abc")


def test_identity_falls_back_to_the_name_longest_known_id_first():
    c = FakeContainer("phantom-connector-cortex-xdr-Cortex_XDR", env=["INSTANCE_ID=from-env"])
    assert updater_main._identify_connector_container(c) == ("cortex-xdr", "Cortex_XDR", "from-env")


def test_identity_ignores_containers_that_are_not_ours():
    assert updater_main._identify_connector_container(FakeContainer("phantom-connector-mystery-x")) is None
    assert updater_main._identify_connector_container(FakeContainer("redis")) is None


# ── running digest ──────────────────────────────────────────────────────

def test_running_digest_ignores_the_registry_owner():
    c = labelled("caldera", "Caldera", repo_digests=[digest_of(LEGACY, "caldera", OLD)])
    assert updater_main._running_image_digest(c, "caldera") == OLD


def test_running_digest_prefers_the_current_owner():
    c = labelled("xsiam", "X", repo_digests=[digest_of(LEGACY, "xsiam", OLD), digest_of(OWNER, "xsiam", NEW)])
    assert updater_main._running_image_digest(c, "xsiam") == NEW


def test_running_digest_uses_the_container_ref_when_the_image_object_is_gone():
    c = labelled("xlog", "Xlog", image_gone=True, config_image=digest_of(OWNER, "xlog", OLD))
    assert updater_main._running_image_digest(c, "xlog") == OLD


def test_running_digest_is_none_when_nothing_identifies_it():
    assert updater_main._running_image_digest(labelled("xlog", "Xlog", image_gone=True), "xlog") is None


# ── registry denials ──────────────────────────────────────────────

@pytest.mark.parametrize("msg", [
    "denied: denied", "unauthorized: authentication required", "pull access denied for x",
    "Head https://ghcr.io/v2/o/p/manifests/dev: 403 Forbidden",
])
def test_denials_are_recognised(msg):
    assert updater_main._is_registry_auth_failure(DockerException(msg))


def test_a_network_error_is_not_a_denial():
    assert not updater_main._is_registry_auth_failure(DockerException("dial tcp: i/o timeout"))


class FakePuller:
    def __init__(self, pull_exc, cached=True):
        self.calls = 0
        self._exc, self._cached = pull_exc, cached
        self.images = self

    def pull(self, image):
        self.calls += 1
        raise self._exc

    def get(self, image):
        if not self._cached:
            raise NotFound("not cached")
        return object()


def test_a_denied_pull_is_not_retried_and_the_reason_is_returned():
    client = FakePuller(DockerException("denied: denied"))
    outcome = updater_main._pull_with_retry(client, "ghcr.io/o/p:1", base_delay_s=0, max_delay_s=0)
    assert client.calls == 1, "an auth failure must not be retried"
    assert outcome.status == "cached" and "is the package public" in outcome.error


def test_a_transient_failure_is_still_retried():
    client = FakePuller(DockerException("dial tcp: i/o timeout"))
    outcome = updater_main._pull_with_retry(client, "ghcr.io/o/p:1", max_attempts=3, base_delay_s=0, max_delay_s=0)
    assert client.calls == 3 and outcome.status == "cached"


def test_no_cache_and_no_registry_is_a_502_that_says_why():
    client = FakePuller(DockerException("denied: denied"), cached=False)
    with pytest.raises(updater_main.HTTPException) as err:
        updater_main._pull_with_retry(client, "ghcr.io/o/p:1", base_delay_s=0, max_delay_s=0)
    assert err.value.status_code == 502 and "is the package public" in err.value.detail


# ── the drift sweep ─────────────────────────────────────────────────────

class FakeDocker:
    def __init__(self, containers):
        self.containers = self
        self._c = containers

    def list(self, **_kw):
        return self._c


class FakeHttp:
    """Stands in for httpx.AsyncClient; records the start calls the sweep makes."""
    posts: list = []

    def __init__(self, *a, **kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, headers=None, json=None):
        FakeHttp.posts.append((url, json))
        return httpx.Response(200, json={"status": "started"}, request=httpx.Request("POST", url))


@pytest.fixture
def sweep(monkeypatch):
    FakeHttp.posts = []
    pins = {"xlog": NEW, "caldera": NEW, "cortex-xdr": NEW, "xsiam": NEW}
    monkeypatch.setattr(updater_main, "_connector_digest", lambda cid: pins.get(cid))
    monkeypatch.setattr(httpx, "AsyncClient", FakeHttp)

    def run(containers):
        monkeypatch.setattr(updater_main, "_docker_client", lambda: FakeDocker(containers))
        return asyncio.run(updater_main._reconcile_connector_digest_drift())

    return run


def test_every_drifted_container_is_recreated_despite_the_three_blind_spots(sweep):
    containers = [
        # 1. image pruned: must not raise and abort the sweep
        labelled("xlog", "Xlog", "i1", image_gone=True, config_image=digest_of(OWNER, "xlog", OLD)),
        # 2. pulled under another owner: still yields a digest, so it can drift
        labelled("caldera", "Caldera", "i2", repo_digests=[digest_of(LEGACY, "caldera", OLD)]),
        # 3. hyphenated id: parsed as "cortex-xdr", not "cortex"
        labelled("cortex-xdr", "Cortex_XDR", "i3", repo_digests=[digest_of(LEGACY, "cortex-xdr", OLD)]),
    ]
    result = sweep(containers)
    assert [r["container"] for r in result["recreated"]] == [c.name for c in containers]
    assert result["failed"] == []
    starts = sorted(url.split("/api/v1/connectors/")[1] for url, _ in FakeHttp.posts)
    assert starts == ["caldera/instances/Caldera/start", "cortex-xdr/instances/Cortex_XDR/start", "xlog/instances/Xlog/start"]
    assert {body["instance_id"] for _, body in FakeHttp.posts} == {"i1", "i2", "i3"}


def test_a_container_on_its_pin_is_unchanged_whatever_the_owner(sweep):
    c = labelled("xsiam", "X", repo_digests=[digest_of(LEGACY, "xsiam", NEW)])
    result = sweep([c])
    assert [u["container"] for u in result["unchanged"]] == [c.name] and not result["recreated"]


def test_an_unmeasurable_container_is_reported_failed_not_unchanged(sweep):
    c = labelled("xlog", "Xlog", image_gone=True)
    result = sweep([c])
    assert result["failed"] and "cannot determine" in result["failed"][0]["reason"]
    assert not result["unchanged"]


def test_one_unreadable_container_does_not_stop_the_sweep(sweep, monkeypatch):
    bad = labelled("xlog", "Xlog", "i1")
    good = labelled("caldera", "Caldera", "i2", repo_digests=[digest_of(OWNER, "caldera", OLD)])
    real = updater_main._running_image_digest

    def flaky(container, connector_id, **kw):
        if container is bad:
            raise RuntimeError("daemon hiccup")
        return real(container, connector_id, **kw)

    monkeypatch.setattr(updater_main, "_running_image_digest", flaky)
    result = sweep([bad, good])
    assert [r["container"] for r in result["recreated"]] == [good.name]
    assert result["failed"][0]["container"] == bad.name


def test_a_user_connector_has_no_pin_and_is_left_alone(sweep):
    c = labelled("acme-feed", "ds-1", repo_digests=[digest_of(OWNER, "acme-feed", OLD)])
    result = sweep([c])
    assert result["unchanged"] == [{"container": c.name, "reason": "no pinned digest"}]


# ── the digests listing (the /observability/connectors digest column) ───

def test_digest_rows_include_hyphenated_connectors_and_flag_drift_and_cached_pulls(monkeypatch):
    monkeypatch.setattr(updater_main, "_connector_digest", lambda cid: NEW)
    containers = [
        labelled("cortex-xdr", "Cortex_XDR", "i3", repo_digests=[digest_of(LEGACY, "cortex-xdr", OLD)]),
        labelled("xlog", "Xlog", "i1", image_gone=True, config_image=digest_of(OWNER, "xlog", NEW),
                 labels={"phantom.image_pull": "cached"}),
    ]
    monkeypatch.setattr(updater_main, "_docker_client", lambda: FakeDocker(containers))
    rows = {r["connector_id"]: r for r in asyncio.run(updater_main.list_connector_digests())["connectors"]}
    assert rows["cortex-xdr"]["drift"] is True and rows["cortex-xdr"]["digest"] == OLD
    assert rows["cortex-xdr"]["pinned_digest"] == NEW
    assert rows["xlog"]["drift"] is False and rows["xlog"]["image_pull"] == "cached"
    assert rows["xlog"]["image_ref"].endswith(NEW), "an unreadable image must not take the listing down"


def test_one_unreadable_container_does_not_take_the_digest_listing_down(monkeypatch):
    monkeypatch.setattr(updater_main, "_connector_digest", lambda cid: NEW)
    bad = labelled("xlog", "Xlog", "i1")
    bad.labels = None
    good = labelled("caldera", "Caldera", "i2", repo_digests=[digest_of(OWNER, "caldera", NEW)])
    monkeypatch.setattr(updater_main, "_running_image_digest",
                        lambda c, cid, **kw: (_ for _ in ()).throw(RuntimeError("boom")) if c is bad else NEW)
    monkeypatch.setattr(updater_main, "_docker_client", lambda: FakeDocker([bad, good]))
    rows = asyncio.run(updater_main.list_connector_digests())["connectors"]
    assert [r["connector_id"] for r in rows] == ["caldera"]
