"""Windows events through the `cribl_windows_events` destination. No network: the endpoint is an httpx MockTransport,
or (for the secret hygiene check) a 127.0.0.1 socket server; the token is an obviously fake value.

The renderer and the structured-event validation are copies of wec-sender's, so the tests load wec-sender's own code by path
and compare the XML byte for byte for the event blocks of the nine WEC trigger skills.

Run from the connector directory:  python3 -m pytest -x
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[0]))
sys.path.insert(0, str(HERE))  # test_secret_hygiene's server and assertions are reused below

from src import connector, cribl, destinations, windows_events, winevent  # noqa: E402
import test_secret_hygiene as hygiene  # noqa: E402

REPO = HERE.parents[4]
WEC_SRC = REPO / "bundles/spark/connectors/wec-sender/src"
SKILLS = REPO / "bundles/spark/mcp/skills/workflows"
STEMS = ["machine_account_domain_admins", "privileged_group_add", "dcsync", "guest_account_enabled", "sms_admins",
         "weak_service_tickets", "excessive_lockouts", "samaccountname_change", "multiple_account_deletions"]

TOKEN = "test-token-not-real"
URL = "https://api-tenant.example.test/logs/v1/integrated/cribl/data"
HTTP_URL = "https://api-tenant.example.test/logs/v1/event"
HTTP_KEY = "test-collector-key-not-real"
WIN = cribl.SOURCES["windows_events"]
REAL_POST = cribl.post  # the fixtures below replace connector.cribl.post
BASE = datetime(2026, 10, 5, 12, 0, 0, tzinfo=timezone.utc)
DNS = "phantom.lab"


def load_wec():
    """wec-sender's own package, loaded by path under a private name (it also has a `src` package)."""
    spec = importlib.util.spec_from_file_location("wec_sender_src", WEC_SRC / "__init__.py",
                                                  submodule_search_locations=[str(WEC_SRC)])
    module = importlib.util.module_from_spec(spec)
    sys.modules["wec_sender_src"] = module
    keep, sys.dont_write_bytecode = sys.dont_write_bytecode, True  # never write a __pycache__ into wec-sender
    try:
        spec.loader.exec_module(module)
        import wec_sender_src.connector as wec_connector
        import wec_sender_src.winevent as wec_winevent
    finally:
        sys.dont_write_bytecode = keep

    return wec_connector, wec_winevent


wec_connector, wec_winevent = load_wec()


# -- the skills' event blocks -------------------------------------------------------------------------------------

