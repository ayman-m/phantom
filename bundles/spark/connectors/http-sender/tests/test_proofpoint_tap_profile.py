"""proofpoint_tap event profile: unit tests. No network, no files.

Run from the connector directory:  python3 -m pytest -x

The shape assertions mirror what the ProofpointTAP `_1_3` modeling rule reads: which columns
are arrays versus scalars, which JSON paths inside `messageParts` / `threatsInfoMap`, and
the `_log_type` that builds `xdm.event.type`.
"""
from __future__ import annotations

import ipaddress
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runtime.organization_view import get_view  # noqa: E402
from src import profiles  # noqa: E402
from src.profiles import _org, ippools, proofpoint_tap as tap  # noqa: E402

NOW = datetime(2026, 9, 30, 12, 0, 0, tzinfo=timezone.utc)
TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
MESSAGE_TYPES = {"message-delivered", "message-blocked"}
CLICK_TYPES = {"click-blocked", "click-permitted"}
ATTACK_SCENARIOS = ("phishing_url", "malware_attachment", "credential_phishing", "bec_impostor", "click_chain")


def build(scenario, count, **kw):
    kw.setdefault("seed", 7)
    return tap.build_events(scenario, count, view=get_view(), now=NOW, **kw)


def domain():
    return get_view().email_domain


def person(login):
    return get_view().person(login)


def parse(ts):
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)


def in_range(ip, pool_range):
    return ipaddress.ip_address(ip) in ipaddress.ip_network(pool_range.cidr)


def sender_ips(scenario, count=60, **kw):
    return {e["senderIP"] for e in build(scenario, count, **kw)}


def is_str_list(value):
    return isinstance(value, list) and all(isinstance(v, str) for v in value)


# ── interface ───────────────────────────────────────────────────────────

def test_profile_constants():
    assert tap.NAME == "proofpoint_tap" and tap.EXPECTED_DATASET == "proofpoint_tap"
    assert tap.EXPECTED_DATASETS == ("proofpoint_tap",)
    assert tap.TIME_FIELD == "messageTime" and tap.TEST_ID_FIELD == "GUID"
    assert tap.SCENARIOS == ("benign_mail", "phishing_url", "malware_attachment",
                             "credential_phishing", "bec_impostor", "click_chain")
    assert tap.DESCRIPTION


# ── per-event-type shape (what the modeling rule reads) ─────────────────

def check_message(ev):
    assert ev["_log_type"] in MESSAGE_TYPES
    assert TIMESTAMP.match(ev["messageTime"])
    for key in ("GUID", "messageID", "sender", "senderIP", "subject"):
        assert isinstance(ev[key], str) and ev[key], key
    # array columns in the rule's schema
    for key in ("recipient", "ccAddresses", "fromAddress"):
        assert is_str_list(ev[key]), key
    assert len(ev["recipient"]) >= 1 and ev["fromAddress"] == [ev["sender"]]
    # attachment mapping: filename / md5 / sha256 read from every messageParts element
    assert isinstance(ev["messageParts"], list) and ev["messageParts"]
    for part in ev["messageParts"]:
        assert isinstance(part["filename"], str) and part["filename"]
        assert re.fullmatch(r"[0-9a-f]{32}", part["md5"])
        assert re.fullmatch(r"[0-9a-f]{64}", part["sha256"])
    # threat mapping: threatType / threatID read from every threatsInfoMap element
    assert isinstance(ev["threatsInfoMap"], list)
    for entry in ev["threatsInfoMap"]:
        assert entry["threatType"] in ("URL", "ATTACHMENT")
        assert re.fullmatch(r"[0-9a-f]{64}", entry["threatID"])
        assert entry["classification"] and entry["threatStatus"] == "active"
    for score in ("phishScore", "malwareScore", "spamScore", "impostorScore"):
        assert isinstance(ev[score], int) and 0 <= ev[score] <= 100


