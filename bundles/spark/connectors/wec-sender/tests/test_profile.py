"""The `windows` profile: deterministic identities and the baseline_logons scenario. Offline."""
from __future__ import annotations

import ipaddress
import re
from collections import Counter
from datetime import datetime, timedelta, timezone

import pytest

from src import profiles, winevent
from src.profiles import windows

D = windows.Directory()
BUSINESS = datetime(2026, 10, 5, 8, 0, 0, tzinfo=timezone.utc)   # Monday 11:00 Riyadh
NIGHT = datetime(2026, 10, 9, 22, 0, 0, tzinfo=timezone.utc)     # Saturday 01:00 Riyadh


def build(count=200, now=BUSINESS, **kw):
    kw.setdefault("seed", 7)
    kw.setdefault("spread_seconds", 600)
    return windows.build_events("baseline_logons", count, directory=D, now=now, **kw)


def data(ev):
    return dict(ev.data)


# ── identities ──────────────────────────────────────────────────────────────────────────────────────────────────
def test_default_directory_shape():
    assert (len(D.hosts), len(D.dcs), len(D.servers), len(D.workstations)) == (32, 2, 4, 26)
    assert [h.name for h in D.dcs] == ["PHDC01", "PHDC02"]
    assert [h.name for h in D.servers] == ["PHSRV-FS01", "PHSRV-APP01", "PHSRV-SQL01", "PHSRV-WEB01"]
    assert D.workstations[0].name == "PHWS-001" and D.workstations[-1].name == "PHWS-026"
    assert D.host("PHDC01").fqdn == "PHDC01.phantom.lab"
    assert D.host("phdc01.phantom.lab").name == "PHDC01"
    assert len({h.ip for h in D.hosts}) == 32 and len({h.sid for h in D.hosts}) == 32
    assert all(ipaddress.ip_address(h.ip).is_private for h in D.hosts)
    assert not any("PHTM-WEC" in h.name.upper() for h in D.hosts)


def test_users_are_about_thirty_with_stable_sids_and_homes():
    assert len(D.users) == 30
    assert (len(D.staff), len(D.admins), len(D.services)) == (22, 4, 4)
    assert len({u.login for u in D.users}) == 30
    rids = [int(u.sid.rsplit("-", 1)[1]) for u in D.users]
    assert rids == list(range(1105, 1135))
    assert all(u.sid.startswith("S-1-5-21-3623811015-3361044348-30300820-") for u in D.users)
    again = windows.Directory()
    assert again.users == D.users and again.hosts == D.hosts, "pure function of the names"
    ws_names = {h.name for h in D.workstations}
    assert all(u.home in ws_names for u in D.staff + D.admins)
    assert all(u.home in {h.name for h in D.servers} for u in D.services)
    assert D.user("NALHARBI").sid == D.users[0].sid


def test_unknown_login_gets_a_stable_sid():
    assert D.user_sid("someone.else") == D.user_sid("SOMEONE.ELSE") and D.user_sid("someone.else").startswith(windows.DOMAIN_SID)


@pytest.mark.parametrize("count,expected", [(8, 8), (50, 50), (500, 100), (0, 32), (None, 32)])
def test_host_count_keeps_dcs_and_servers(count, expected):
    d = windows.Directory(host_count=count)
    assert len(d.hosts) == expected and len(d.dcs) == 2 and len(d.servers) == 4
    assert len({h.ip for h in d.hosts}) == expected


def test_domain_names_are_configurable():
    d = windows.Directory("lab", "Corp.Example")
    assert d.netbios == "LAB" and d.host("PHDC01").fqdn == "PHDC01.corp.example"


# ── baseline_logons ─────────────────────────────────────────────────────────────────────────────────────────────
def test_exact_count_ascending_and_inside_the_window():
    events = build(173, spread_seconds=900, start_offset_minutes=0)
    assert len(events) == 173
    times = [e.time for e in events]
    assert times == sorted(times)
    assert times[-1] <= BUSINESS and times[0] >= BUSINESS - timedelta(seconds=900)


