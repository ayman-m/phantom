"""The four tools end to end against the fake applet, the secret-handling guarantees, and the manifest."""
from __future__ import annotations

import ast
import importlib.util
import inspect
import ipaddress
import json
import logging
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from conftest import MANAGER_PATH, PFX_PASSWORD, ROOT
from runtime import organization_view as ov
from src import connector, wsman

S, W = wsman.SOAP, wsman.WSMAN


@pytest.fixture()
def cfg(applet, pki, monkeypatch):
    """Instance settings pointing at the fake applet; tests may edit the dict."""
    settings = {"url": f"Server=HTTPS://127.0.0.1:{applet.port}{MANAGER_PATH},Refresh=600,IssuerCA={pki.ca_thumbprint}",
                "sender": "phantom-wec-sender.phantom.lab", "timeout": 5.0, "organization": "",
                "pfx": pki.pfx_b64_wrapped(), "pfx_password": PFX_PASSWORD}
    monkeypatch.setattr(connector, "_settings", lambda: settings)
    return settings


def delivered_events(applet):
    out = []
    for d in applet.deliveries:
        root = ET.fromstring(wsman.decode_message(d["body"]))
        out += [ET.fromstring(e.text) for e in root.findall(f"{{{S}}}Body/{{{W}}}Events/{{{W}}}Event")]
    return out


EVT = "{http://schemas.microsoft.com/win/2004/08/events/event}"


def secrets_of(pki):
    return [pki.pfx_b64, pki.pfx_b64[:60], PFX_PASSWORD, "BEGIN PRIVATE KEY", "BEGIN ENCRYPTED PRIVATE KEY"]


# ── list_subscriptions ──────────────────────────────────────────────────────────────────────────────────────────
def test_list_subscriptions(cfg, applet):
    r = connector.phantom_list_subscriptions()
    assert r["ok"] is True and r["manager"] == f"127.0.0.1:{applet.port}"
    names = {s["name"]: s for s in r["subscriptions"]}
    assert set(names) == {"ForwardedEvents", "Authentication Event Logs"}
    auth = names["Authentication Event Logs"]
    assert auth["delivery_path"] == "/wsman/subscriptions/aaaaaaaa-bbbb-4ccc-8ddd-000000000001/1"
    assert auth["max_envelope_size"] == 524288 and auth["heartbeat"] == "PT3600.000S" and auth["channels"] == ["Security"]
    q = auth["queries"][0]
    assert q["path"] == "Security" and q["xpath"].endswith("...") and len(q["xpath"]) <= connector.XPATH_PREVIEW + 3
    assert "identifier" not in json.dumps(r).lower()


# ── send_test_event ─────────────────────────────────────────────────────────────────────────────────────────────
def test_send_test_event(cfg, applet, bundled_organization):
    view = ov.get_view()
    expected = f"{view.netbios}-WECTEST01.{view.dns}"
    r = connector.phantom_send_test_event()
    assert r["ok"] and r["sent"] == 1 and r["computer"] == expected and r["event_id"] == 4624
    assert r["verify_with_xql"] == ('dataset = microsoft_windows_raw | filter _collector_type = "WEC" and '
                                    f'computer_name = "{expected}"')
    assert r["subscriptions"] == {"Authentication Event Logs": 1}
    (event,) = delivered_events(applet)
    guid = [d.text for d in event.findall(f"{EVT}EventData/{EVT}Data") if d.get("Name") == "LogonGuid"][0]
    assert guid == "{" + r["test_id"].upper() + "}" and r["test_id_field"] == "LogonGuid"
    assert event.find(f"{EVT}System/{EVT}Computer").text == r["computer"]
    assert event.find(f"{EVT}System/{EVT}EventRecordID").text == str(r["record_id"])
    ip = [d.text for d in event.findall(f"{EVT}EventData/{EVT}Data") if d.get("Name") == "IpAddress"][0]
    low, high = view.fresh_ip_range()
    assert low <= int(ipaddress.ip_address(ip)) <= high, "the test logon comes from the organization's unmanaged pool"
    assert all(ip != h["ip"] for h in view.hosts)