def check_click(ev):
    assert ev["_log_type"] in CLICK_TYPES
    assert TIMESTAMP.match(ev["clickTime"]) and ev["messageTime"] == ev["clickTime"]
    assert isinstance(ev["recipient"], str) and "@" in ev["recipient"]  # a string, not an array
    assert is_str_list(ev["fromAddress"]) and "messageParts" not in ev and "threatsInfoMap" not in ev
    for key in ("GUID", "messageID", "clickIP", "userAgent", "url", "sender", "senderIP",
                "threatID", "threatURL", "classification", "id"):
        assert isinstance(ev[key], str) and ev[key], key
    assert any(in_range(ev["clickIP"], r) for r in ippools.HOME)  # a click comes from the recipient's home address


@pytest.mark.parametrize("scenario", tap.SCENARIOS)
def test_every_scenario_returns_count_valid_events(scenario):
    for count in (1, 2, 5, 17):
        events = build(scenario, count)
        assert len(events) == count
        for ev in events:
            (check_message if ev["_log_type"] in MESSAGE_TYPES else check_click)(ev)
            assert json.loads(json.dumps(ev)) == ev  # plain JSON all the way down


def test_benign_mail_is_delivered_clean_mail():
    events = build("benign_mail", 12)
    assert {e["_log_type"] for e in events} == {"message-delivered"}
    for ev in events:
        assert ev["threatsInfoMap"] == [] and "classification" not in ev and "url" not in ev
        assert ev["quarantineFolder"] is None and ev["phishScore"] <= 15
    emails = {p["email"] for p in _org.logon_people(get_view())}
    assert {e["recipient"][0] for e in events} <= emails and len({e["recipient"][0] for e in events}) == 12
    assert {a for e in events for a in e["ccAddresses"]} <= emails
    assert any(e["ccAddresses"] for e in events) and any(len(e["messageParts"]) > 1 for e in events)


@pytest.mark.parametrize("scenario,classification,threat_type", [
    ("phishing_url", "PHISHING", "URL"), ("credential_phishing", "PHISHING", "URL"),
    ("malware_attachment", "MALWARE", "ATTACHMENT")])
def test_blocked_threat_scenarios(scenario, classification, threat_type):
    events = build(scenario, 9)
    assert {e["_log_type"] for e in events} == {"message-blocked"}
    for ev in events:
        (entry,) = ev["threatsInfoMap"]
        assert entry["classification"] == ev["classification"] == classification
        assert entry["threatType"] == threat_type and entry["threatID"] == ev["threatID"]
        assert ev["quarantineFolder"] in ("Phish", "Malware") and ev["quarantineRule"]
        assert entry["threatTime"] == ev["messageTime"]
        if threat_type == "URL":
            assert ev["url"] == entry["threat"] and ev["url"].startswith("https://")
        else:
            attachment = ev["messageParts"][-1]
            assert attachment["sandboxStatus"] == "MALICIOUS" and ev["malwareScore"] >= 90
            assert ev["threatID"] == attachment["sha256"] and "url" not in ev


def test_bec_impostor_is_delivered_with_lookalike_sender_and_reply_to():
    events = build("bec_impostor", 6)
    for ev in events:
        assert ev["_log_type"] == "message-delivered" and ev["impostorScore"] >= 75
        assert ev["classification"] == "IMPOSTOR" and ev["threatsInfoMap"] == []
        assert ev["sender"].endswith(f"@{domain().split('.')[0]}-secure.example")
        assert ev["replyToAddress"] and ev["replyToAddress"][0] != ev["sender"]