def test_back_dating_ends_the_window_in_the_past():
    events = build(120, spread_seconds=300, start_offset_minutes=90)
    end = BUSINESS - timedelta(minutes=90)
    assert max(e.time for e in events) <= end and min(e.time for e in events) >= end - timedelta(seconds=300)


def test_same_seed_same_events_different_seed_different_events():
    key = lambda evs: [(e.event_id, e.computer, e.time, tuple(sorted(dict(e.data).items()))) for e in evs]
    assert key(build(60, seed=3)) == key(build(60, seed=3))
    assert key(build(60, seed=3)) != key(build(60, seed=4))


def test_every_logoff_follows_its_logon_with_the_same_logon_id():
    events = build(400)
    logons = {}
    for e in events:
        d = data(e)
        if e.event_id == 4624:
            logons[(e.computer, d["TargetLogonId"])] = e
        elif e.event_id == 4634:
            logon = logons.get((e.computer, d["TargetLogonId"]))
            assert logon is not None, "4634 without an earlier 4624"
            assert logon.time < e.time
            assert d["TargetUserName"] == data(logon)["TargetUserName"] and d["LogonType"] == data(logon)["LogonType"]
    logged_off = {(e.computer, data(e)["TargetLogonId"]) for e in events if e.event_id == 4634}
    assert len(set(logons) - logged_off) <= 1, "at most one session is left open"
    assert len(logons) == len({(e.computer, data(e)["TargetLogonId"]) for e in events if e.event_id == 4624})


def test_privileges_are_assigned_only_to_administrators_with_the_same_logon_id():
    events = build(500)
    admins = {u.login for u in D.admins}
    logon_ids = {(e.computer, data(e)["TargetLogonId"]): data(e)["TargetUserName"] for e in events if e.event_id == 4624}
    specials = [e for e in events if e.event_id == 4672]
    assert specials
    for e in specials:
        d = data(e)
        assert d["SubjectUserName"] in admins
        assert logon_ids[(e.computer, d["SubjectLogonId"])] == d["SubjectUserName"]
    admin_logons = [k for k, u in logon_ids.items() if u in admins]
    assert len(admin_logons) == len(specials), "every administrator logon, and only those, gets a 4672"


def test_identity_is_stable_across_runs_and_seeds():
    seen = {}
    for seed in range(6):
        for e in build(300, seed=seed):
            if e.event_id != 4624:
                continue
            d = data(e)
            u = D.user(d["TargetUserName"])
            assert d["TargetUserSid"] == u.sid and d["TargetDomainName"] == "PHANTOM"
            seen.setdefault(u.login, set()).add(u.sid)
            if u.role in ("staff", "admin"):
                home = D.host(u.home)
                assert d["WorkstationName"] == home.name and d["IpAddress"] == home.ip, "source is the home workstation"
                if d["LogonType"] in ("2", "7", "11"):
                    assert e.computer == home.fqdn, "interactive logons happen on the home workstation"
    assert all(len(v) == 1 for v in seen.values()) and len(seen) > 20


def test_business_hours_shape_the_mix():
    def mix(now):
        c = Counter()
        for e in build(600, now=now):
            if e.event_id == 4624:
                u = D.user(data(e)["TargetUserName"])
                c["service" if u.role == "service" else ("interactive" if data(e)["LogonType"] in ("2", "7", "11") else "network")] += 1
        return c
    day, night = mix(BUSINESS), mix(NIGHT)
    assert day["interactive"] > day["service"] * 2
    assert night["service"] > night["interactive"] * 2