def test_send_test_event_custom_computer_and_other_ids(cfg, applet):
    r = connector.phantom_send_test_event(computer="ws-test9", event_id=4625)
    assert r["ok"] and r["computer"] == f"ws-test9.{ov.get_view().dns}"
    (event,) = delivered_events(applet)
    assert event.find(f"{EVT}System/{EVT}Keywords").text == "0x8010000000000000"
    names = [d.get("Name") for d in event.findall(f"{EVT}EventData/{EVT}Data")]
    assert "SubjectUserName" in names and "TargetUserName" in names
    bad = connector.phantom_send_test_event(event_id=4688)
    assert bad["ok"] is False and "catalogue" in bad["error"]


# ── generate_events ─────────────────────────────────────────────────────────────────────────────────────────────
def test_generate_events_sends_and_summarises(cfg, applet):
    r = connector.phantom_generate_events("windows", "baseline_logons", count=75, spread_seconds=300, start_offset_minutes=30)
    assert r["ok"] and r["events"] == 75 and r["sent"] == 75 and r["profile"] == "windows"
    assert sum(r["computers"].values()) == 75 and all(c.endswith("." + ov.get_view().dns) for c in r["computers"])
    assert len(r["sample_record_ids"]) == 5 and r["first_time"] <= r["last_time"]
    events = delivered_events(applet)
    assert len(events) == 75
    per_computer = {}
    for e in events:
        c = e.find(f"{EVT}System/{EVT}Computer").text
        per_computer[c] = per_computer.get(c, 0) + 1
    assert per_computer == r["computers"]
    assert r["subscriptions"] == {"Authentication Event Logs": 75}
    assert r["last_time"] < __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()[:19], "back-dated"


def test_generate_events_dry_run_sends_nothing_and_needs_no_secrets(cfg, applet):
    cfg.update(pfx="", pfx_password="", url="")
    r = connector.phantom_generate_events(count=10, dry_run=True)
    assert r["ok"] and r["dry_run"] and r["sent"] == 0 and len(r["preview"]) == 3
    assert all("<Event xmlns=" in p["xml"] and p["record_id"] for p in r["preview"])
    assert applet.deliveries == [] and applet.enumerations == 0


@pytest.mark.parametrize("kwargs,fragment", [
    (dict(count=0), "count must be"), (dict(count=5001), "count must be"), (dict(count="7"), "count must be"),
    (dict(profile="okta"), "unknown profile"), (dict(scenario="failed_logons"), "unknown scenario"),
])
def test_generate_events_validation(cfg, applet, kwargs, fragment):
    r = connector.phantom_generate_events(**kwargs)
    assert r["ok"] is False and fragment in r["error"]
    assert applet.deliveries == []


# ── send_events ─────────────────────────────────────────────────────────────────────────────────────────────────
def test_send_events_structured(cfg, applet):
    view = ov.get_view()
    person = view.people[0]
    ws = view.host(person["workstation"])
    adfs = f"ADFS01.{view.dns}"
    r = connector.phantom_send_events([
        {"event_id": 4625, "computer": ws["name"], "outcome": "failure", "time": "2026-10-03T09:15:00.1234567Z",
         "event_data": {"TargetUserName": person["login"], "IpAddress": ws["ip"]}},
        {"event_id": 1200, "computer": adfs, "channel": "Security", "provider": "AD FS Auditing",
         "time": 1790000000, "event_data": ["a", "b", "c"], "message": "The Federation Service issued a valid token.",
         "rendering": {"task": "None"}},
    ])
    assert r["ok"] and r["sent"] == 2 and set(r["computers"]) == {f"{ws['name']}.{view.dns}", adfs}, \
        "a short computer name gets the active organization's DNS suffix"
    by_id = {e.find(f"{EVT}System/{EVT}EventID").text: e for e in delivered_events(applet)}
    fail = by_id["4625"]
    assert fail.find(f"{EVT}System/{EVT}TimeCreated").get("SystemTime") == "2026-10-03T09:15:00.1234560Z"
    assert fail.find(f"{EVT}RenderingInfo/{EVT}Keywords/{EVT}Keyword").text == "Audit Failure"
    adfs = by_id["1200"]
    assert [d.text for d in adfs.findall(f"{EVT}EventData/{EVT}Data")] == ["a", "b", "c"]
    assert all(d.get("Name") is None for d in adfs.findall(f"{EVT}EventData/{EVT}Data"))
    assert adfs.find(f"{EVT}System/{EVT}Provider").get("Name") == "AD FS Auditing"


