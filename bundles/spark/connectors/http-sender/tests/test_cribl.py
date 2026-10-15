"""Cribl mode: the transport, the `cribl_<source>` destinations and how the tools use them. No network: the
endpoint is an httpx MockTransport and the token is an obviously fake value.

Run from the connector directory:  python3 -m pytest -x
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runtime.organization_view import get_view  # noqa: E402
from src import collector, connector, cribl, destinations, profiles  # noqa: E402

TOKEN = "test-token-not-real"
URL = "https://api-tenant.example.test/logs/v1/integrated/cribl/data"
HTTP_URL = "https://api-tenant.example.test/logs/v1/event"
HTTP_KEY = "test-collector-key-not-real"
OKTA = cribl.SOURCES["okta_sso"]
AWS = cribl.SOURCES["aws_audit"]


def events(n, **extra):
    return [{"n": i, **extra} for i in range(n)]


def mock(statuses=(200,), seen=None, body=None):
    """Answer with `statuses` in order (the last repeats); a 200 counts the NDJSON lines unless `body` says otherwise."""
    queue = list(statuses)
    seen = seen if seen is not None else []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        status = queue.pop(0) if len(queue) > 1 else queue[0]
        if status != 200:
            return httpx.Response(status, json={"error": "x"})
        lines = [x for x in request.content.decode().split("\n") if x]
        return httpx.Response(200, json=body if body is not None else {"num_records": len(lines), "success": "true"})

    return httpx.MockTransport(handler)


def post(evs, *, source=OKTA, statuses=(200,), seen=None, body=None, sleeps=None, **kw):
    return cribl.post(URL, TOKEN, source, evs, transport=mock(statuses, seen, body),
                      sleep=(sleeps.append if sleeps is not None else (lambda _s: None)), **kw)


# -- the wire contract --------------------------------------------------------------------------------------------

def test_request_matches_the_measured_wire_contract():
    seen: list[httpx.Request] = []
    result = post(events(3, vendor="evt"), seen=seen, integration="my-wave")
    assert result["ok"] and result["sent"] == 3 and result["batches"] == 1 and result["num_records"] == 3
    assert len(seen) == 1
    req = seen[0]
    assert str(req.url) == URL and req.method == "POST"
    assert req.headers["authorization"] == TOKEN  # raw, no Bearer
    assert req.headers["source-identifier"] == OKTA.uuid
    assert req.headers["format"] == "json"
    assert req.headers["integration-identifier"] == "my-wave"
    assert req.headers["content-type"] == "application/json"
    assert "vendor" not in req.headers and "product" not in req.headers  # only the generic UUID needs them


def test_every_line_is_wrapped_in_data_and_the_body_ends_with_a_newline():
    seen: list[httpx.Request] = []
    sent = [{"eventType": "user.session.start", "nested": {"a": [1, 2]}, "text": "line\nbreak"}, {"x": 1}]
    post(sent, seen=seen)
    body = seen[0].content.decode()
    assert body.endswith("\n") and not body.endswith("\n\n")
    lines = body.split("\n")[:-1]
    assert len(lines) == 2  # an embedded newline is escaped, so it never splits a record
    assert [json.loads(line) for line in lines] == [{"data": e} for e in sent]
    assert all(set(json.loads(line)) == {"data"} for line in lines)


def test_default_integration_name_is_used():
    seen: list[httpx.Request] = []
    post(events(1), seen=seen)
    assert seen[0].headers["integration-identifier"] == cribl.DEFAULT_INTEGRATION == "phantom-http-sender"


def test_601_events_go_out_in_batches_of_300_300_1():
    seen: list[httpx.Request] = []
    result = post(events(601), seen=seen)
    sizes = [len([x for x in r.content.decode().split("\n") if x]) for r in seen]
    assert sizes == [300, 300, 1]
    assert result["ok"] and result["sent"] == 601 and result["batches"] == 3
    assert result["batch_status"] == [200, 200, 200] and result["num_records"] == 601
    nums = [json.loads(x)["data"]["n"] for r in seen for x in r.content.decode().split("\n") if x]
    assert nums == list(range(601))  # order kept


def test_a_batch_is_also_kept_under_the_byte_limit():
    seen: list[httpx.Request] = []
    big = [{"blob": "x" * 400_000, "n": i} for i in range(5)]
    result = post(big, seen=seen)
    assert result["ok"] and len(seen) == 3 and all(len(r.content) <= 900_000 + 10 for r in seen)
    assert result["sent"] == 5


def test_an_oversized_event_is_refused_before_anything_is_sent():
    seen: list[httpx.Request] = []
    result = post([{"blob": "x" * 4_100_000}], seen=seen)
    assert not result["ok"] and "per-record size limit" in result["error"] and seen == []


def test_the_destination_is_not_a_vendor_collector_post():
    # The Cribl path never goes through collector.post_events (no vendor/product hint headers).
    seen: list[httpx.Request] = []
    post(events(1), seen=seen)
    assert "x-palo-alto-networks-vendor" not in seen[0].headers


def test_tls_verification_and_timeout_are_honoured(monkeypatch):
    captured = {}
    real = httpx.Client

    def spy(*args, **kw):
        captured.update(kw)
        return real(*args, **kw)

    monkeypatch.setattr(cribl.httpx, "Client", spy)
    post(events(1), verify_tls=False, timeout=7.5)
    assert captured["verify"] is False and captured["timeout"] == 60.0  # never below the lab sender's 60 s
    post(events(1))
    assert captured["verify"] is True and captured["timeout"] == 60.0
    post(events(1), timeout=90)
    assert captured["timeout"] == 90
    assert captured["follow_redirects"] is False  # pinned, not left to the library default


def test_a_redirect_is_never_followed_so_the_token_cannot_be_forwarded():
    seen: list[httpx.Request] = []

    def redirect(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(302, headers={"location": "https://elsewhere.example.test/steal"})

    result = cribl.post(URL, TOKEN, OKTA, events(1), transport=httpx.MockTransport(redirect))
    assert not result["ok"] and result["http_status"] == 302 and len(seen) == 1
    assert TOKEN not in repr(result)


def test_a_lost_answer_is_never_retried_but_a_failed_connection_is():
    seen: list[httpx.Request] = []
    sleeps: list[float] = []

    def timeout(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        raise httpx.ReadTimeout("timed out")

    lost = cribl.post(URL, TOKEN, OKTA, events(1), transport=httpx.MockTransport(timeout), sleep=sleeps.append)
    assert not lost["ok"] and len(seen) == 1 and sleeps == [] and lost["error"].startswith("ReadTimeout")
    seen.clear()

    def refused(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        raise httpx.ConnectError("refused")

    down = cribl.post(URL, TOKEN, OKTA, events(1), transport=httpx.MockTransport(refused), sleep=sleeps.append)
    assert not down["ok"] and len(seen) == 4 and len(sleeps) == 3 and down["error"].startswith("ConnectError")


# -- failures -----------------------------------------------------------------------------------------------------

def test_a_wrong_num_records_or_success_flag_is_a_failure():
    short = post(events(3), body={"num_records": 2, "success": "true"})
    assert not short["ok"] and short["sent"] == 0 and "counted 2 records for a batch of 3" in short["error"]
    refused = post(events(3), body={"num_records": 3, "success": "false"})
    assert not refused["ok"] and "success=false" in refused["error"]
    odd = post(events(3), body={"hello": "world"})
    assert not odd["ok"] and "num_records" in odd["error"]


def test_num_records_may_be_a_string_of_digits_but_nothing_else():
    ok = post(events(3), body={"num_records": "3", "success": "true"})
    assert ok["ok"] and ok["sent"] == 3 and ok["num_records"] == 3  # a landed batch is never reported as failed
    for bad in ("three", "3.0", "-3", "", None, 3.0, True, [3], "٣"):
        result = post(events(3), body={"num_records": bad, "success": "true"})
        assert not result["ok"] and result["sent"] == 0, repr(bad)
    short = post(events(3), body={"num_records": "2", "success": "true"})
    assert not short["ok"] and "counted 2 records" in short["error"] and short["num_records"] == 0


def test_each_status_is_explained_without_the_collector_wording():
    for status, needle in ((400, "required header"), (401, "token is wrong"), (403, "not allowed"),
                           (404, "integrated/cribl/data"), (413, "too large"), (500, "HTTP 500")):
        seen: list[httpx.Request] = []
        result = post(events(2), statuses=(status,), seen=seen)
        assert not result["ok"] and result["http_status"] == status and needle in result["error"], status
        assert len(seen) == 1, f"{status} must not be retried"
        assert "/logs/v1/event" not in result["error"]


def test_429_is_retried_with_backoff_then_succeeds():
    seen: list[httpx.Request] = []
    sleeps: list[float] = []
    result = post(events(2), statuses=(429, 429, 200), seen=seen, sleeps=sleeps)
    assert result["ok"] and len(seen) == 3 and sleeps == [1.0, 2.0]


def test_a_failure_after_the_first_batch_reports_what_was_accepted():
    result = post(events(650), statuses=(200, 401))
    assert not result["ok"] and result["sent"] == 300 and result["failed"] == 350
    assert result["batches"] == 1 and result["batch_status"] == [200, 401] and result["http_status"] == 401


def test_the_http_collector_url_is_refused_by_name_before_any_request():
    seen: list[httpx.Request] = []
    for wrong in ("https://api-tenant.example.test/logs/v1/event", "https://api-tenant.example.test/",
                  "https://api-tenant.example.test/logs/v1/integrated/cribl/data/extra"):
        result = cribl.post(wrong, TOKEN, OKTA, events(1), transport=mock(seen=seen))
        assert not result["ok"] and cribl.PATH in result["error"] and "/logs/v1/event URL" in result["error"], wrong
        assert cribl.check_url(wrong) == result["error"].removeprefix("")
    assert seen == [] and cribl.check_url(URL) is None
    assert cribl.check_url("https://api-tenant.example.test/proxy" + cribl.PATH) is None  # a prefix path is fine


def test_a_non_https_url_and_a_bad_integration_name_never_reach_the_network():
    seen: list[httpx.Request] = []
    plain = cribl.post("http://api-tenant.example.test/x", TOKEN, OKTA, events(1), transport=mock(seen=seen))
    assert not plain["ok"] and "https" in plain["error"]
    for bad in ("", "has\nnewline", "x" * 65, "-leading"):
        result = post(events(1), seen=seen, integration=bad)
        assert not result["ok"] and "criblIntegration" in result["error"], repr(bad)
    assert seen == []


# -- the token never leaves ---------------------------------------------------------------------------------------

def test_the_token_is_scrubbed_from_a_response_that_echoes_it():
    def echo(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text=f"bad Authorization header {request.headers['authorization']}")

    result = cribl.post(URL, TOKEN, OKTA, events(1), transport=httpx.MockTransport(echo))
    assert not result["ok"] and "bad Authorization header" in result["response"]
    assert TOKEN not in repr(result) and "[redacted]" in result["response"]


def test_a_transport_error_is_reported_by_type_only_whatever_its_message_quotes():
    # h11's complaint about a bad header value quotes it, escaped; scrubbing the raw token would miss that form.
    tricky = "tok-line1\nline2"

    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.LocalProtocolError(f"Illegal header value {tricky.encode()!r} for {tricky!r} {TOKEN}")

    sleeps: list[float] = []
    result = cribl.post(URL, TOKEN, OKTA, events(1), transport=httpx.MockTransport(boom), sleep=sleeps.append)
    assert result["error"] == "LocalProtocolError: the request could not be completed"
    assert sleeps == []  # a malformed request is not retried
    text = repr(result)
    for form in (TOKEN, tricky, repr(tricky), repr(tricky.encode()), "line2"):
        assert form not in text


def test_the_token_is_scrubbed_from_a_200_that_echoes_it():
    result = post(events(1), body={"num_records": 1, "success": "true", "echo": TOKEN})
    assert result["ok"] and TOKEN not in repr(result)


def test_every_refusal_is_a_fixed_message_that_names_no_part_of_the_token():
    seen: list[httpx.Request] = []
    for bad in ("alpha-secret beta-secret", "gamma-secret\ndelta-secret", "ünïcode-secret-ε", "x1y2z3\tq4r5s6",
                "x" * 40 + " " + "y" * 40, ""):
        result = cribl.post(URL, bad, OKTA, events(1), transport=mock(seen=seen))
        assert result["error"] == collector.SECRET_REFUSED.format(what="the Cribl token (criblToken)"), repr(bad)
        assert bad.strip() == "" or all(chunk not in repr(result) for chunk in bad.split())
    assert seen == []  # nothing is sent with a token that cannot be a header value
    for url in (f"http://{TOKEN}.example.test/", f"https://{TOKEN}.example.test/other"):
        result = cribl.post(url, TOKEN, OKTA, events(1), transport=mock(seen=seen))
        assert not result["ok"] and TOKEN not in repr(result)


# -- the source table ---------------------------------------------------------------------------------------------

def test_the_source_table_mirrors_the_lab_sender():
    assert set(cribl.SOURCES) == {"okta_sso", "azure_ad_signins", "azure_ad_audit", "azure_event_hub", "aws_audit",
                                  "gcp_cloud_logging", "windows_events", "proofpoint_tap"}
    assert cribl.SOURCES["okta_sso"].dataset == "okta_sso_raw" and cribl.SOURCES["aws_audit"].dataset == "amazon_aws_raw"
    assert cribl.SOURCES["gcp_cloud_logging"].dataset == "google_cloud_logging_raw"
    assert cribl.SOURCES["azure_ad_audit"].dataset == "msft_azure_ad_audit_raw"
    uuids = [s.uuid for s in cribl.SOURCES.values()]
    assert len(set(uuids)) == len(uuids) and all(len(u) == 32 and int(u, 16) >= 0 for u in uuids)
    assert "af01292940d7426594d3d3e55ae17ee0" not in uuids  # the generic UUID is the HTTP collector's job


# -- destinations -------------------------------------------------------------------------------------------------

def load(**over):
    cfg = {"url": HTTP_URL, "key": HTTP_KEY, "vendor": "Okta", "product": "SSO", "extra": "", "extra_keys": "",
           "cribl_url": URL, "cribl_token": TOKEN, **over}
    return destinations.load(cfg)


def test_both_set_registers_one_destination_per_source_after_the_http_ones():
    dests, problems = load()
    assert problems == []
    assert list(dests)[0] == "okta_sso"  # the primary stays the default
    assert [n for n in dests if n.startswith("cribl_")] == [f"cribl_{a}" for a in cribl.SOURCES]
    d = dests["cribl_aws_audit"]
    assert (d.url, d.key, d.source, d.dataset) == (URL, TOKEN, "aws_audit", "amazon_aws_raw")
    assert d.host == "api-tenant.example.test" and not d.primary
    assert dests["cribl_okta_sso"].dataset == "okta_sso_raw"  # its own destination, next to the HTTP okta_sso


@pytest.mark.parametrize("over,needle", [
    ({"cribl_token": ""}, "criblUrl is set but the criblToken secret is empty"),
    ({"cribl_url": ""}, "criblToken secret is set but criblUrl is empty"),
])
def test_only_one_of_url_and_token_registers_nothing_and_says_so(over, needle):
    dests, problems = load(**over)
    assert list(dests) == ["okta_sso"]
    assert any(needle in p for p in problems)
    assert TOKEN not in " ".join(problems)


def test_neither_set_is_the_unchanged_http_only_instance():
    dests, problems = load(cribl_url="", cribl_token="")
    assert list(dests) == ["okta_sso"] and problems == []
    assert destinations.load({"url": HTTP_URL, "key": HTTP_KEY, "vendor": "Okta", "product": "SSO"})[1] == []


def test_cribl_destinations_exist_without_a_primary_and_a_reserved_name_is_reported():
    dests, problems = load(vendor="", product="")
    assert any("vendor and product are required" in p for p in problems) and "cribl_okta_sso" in dests
    clash = f'[{{"url": "{HTTP_URL}", "vendor": "Cribl", "product": "Okta SSO"}}]'
    dests, problems = load(extra=clash)
    assert dests["cribl_okta_sso"].source is None  # the configured HTTP destination keeps the name
    assert any("reserved for the Cribl source 'okta_sso'" in p for p in problems)


def test_a_bad_integration_name_is_a_listed_problem_not_a_silent_send_failure():
    _, problems = load(cribl_integration="bad\nname")
    assert any("criblIntegration" in p and "will fail" in p for p in problems)
    assert load(cribl_integration="ok-name")[1] == [] and load()[1] == []
    # With only the token set Cribl is not configured, so the name is not checked (the one-of-two problem is reported instead).
    assert not any("criblIntegration" in p for p in load(cribl_url="", cribl_integration="bad\nname")[1])


@pytest.mark.parametrize("wanted", ["cribl_aws_audit", "CRIBL_AWS_AUDIT", "cribl_aws_audit_raw", " cribl-aws-audit "])
def test_a_cribl_destination_is_addressed_by_name(wanted):
    dests, problems = load()
    dest, error = destinations.resolve(dests, problems, wanted)
    assert error is None and dest.name == "cribl_aws_audit"


def test_a_destination_never_shows_its_key_in_a_repr():
    dests, _ = load(extra=f'[{{"url": "{HTTP_URL}", "vendor": "A", "product": "B"}}]', extra_keys='{"a_b": "other-key-not-real"}')
    text = repr(dests)
    assert TOKEN not in text and HTTP_KEY not in text and "other-key-not-real" not in text


def test_check_flags_a_key_that_cannot_be_a_header_value_for_both_kinds_of_destination():
    http, _ = load(key="has space")
    problem = destinations.check(http["okta_sso"])
    assert "collectorKey" in problem and "printable ASCII" in problem and "has space" not in problem
    cr, _ = load(cribl_token="tok\nnewline")
    problem = destinations.check(cr["cribl_okta_sso"])
    assert "criblToken" in problem and "printable ASCII" in problem and "newline" not in problem


def test_check_flags_a_non_https_cribl_url_and_passes_a_good_one():
    dests, _ = load()
    assert destinations.check(dests["cribl_aws_audit"]) is None
    bad, _ = load(cribl_url="http://api-tenant.example.test/x")
    problem = destinations.check(bad["cribl_aws_audit"])
    assert "https" in problem and "criblUrl" in problem and TOKEN not in problem
    bare = destinations.Destination("cribl_x", URL, "", "Cribl", "X", source="aws_audit")
    assert "criblToken" in destinations.check(bare)
    wrong_path, _ = load(cribl_url=HTTP_URL)  # the HTTP collector's URL pasted into criblUrl
    assert cribl.PATH in destinations.check(wrong_path["cribl_aws_audit"])


# -- the tool layer -----------------------------------------------------------------------------------------------

@pytest.fixture
def cfg(monkeypatch):
    values = {"url": HTTP_URL, "key": HTTP_KEY, "vendor": "Okta", "product": "SSO", "extra": "", "extra_keys": "",
              "organization": "", "verify_tls": True, "timeout": 5.0,
              "cribl_url": URL, "cribl_token": TOKEN, "cribl_integration": "wave-7"}
    monkeypatch.setattr(connector, "_settings", lambda: dict(values))
    return values


@pytest.fixture
def out(monkeypatch):
    """Stand-ins for both transports, recording which one each send used."""
    calls = {"http": [], "cribl": []}

    def fake_http(url, key, evs, **kw):
        calls["http"].append({"url": url, "key": key, "events": evs, **kw})
        return {"ok": True, "sent": len(evs), "failed": 0, "batches": 1, "http_status": 200, "response": "{}"}

    def fake_cribl(url, token, source, evs, **kw):
        calls["cribl"].append({"url": url, "token": token, "source": source, "events": evs, **kw})
        return {"ok": True, "sent": len(evs), "failed": 0, "batches": 1, "batch_status": [200],
                "num_records": len(evs), "http_status": 200, "response": '{"num_records":%d,"success":"true"}' % len(evs)}

    monkeypatch.setattr(connector.collector, "post_events", fake_http)
    monkeypatch.setattr(connector.cribl, "post", fake_cribl)
    return calls


def test_list_destinations_shows_the_cribl_destinations_and_never_the_token(cfg):
    result = connector.phantom_list_destinations()
    rows = {r["destination"]: r for r in result["destinations"]}
    assert list(rows)[0] == "okta_sso" and rows["okta_sso"]["default"] and rows["okta_sso"]["mode"] == "http"
    row = rows["cribl_aws_audit"]
    assert row["mode"] == "cribl" and row["source"] == "aws_audit" and row["dataset"] == "amazon_aws_raw"
    assert row["host"] == "api-tenant.example.test" and row["ready"] and row["problem"] is None and not row["default"]
    assert "source" not in rows["okta_sso"]
    assert {"aws_cloudtrail", "gcp_audit", "azure_ad_audit"} <= set(result["profiles"])
    assert TOKEN not in repr(result) and HTTP_KEY not in repr(result)


@pytest.mark.parametrize("which,needle", [("cribl_token", "criblUrl is set but the criblToken"),
                                           ("cribl_url", "criblToken secret is set but criblUrl is empty")])
def test_list_destinations_reports_one_of_the_two_missing(cfg, which, needle):
    cfg[which] = ""
    result = connector.phantom_list_destinations()
    assert any(needle in p for p in result["problems"])
    assert [r["destination"] for r in result["destinations"]] == ["okta_sso"]


def test_list_destinations_reports_a_bad_integration_name(cfg):
    cfg["cribl_integration"] = "bad\nname"
    assert any("criblIntegration" in p for p in connector.phantom_list_destinations()["problems"])


def test_list_destinations_marks_a_cribl_destination_with_a_bad_url_not_ready(cfg):
    cfg["cribl_url"] = "http://api-tenant.example.test/x"
    row = next(r for r in connector.phantom_list_destinations()["destinations"] if r["destination"] == "cribl_okta_sso")
    assert not row["ready"] and "https" in row["problem"]


def test_send_events_to_a_cribl_destination_goes_through_cribl_post_unchanged(cfg, out):
    payload = [{"eventType": "user.session.start", "published": "2026-10-04T10:00:00.000Z"}]
    result = connector.phantom_send_events(payload, destination="cribl_okta_sso")
    assert result["ok"] and result["destination"] == "cribl_okta_sso" and result["dataset"] == "okta_sso_raw"
    assert result["num_records"] == 1 and result["batch_status"] == [200]
    assert out["http"] == []
    call = out["cribl"][0]
    assert (call["url"], call["token"], call["source"], call["events"]) == (URL, TOKEN, cribl.SOURCES["okta_sso"], payload)
    assert call["integration"] == "wave-7" and call["verify_tls"] is True and call["timeout"] == 5.0
    assert TOKEN not in repr(result)


def test_other_destinations_behave_exactly_as_before(cfg, out):
    result = connector.phantom_send_events([{"a": 1}])
    assert result["destination"] == "okta_sso" and "num_records" not in result
    connector.phantom_generate_events("okta", "benign_logins", count=3)
    connector.phantom_send_test_event()
    assert out["cribl"] == [] and len(out["http"]) == 3
    assert all((c["url"], c["key"]) == (HTTP_URL, HTTP_KEY) for c in out["http"])
    assert out["http"][1]["events"][0]["actor"]["alternateId"].endswith("@" + get_view().email_domain)  # the organization's people, as before


def test_generate_events_defaults_a_cloud_profile_to_its_cribl_destination(cfg, out):
    result = connector.phantom_generate_events("aws_cloudtrail", "s3_public_exposure", count=3)
    assert result["ok"] and result["destination"] == "cribl_aws_audit" and result["dataset"] == "amazon_aws_raw"
    assert "warning" not in result and result["sent"] == 3 and result["profile"] == "aws_cloudtrail"
    assert out["http"] == [] and out["cribl"][0]["source"] == cribl.SOURCES["aws_audit"]
    assert [e["eventName"] for e in out["cribl"][0]["events"]] == ["PutBucketPolicy", "PutBucketAcl", "DeletePublicAccessBlock"]
    for profile, scenario, dest in (("gcp_audit", "data_asset_public", "cribl_gcp_cloud_logging"),
                                    ("azure_ad_audit", "ca_policy_deleted", "cribl_azure_ad_audit"),
                                    ("okta", "tor_signin", "cribl_okta_sso"), ("okta", "fastpass_phishing", "cribl_okta_sso")):
        assert connector.phantom_generate_events(profile, scenario, count=2)["destination"] == dest


def test_a_cloud_profile_never_falls_back_to_the_http_primary(cfg, out):
    cfg["cribl_url"] = cfg["cribl_token"] = ""
    result = connector.phantom_generate_events("aws_cloudtrail", "guardduty_detector_deleted", count=1)
    assert not result["ok"] and "criblUrl" in result["error"] and "criblToken" in result["error"]
    assert out["http"] == [] and out["cribl"] == []
    cfg["cribl_url"] = URL  # one of the two is not enough either
    assert not connector.phantom_generate_events("gcp_audit", "data_asset_public", count=1)["ok"]


def test_a_cloud_dry_run_needs_no_cribl_and_sends_nothing(cfg, out):
    cfg["cribl_url"] = cfg["cribl_token"] = cfg["url"] = cfg["key"] = ""
    result = connector.phantom_generate_events("aws_cloudtrail", "pentest_tool", count=6, dry_run=True)
    assert result["ok"] and result["dry_run"] and result["sent"] == 0 and len(result["events"]) == 3
    assert result["destination"] == "cribl_aws_audit" and result["dataset"] == "amazon_aws_raw" and "warning" not in result
    assert out == {"http": [], "cribl": []}


def test_with_cribl_configured_four_okta_scenarios_move_to_it_and_the_others_keep_the_primary(cfg, out):
    for scenario in ("password_spray", "benign_logins"):
        assert connector.phantom_generate_events("okta", scenario, count=4)["destination"] == "okta_sso"
    for scenario in ("failed_then_success", "mfa_fatigue", "tor_signin", "fastpass_phishing"):
        assert connector.phantom_generate_events("okta", scenario, count=4)["destination"] == "cribl_okta_sso", scenario
    assert [len(out["http"]), len(out["cribl"])] == [2, 4]


def test_without_cribl_every_okta_scenario_behaves_as_in_0_3_1(cfg, out):
    cfg["cribl_url"] = cfg["cribl_token"] = ""
    for scenario in ("benign_logins", "failed_then_success", "password_spray", "mfa_fatigue"):
        result = connector.phantom_generate_events("okta", scenario, count=4)
        assert result["destination"] == "okta_sso" and "warning" not in result, scenario
    assert len(out["http"]) == 4 and out["cribl"] == []


def test_sending_mfa_fatigue_to_the_http_collector_warns_only_when_cribl_is_configured(cfg, out):
    warned = connector.phantom_generate_events("okta", "mfa_fatigue", count=4, destination="okta_sso")
    assert "meant for the destination 'cribl_okta_sso'" in warned["warning"]
    cfg["cribl_url"] = cfg["cribl_token"] = ""
    assert "warning" not in connector.phantom_generate_events("okta", "mfa_fatigue", count=4, destination="okta_sso")


def test_the_agent_facing_text_says_okta_mfa_scenarios_go_through_cribl():
    import yaml

    doc = connector.phantom_generate_events.__doc__
    assert "mfa_fatigue and failed_then_success" in doc and "cribl_okta_sso" in doc
    manifest = yaml.safe_load((Path(__file__).resolve().parents[1] / "connector.yaml").read_text())
    tool = next(t for t in manifest["spec"]["tools"] if t["name"] == "generate_events")
    assert "mfa_fatigue / failed_then_success" in tool["description"] and "cribl_okta_sso" in tool["description"]


def test_an_omitted_count_is_one_recipe_for_a_cloud_profile_and_20_for_the_rest(cfg, out):
    assert connector.phantom_generate_events("aws_cloudtrail", "guardduty_detector_deleted")["sent"] == 1
    assert connector.phantom_generate_events("aws_cloudtrail", "iam_new_admin_identity")["sent"] == 5
    assert connector.phantom_generate_events("azure_ad_audit", "ca_policy_deleted")["sent"] == 1
    assert connector.phantom_generate_events("okta", "tor_signin")["sent"] == 20
    assert connector.phantom_generate_events("okta", "benign_logins")["sent"] == 20
    assert connector.phantom_generate_events("aws_cloudtrail", "guardduty_detector_deleted", count=7)["sent"] == 7


def test_okta_cribl_scenario_without_cribl_falls_back_to_the_primary_with_a_warning(cfg, out):
    cfg["cribl_url"] = cfg["cribl_token"] = ""
    result = connector.phantom_generate_events("okta", "tor_signin", count=2)
    assert result["ok"] and result["destination"] == "okta_sso"
    assert "meant for the destination 'cribl_okta_sso'" in result["warning"]


def test_okta_mfa_fatigue_can_be_sent_to_the_cribl_destination_without_a_warning(cfg, out):
    result = connector.phantom_generate_events("okta", "mfa_fatigue", count=5, destination="cribl_okta_sso")
    assert result["ok"] and "warning" not in result and out["cribl"][0]["source"].uuid == cribl.SOURCES["okta_sso"].uuid


def test_warnings_for_a_destination_the_profile_is_not_meant_for(cfg, out):
    wrong = connector.phantom_generate_events("aws_cloudtrail", "guardduty_detector_deleted", count=1, destination="okta_sso")
    assert "produces events for 'cribl_aws_audit' but the destination is 'okta_sso'" in wrong["warning"]
    elsewhere = connector.phantom_generate_events("okta", "benign_logins", count=2, destination="cribl_aws_audit")
    assert "'okta_okta' or 'okta_sso'" in elsewhere["warning"]
    odd = connector.phantom_generate_events("okta", "fastpass_phishing", count=1, destination="okta_sso")
    assert "meant for the destination 'cribl_okta_sso'" in odd["warning"]


def test_a_cloud_scenario_raises_a_too_small_count_to_its_step_count(cfg, out):
    """Asking for fewer events than the pattern needs still gets the pattern; the result says what was used."""
    result = connector.phantom_generate_events("aws_cloudtrail", "iam_new_admin_identity", count=3)
    assert result["ok"] and result["count_raised"]["asked"] == 3 and result["count_raised"]["used"] == 5


def test_send_test_event_to_a_cribl_destination_uses_its_sources_profile(cfg, out):
    result = connector.phantom_send_test_event(destination="cribl_aws_audit")
    event = out["cribl"][0]["events"][0]
    assert result["ok"] and event["eventSource"] == "sts.amazonaws.com" and event["eventName"] == "GetCallerIdentity"
    assert result["test_id"] == event["eventID"] and result["dataset"] == "amazon_aws_raw"
    assert result["verify_with_xql"] == f'dataset = amazon_aws_raw | filter eventID = "{event["eventID"]}"'
    assert result["num_records"] == 1 and TOKEN not in repr(result)
    connector.phantom_send_test_event(destination="cribl_okta_sso")
    assert out["cribl"][1]["events"][0]["eventType"] == "user.session.start"


def test_send_test_event_to_a_cribl_source_without_a_profile_is_the_generic_object(cfg, out):
    # (cribl_windows_events has its own rendered 4624, see test_windows_events.py)
    assert profiles.for_destination("cribl_azure_event_hub") is None
    result = connector.phantom_send_test_event(destination="cribl_azure_event_hub")
    assert set(out["cribl"][0]["events"][0]) == {"phantom_test_id", "phantom_test_time", "message"}
    assert result["dataset"] == "msft_azure_raw"


def test_a_cribl_destination_with_a_bad_url_is_refused_before_any_send(cfg, out):
    cfg["cribl_url"] = "http://api-tenant.example.test/x"
    for result in (connector.phantom_send_events([{"a": 1}], destination="cribl_aws_audit"),
                   connector.phantom_send_test_event(destination="cribl_aws_audit"),
                   connector.phantom_generate_events("aws_cloudtrail", "guardduty_detector_deleted", count=1)):
        assert not result["ok"] and "https" in result["error"]
    assert out == {"http": [], "cribl": []}


def test_end_to_end_through_the_real_transport_and_the_token_stays_out_of_every_result(cfg, monkeypatch):
    seen: list[httpx.Request] = []
    real = cribl.post
    monkeypatch.setattr(connector.cribl, "post", lambda *a, **k: real(*a, transport=mock(seen=seen), **k))
    results = [
        connector.phantom_generate_events("aws_cloudtrail", "s3_public_exposure", count=3),
        connector.phantom_generate_events("gcp_audit", "tor_api_call", count=1),
        connector.phantom_send_events([{"a": 1}], destination="cribl_okta_sso"),
        connector.phantom_send_test_event(destination="cribl_azure_ad_audit"),
        connector.phantom_list_destinations(),
    ]
    assert all(r["ok"] for r in results)
    assert [r.headers["source-identifier"] for r in seen] == [
        cribl.SOURCES[a].uuid for a in ("aws_audit", "gcp_cloud_logging", "okta_sso", "azure_ad_audit")]
    assert all(r.headers["integration-identifier"] == "wave-7" and r.headers["authorization"] == TOKEN for r in seen)
    assert all(json.loads(line).keys() == {"data"} for r in seen for line in r.content.decode().split("\n") if line)
    assert TOKEN not in repr(results) and HTTP_KEY not in repr(results)


def test_settings_reads_the_cribl_fields_with_defaults(monkeypatch):
    import types

    cfg_mod = types.ModuleType("config.config")
    cfg_mod.get_config = lambda: types.SimpleNamespace(collectorUrl=HTTP_URL, collectorKey=HTTP_KEY, vendor="Okta",
                                                       product="SSO")
    monkeypatch.setitem(sys.modules, "config", types.ModuleType("config"))
    monkeypatch.setitem(sys.modules, "config.config", cfg_mod)
    plain = connector._settings()
    assert plain["cribl_url"] == "" and plain["cribl_token"] == "" and plain["cribl_integration"] == "phantom-http-sender"
    cfg_mod.get_config = lambda: types.SimpleNamespace(
        collectorUrl=HTTP_URL, collectorKey=HTTP_KEY, vendor="Okta", product="SSO",
        criblUrl=f" {URL} ", criblToken=f" {TOKEN} ", criblIntegration="")
    full = connector._settings()
    assert (full["cribl_url"], full["cribl_token"], full["cribl_integration"]) == (URL, TOKEN, "phantom-http-sender")


def test_profile_lookup_helpers():
    assert profiles.for_destination("cribl_okta_sso").NAME == "okta"
    assert profiles.for_destination("cribl_gcp_cloud_logging").NAME == "gcp_audit"
    assert profiles.for_destination("cribl_windows_events").NAME == "windows"  # 0.6.0: the windows profile (was None before it)
    assert profiles.for_destination("cribl_azure_event_hub") is None  # a Cribl source with no profile
    assert profiles.for_destination("cribl_proofpoint_tap").NAME == "proofpoint_tap"  # sample only; the HTTP collector stays its default
    assert profiles.default_destination(profiles.get("proofpoint_tap"), "benign_mail") is None
    assert profiles.default_destination(profiles.get("okta"), "benign_logins") is None
    assert profiles.default_destination(profiles.get("okta"), "tor_signin") == "cribl_okta_sso"
    assert profiles.default_destination(profiles.get("aws_cloudtrail"), "tor_api_call") == "cribl_aws_audit"