def test_click_chain_clicks_follow_and_reference_their_message():
    events = build("click_chain", 12)
    messages = [e for e in events if e["_log_type"] in MESSAGE_TYPES]
    clicks = [e for e in events if e["_log_type"] in CLICK_TYPES]
    assert len(messages) == 4 and len(clicks) == 8
    assert events[:4] == messages  # messages first, then clicks
    assert {m["_log_type"] for m in messages} == {"message-delivered"}
    assert {c["_log_type"] for c in clicks} == CLICK_TYPES
    by_guid = {m["GUID"]: m for m in messages}
    for click in clicks:
        msg = by_guid[click["GUID"]]
        (entry,) = msg["threatsInfoMap"]
        assert click["recipient"] == msg["recipient"][0] and click["messageID"] == msg["messageID"]
        assert click["url"] == msg["url"] and click["threatID"] == entry["threatID"]
        assert click["campaignId"] == entry["campaignID"] and click["sender"] == msg["sender"]
        assert parse(click["clickTime"]) > parse(msg["messageTime"])
    assert {c["GUID"] for c in clicks} == set(by_guid)  # every message got a click
    # one user, one home address: clicks on the same message come from one address, the recipient's own
    for guid in by_guid:
        assert len({c["clickIP"] for c in clicks if c["GUID"] == guid}) == 1
    by_email = {p["email"]: p for p in get_view().people}
    for click in clicks:
        assert click["clickIP"] == by_email[click["recipient"]]["home_ip"]
        assert ippools.range_of(click["clickIP"]).country == "Saudi Arabia"


def test_a_named_recipient_clicks_from_one_stable_home_address_in_every_run():
    first = build("click_chain", 9, target_user="kalotaibi", seed=1)
    second = build("click_chain", 12, target_user="khalid.alotaibi", seed=2)
    ips = {e["clickIP"] for e in first + second if "clickIP" in e}
    assert ips == {person("kalotaibi")["home_ip"]}


def test_the_same_user_clicks_from_the_same_address_as_the_other_profiles():
    ev = build("click_chain", 6, target_user="noura.alharbi")[-1]
    assert ev["clickIP"] == person("nalharbi")["home_ip"]


def test_an_unknown_recipient_is_refused_with_the_valid_emails():
    with pytest.raises(ValueError, match="nobody in the organization") as err:
        build("click_chain", 6, target_user="someone.new")
    assert person("nalharbi")["email"] in str(err.value)


def test_click_chain_of_one_is_just_the_message():
    (ev,) = build("click_chain", 1)
    assert ev["_log_type"] == "message-delivered"


# ── ids, time, determinism ──────────────────────────────────────────────

@pytest.mark.parametrize("scenario", tap.SCENARIOS)
def test_message_ids_are_unique_and_clicks_have_unique_ids(scenario):
    events = build(scenario, 40)
    messages = [e for e in events if e["_log_type"] in MESSAGE_TYPES]
    assert len({m["GUID"] for m in messages}) == len(messages)
    assert len({m["messageID"] for m in messages}) == len(messages)
    clicks = [e for e in events if e["_log_type"] in CLICK_TYPES]
    assert len({c["id"] for c in clicks}) == len(clicks)


@pytest.mark.parametrize("scenario", tap.SCENARIOS)
def test_time_field_is_present_utc_ascending_and_never_after_now(scenario):
    events = build(scenario, 10, spread_seconds=300, start_offset_minutes=5)
    times = [parse(e[tap.TIME_FIELD]) for e in events]  # raises on a bad format
    assert times == sorted(times)
    assert events[-1][tap.TIME_FIELD] == "2026-09-30T11:55:00.000Z"  # 5 minutes back-dated, never after now


@pytest.mark.parametrize("scenario", tap.SCENARIOS)
def test_same_seed_same_events_other_seed_different(scenario):
    assert build(scenario, 8, seed=3) == build(scenario, 8, seed=3)
    assert build(scenario, 8, seed=3) != build(scenario, 8, seed=4)


def test_target_user_and_source_ip_are_honoured_by_attack_scenarios():
    for scenario in ATTACK_SCENARIOS:
        events = build(scenario, 6, target_user="Acme\\Noura.Alharbi", source_ip="203.0.113.99")
        recipients = {e["recipient"][0] if isinstance(e["recipient"], list) else e["recipient"] for e in events}
        assert recipients == {person("nalharbi")["email"]}
        assert {e["senderIP"] for e in events} == {"203.0.113.99"}