@pytest.mark.parametrize("events,fragment", [
    ([], "non-empty"), ("x", "non-empty"), ([1], "must be an object"),
    ([{"computer": "a"}], "event_id is required"), ([{"event_id": 4624}], "computer is required"),
    ([{"event_id": 4624, "computer": "a", "evnt_data": {}}], "unknown field"),
    ([{"event_id": 4624, "computer": "a", "time": "yesterday"}], "time must be"),
    ([{"event_id": 4624, "computer": "a", "event_data": "x"}], "event_data must be"),
    ([{"event_id": 4624, "computer": "a", "record_id": "x"}], "whole numbers"),
    ([{"event_id": 4624, "computer": "a"}, {"event_id": 777, "computer": "a"}], "not in the catalogue"),
])
def test_send_events_validation_sends_nothing(cfg, applet, events, fragment):
    r = connector.phantom_send_events(events)
    assert r["ok"] is False and fragment in r["error"]
    assert applet.deliveries == []


def test_send_events_limit(cfg):
    assert "at most 5000" in connector.phantom_send_events([{"event_id": 4624, "computer": "a"}] * 5001)["error"]


# ── failure handling and secrets ────────────────────────────────────────────────────────────────────────────────
def test_missing_or_wrong_secrets_give_clear_results_not_stack_traces(cfg, pki):
    for change, fragment in [({"pfx": ""}, "clientPfx"), ({"pfx_password": "  "}, "clientPfxPassword"), ({"url": ""}, "subscriptionManagerUrl"),
                             ({"pfx_password": "wrong"}, "clientPfxPassword"), ({"pfx": "!!notbase64!!"}, "base64"),
                             ({"url": "http://plain"}, "https")]:
        saved = dict(cfg)
        cfg.update(change)
        for call in (connector.phantom_list_subscriptions, connector.phantom_send_test_event,
                     lambda: connector.phantom_generate_events(count=3), lambda: connector.phantom_send_events([{"event_id": 4624, "computer": "a"}])):
            r = call()
            assert r["ok"] is False and fragment in r["error"], (change, r)
            assert "Traceback" not in json.dumps(r)
        cfg.clear()
        cfg.update(saved)


def test_delivery_failure_reports_partial_progress(cfg, applet):
    applet.statuses = [200, 500, 500]
    r = connector.phantom_send_events([{"event_id": 4624, "computer": "a1"}, {"event_id": 4624, "computer": "b1"}])
    assert r["ok"] is False and "500" in r["error"] and r["sent"] == 1


def test_unexpected_errors_name_only_the_type(cfg, monkeypatch, caplog):
    def boom(self):
        raise RuntimeError("super-secret-detail")
    monkeypatch.setattr(wsman.WecClient, "enumerate", boom)
    with caplog.at_level(logging.DEBUG):
        r = connector.phantom_list_subscriptions()
    assert r["ok"] is False and "RuntimeError" in r["error"]
    assert "super-secret-detail" not in json.dumps(r) + caplog.text


