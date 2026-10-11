"""google_workspace event profile: unit tests. No network, no files.

Run from the connector directory:  python3 -m pytest -x
"""
from __future__ import annotations

import ipaddress
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.profiles import google_workspace as gw, ippools  # noqa: E402

NOW = datetime(2026, 9, 30, 12, 0, 0, tzinfo=timezone.utc)
DOMAIN = "phantom-lab.example"
ID_TIME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


def is_home(ip):
    return any(ipaddress.ip_address(ip) in ipaddress.ip_network(r.cidr) for r in ippools.HOME)


def country(ip):
    pool_range = ippools.range_of(ip)
    return pool_range.country if pool_range else None


def build(scenario, count, **kw):
    return gw.build_events(scenario, count, domain=DOMAIN, now=NOW, seed=7, **kw)


def parsed(ev):
    return datetime.strptime(ev["id"]["time"], "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)


def op(ev):
    return ev["events"][0]["name"]


def params(ev):
    return {p["name"]: p for p in ev["events"][0]["parameters"]}


def model_rule_view(ev):
    """What the Drive modeling rule extracts: the regexes run over the re-serialised parameters."""
    wire = json.dumps(ev["events"][0]["parameters"], separators=(",", ":"))
    out = {}
    for key in ("doc_type", "doc_title", "owner"):
        m = re.findall(rf'"name":"{key}","value":"([^"]+)"', wire)
        out[key] = m[0] if m else None
    return out


# ── module constants ────────────────────────────────────────────────────

def test_interface_constants():
    assert gw.NAME == "google_workspace"
    assert gw.EXPECTED_DATASET == "google_workspace_drive"
    assert gw.EXPECTED_DATASETS == ("google_workspace_drive",)
    assert gw.SCENARIOS == ("benign_drive", "public_share", "sensitive_download", "impossible_travel_login")
    assert "google_workspace_drive_raw" in gw.DESCRIPTION
    assert gw.TIME_FIELD == "id.time"
    # connector.py reads TEST_ID_FIELD with event[...]/event.get(...): it must be a top-level key
    assert gw.TEST_ID_FIELD in build("benign_drive", 1)[0]


# ── event shape (the Activity resource and the Drive modeling rule) ─────

REQUIRED = {"kind", "etag", "ownerDomain", "ipAddress", "id", "actor", "events"}


@pytest.mark.parametrize("scenario", gw.SCENARIOS)
def test_every_scenario_emits_full_activity_objects(scenario):
    events = build(scenario, 8)
    assert len(events) == 8
    for ev in events:
        assert REQUIRED <= ev.keys()
        assert ev["kind"] == "admin#reports#activity"
        assert ev["ownerDomain"] == DOMAIN
        assert {"time", "uniqueQualifier", "applicationName", "customerId"} <= ev["id"].keys()
        assert ev["id"]["applicationName"] in ("drive", "login")
        assert ev["actor"]["email"].endswith("@" + DOMAIN)
        assert re.fullmatch(r"\d{21}", ev["actor"]["profileId"])
        assert ev["actor"]["callerType"] == "USER"
        assert isinstance(ev["events"], list) and len(ev["events"]) == 1
        e0 = ev["events"][0]
        assert isinstance(e0["type"], str) and isinstance(e0["name"], str) and isinstance(e0["parameters"], list)
        assert not {"_vendor", "_product", "_time"} & ev.keys()  # the collector adds these


@pytest.mark.parametrize("scenario", [s for s in gw.SCENARIOS if s != "impossible_travel_login"])
def test_drive_events_carry_the_three_parameters_the_modeling_rule_reads(scenario):
    for ev in build(scenario, 12):
        assert ev["id"]["applicationName"] == "drive"
        view = model_rule_view(ev)
        assert view["doc_type"] and view["doc_title"] and view["owner"] and "@" in view["owner"]
        p = params(ev)
        for name in ("doc_type", "doc_title", "owner", "doc_id"):  # string form, name before value
            assert list(p[name]) == ["name", "value"] and isinstance(p[name]["value"], str)
        assert len(p["doc_id"]["value"]) == 44
        assert isinstance(p["primary_event"]["boolValue"], bool)
        assert '"' not in view["doc_title"] and "\\" not in view["doc_title"]


def test_the_drive_rule_reads_the_expected_columns_after_a_wire_round_trip():
    ev = json.loads(json.dumps(build("sensitive_download", 3)[0], separators=(",", ":")))
    assert ev["events"][0]["type"] == "access" and ev["events"][0]["name"] == "download"
    assert ev["actor"]["email"] and ev["actor"]["profileId"] and ev["ipAddress"] and ev["kind"]
    assert model_rule_view(ev)["doc_title"] in {t for t, _ in gw._SENSITIVE}


# ── scenarios ───────────────────────────────────────────────────────────

def test_benign_drive_mixes_kinds_across_several_users_from_home_addresses():
    events = build("benign_drive", 16)
    kinds = {op(e) for e in events}
    assert {"view", "download", "change_user_access", "trash"} == kinds
    assert op(events[0]) == "view" and sum(op(e) == "view" for e in events) > len(events) // 2
    assert len({e["actor"]["email"] for e in events}) > 3
    assert all(is_home(e["ipAddress"]) and country(e["ipAddress"]) == "Saudi Arabia" for e in events)
    assert not any(params(e)["visibility"]["value"] == "public_on_the_web" for e in events)


def test_each_user_has_one_stable_home_address_across_runs_and_profiles():
    def by_actor(events):
        out = {}
        for e in events:
            out.setdefault(e["actor"]["email"], set()).add(e["ipAddress"])
        return out

    first, second = by_actor(build("benign_drive", 48)), by_actor(build("benign_drive", 30, start_offset_minutes=60))
    assert len(first) == 12 and all(len(ips) == 1 for ips in first.values())
    assert all(second[actor] == ips for actor, ips in first.items() if actor in second)
    assert len({next(iter(ips)) for ips in first.values()}) == 12
    assert first[f"noura.alharbi@{DOMAIN}"] == {ippools.home_for(0)[0]}  # the same address as in the okta profile


def test_external_share_names_an_outside_reserved_domain_and_uses_multivalue():
    ev = next(e for e in build("benign_drive", 16) if op(e) == "change_user_access")
    p = params(ev)
    assert ev["events"][0]["type"] == "acl_change"
    assert p["visibility"]["value"] == "shared_externally"
    assert p["target_user"]["value"].endswith("@external-partner.example")
    assert p["new_value"]["multiValue"] == ["can_view"]


def test_public_share_is_one_actor_making_sensitive_files_public():
    events = build("public_share", 5, target_user="Noura.Alharbi", source_ip="203.0.113.99")
    assert {e["actor"]["email"] for e in events} == {f"noura.alharbi@{DOMAIN}"}
    assert {e["ipAddress"] for e in events} == {"203.0.113.99"}  # the override wins, even outside every pool
    for ev in events:
        assert (ev["events"][0]["type"], op(ev)) == ("acl_change", "change_document_visibility")
        p = params(ev)
        assert p["visibility"]["value"] == p["new_visibility"]["value"] == "public_on_the_web"
        assert p["old_visibility"]["value"] == "private"
        assert p["doc_title"]["value"] in {t for t, _ in gw._SENSITIVE}
    assert len({params(e)["doc_id"]["value"] for e in events}) == 5


def test_sensitive_download_is_a_burst_by_one_actor_of_sensitive_filenames():
    events = build("sensitive_download", 25, spread_seconds=180)
    assert len({e["actor"]["email"] for e in events}) == 1
    assert len({e["ipAddress"] for e in events}) == 1 and is_home(events[0]["ipAddress"])
    assert {op(e) for e in events} == {"download"}
    assert {params(e)["doc_title"]["value"] for e in events} <= {t for t, _ in gw._SENSITIVE}
    assert parsed(events[-1]) - parsed(events[0]) == timedelta(seconds=180)
    assert all(params(e)["owner"]["value"] != e["actor"]["email"] for e in events)


@pytest.mark.parametrize("scenario", ["public_share", "sensitive_download"])
def test_without_source_ip_the_actor_acts_from_their_own_home_address(scenario):
    (home,) = {e["ipAddress"] for e in build(scenario, 4, target_user="khalid.alotaibi")}
    assert home == ippools.home_for(1)[0] and country(home) == "Saudi Arabia"
    (stranger,) = {e["ipAddress"] for e in build(scenario, 4, target_user="someone.new")}
    assert is_home(stranger)
    other_seed = gw.build_events(scenario, 2, domain=DOMAIN, now=NOW, seed=5, target_user="someone.new")
    assert {e["ipAddress"] for e in other_seed} == {stranger}


def test_impossible_travel_is_two_logins_for_one_actor_hours_apart_from_different_addresses():
    events = build("impossible_travel_login", 2, target_user="noura.alharbi")
    assert len(events) == 2
    a, b = events
    assert a["actor"]["email"] == b["actor"]["email"] == f"noura.alharbi@{DOMAIN}"
    assert all(e["id"]["applicationName"] == "login" and e["events"][0]["type"] == "login" for e in events)
    assert {op(a), op(b)} == {"login_success"}
    assert parsed(b) - parsed(a) > timedelta(hours=2)
    assert parsed(b) - parsed(a) <= timedelta(hours=6, seconds=120)
    assert parsed(b) <= NOW
    assert a["ipAddress"] == ippools.home_for(0)[0] and is_home(a["ipAddress"])
    assert not is_home(b["ipAddress"]) and ippools.range_of(b["ipAddress"]) in ippools.ABROAD
    assert country(a["ipAddress"]) == "Saudi Arabia" and country(b["ipAddress"]) not in (None, "Saudi Arabia")
    assert params(a)["affected_email_address"]["value"] == a["actor"]["email"]


def test_impossible_travel_with_more_events_keeps_two_clusters_oldest_first():
    events = build("impossible_travel_login", 7, spread_seconds=600)
    times = [parsed(e) for e in events]
    assert times == sorted(times)
    early, late = events[:3], events[3:]
    assert len({e["ipAddress"] for e in early}) == 1 and len({e["ipAddress"] for e in late}) == 1
    assert country(early[0]["ipAddress"]) != country(late[0]["ipAddress"])
    assert times[3] - times[2] > timedelta(hours=2)


def test_impossible_travel_needs_two_events():
    with pytest.raises(ValueError, match="count >= 2"):
        build("impossible_travel_login", 1)


def test_unknown_scenario_and_bad_count_are_refused():
    with pytest.raises(ValueError, match="unknown scenario"):
        build("nope", 3)
    with pytest.raises(ValueError, match="count"):
        build("benign_drive", 0)


# ── time, ids, determinism ──────────────────────────────────────────────

@pytest.mark.parametrize("scenario", [s for s in gw.SCENARIOS if s != "impossible_travel_login"])
def test_id_time_is_millisecond_utc_ascending_never_after_now(scenario):
    events = build(scenario, 10, spread_seconds=300, start_offset_minutes=5)
    times = [e["id"]["time"] for e in events]
    assert all(ID_TIME.match(t) for t in times)  # the parsing rule accepts ...Z or ...SS.mmmZ
    assert times == sorted(times)
    assert times[-1] == "2026-09-30T11:55:00.000Z"  # 5 minutes back-dated


def test_impossible_travel_times_are_iso_utc_and_ascending():
    times = [e["id"]["time"] for e in build("impossible_travel_login", 6, spread_seconds=90)]
    assert all(ID_TIME.match(t) for t in times) and times == sorted(times)
    assert max(parsed(e) for e in build("impossible_travel_login", 6)) <= NOW


@pytest.mark.parametrize("scenario", gw.SCENARIOS)
def test_ids_are_unique(scenario):
    events = build(scenario, 40)
    assert len({e["etag"] for e in events}) == 40
    assert len({e["id"]["uniqueQualifier"] for e in events}) == 40
    assert all(-(2**63) <= int(e["id"]["uniqueQualifier"]) < 2**63 for e in events)


def test_a_fixed_seed_is_deterministic_and_another_differs():
    for scenario in gw.SCENARIOS:
        assert build(scenario, 6) == build(scenario, 6)
        other = gw.build_events(scenario, 6, domain=DOMAIN, now=NOW, seed=8)
        assert other != build(scenario, 6)


def test_actor_is_normalised_like_the_other_profiles():
    ev = build("public_share", 1, target_user="PHANTOM\\Khalid.Alotaibi")[0]
    assert ev["actor"]["email"] == f"khalid.alotaibi@{DOMAIN}"
    assert build("public_share", 1, target_user="a@" + DOMAIN)[0]["actor"]["email"] == "a@" + DOMAIN


def test_profile_id_is_stable_per_address():
    assert gw._Factory.profile_id("A@x.example") == gw._Factory.profile_id("a@x.example")
    assert gw._Factory.profile_id("a@x.example") != gw._Factory.profile_id("b@x.example")


# ── fictitious identities, real addresses ───────────────────────────────

EMAIL = re.compile(r"[\w.+-]+@([\w.-]+)")
IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")


@pytest.mark.parametrize("scenario", gw.SCENARIOS)
def test_only_reserved_domains_and_addresses_from_the_pools(scenario):
    for ev in build(scenario, 24) + [gw.sample_event(domain=DOMAIN, now=NOW)]:
        text = json.dumps(ev)
        for host in EMAIL.findall(text):
            assert host in (DOMAIN, "external-partner.example"), host
        for raw in IPV4.findall(text):
            assert ippools.range_of(raw) is not None, raw


def test_a_source_ip_override_is_used_as_given():
    assert {e["ipAddress"] for e in build("sensitive_download", 4, source_ip="192.0.2.50")} == {"192.0.2.50"}
    far = build("impossible_travel_login", 2, source_ip="192.0.2.50")[1]
    assert far["ipAddress"] == "192.0.2.50"


def test_the_default_far_login_is_seeded_and_varies_with_the_seed():
    def far(seed):
        return gw.build_events("impossible_travel_login", 2, domain=DOMAIN, now=NOW, seed=seed)[1]["ipAddress"]

    assert far(3) == far(3) and len({far(seed) for seed in range(30)}) > 5


# ── sample event ────────────────────────────────────────────────────────

def test_sample_event_is_a_valid_identifiable_login():
    ev = gw.sample_event(domain=DOMAIN, now=NOW)
    assert REQUIRED <= ev.keys() and ev[gw.TEST_ID_FIELD]
    assert ev["actor"]["email"] == f"phantom.test@{DOMAIN}"
    assert op(ev) == "login_success" and ev["id"]["time"] == "2026-09-30T12:00:00.000Z"
    assert ev["ipAddress"] == ippools.home_for(0)[0]