def test_logon_types_and_places():
    events = build(800)
    types = Counter(data(e)["LogonType"] for e in events if e.event_id == 4624)
    assert {"2", "3", "10"} <= set(types) and {"7", "11"} & set(types)
    by_host = {h.fqdn: h for h in D.hosts}
    for e in events:
        if e.event_id == 4624 and data(e)["LogonType"] == "10":
            assert by_host[e.computer].role in ("server", "dc")
        if e.event_id == 4624 and data(e)["LogonType"] == "3":
            assert by_host[e.computer].role in ("server", "dc")
    assert all(e.channel == "Security" for e in events)


def test_rendered_events_are_real_and_never_use_probe_names():
    rendered = winevent.render_all(build(300))
    assert len(rendered) == 300
    assert not any("PHTM-WEC" in r.xml.upper() for r in rendered)
    kinds = {r.event_id for r in rendered}
    assert kinds == {4624, 4634, 4672}
    assert all("An account" in r.xml or "Special privileges" in r.xml for r in rendered)


def test_registry_and_errors():
    assert profiles.get("WINDOWS") is windows
    with pytest.raises(ValueError, match="choose one of"):
        profiles.get("okta")
    with pytest.raises(ValueError, match="baseline_logons"):
        windows.build_events("nope", 5, directory=D, now=BUSINESS)
    with pytest.raises(ValueError):
        windows.build_events("baseline_logons", 0, directory=D, now=BUSINESS)


def test_tiny_windows_and_counts_still_work():
    for count in (1, 2, 3):
        assert len(windows.build_events("baseline_logons", count, directory=D, now=BUSINESS, spread_seconds=0, seed=1)) == count


def test_test_logon_carries_its_id_in_logon_guid():
    ev = windows.synthetic_test_logon(D, "PHANTOM-WECTEST01.phantom.lab", "abcdef01-2345-6789-abcd-ef0123456789", BUSINESS)
    assert data(ev)["LogonGuid"] == "{ABCDEF01-2345-6789-ABCD-EF0123456789}"
    assert ev.event_id == 4624 and ev.computer.startswith("PHANTOM-WECTEST01")


@pytest.mark.parametrize("count", range(1, 40))
def test_at_most_one_open_session_and_the_count_is_exact(count):
    events = build(count, seed=count, spread_seconds=120)
    assert len(events) == count
    logons = {(e.computer, data(e)["TargetLogonId"]) for e in events if e.event_id == 4624}
    logoffs = {(e.computer, data(e)["TargetLogonId"]) for e in events if e.event_id == 4634}
    assert logoffs <= logons and len(logons - logoffs) <= 1
    admin_logons = {(e.computer, data(e)["TargetLogonId"]) for e in events if e.event_id == 4624 and D.user(data(e)["TargetUserName"]).role == "admin"}
    specials = {(e.computer, data(e)["SubjectLogonId"]) for e in events if e.event_id == 4672}
    assert specials == admin_logons, "an administrator logon always has its 4672 and nothing else does"


def test_logoffs_are_spread_in_a_short_window_not_piled_on_the_end():
    events = build(400, spread_seconds=60, seed=11)
    times = Counter(e.time for e in events if e.event_id == 4634)
    assert len(times) > 100, "distinct logoff timestamps"
    assert max(times.values()) / sum(times.values()) < 0.1
    first_logon = {}
    for e in events:
        if e.event_id == 4624:
            first_logon[(e.computer, data(e)["TargetLogonId"])] = e.time
        if e.event_id == 4634:
            assert first_logon[(e.computer, data(e)["TargetLogonId"])] < e.time
    assert max(e.time for e in events) <= BUSINESS


def test_test_logoff_pairs_with_its_logon():
    logon = windows.synthetic_test_logon(D, "T1.phantom.lab", "abcdef01-2345-6789-abcd-ef0123456789", BUSINESS)
    off = windows.synthetic_test_logoff(logon, BUSINESS + timedelta(seconds=2))
    assert off.event_id == 4634 and off.computer == logon.computer
    assert data(off)["TargetLogonId"] == data(logon)["TargetLogonId"] and data(off)["TargetUserName"] == data(logon)["TargetUserName"]