def test_no_secret_appears_in_any_result_or_log(cfg, applet, pki, caplog):
    results = []
    with caplog.at_level(logging.DEBUG):
        results.append(connector.phantom_list_subscriptions())
        results.append(connector.phantom_send_test_event())
        results.append(connector.phantom_generate_events(count=20))
        results.append(connector.phantom_generate_events(count=5, dry_run=True))
        results.append(connector.phantom_send_events([{"event_id": 4624, "computer": "a"}]))
        applet.statuses = [500, 500]
        results.append(connector.phantom_send_events([{"event_id": 4624, "computer": "a"}]))
        cfg["pfx_password"] = "wrong"
        results.append(connector.phantom_list_subscriptions())
        cfg["pfx_password"] = PFX_PASSWORD
        cfg["pfx"] = pki.pfx_b64[:-8]
        results.append(connector.phantom_list_subscriptions())
    blob = json.dumps(results, default=str) + caplog.text
    for secret in secrets_of(pki) + [pki.pfx.hex(), repr(pki.pfx)]:
        assert secret not in blob
    # raw key bytes (DER) of the client key must not be anywhere either
    from cryptography.hazmat.primitives import serialization
    der = pki.client_key.private_bytes(serialization.Encoding.DER, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    assert der.hex() not in blob


def test_tool_signatures_survive_the_guard():
    sig = inspect.signature(connector.phantom_generate_events)
    assert list(sig.parameters) == ["profile", "scenario", "count", "spread_seconds", "start_offset_minutes", "dry_run"]
    assert connector.phantom_generate_events.__name__ == "phantom_generate_events"
    assert "baseline_logons" in connector.phantom_generate_events.__doc__


# ── manifest ────────────────────────────────────────────────────────────────────────────────────────────────────
def manifest():
    yaml = pytest.importorskip("yaml")
    return yaml.safe_load((ROOT / "connector.yaml").read_text())


def test_connector_yaml_validates_against_the_schema():
    jsonschema = pytest.importorskip("jsonschema")
    schema_path = ROOT.parents[1] / "connectors" / "connector.schema.json"
    jsonschema.Draft202012Validator(json.loads(schema_path.read_text())).validate(manifest())


def test_connector_yaml_matches_the_code():
    m = manifest()
    # a bundle connector declares no `image`: the updater derives it from the release digest pin
    assert m["id"] == "wec-sender" and m["version"] == "1.0.0" and "image" not in m
    tools = {t["name"]: t for t in m["spec"]["tools"]}
    fns = {n[len("phantom_"):]: getattr(connector, n) for n in connector.__all__}
    assert set(tools) == set(fns) == {"list_subscriptions", "send_test_event", "generate_events", "send_events"}
    for name, tool in tools.items():
        declared = [a["name"] for a in tool["args"]]
        assert declared == list(inspect.signature(fns[name]).parameters), name
        assert tool["returns"]["description"]
    assert [s["name"] for s in m["secretSlots"]] == ["clientPfx", "clientPfxPassword"] and all(s["required"] for s in m["secretSlots"])
    props = m["configSchema"]["properties"]
    assert set(props) == {"subscriptionManagerUrl", "senderComputerName", "timeoutSeconds", "organization"}
    assert "verifyTls" not in props and m["configSchema"]["required"] == ["subscriptionManagerUrl"]
    assert props["timeoutSeconds"]["default"] == 30
    assert props["organization"]["type"] == "string" and props["organization"]["default"] == ""
    assert "active organization" in props["organization"]["description"], "empty follows the active organization"
    header = (ROOT / "connector.yaml").read_text().split("id:")[0]
    assert "syslog/CEF" in header


# ── provenance and layering ─────────────────────────────────────────────────────────────────────────────────────
def imports_of(path: Path) -> set[str]:
    out = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            out |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            out.add("." * node.level + (node.module or "").split(".")[0])
    return out


def test_transport_and_renderer_have_no_runtime_or_package_imports():
    import sys
    stdlib = set(sys.stdlib_module_names)
    assert imports_of(ROOT / "src" / "wsman.py") <= stdlib | {"cryptography"}
    assert imports_of(ROOT / "src" / "winevent.py") <= stdlib


def test_transport_loads_standalone_by_file_path():
    spec = importlib.util.spec_from_file_location("wsman_standalone", ROOT / "src" / "wsman.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.parse_subscription_manager_url("https://b.example/wsman/SubscriptionManager/WEC").port == 5986


def test_no_unverified_tls_anywhere():
    for path in (ROOT / "src").rglob("*.py"):
        text = path.read_text()
        assert "verify=False" not in text and "_create_unverified_context" not in text and "CERT_NONE" not in text, path


# ── spread_seconds / start_offset_minutes validation ────────────────────────────────────────────────────────────
@pytest.mark.parametrize("kwargs,fragment", [
    (dict(spread_seconds="abc"), "spread_seconds must be a whole number from 1 to 604800"),
    (dict(spread_seconds=0), "spread_seconds must be"), (dict(spread_seconds=-5), "spread_seconds must be"),
    (dict(spread_seconds=604801), "spread_seconds must be"), (dict(spread_seconds=10 ** 30), "spread_seconds must be"),
    (dict(spread_seconds=1.5), "spread_seconds must be"), (dict(spread_seconds=True), "spread_seconds must be"),
    (dict(spread_seconds=None), "spread_seconds must be"), (dict(spread_seconds=float("inf")), "spread_seconds must be"),
    (dict(start_offset_minutes="x"), "start_offset_minutes must be a whole number from 0 to 1051200"),
    (dict(start_offset_minutes=-1), "start_offset_minutes must be"), (dict(start_offset_minutes=10 ** 30), "start_offset_minutes must be"),
    (dict(start_offset_minutes=1051201), "start_offset_minutes must be"), (dict(start_offset_minutes=2.5), "start_offset_minutes must be"),
])
def test_window_arguments_are_validated_with_clear_messages(cfg, applet, kwargs, fragment):
    for dry in (True, False):
        r = connector.phantom_generate_events(count=3, dry_run=dry, **kwargs)
        assert r["ok"] is False and fragment in r["error"], r
        assert "invalid literal" not in r["error"] and "Overflow" not in r["error"] and "unexpected" not in r["error"]
    assert applet.deliveries == []


def test_window_arguments_at_their_limits_work(cfg):
    assert connector.phantom_generate_events(count=3, spread_seconds=604800, start_offset_minutes=1051200, dry_run=True)["ok"]
    assert connector.phantom_generate_events(count=3, spread_seconds=1, start_offset_minutes=0, dry_run=True)["ok"]


# ── send_test_event(4634) ───────────────────────────────────────────────────────────────────────────────────────
def test_a_test_logoff_is_preceded_by_its_logon_with_the_same_logon_id(cfg, applet):
    r = connector.phantom_send_test_event(event_id=4634)
    assert r["ok"] and r["sent"] == 2 and r["event_id"] == 4634 and r["test_id_field"] == "LogonGuid"
    assert [e["event_id"] for e in r["events"]] == [4624, 4634]
    assert r["events"][0]["time"] < r["events"][1]["time"] and r["record_id"] == r["events"][1]["record_id"]
    events = delivered_events(applet)
    assert len(events) == 2 and len(applet.deliveries) == 1, "one envelope, same computer"
    by_id = {e.find(f"{EVT}System/{EVT}EventID").text: e for e in events}
    def field(e, name):
        return [d.text for d in e.findall(f"{EVT}EventData/{EVT}Data") if d.get("Name") == name][0]
    logon_id = field(by_id["4624"], "TargetLogonId")
    assert logon_id not in ("0x0", "-") and field(by_id["4634"], "TargetLogonId") == logon_id == r["logon_id"]
    assert field(by_id["4634"], "TargetUserName") == field(by_id["4624"], "TargetUserName")
    assert field(by_id["4624"], "LogonGuid") == "{" + r["test_id"].upper() + "}"


def test_the_other_test_events_are_still_single(cfg, applet):
    for event_id in (4624, 4625, 4672):
        applet.deliveries.clear()
        r = connector.phantom_send_test_event(event_id=event_id)
        assert r["ok"] and r["sent"] == 1 and [e["event_id"] for e in r["events"]] == [event_id]
        assert len(delivered_events(applet)) == 1


@pytest.mark.parametrize("bad", ["4624", None, 4.5, True, 9999])
def test_bad_test_event_ids_are_clean_errors(cfg, applet, bad):
    r = connector.phantom_send_test_event(event_id=bad)
    assert r["ok"] is False and "catalogue" in r["error"] and applet.deliveries == []


# ── caller strings that reach the XML ───────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("event,fragment", [
    ({"event_id": 4624, "computer": "ph\x01host"}, "control or invalid"),
    ({"event_id": 4624, "computer": "ph\ud800host"}, "control or invalid"),
    ({"event_id": 4624, "computer": "a", "event_data": {"Na\x00me": "x"}}, "control or invalid"),
    ({"event_id": 4624, "computer": "a", "event_data": {"Na\udc00me": "x"}}, "control or invalid"),
    ({"event_id": 4624, "computer": "a", "channel": 5}, "channel must be a string"),
    ({"event_id": 4624, "computer": "a", "provider": ["x"]}, "provider must be a string"),
    ({"event_id": 4624, "computer": "a", "time": 1e30}, "time must be"),
    ({"event_id": float("inf"), "computer": "a"}, "event_id is required"),
    ({"event_id": 4624, "computer": "a", "process_id": float("inf")}, "whole numbers"),
])
def test_send_events_rejects_unsendable_names_with_a_clean_error(cfg, applet, event, fragment):
    r = connector.phantom_send_events([{"event_id": 4624, "computer": "ok1"}, event])
    assert r["ok"] is False and fragment in r["error"], r
    assert "unexpected" not in r["error"] and "Traceback" not in json.dumps(r)
    assert applet.deliveries == [], "nothing is sent when any event is bad"


