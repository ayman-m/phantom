"""Test Connection for every bundle connector: the read-only probes.

The probes run whenever the operator presses Test Connection, so the property
that matters most is what they must NOT do: the sender connectors never send an
event, never put a key on the wire, and never make anything but a GET (or, for
wec-sender, a bare TCP connect). The rest pins what each probe proves and how it
classifies a failure.
"""
from __future__ import annotations

import asyncio
import json
import ssl
from pathlib import Path

import httpx
import pytest

from usecase import connector_probes as cp

BUNDLE_CONNECTORS = Path(__file__).resolve().parents[1].parent / "connectors"


def run(coro):
    return asyncio.run(coro)


class Net:
    """Replaces the probe module's HTTP client factory with a MockTransport and records every request."""

    def __init__(self, monkeypatch, handler):
        self.requests: list[httpx.Request] = []
        self.client_kwargs: list[dict] = []
        self._handler = handler

        def factory(**kwargs):
            self.client_kwargs.append(kwargs)
            kwargs = {k: v for k, v in kwargs.items() if k in ("timeout", "follow_redirects")}
            return httpx.AsyncClient(transport=httpx.MockTransport(self._record), **kwargs)

        monkeypatch.setattr(cp, "_new_client", factory)

    def _record(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        out = self._handler(request)
        if isinstance(out, Exception):
            raise out
        return out


def reply(status=200, body=None):
    return httpx.Response(status, json=body if body is not None else {})


# ── coverage ─────────────────────────────────────────────────────────────────


def test_every_bundle_connector_has_a_probe():
    bundled = {p.name for p in BUNDLE_CONNECTORS.iterdir() if p.is_dir() and not p.name.startswith("_")}
    assert cp.PROBE_IMPLEMENTED == bundled
    assert set(cp._HANDLERS) == set(cp.PROBE_IMPLEMENTED)


def test_a_connector_without_a_probe_fails_instead_of_passing():
    res = run(cp.probe("acme-uploaded"))
    assert res.ok is False and "no built-in test" in res.error


# ── web ──────────────────────────────────────────────────────────────────────

CDP_BODY = {"Browser": "HeadlessChrome/126.0", "webSocketDebuggerUrl": "ws://10.1.2.3:9222/devtools/browser/x"}


def test_web_passes_on_a_devtools_description_and_asks_the_resolved_ip(monkeypatch):
    net = Net(monkeypatch, lambda r: reply(200, CDP_BODY))

    async def resolve(host):
        assert host == "phantom-browser"
        return "172.18.0.3"

    monkeypatch.setattr(cp, "_resolve_ipv4", resolve)
    res = run(cp.probe("web", config={}))
    assert res.ok and "HeadlessChrome" in res.message
    assert str(net.requests[0].url) == "http://172.18.0.3:9222/json/version"
    assert [r.method for r in net.requests] == ["GET"]


def test_web_derives_the_http_form_of_a_ws_url(monkeypatch):
    net = Net(monkeypatch, lambda r: reply(200, CDP_BODY))
    res = run(cp.probe("web", config={"cdp_url": "ws://10.0.0.9:9333"}))
    assert res.ok
    assert str(net.requests[0].url) == "http://10.0.0.9:9333/json/version"
    run(cp.probe("web", config={"cdp_url": "wss://10.0.0.9:9333/"}))
    assert str(net.requests[1].url) == "https://10.0.0.9:9333/json/version"


def test_web_fails_on_a_non_200_and_on_a_page_that_is_not_devtools(monkeypatch):
    Net(monkeypatch, lambda r: reply(500, {"error": "Host header"}))
    res = run(cp.probe("web", config={"cdp_url": "http://10.0.0.9:9222"}))
    assert not res.ok and "HTTP 500" in res.error
    Net(monkeypatch, lambda r: reply(200, {"hello": "world"}))
    res = run(cp.probe("web", config={"cdp_url": "http://10.0.0.9:9222"}))
    assert not res.ok and "DevTools" in res.error


def test_web_reports_an_unreachable_browser_and_an_unresolvable_host(monkeypatch):
    Net(monkeypatch, lambda r: httpx.ConnectError("refused"))
    res = run(cp.probe("web", config={"cdp_url": "http://10.0.0.9:9222"}))
    assert not res.ok and "cannot connect" in res.error

    async def nxdomain(host):
        raise OSError("Name or service not known")

    monkeypatch.setattr(cp, "_resolve_ipv4", nxdomain)
    res = run(cp.probe("web", config={}))
    assert not res.ok and "phantom-browser" in res.error


def test_web_rejects_a_cdp_url_that_is_not_a_url(monkeypatch):
    net = Net(monkeypatch, lambda r: reply(200, CDP_BODY))
    res = run(cp.probe("web", config={"cdp_url": "ftp://x"}))
    assert not res.ok and not net.requests


# ── http-sender ──────────────────────────────────────────────────────────────

HTTP_CFG = {"collectorUrl": "https://api-lab.example/logs/v1/event", "vendor": "Okta", "product": "SSO"}
HTTP_SEC = {"collectorKey": "SECRET-COLLECTOR-KEY"}


@pytest.mark.parametrize("status", [200, 401, 404, 405])
def test_http_sender_counts_any_http_answer_as_reachable_and_sends_no_key(monkeypatch, status):
    net = Net(monkeypatch, lambda r: reply(status))
    res = run(cp.probe("http-sender", config=HTTP_CFG, secrets=HTTP_SEC))
    assert res.ok
    assert "NOT verified" in res.message and "send_test_event" in res.message and "no event was sent" in res.message
    assert [r.method for r in net.requests] == ["GET"]
    req = net.requests[0]
    assert "authorization" not in req.headers and req.content == b""
    assert "SECRET-COLLECTOR-KEY" not in str(req.headers) + str(req.url) + res.message


def test_http_sender_never_posts_and_never_contacts_other_destinations(monkeypatch):
    net = Net(monkeypatch, lambda r: reply(200))
    cfg = {
        **HTTP_CFG,
        "additionalDestinations": json.dumps([{"url": "https://other.example/x", "vendor": "A", "product": "B"}]),
        "criblUrl": "https://api-lab.example/logs/v1/integrated/cribl/data",
    }
    sec = {**HTTP_SEC, "additionalKeys": '{"a_b": "K2"}', "criblToken": "TOKEN"}
    res = run(cp.probe("http-sender", config=cfg, secrets=sec))
    assert res.ok
    assert {r.url.host for r in net.requests} == {"api-lab.example"} and len(net.requests) == 1
    assert all(r.method == "GET" for r in net.requests)
    assert "1 additional destination(s)" in res.message and "Cribl" in res.message and "Not contacted" in res.message


def test_http_sender_reports_connect_timeout_and_tls_failures(monkeypatch):
    Net(monkeypatch, lambda r: httpx.ConnectTimeout("slow"))
    res = run(cp.probe("http-sender", config=HTTP_CFG, secrets=HTTP_SEC))
    assert not res.ok and "timed out" in res.error

    tls = httpx.ConnectError("[SSL: CERTIFICATE_VERIFY_FAILED]")
    tls.__cause__ = ssl.SSLCertVerificationError(1, "certificate verify failed: self-signed certificate")
    Net(monkeypatch, lambda r: tls)
    res = run(cp.probe("http-sender", config=HTTP_CFG, secrets=HTTP_SEC))
    assert not res.ok and "TLS error" in res.error and "api-lab.example" in res.error

    Net(monkeypatch, lambda r: httpx.ConnectError("refused"))
    res = run(cp.probe("http-sender", config=HTTP_CFG, secrets=HTTP_SEC))
    assert not res.ok and "cannot connect" in res.error


def test_http_sender_honours_verify_tls_and_timeout_config(monkeypatch):
    net = Net(monkeypatch, lambda r: reply(200))
    run(cp.probe("http-sender", config={**HTTP_CFG, "verifyTls": False, "timeoutSeconds": 3}, secrets=HTTP_SEC))
    kw = net.client_kwargs[-1]
    assert kw["verify"] is False and kw["timeout"].read == 3 and kw["follow_redirects"] is False
    run(cp.probe("http-sender", config={**HTTP_CFG, "verifyTls": "false"}, secrets=HTTP_SEC))
    assert net.client_kwargs[-1]["verify"] is False
    run(cp.probe("http-sender", config=HTTP_CFG, secrets=HTTP_SEC))
    assert net.client_kwargs[-1]["verify"] is True
    run(cp.probe("http-sender", config={**HTTP_CFG, "timeoutSeconds": 600}, secrets=HTTP_SEC))
    assert net.client_kwargs[-1]["timeout"].read == cp._SENDER_TIMEOUT_CAP_S


@pytest.mark.parametrize(
    "cfg,sec,needle,auth",
    [
        ({**HTTP_CFG, "collectorUrl": ""}, HTTP_SEC, "collectorUrl is not set", False),
        ({**HTTP_CFG, "collectorUrl": "http://api-lab.example/x"}, HTTP_SEC, "https://", False),
        ({**HTTP_CFG, "collectorUrl": "not a url"}, HTTP_SEC, "https://", False),
        ({**HTTP_CFG, "vendor": ""}, HTTP_SEC, "vendor and product", False),
        (HTTP_CFG, {}, "collectorKey", True),
        (HTTP_CFG, {"collectorKey": "  "}, "collectorKey", True),
    ],
)
def test_http_sender_missing_config_or_key_slot_fails_without_a_request(monkeypatch, cfg, sec, needle, auth):
    net = Net(monkeypatch, lambda r: reply(200))
    res = run(cp.probe("http-sender", config=cfg, secrets=sec))
    assert not res.ok and needle in res.error and res.is_auth_error is auth
    assert net.requests == []


CRIBL_CFG = {"criblUrl": "https://api-lab.example/logs/v1/integrated/cribl/data"}
CRIBL_SEC = {"criblToken": "SECRET-CRIBL-TOKEN"}


@pytest.mark.parametrize("status", [200, 401, 404, 405])
def test_http_sender_cribl_only_passes_with_one_get_and_no_token(monkeypatch, status):
    net = Net(monkeypatch, lambda r: reply(status))
    res = run(cp.probe("http-sender", config=CRIBL_CFG, secrets=CRIBL_SEC))
    assert res.ok
    assert "Cribl endpoint" in res.message and "NOT verified" in res.message and "no event was sent" in res.message
    assert [r.method for r in net.requests] == ["GET"]
    req = net.requests[0]
    assert req.url.host == "api-lab.example" and req.url.path.endswith("/logs/v1/integrated/cribl/data")
    assert "authorization" not in req.headers and req.content == b""
    assert "SECRET-CRIBL-TOKEN" not in str(req.headers) + str(req.url) + res.message


def test_http_sender_cribl_only_does_not_need_vendor_product_or_a_collector_key(monkeypatch):
    net = Net(monkeypatch, lambda r: reply(200))
    cfg = {**CRIBL_CFG, "collectorUrl": "", "vendor": "", "product": "", "additionalDestinations": ""}
    assert run(cp.probe("http-sender", config=cfg, secrets=CRIBL_SEC)).ok
    assert len(net.requests) == 1


def test_http_sender_cribl_only_mentions_additional_destinations_it_did_not_contact(monkeypatch):
    Net(monkeypatch, lambda r: reply(200))
    cfg = {**CRIBL_CFG, "additionalDestinations": json.dumps([{"url": "https://other.example/x", "vendor": "A", "product": "B"}])}
    res = run(cp.probe("http-sender", config=cfg, secrets=CRIBL_SEC))
    assert res.ok and "1 additional destination(s)" in res.message and "Not contacted" in res.message


def test_http_sender_cribl_only_honours_verify_tls_and_timeout(monkeypatch):
    net = Net(monkeypatch, lambda r: reply(200))
    run(cp.probe("http-sender", config={**CRIBL_CFG, "verifyTls": "false", "timeoutSeconds": 3}, secrets=CRIBL_SEC))
    kw = net.client_kwargs[-1]
    assert kw["verify"] is False and kw["timeout"].read == 3 and kw["follow_redirects"] is False


def test_http_sender_cribl_only_reports_transport_failures(monkeypatch):
    Net(monkeypatch, lambda r: httpx.ConnectError("refused"))
    res = run(cp.probe("http-sender", config=CRIBL_CFG, secrets=CRIBL_SEC))
    assert not res.ok and "cannot connect" in res.error and "api-lab.example" in res.error


@pytest.mark.parametrize(
    "cfg,sec,needle,auth",
    [
        ({"criblUrl": "http://api-lab.example/logs/v1/integrated/cribl/data"}, CRIBL_SEC, "https://", False),
        ({"criblUrl": "https://api-lab.example/logs/v1/event"}, CRIBL_SEC, "/logs/v1/integrated/cribl/data", False),
        (CRIBL_CFG, {}, "criblToken", True),
        (CRIBL_CFG, {"criblToken": "  "}, "criblToken", True),
        ({"criblUrl": "https://api-lab.example/logs/v1/event"}, {}, "criblToken", False),
    ],
)
def test_http_sender_cribl_only_bad_config_fails_without_a_request(monkeypatch, cfg, sec, needle, auth):
    net = Net(monkeypatch, lambda r: reply(200))
    res = run(cp.probe("http-sender", config=cfg, secrets=sec))
    assert not res.ok and needle in res.error and res.is_auth_error is auth
    assert net.requests == []


def test_http_sender_with_a_collector_url_still_probes_the_collector_not_cribl(monkeypatch):
    net = Net(monkeypatch, lambda r: reply(200))
    res = run(cp.probe("http-sender", config={**HTTP_CFG, **CRIBL_CFG}, secrets={**HTTP_SEC, **CRIBL_SEC}))
    assert res.ok and "collector at" in res.message and "Cribl" in res.message
    assert len(net.requests) == 1 and net.requests[0].url.path == "/logs/v1/event"


def test_http_sender_vendor_without_url_keeps_the_collector_failure_even_with_cribl(monkeypatch):
    net = Net(monkeypatch, lambda r: reply(200))
    res = run(cp.probe("http-sender", config={**CRIBL_CFG, "vendor": "Okta"}, secrets={**HTTP_SEC, **CRIBL_SEC}))
    assert not res.ok and "collectorUrl is not set" in res.error
    assert net.requests == []


# ── wec-sender ───────────────────────────────────────────────────────────────

WEC_URL = "Server=HTTPS://broker.lab.example:5986/wsman/SubscriptionManager/WEC,Refresh=600,IssuerCA=" + "AB" * 20
WEC_SEC = {"clientPfx": "BASE64PFX", "clientPfxPassword": "PFX-PASSWORD"}


class FakeWriter:
    def __init__(self):
        self.writes: list[bytes] = []
        self.closed = False

    def write(self, data):
        self.writes.append(data)

    def close(self):
        self.closed = True

    async def wait_closed(self):
        return None


def patch_connection(monkeypatch, outcome):
    calls, writer = [], FakeWriter()

    async def fake(host, port):
        calls.append((host, port))
        if isinstance(outcome, BaseException):
            raise outcome
        return object(), writer

    monkeypatch.setattr(cp, "_open_connection", fake)
    return calls, writer


def test_wec_sender_connects_to_the_broker_port_and_sends_nothing(monkeypatch):
    calls, writer = patch_connection(monkeypatch, None)
    net = Net(monkeypatch, lambda r: reply(200))
    res = run(cp.probe("wec-sender", config={"subscriptionManagerUrl": WEC_URL}, secrets=WEC_SEC))
    assert res.ok
    assert calls == [("broker.lab.example", 5986)]
    assert writer.writes == [] and writer.closed and net.requests == []
    assert "NOT verified" in res.message and "list_subscriptions" in res.message and "no event was sent" in res.message
    assert "PFX-PASSWORD" not in res.message


def test_wec_sender_accepts_a_bare_url_and_defaults_the_port(monkeypatch):
    calls, _ = patch_connection(monkeypatch, None)
    run(cp.probe("wec-sender", config={"subscriptionManagerUrl": "https://broker.lab.example/wsman/x"}, secrets=WEC_SEC))
    run(cp.probe("wec-sender", config={"subscriptionManagerUrl": "https://10.0.0.5:6000/wsman/x"}, secrets=WEC_SEC))
    assert calls == [("broker.lab.example", 5986), ("10.0.0.5", 6000)]


def test_wec_sender_reports_refused_and_timed_out_connections(monkeypatch):
    patch_connection(monkeypatch, ConnectionRefusedError(111, "Connection refused"))
    res = run(cp.probe("wec-sender", config={"subscriptionManagerUrl": WEC_URL}, secrets=WEC_SEC))
    assert not res.ok and "broker.lab.example:5986" in res.error
    patch_connection(monkeypatch, asyncio.TimeoutError())
    res = run(cp.probe("wec-sender", config={"subscriptionManagerUrl": WEC_URL}, secrets=WEC_SEC))
    assert not res.ok and "timed out" in res.error


@pytest.mark.parametrize(
    "url,sec,needle",
    [
        ("", WEC_SEC, "not set"),
        ("http://broker.lab.example/x", WEC_SEC, "https"),
        ("Refresh=600", WEC_SEC, "Server="),
        ("gibberish", WEC_SEC, "expected Server="),
        ("https://broker.lab.example:99999999/x", WEC_SEC, "port"),
        ("Server=HTTPS://b.example:5986/x,Refresh=soon", WEC_SEC, "Refresh"),
        ("Server=HTTPS://b.example:5986/x,IssuerCA=XYZ", WEC_SEC, "IssuerCA"),
        (WEC_URL, {"clientPfxPassword": "x"}, "clientPfx secret"),
        (WEC_URL, {"clientPfx": "x"}, "clientPfxPassword"),
    ],
)
def test_wec_sender_missing_or_bad_config_fails_without_connecting(monkeypatch, url, sec, needle):
    calls, _ = patch_connection(monkeypatch, None)
    res = run(cp.probe("wec-sender", config={"subscriptionManagerUrl": url}, secrets=sec))
    assert not res.ok and needle in res.error
    assert calls == []


# ── xsiam / cortex-xdr ───────────────────────────────────────────────────────

XSIAM_CFG = {"api_url": "https://api-lab.xdr.example", "api_id": "42"}
XSIAM_SEC = {"api_key": "STANDARD-KEY"}


@pytest.mark.parametrize("connector,cfg,sec,path", [
    ("xsiam", XSIAM_CFG, XSIAM_SEC, "/public_api/v1/xql/get_datasets"),
    ("cortex-xdr", XSIAM_CFG, XSIAM_SEC, "/public_api/v1/incidents/get_incidents"),
])
def test_cortex_probes_send_a_standard_key_as_plain_headers(monkeypatch, connector, cfg, sec, path):
    net = Net(monkeypatch, lambda r: reply(200, {"reply": []}))
    res = run(cp.probe(connector, config=cfg, secrets=sec))
    assert res.ok
    req = net.requests[0]
    assert req.method == "POST" and req.url.path == path
    assert req.headers["authorization"] == "STANDARD-KEY" and req.headers["x-xdr-auth-id"] == "42"
    # An internet callee is always verified, like the connector's own client.
    assert net.client_kwargs[0]["verify"] is True


@pytest.mark.parametrize("given", [
    "https://api-lab.xdr.example",
    "https://api-lab.xdr.example/",
    "https://api-lab.xdr.example/public_api",
    "https://api-lab.xdr.example/public_api/v1",
    "https://api-lab.xdr.example/public_api/v1/",
    "https://api-lab.xdr.example/public_api/v1/xql",
    "https://api-lab.xdr.example/public_api/v2/",
])
@pytest.mark.parametrize("connector", ["xsiam", "cortex-xdr"])
def test_cortex_probes_normalise_api_url_like_the_connectors_fetcher(monkeypatch, connector, given):
    net = Net(monkeypatch, lambda r: reply(200))
    run(cp.probe(connector, config={**XSIAM_CFG, "api_url": given}, secrets=XSIAM_SEC))
    base = "https://api-lab.xdr.example/public_api/v1/"
    assert str(net.requests[0].url).startswith(base)
    assert "/public_api/" not in str(net.requests[0].url).split("/public_api/v1/", 1)[1]


def test_cortex_401_is_an_auth_error_and_names_the_standard_key(monkeypatch):
    Net(monkeypatch, lambda r: reply(401, {"reply": {"err_msg": "Public API request unauthorized"}}))
    for connector in ("xsiam", "cortex-xdr"):
        res = run(cp.probe(connector, config=XSIAM_CFG, secrets=XSIAM_SEC))
        assert not res.ok and res.is_auth_error and "Standard" in res.error and "STANDARD-KEY" not in res.error


def test_cortex_403_datasets_not_found_is_not_an_auth_failure(monkeypatch):
    Net(monkeypatch, lambda r: reply(403, {"reply": {"err_msg": "Datasets not found"}}))
    res = run(cp.probe("xsiam", config=XSIAM_CFG, secrets=XSIAM_SEC))
    assert res.ok and res.is_auth_error is False and "no datasets" in res.message


def test_cortex_other_403_names_the_role_problem(monkeypatch):
    Net(monkeypatch, lambda r: reply(403, {"reply": {"err_msg": "Access denied: missing permission X"}}))
    res = run(cp.probe("cortex-xdr", config=XSIAM_CFG, secrets=XSIAM_SEC))
    assert not res.ok and "role lacks permission" in res.error and "missing permission X" in res.error


def test_cortex_server_error_and_missing_config(monkeypatch):
    net = Net(monkeypatch, lambda r: reply(500))
    res = run(cp.probe("xsiam", config=XSIAM_CFG, secrets=XSIAM_SEC))
    assert not res.ok and not res.is_auth_error and "HTTP 500" in res.error
    for connector in ("xsiam", "cortex-xdr"):
        assert not run(cp.probe(connector, config={"api_id": "1"}, secrets=XSIAM_SEC)).ok
        res = run(cp.probe(connector, config={"api_url": "https://x"}, secrets=XSIAM_SEC))
        assert not res.ok and "api_id" in res.error
        res = run(cp.probe(connector, config=XSIAM_CFG, secrets={}))
        assert not res.ok and "api_key" in res.error and res.is_auth_error
    assert len(net.requests) == 1


# ── xlog / caldera / cortex-docs / cortex-content ────────────────────────────


def test_xlog_checks_the_token_on_an_authenticated_path_not_just_health(monkeypatch):
    def handler(r):
        if r.url.path == "/health":
            return reply(200, {"status": "ok"})
        return reply(200, {}) if r.headers.get("authorization") == "good" else reply(401)

    net = Net(monkeypatch, handler)
    cfg = {"baseUrl": "https://xlog:8000"}
    ok = run(cp.probe("xlog", config=cfg, secrets={"apiToken": "good"}))
    assert ok.ok and net.requests[-1].url.path == "/api/v1/worker-rates"
    bad = run(cp.probe("xlog", config=cfg, secrets={"apiToken": "wrong"}))
    assert not bad.ok and bad.is_auth_error
    none = run(cp.probe("xlog", config=cfg, secrets={}))
    assert not none.ok and none.is_auth_error


def test_xlog_distinguishes_a_service_without_a_token_and_a_down_service(monkeypatch):
    Net(monkeypatch, lambda r: reply(200) if r.url.path == "/health" else reply(503))
    res = run(cp.probe("xlog", config={"baseUrl": "https://xlog:8000"}, secrets={"apiToken": "t"}))
    assert not res.ok and not res.is_auth_error and "XLOG_API_KEY" in res.error
    Net(monkeypatch, lambda r: httpx.ConnectError("refused"))
    res = run(cp.probe("xlog", config={"baseUrl": "https://xlog:8000"}, secrets={"apiToken": "t"}))
    assert not res.ok and not res.is_auth_error


def test_caldera_sends_the_key_header_and_classifies_401(monkeypatch):
    net = Net(monkeypatch, lambda r: reply(200) if r.headers.get("key") == "k" else reply(401))
    assert run(cp.probe("caldera", config={"baseUrl": "http://caldera:8888"}, secrets={"apiKey": "k"})).ok
    assert net.requests[0].url.path == "/api/v2/health"
    bad = run(cp.probe("caldera", config={"baseUrl": "http://caldera:8888"}, secrets={"apiKey": "x"}))
    assert not bad.ok and bad.is_auth_error
    assert run(cp.probe("caldera", config={}, secrets={})).is_auth_error


def test_cortex_docs_requires_a_200_and_verifies_tls(monkeypatch):
    net = Net(monkeypatch, lambda r: reply(200))
    assert run(cp.probe("cortex-docs")).ok and net.client_kwargs[0]["verify"] is True
    Net(monkeypatch, lambda r: reply(404))
    assert not run(cp.probe("cortex-docs")).ok


def test_cortex_content_checks_the_baked_catalog():
    assert run(cp.probe("cortex-content")).ok


# ── container check ──────────────────────────────────────────────────────────


def test_container_check_runs_first_and_reports_a_missing_or_dead_container(monkeypatch):
    net = Net(monkeypatch, lambda r: reply(200))
    res = run(cp.probe("cortex-docs", check_container=True, container_url=None))
    assert not res.ok and "has not started" in res.error and net.requests == []

    net = Net(monkeypatch, lambda r: reply(503) if r.url.path == "/health" else reply(200))
    res = run(cp.probe("cortex-docs", check_container=True, container_url="http://phantom-connector-cortex-docs-x:9000"))
    assert not res.ok and "HTTP 503" in res.error and len(net.requests) == 1

    Net(monkeypatch, lambda r: httpx.ConnectError("no route"))
    res = run(cp.probe("cortex-docs", check_container=True, container_url="http://phantom-connector-cortex-docs-x:9000"))
    assert not res.ok and "unreachable" in res.error


def test_container_check_passes_through_to_the_upstream_probe(monkeypatch):
    net = Net(monkeypatch, lambda r: reply(200))
    res = run(cp.probe("cortex-docs", check_container=True, container_url="http://c:9000"))
    assert res.ok and "container is up" in res.message
    assert [r.url.path for r in net.requests] == ["/health", "/cortex-xsiam.md"]


def test_container_check_is_skipped_unless_asked_for(monkeypatch):
    net = Net(monkeypatch, lambda r: reply(200))
    run(cp.probe("cortex-docs", container_url="http://c:9000"))
    assert [r.url.path for r in net.requests] == ["/cortex-xsiam.md"]


# ── the property that matters: nothing here can send an event ────────────────


@pytest.mark.parametrize("connector,cfg,sec", [
    ("http-sender", HTTP_CFG, HTTP_SEC),
    ("wec-sender", {"subscriptionManagerUrl": WEC_URL}, WEC_SEC),
    ("web", {"cdp_url": "http://10.0.0.9:9222"}, {}),
])
def test_no_sender_or_browser_probe_ever_posts(monkeypatch, connector, cfg, sec):
    net = Net(monkeypatch, lambda r: reply(200, CDP_BODY))
    calls, writer = patch_connection(monkeypatch, None)
    run(cp.probe(connector, config=cfg, secrets=sec, check_container=True, container_url="http://c:9000"))
    assert {r.method for r in net.requests} <= {"GET"}
    assert all(not r.content for r in net.requests)
    assert writer.writes == []


def test_real_probe_keeps_the_tuple_contract(monkeypatch):
    Net(monkeypatch, lambda r: reply(401))
    assert run(cp.real_probe("caldera", config={}, secrets={"apiKey": "k"})) == (
        False,
        "HTTP 401 from http://caldera:8888/api/v2/health (API key rejected)",
        True,
    )