def fill(text: str) -> str:
    """Replace the skill's `<CHANGE: label>` placeholders with simple fixed values (a time for `now minus N s`)."""
    def value(match: re.Match) -> str:
        label = match.group(1).strip()
        ago = re.fullmatch(r"now minus (\d+) s", label)
        if ago:
            return datetime.fromtimestamp(BASE.timestamp() - int(ago.group(1)), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        if "logon id" in label:
            return "0x9A4C21"
        if "RID" in label:
            return str(3300 + sum(map(ord, label)) % 500)
        if "IP" in label:
            return "10.20.30.40"
        return "fx-" + re.sub(r"\W+", "-", label)
    return re.sub(r"<CHANGE: ([^>]*)>", value, text)


def _normalise_now_tokens(text: str) -> str:
    """The skills write an event time as the literal `"now-310s"` (the connector resolves it); the profile's recipes keep the
    older `<CHANGE: now minus 310 s>` label form. Compare them in that one form."""
    return re.sub(r'"now-(\d+)s"', r'"<CHANGE: now minus \1 s>"', text)


def skill_events(stem: str) -> list[dict]:
    text = (SKILLS / f"trigger_{stem}_alert.md").read_text()
    blocks = [b for b in re.findall(r"```json\n(.*?)\n```", text, re.S) if '"events"' in b]
    assert blocks, stem
    parsed = []
    for block in blocks:
        filled = fill(_normalise_now_tokens(block))
        assert "<CHANGE" not in filled
        parsed.append(json.loads(filled)["events"])
    # A skill may repeat its events block (a Route B for Cribl): every copy must be the same events.
    assert all(events == parsed[0] for events in parsed[1:]), f"{stem}: its events blocks differ"
    return parsed[0]


# -- helpers: the endpoint and the tool layer ---------------------------------------------------------------------

def mock(seen):
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        lines = [x for x in request.content.decode().split("\n") if x]
        return httpx.Response(200, json={"num_records": len(lines), "success": "true"})

    return httpx.MockTransport(handler)


@pytest.fixture
def cfg(monkeypatch):
    values = {"url": HTTP_URL, "key": HTTP_KEY, "vendor": "Okta", "product": "SSO", "extra": "", "extra_keys": "",
              "organization": "", "verify_tls": True, "timeout": 5.0, "cribl_url": URL, "cribl_token": TOKEN,
              "cribl_integration": "wave-7"}
    monkeypatch.setattr(connector, "_settings", lambda: dict(values))
    return values


@pytest.fixture
def wire(cfg, monkeypatch):
    """The real cribl.post over a MockTransport; every request it makes is collected."""
    seen: list[httpx.Request] = []
    real = cribl.post
    monkeypatch.setattr(connector.cribl, "post", lambda *a, **k: real(*a, transport=mock(seen), **k))
    return seen


@pytest.fixture
def posted(cfg, monkeypatch):
    """A recording stand-in for cribl.post (and the HTTP collector), to prove what is, and is not, sent."""
    calls = {"cribl": [], "http": []}

    def fake_cribl(url, token, source, evs, **kw):
        calls["cribl"].append({"source": source, "events": evs})
        return {"ok": True, "sent": len(evs), "failed": 0, "batches": 1, "batch_status": [200],
                "num_records": len(evs), "http_status": 200, "response": "{}"}

    def fake_http(url, key, evs, **kw):
        calls["http"].append({"events": evs})
        return {"ok": True, "sent": len(evs), "failed": 0, "batches": 1, "http_status": 200, "response": "{}"}

    monkeypatch.setattr(connector.cribl, "post", fake_cribl)
    monkeypatch.setattr(connector.collector, "post_events", fake_http)
    return calls


def lines_of(request: httpx.Request) -> list[dict]:
    return [json.loads(x) for x in request.content.decode().split("\n") if x]


def logon(**kw) -> dict:
    return {"event_id": 4624, "computer": "PHWS-001", "time": "2026-10-05T10:00:00Z",
            "event_data": {"TargetUserName": "alice", "TargetDomainName": "PHANTOM", "LogonType": "3"}, **kw}


# -- (a) rendering parity with wec-sender -------------------------------------------------------------------------

@pytest.mark.parametrize("stem", STEMS)
def test_the_xml_is_byte_for_byte_what_wec_sender_renders_for_the_skills_events(stem):
    events = skill_events(stem)
    assert events
    ours = [p.xml for p in windows_events.prepare(events, DNS)]
    parsed = [wec_connector._structured_event(i, raw, DNS) for i, raw in enumerate(events)]
    theirs = [r.xml for r in wec_winevent.render_all(parsed)]
    assert ours == theirs and len(ours) == len(events)
    for xml in ours:  # and it is Windows Event XML
        assert ET.fromstring(xml).tag == f"{{{winevent.EVT_NS}}}Event"


@pytest.mark.parametrize("dns", ["Corp.Example", "PHANTOM.LAB", "phantom.lab"])
def test_the_computer_qualification_matches_wec_sender_for_any_suffix_case(dns):
    events = [logon(computer="PHDC02"), logon(computer="Srv.Other.Test", time="2026-10-05T10:01:00Z")]
    ours = [p.xml for p in windows_events.prepare(events, dns)]
    theirs = [r.xml for r in wec_winevent.render_all([wec_connector._structured_event(i, e, dns) for i, e in enumerate(events)])]
    assert ours == theirs and f"<Computer>PHDC02.{dns}</Computer>" in ours[0]


def test_the_copied_renderer_and_the_helpers_match_wec_sender_exactly():
    own, theirs = (winevent.__file__, wec_winevent.__file__)
    assert Path(own).read_text().split("\n", 4)[4] == Path(theirs).read_text()  # only the 4-line header differs
    for name in ("_EVENT_KEYS", "_SYSTEM_KEYS"):
        assert getattr(wec_connector, name) == getattr(windows_events, name)
    for value in (None, "", 1759658400, "2026-10-05T10:00:00Z", "2026-10-05T10:00:00.1234567Z", "2026-10-05T10:00:00+03:00"):
        assert windows_events.parse_time(value) == wec_connector._parse_time(value)
    assert windows_events.qualify(" PHDC02 ", DNS) == wec_connector._qualify(" PHDC02 ", DNS) == "PHDC02.phantom.lab"
    assert windows_events.qualify("dc.corp.example", DNS) == "dc.corp.example"


def test_record_ids_and_time_order_follow_wec_sender_when_computers_collide():
    events = [logon(time="2026-10-05T10:00:00Z"), logon(time="2026-10-05T10:00:00Z"), logon(time="2026-10-05T09:00:00Z")]
    ours = [p.xml for p in windows_events.prepare(events, DNS)]
    theirs = [r.xml for r in wec_winevent.render_all([wec_connector._structured_event(i, e, DNS) for i, e in enumerate(events)])]
    assert ours == theirs
    ids = [p.record_id for p in windows_events.prepare(events, DNS)]
    assert len(set(ids)) == 3 and ids == sorted(ids)


# -- (b) the wire: every posted line is {"data": "<Event ...>"} ----------------------------------------------------

def test_each_posted_line_is_a_data_wrapper_around_one_plain_xml_string(cfg, wire):
    events = skill_events("dcsync") + skill_events("sms_admins")
    result = connector.phantom_send_events(events, destination="cribl_windows_events")
    assert result["ok"] and result["sent"] == len(events) and result["num_records"] == len(events)
    assert len(wire) == 1
    req = wire[0]
    assert req.headers["source-identifier"] == WIN.uuid and req.headers["authorization"] == TOKEN
    assert req.headers["integration-identifier"] == "wave-7" and req.headers["format"] == "json"
    lines = lines_of(req)
    assert len(lines) == len(events)
    for line in lines:
        assert set(line) == {"data"} and isinstance(line["data"], str) and not isinstance(line["data"], dict)
        assert line["data"].startswith("<Event xmlns=") and line["data"].endswith("</Event>")
        assert ET.fromstring(line["data"]).tag.endswith("}Event")
    assert result["destination"] == "cribl_windows_events" and result["dataset"] == "microsoft_windows_raw"


def test_a_large_call_is_batched_by_cribl_post_at_300_lines(cfg, wire):
    events = [logon(event_data={"TargetUserName": f"u{i}"}) for i in range(650)]
    result = connector.phantom_send_events(events, destination="cribl_windows_events")
    assert result["ok"] and result["sent"] == 650 and result["batches"] == 3
    assert [len(lines_of(r)) for r in wire] == [300, 300, 50]
    assert all(isinstance(line["data"], str) for r in wire for line in lines_of(r))


def test_the_result_reports_what_was_rendered(cfg, wire):
    events = [logon(computer="PHWS-001", time="2026-10-05T10:00:00Z"), logon(computer="PHWS-002", time="2026-10-05T10:05:00Z"),
              logon(computer="dc.corp.example", time="2026-10-05T10:02:00Z")]
    result = connector.phantom_send_events(events, destination="cribl_windows_events")
    assert result["events"] == 3
    assert result["computers"] == {"PHWS-001.phantom.lab": 1, "PHWS-002.phantom.lab": 1, "dc.corp.example": 1}
    assert result["first_time"] == "2026-10-05T10:00:00.000Z" and result["last_time"] == "2026-10-05T10:05:00.000Z"
    assert len(result["sample_record_ids"]) == 3


def test_an_object_for_the_windows_source_is_refused_by_the_transport_and_nothing_is_sent():
    """The measured trap: {"data": {"_raw": ...}} is answered 200 and lands nothing."""
    seen: list[httpx.Request] = []
    post = lambda evs: REAL_POST(URL, TOKEN, WIN, evs, transport=mock(seen), sleep=lambda _s: None)  # noqa: E731
    result = post([{"_raw": "<Event/>"}])
    assert not result["ok"] and result["sent"] == 0 and "plain" in result["error"] and seen == []
    assert not post(["<Event/>", {"a": 1}])["ok"] and seen == []
    ok = post(["<Event/>"])
    assert ok["ok"] and lines_of(seen[0]) == [{"data": "<Event/>"}]
    other = REAL_POST(URL, TOKEN, cribl.SOURCES["aws_audit"], [{"a": 1}], transport=mock(seen), sleep=lambda _s: None)
    assert other["ok"] and lines_of(seen[1]) == [{"data": {"a": 1}}]  # objects stay fine for every other source


def test_profile_events_sent_to_the_windows_destination_keep_the_warning_and_are_not_sent_as_objects(cfg, wire):
    result = connector.phantom_generate_events("okta", "benign_logins", count=2, destination="cribl_windows_events")
    assert "'okta_okta' or 'okta_sso'" in result["warning"] and not result["ok"] and wire == []
    dry = connector.phantom_generate_events("okta", "benign_logins", count=2, destination="cribl_windows_events", dry_run=True)
    assert dry["ok"] and "warning" in dry and dry["dataset"] == "microsoft_windows_raw"


# -- (c) validation errors send nothing ---------------------------------------------------------------------------

BAD = [
    pytest.param(["not an event"], "events[0] is a string but not Windows Event XML", id="string-not-xml"),
    pytest.param([logon(), "<Event>"], "events[1] is not well-formed XML", id="malformed-xml-second-item"),
    pytest.param(["<Event/><Event/>"], "events[0] is not well-formed XML", id="two-roots"),
    pytest.param(['<!DOCTYPE x [<!ENTITY a "b">]><Event/>'], "events[0] is a string but not", id="doctype-before-event"),
    pytest.param(['<Event xmlns="urn:x"><!DOCTYPE y></Event>'], "must not declare a DOCTYPE", id="doctype-inside"),
    pytest.param(["<EventLog/>"], "root is not <Event>", id="wrong-root"),
    pytest.param([42], "events[0] must be an object", id="number"),
    pytest.param([None], "events[0] must be an object", id="none"),
    pytest.param([["a"]], "events[0] must be an object", id="list"),
    pytest.param([logon(), {"a": 1}], "events[1] has unknown field(s) a", id="vendor-object"),
    pytest.param([{"computer": "PHWS-001"}], "events[0].event_id is required", id="no-event-id"),
    pytest.param([{"event_id": "x", "computer": "PHWS-001"}], "events[0].event_id is required", id="bad-event-id"),
    pytest.param([{"event_id": 4624}], "events[0].computer is required", id="no-computer"),
    pytest.param([{"event_id": 4624, "computer": "  "}], "events[0].computer is required", id="blank-computer"),
    pytest.param([logon(time="yesterday")], "events[0].time must be an ISO-8601 timestamp", id="bad-time"),
    pytest.param([logon(event_data="x")], "events[0].event_data must be an object", id="bad-data"),
    pytest.param([logon(rendering="x")], "events[0].rendering must be an object", id="bad-rendering"),
    pytest.param([logon(provider=7)], "events[0].provider must be a string", id="bad-provider"),
    pytest.param([logon(), logon(level="high")], "events[1]: version, level, task", id="bad-level"),
    pytest.param([logon(), {"event_id": 9999, "computer": "PHWS-001"}], "events[1]: event id 9999 is not in the catalogue", id="uncatalogued"),
    pytest.param([logon(computer="PHWS\x01")], "control or invalid character", id="control-char-in-computer"),
]


@pytest.mark.parametrize("items,message", BAD)
def test_a_bad_item_returns_an_error_naming_it_and_nothing_is_sent(posted, items, message):
    result = connector.phantom_send_events(items, destination="cribl_windows_events")
    assert result["ok"] is False and message in result["error"], result
    assert posted == {"cribl": [], "http": []}


@pytest.mark.parametrize("events,message", [([], "non-empty list"), ("x", "non-empty list"), (None, "non-empty list"),
                                            ([logon()] * 5001, "at most 5000")])
def test_the_list_itself_is_validated_like_for_every_destination(posted, events, message):
    result = connector.phantom_send_events(events, destination="cribl_windows_events")
    assert not result["ok"] and message in result["error"] and posted == {"cribl": [], "http": []}


def test_the_destination_must_be_ready_first(cfg, posted):
    cfg["cribl_token"] = ""
    result = connector.phantom_send_events([logon()], destination="cribl_windows_events")
    assert not result["ok"] and "unknown destination" in result["error"] and posted["cribl"] == []


# -- (d) already-rendered XML passes through unchanged ------------------------------------------------------------

def test_an_xml_string_is_posted_exactly_as_given(cfg, wire):
    xml = wec_winevent.render_event(wec_connector._structured_event(0, logon(), DNS)).xml
    padded = "\n  " + xml + "\n"
    result = connector.phantom_send_events([xml, padded], destination="cribl_windows_events")
    assert result["ok"] and [line["data"] for line in lines_of(wire[0])] == [xml, padded]
    assert result["events"] == 2 and result["computers"] == {"PHWS-001.phantom.lab": 2}
    assert result["first_time"] == "2026-10-05T10:00:00.000Z" and len(result["sample_record_ids"]) == 2


def test_structured_and_xml_items_can_be_mixed_structured_first(cfg, wire):
    xml = wec_winevent.render_event(wec_connector._structured_event(0, logon(computer="PHWS-009"), DNS)).xml
    result = connector.phantom_send_events([xml, logon(computer="PHWS-002")], destination="cribl_windows_events")
    sent = [line["data"] for line in lines_of(wire[0])]
    assert result["ok"] and sent[1] == xml and "<Computer>PHWS-002.phantom.lab</Computer>" in sent[0]


# -- the DNS suffix and the settings ------------------------------------------------------------------------------

def organization_with_domain(monkeypatch, bundled_organization, dns: str, netbios: str) -> None:
    """The active organization becomes a copy of Phantom Lab on another domain (the autouse fixture restores the loader)."""
    import copy

    from runtime import organization_view as ov

    other = copy.deepcopy(bundled_organization)
    other["id"] = "corp"
    other["domain"].update(dns=dns, netbios=netbios, email_domain=dns)
    ov.set_organization_loader(lambda pinned: other)


def test_short_computer_names_get_the_organizations_suffix(cfg, wire, monkeypatch, bundled_organization):
    organization_with_domain(monkeypatch, bundled_organization, "corp.example", "CORP")
    connector.phantom_send_events([logon(computer="PHDC02"), logon(computer="srv.other.test")], destination="cribl_windows_events")
    xml = "".join(line["data"] for line in lines_of(wire[0]))
    assert "<Computer>PHDC02.corp.example</Computer>" in xml and "<Computer>srv.other.test</Computer>" in xml


def test_short_computer_names_get_phantom_labs_suffix_by_default(cfg, wire):
    connector.phantom_send_events([logon(computer="PHDC02")], destination="cribl_windows_events")
    assert "<Computer>PHDC02.phantom.lab</Computer>" in lines_of(wire[0])[0]["data"]


def test_a_missing_organization_is_a_clear_error_and_nothing_is_sent(cfg, wire):
    from runtime import organization_view as ov
    from runtime.organization_reader import OrganizationUnavailable

    def broken(pinned):
        raise OrganizationUnavailable("organization.db not found at /app/data/organization.db")

    ov.set_organization_loader(broken)
    for result in (connector.phantom_send_events([logon(computer="PHDC02")], destination="cribl_windows_events"),
                   connector.phantom_send_test_event(destination="cribl_windows_events")):
        assert not result["ok"] and "organization.db not found" in result["error"]
    assert wire == []
    # An item that is already XML needs no DNS suffix to be checked, but the tool still reads the organization: same error.
    assert not connector.phantom_send_events(["<Event/>"], destination="cribl_windows_events")["ok"] and wire == []


def test_the_connector_has_no_windows_dns_setting_of_its_own(monkeypatch):
    import types

    cfg_mod = types.ModuleType("config.config")
    monkeypatch.setitem(sys.modules, "config", types.ModuleType("config"))
    monkeypatch.setitem(sys.modules, "config.config", cfg_mod)
    cfg_mod.get_config = lambda: types.SimpleNamespace(collectorUrl=HTTP_URL, collectorKey=HTTP_KEY, vendor="Okta",
                                                      product="SSO", windowsDnsSuffix="elsewhere.test")
    assert "windows_dns" not in connector._settings() and "elsewhere.test" not in repr(connector._settings())


# -- the test event -----------------------------------------------------------------------------------------------

def test_send_test_event_posts_one_rendered_4624_by_a_fresh_actor(cfg, wire):
    first = connector.phantom_send_test_event(destination="cribl_windows_events")
    second = connector.phantom_send_test_event(destination="cribl_windows_events")
    assert first["ok"] and first["sent"] == 1 and first["num_records"] == 1 and first["event_id"] == 4624
    data = lines_of(wire[0])[0]["data"]
    root = ET.fromstring(data)
    ns = {"e": winevent.EVT_NS}
    assert root.find("e:System/e:EventID", ns).text == "4624"
    assert root.find("e:System/e:Computer", ns).text == "PHANTOM-CRIBLTEST01.phantom.lab"
    named = {d.get("Name"): d.text for d in root.find("e:EventData", ns)}
    assert named["TargetUserName"] == first["actor"] and named["LogonGuid"] == "{" + first["test_id"].upper() + "}"
    assert named["TargetDomainName"] == "PHANTOM" and named["LogonType"] == "3" and named["TargetLogonId"] == first["logon_id"]
    assert "An account was successfully logged on." in root.find("e:RenderingInfo/e:Message", ns).text
    assert first["actor"].startswith("phantom.test") and first["actor"] != second["actor"]  # fresh each call
    assert first["test_id_field"] == "LogonGuid" and first["dataset"] == "microsoft_windows_raw"
    assert first["verify_with_xql"] == ('dataset = microsoft_windows_raw | filter computer_name = '
                                        '"PHANTOM-CRIBLTEST01.phantom.lab" | sort desc _time | limit 5')
    assert first["computers"] == {"PHANTOM-CRIBLTEST01.phantom.lab": 1} and TOKEN not in repr(first)
    assert wire[0].headers["source-identifier"] == WIN.uuid and all(isinstance(line["data"], str) for r in wire for line in lines_of(r))


def test_the_test_event_follows_the_organizations_domain(cfg, wire, monkeypatch, bundled_organization):
    organization_with_domain(monkeypatch, bundled_organization, "Corp.Example", "corp")
    result = connector.phantom_send_test_event(destination="cribl_windows_events")
    named = {d.get("Name"): d.text for d in ET.fromstring(lines_of(wire[0])[0]["data"]).iter() if d.get("Name")}
    assert result["computers"] == {"CORP-CRIBLTEST01.corp.example": 1} and named["TargetDomainName"] == "CORP"
    assert named["TargetUserSid"].startswith(bundled_organization["domain"]["sid"] + "-")
    assert named["SubjectUserName"] == "CORP-CRIBLTEST01$" and named["WorkstationName"] == "CORP-CRIBLTEST01"


def test_the_test_event_comes_from_the_unmanaged_pool_and_needs_one(cfg, wire, bundled_organization):
    import copy
    import ipaddress

    from runtime import organization_view as ov

    event, _ = windows_events.build_test_event(ov.get_view(), "11111111-2222-3333-4444-555555555555",
                                              datetime(2026, 10, 5, 10, 0, 0, tzinfo=timezone.utc))
    low, high = ov.get_view().fresh_ip_range()
    assert low <= int(ipaddress.ip_address(event["event_data"]["IpAddress"])) <= high
    without = copy.deepcopy(bundled_organization)
    without["networks"] = [n for n in without["networks"] if n["kind"] != "unmanaged"]
    ov.set_organization_loader(lambda pinned: without)
    result = connector.phantom_send_test_event(destination="cribl_windows_events")
    assert not result["ok"] and "unmanaged" in result["error"] and wire == []


def test_the_windows_test_event_returns_exactly_the_declared_keys(cfg, wire):
    result = connector.phantom_send_test_event(destination="cribl_windows_events")
    cribl_keys = {"ok", "sent", "failed", "batches", "batch_status", "num_records", "http_status", "response"}
    declared = cribl_keys | {"destination", "dataset", "test_id", "sent_at", "verify_with_xql",  # every send_test_event
                             "actor", "logon_id", "event_id", "test_id_field", "events", "computers", "first_time",
                             "last_time", "sample_record_ids"}  # + the Windows ones, as connector.yaml and the docstring say
    assert set(result) == declared
    assert all(key in connector.phantom_send_test_event.__doc__ for key in
               ("actor", "logon_id", "event_id", "test_id_field", "events", "computers", "first_time", "last_time", "sample_record_ids"))
    import yaml

    spec = yaml.safe_load((HERE.parent / "connector.yaml").read_text())
    returns = next(t for t in spec["spec"]["tools"] if t["name"] == "send_test_event")["returns"]["description"]
    assert all(key in returns for key in ("actor", "logon_id", "event_id", "test_id_field", "events", "computers",
                                          "first_time", "last_time", "sample_record_ids"))


def test_the_test_event_matches_wec_senders(cfg):
    """Same shape as wec-sender's phantom_send_test_event 4624, except for the actor (fresh here)."""
    from runtime import organization_view as ov

    wec_profile = wec_connector.profiles.windows
    directory = wec_profile.directory()
    now = datetime(2026, 10, 5, 10, 0, 0, tzinfo=timezone.utc)
    test_id = "11111111-2222-3333-4444-555555555555"
    event, facts = windows_events.build_test_event(ov.get_view(), test_id, now)
    theirs = wec_profile.synthetic_test_logon(directory, "PHANTOM-CRIBLTEST01." + DNS, test_id, now)
    ours = dict(event["event_data"])
    # The actor is fresh here and fixed there; each connector's test host has its own address inside the organization's pool.
    for key in ("TargetUserName", "TargetUserSid", "TargetLogonId", "IpAddress"):
        ours.pop(key), theirs.data.pop(key)
    assert ours == theirs.data and event["event_id"] == theirs.event_id == 4624 and event["channel"] == "Security"
    assert facts["actor"] == "phantom.test111111"


def test_a_profile_is_refused_for_the_windows_test_event_and_nothing_is_sent(posted):
    result = connector.phantom_send_test_event(destination="cribl_windows_events", profile="okta")
    assert not result["ok"] and "takes no profile" in result["error"] and posted["cribl"] == []


# -- (e) secrets never leak ---------------------------------------------------------------------------------------

def test_the_token_is_in_no_result_or_error(cfg, wire):
    results = [
        connector.phantom_send_events(skill_events("guest_account_enabled"), destination="cribl_windows_events"),
        connector.phantom_send_events(["<Event/>", {"bogus": 1}], destination="cribl_windows_events"),
        connector.phantom_send_test_event(destination="cribl_windows_events"),
        connector.phantom_list_destinations(),
    ]
    assert TOKEN not in repr(results) and HTTP_KEY not in repr(results)


@pytest.fixture
def local_http_allowed(monkeypatch):
    monkeypatch.setattr(cribl, "check_url", lambda url: None)  # cribl.post insists on https; the test server is plain http


@pytest.fixture
def server():
    srv = hygiene.Server()
    yield srv
    srv.close()


def test_a_token_echoed_by_the_endpoint_is_scrubbed_on_the_windows_path_too(cfg, server, local_http_allowed):
    cfg["cribl_url"] = f"{server.url}{cribl.PATH}"
    cfg["cribl_token"] = hygiene.LONG_TOKEN
    cfg["verify_tls"] = False
    server.mode = "echo"
    result = connector.phantom_send_events(skill_events("sms_admins"), destination="cribl_windows_events")
    assert not result["ok"] and result["http_status"] == 400 and "[redacted]" in result["response"]
    assert server.requests[0]["auth"] == hygiene.LONG_TOKEN  # it really was on the wire and really was echoed
    hygiene.assert_clean(result, hygiene.LONG_TOKEN)
    server.mode = "count"
    ok = connector.phantom_send_events(skill_events("sms_admins"), destination="cribl_windows_events")
    assert ok["ok"] and server.requests[-1]["headers"]["Source-Identifier"] == WIN.uuid
    hygiene.assert_clean(ok, hygiene.LONG_TOKEN)


def test_a_token_that_cannot_be_a_header_value_is_refused_before_any_windows_request(cfg, server, local_http_allowed):
    cfg["cribl_url"] = f"{server.url}{cribl.PATH}"
    cfg["cribl_token"] = hygiene.NEWLINE_TOKEN
    result = connector.phantom_send_events([logon()], destination="cribl_windows_events")
    assert not result["ok"] and server.requests == []
    hygiene.assert_clean(result, hygiene.NEWLINE_TOKEN)


# -- (f) every other destination is unchanged ---------------------------------------------------------------------

def test_a_cribl_object_destination_still_wraps_objects(cfg, wire):
    event = {"eventSource": "guardduty.amazonaws.com", "eventName": "DeleteDetector"}
    result = connector.phantom_send_events([event], destination="cribl_aws_audit")
    assert result["ok"] and lines_of(wire[0]) == [{"data": event}]
    assert wire[0].headers["source-identifier"] == cribl.SOURCES["aws_audit"].uuid


@pytest.mark.parametrize("destination", ["cribl_aws_audit", "cribl_okta_sso", "okta_sso", None])
def test_strings_and_non_objects_are_still_refused_for_every_other_destination(posted, destination):
    for item in ("<Event/>", 5):
        result = connector.phantom_send_events([{"a": 1}, item], destination=destination)
        assert result == {"ok": False, "error": "every item in events must be a JSON object"}
    assert posted == {"cribl": [], "http": []}


def test_a_structured_windows_event_is_not_rendered_for_other_destinations(posted):
    connector.phantom_send_events([logon()], destination="okta_sso")
    connector.phantom_send_events([logon()], destination="cribl_azure_ad_audit")
    assert posted["http"][0]["events"] == [logon()] and posted["cribl"][0]["events"] == [logon()]


def test_other_cribl_test_events_are_unchanged(posted):
    result = connector.phantom_send_test_event(destination="cribl_aws_audit")
    event = posted["cribl"][0]["events"][0]
    assert result["ok"] and isinstance(event, dict) and event["eventSource"] == "sts.amazonaws.com"
    assert "actor" not in result and "computers" not in result


def test_the_windows_destination_is_still_registered_and_ready(cfg):
    dests, problems = destinations.load(connector._settings())
    assert problems == [] and dests["cribl_windows_events"].dataset == "microsoft_windows_raw"
    assert destinations.check(dests["cribl_windows_events"]) is None
    row = next(r for r in connector.phantom_list_destinations()["destinations"] if r["destination"] == "cribl_windows_events")
    assert row["mode"] == "cribl" and row["source"] == "windows_events" and row["ready"]


# -- the tool surface ---------------------------------------------------------------------------------------------

def test_the_docstrings_and_the_manifest_tell_the_agent_not_to_build_xml():
    import yaml

    spec = yaml.safe_load((HERE.parent / "connector.yaml").read_text())
    tools = {t["name"]: t for t in spec["spec"]["tools"]}
    for text in (connector.phantom_send_events.__doc__, tools["send_events"]["description"] + tools["send_events"]["args"][0]["description"]):
        assert "wec-sender.send_events" in text and re.search(r"(?i)do not (hand-)?build xml", text) and "4728" in text
    assert "windowsDnsSuffix" not in spec["configSchema"]["properties"]    # the DNS suffix is the organization's
    assert "cribl_windows_events" in tools["send_test_event"]["description"]
    assert spec["version"] == "1.0.0" and "image" not in spec  # a bundle connector pins no image