# ── where mail comes from ───────────────────────────────────────────────

BENIGN_NETS = ippools.HOME + ippools.ABROAD[:6]


def sender_ip_map(events):
    by_sender = {}
    for ev in events:
        by_sender.setdefault(ev["sender"], set()).add(ev["senderIP"])
    return by_sender


def test_each_benign_sender_has_one_stable_address_in_the_benign_pool():
    by_sender = sender_ip_map(build("benign_mail", 60))
    assert len(by_sender) == len(tap._BENIGN_SENDERS) and all(len(ips) == 1 for ips in by_sender.values())
    assert sender_ip_map(build("benign_mail", 60, seed=99)) == by_sender  # the same on another run
    addresses = [next(iter(ips)) for ips in by_sender.values()]
    assert len(set(addresses)) == len(addresses)
    assert all(ippools.range_of(ip) in BENIGN_NETS for ip in addresses)


@pytest.mark.parametrize("scenario", ATTACK_SCENARIOS)
def test_attack_senders_default_to_the_attack_pool_disjoint_from_the_benign_one(scenario):
    ips = sender_ips(scenario)
    assert len(ips) > 1  # several mail servers across a run, not one
    for ip in ips:
        assert any(in_range(ip, r) for r in ippools.ABROAD[6:]), ip
        assert not any(in_range(ip, r) for r in BENIGN_NETS), ip
    assert ips.isdisjoint(sender_ips("benign_mail"))


def test_attack_sender_pool_and_benign_pool_share_no_range():
    assert not {r.cidr for r in tap._BENIGN_POOL} & {r.cidr for r in tap._ATTACK_POOL}
    assert len(tap._ATTACK_POOL) == 12 and len(tap._BENIGN_POOL) == 30


def test_a_source_ip_inside_a_pool_or_outside_every_pool_is_used_as_given():
    inside = ippools.host_in(ippools.ABROAD[10], 9)
    for ip in (inside, "203.0.113.99"):
        assert {e["senderIP"] for e in build("phishing_url", 5, source_ip=ip)} == {ip}


# ── everything is fictitious ────────────────────────────────────────────

@pytest.mark.parametrize("scenario", tap.SCENARIOS)
def test_only_fictitious_domains_urls_and_known_pool_addresses(scenario):
    for ev in build(scenario, 30):
        blob = json.dumps(ev)
        for host in re.findall(r"@([A-Za-z0-9.-]+)", blob):
            assert host == domain() or host.endswith(".example"), host  # the organization's own domain, else reserved
        for host in re.findall(r"https?://([^/\s\"#]+)", blob):
            assert host.endswith((".example", ".invalid")), host
        for key in ("senderIP", "clickIP"):
            if key in ev:
                assert ippools.range_of(ev[key]) is not None, ev[key]


# ── registry, sample, bad input ─────────────────────────────────────────

def test_sample_event_is_one_valid_identifiable_message():
    ev = tap.sample_event(view=get_view(), now=NOW)
    check_message(ev)
    assert ev["_log_type"] == "message-delivered" and ev["messageTime"] == "2026-09-30T12:00:00.000Z"
    assert ev["recipient"] == [f"phantom.test@{domain()}"] and ev[tap.TEST_ID_FIELD]
    assert ippools.range_of(ev["senderIP"]) in BENIGN_NETS and ev["sender"].endswith(".example")


def test_unknown_scenario_and_zero_count_are_refused():
    with pytest.raises(ValueError, match="benign_mail"):
        build("nope", 3)
    with pytest.raises(ValueError, match="at least 1"):
        build("benign_mail", 0)


def test_module_satisfies_the_profile_interface():
    for attr in ("NAME", "DESCRIPTION", "EXPECTED_DATASET", "SCENARIOS", "TEST_ID_FIELD",
                 "TIME_FIELD", "build_events", "sample_event"):
        assert hasattr(tap, attr)
    assert profiles.get("okta") is not tap  # registering this profile is the operator's one-line change