def test_send_events_cleans_values_and_coerces_activity_id(cfg, applet):
    r = connector.phantom_send_events([{"event_id": 4624, "computer": "a1", "activity_id": 12345,
                                        "message": "lone \ud800 surrogate and \x00 nul",
                                        "event_data": {"TargetUserName": "bo\udfffb\x07"}}])
    assert r["ok"] and r["sent"] == 1
    (event,) = delivered_events(applet)
    assert event.find(f"{EVT}System/{EVT}Correlation").get("ActivityID") == "12345"
    assert event.find(f"{EVT}RenderingInfo/{EVT}Message").text == "lone  surrogate and  nul"
    assert [d.text for d in event.findall(f"{EVT}EventData/{EVT}Data") if d.get("Name") == "TargetUserName"] == ["bob"]


def test_an_oversized_event_for_a_later_computer_sends_nothing(cfg, applet):
    big = {"event_id": 4624, "computer": "b1", "event_data": {"TargetUserName": chr(0x1F600) * 140_000}}
    r = connector.phantom_send_events([{"event_id": 4624, "computer": "a1"}, big])
    assert r["ok"] is False and "does not fit" in r["error"] and r["sent"] == 0
    assert applet.deliveries == []


# ── `sent` means accepted ───────────────────────────────────────────────────────────────────────────────────────
def test_docs_say_sent_means_accepted_not_landed():
    for text in (connector.phantom_generate_events.__doc__, connector.phantom_send_events.__doc__,
                 connector.phantom_send_test_event.__doc__, (ROOT / "README.md").read_text(), (ROOT / "connector.yaml").read_text()):
        assert "HTTP 200" in text and ("ACCEPTED" in text or "accepted" in text)
    m = manifest()
    for tool in m["spec"]["tools"]:
        if tool["name"] != "list_subscriptions":
            assert "HTTP 200" in tool["description"] + tool["returns"]["description"], tool["name"]
            assert "landing" in tool["description"] or "landed" in tool["description"] or "landing" in tool["returns"]["description"] or "not proof" in tool["returns"]["description"]
