"""The `windows` profile: deterministic identities and the baseline_logons scenario. Offline."""
from __future__ import annotations

import ipaddress
import re
from collections import Counter
from datetime import datetime, timedelta, timezone

import pytest

from runtime import organization_view as ov
from src import profiles, winevent
from src.profiles import windows

BUSINESS = datetime(2026, 10, 5, 8, 0, 0, tzinfo=timezone.utc)   # Monday 11:00 Riyadh
NIGHT = datetime(2026, 10, 9, 22, 0, 0, tzinfo=timezone.utc)     # Saturday 01:00 Riyadh


@pytest.fixture()
def directory():
    """The Directory of the active organization (the bundled Phantom Lab, see conftest)."""
    return windows.directory()


def build(directory, count=200, now=BUSINESS, **kw):
    kw.setdefault("seed", 7)
    kw.setdefault("spread_seconds", 600)
    return windows.build_events("baseline_logons", count, directory=directory, now=now, **kw)


def data(ev):
    return dict(ev.data)


# ── identities ──────────────────────────────────────────────────────────────────────────────────────────────────
def test_directory_is_the_active_organizations_domain(directory):
    view = ov.get_view()
    joined = [h for h in view.hosts if h.get("rid") and h.get("domain_joined", True) and h.get("ip")]
    assert [h.name for h in directory.hosts] == [h["name"] for h in joined]
    assert [h.name for h in directory.dcs] == [h["name"] for h in joined if h["role"] == "dc"]
    assert [h.name for h in directory.servers] == [h["name"] for h in joined if h["role"] == "server"]
    assert [h.name for h in directory.workstations] == [h["name"] for h in joined if h["role"] == "workstation"]
    assert len(directory.workstations) == 50 and len(directory.dcs) == 3 and len(directory.servers) == 8
    assert directory.netbios == view.netbios and directory.dns == view.dns
    assert directory.host("PHDC01").fqdn == f"PHDC01.{view.dns}"
    assert directory.host(f"phdc01.{view.dns}").name == "PHDC01"
    assert len({h.ip for h in directory.hosts}) == len(directory.hosts) == len({h.sid for h in directory.hosts})
    assert all(h.sid == view.sid(h2["rid"]) and h.ip == h2["ip"] for h, h2 in zip(directory.hosts, joined))
    assert all(ipaddress.ip_address(h.ip).is_private for h in directory.hosts)
    assert not any("PHTM-WEC" in h.name.upper() for h in directory.hosts)
    assert directory.host("PHDC01").lsass_pid == 685, "600 + the first byte of sha256(name) % 200, unchanged from before"


def test_users_are_the_organizations_accounts_with_stable_sids_and_homes(directory):
    view = ov.get_view()
    expected = {role: [a.login for a in view.accounts_by_role(role)] for role in ("staff", "admin", "service")}
    assert [u.login for u in directory.staff] == expected["staff"]
    assert [u.login for u in directory.admins] == expected["admin"]
    assert [u.login for u in directory.services] == expected["service"]
    assert len(directory.staff) > 22 and len(directory.admins) == 7 and len(directory.services) == 6
    assert len({u.login for u in directory.users}) == len(directory.users)
    assert all(u.sid == view.account(u.login).sid and u.sid.startswith(view.sid_base + "-") for u in directory.users)
    again = windows.Directory(view)
    assert again.users == directory.users and again.hosts == directory.hosts, "pure function of the organization"
    ws_names = {h.name for h in directory.workstations}
    assert all(u.home in ws_names for u in directory.staff + directory.admins)
    assert all(u.home == view.account(u.login).home for u in directory.users)
    assert all(u.home in {h.name for h in directory.hosts} for u in directory.services)
    assert directory.user("NALHARBI").sid == view.sid(1105)


def test_leavers_and_the_break_glass_account_never_enter_the_baseline_pool(directory):
    view = ov.get_view()
    excluded = [a.login for a in view.accounts if not a.active or a.kind == "break_glass"]
    assert excluded, "the bundled organization carries both findings"
    assert not {u.login for u in directory.users} & set(excluded)


def test_unknown_login_gets_a_stable_sid(directory):
    sid = directory.user_sid("someone.else")
    assert sid == directory.user_sid("SOMEONE.ELSE") and sid.startswith(directory.domain_sid + "-")
    assert directory.user_sid("nalharbi") == directory.user("nalharbi").sid


def test_another_organization_changes_every_name(bundled_organization):
    import copy
    doc = copy.deepcopy(bundled_organization)
    doc.update(id="corp-example", name="Corp Example")
    doc["domain"].update(dns="Corp.Example", netbios="lab", sid="S-1-5-21-1-2-3")
    other = windows.Directory(ov.OrganizationView(doc))
    assert other.netbios == "LAB" and other.host("PHDC01").fqdn == "PHDC01.corp.example"
    assert other.user("nalharbi").sid == "S-1-5-21-1-2-3-1105"


# ── baseline_logons ─────────────────────────────────────────────────────────────────────────────────────────────
def test_exact_count_ascending_and_inside_the_window(directory):
    events = build(directory, 173, spread_seconds=900, start_offset_minutes=0)
    assert len(events) == 173
    times = [e.time for e in events]
    assert times == sorted(times)
    assert times[-1] <= BUSINESS and times[0] >= BUSINESS - timedelta(seconds=900)


def test_back_dating_ends_the_window_in_the_past(directory):
    events = build(directory, 120, spread_seconds=300, start_offset_minutes=90)
    end = BUSINESS - timedelta(minutes=90)
    assert max(e.time for e in events) <= end and min(e.time for e in events) >= end - timedelta(seconds=300)


def test_same_seed_same_events_different_seed_different_events(directory):
    key = lambda evs: [(e.event_id, e.computer, e.time, tuple(sorted(dict(e.data).items()))) for e in evs]
    assert key(build(directory, 60, seed=3)) == key(build(directory, 60, seed=3))
    assert key(build(directory, 60, seed=3)) != key(build(directory, 60, seed=4))


def test_every_logoff_follows_its_logon_with_the_same_logon_id(directory):
    events = build(directory, 400)
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


def test_privileges_are_assigned_only_to_administrators_with_the_same_logon_id(directory):
    events = build(directory, 500)
    admins = {u.login for u in directory.admins}
    logon_ids = {(e.computer, data(e)["TargetLogonId"]): data(e)["TargetUserName"] for e in events if e.event_id == 4624}
    specials = [e for e in events if e.event_id == 4672]
    assert specials
    for e in specials:
        d = data(e)
        assert d["SubjectUserName"] in admins
        assert logon_ids[(e.computer, d["SubjectLogonId"])] == d["SubjectUserName"]
    admin_logons = [k for k, u in logon_ids.items() if u in admins]
    assert len(admin_logons) == len(specials), "every administrator logon, and only those, gets a 4672"


def test_identity_is_stable_across_runs_and_seeds(directory):
    seen = {}
    for seed in range(6):
        for e in build(directory, 300, seed=seed):
            if e.event_id != 4624:
                continue
            d = data(e)
            u = directory.user(d["TargetUserName"])
            assert d["TargetUserSid"] == u.sid and d["TargetDomainName"] == directory.netbios
            seen.setdefault(u.login, set()).add(u.sid)
            if u.role in ("staff", "admin"):
                home = directory.host(u.home)
                assert d["WorkstationName"] == home.name and d["IpAddress"] == home.ip, "source is the home workstation"
                if d["LogonType"] in ("2", "7", "11"):
                    assert e.computer == home.fqdn, "interactive logons happen on the home workstation"
    assert all(len(v) == 1 for v in seen.values()) and len(seen) > 20


def test_business_hours_shape_the_mix(directory):
    def mix(now):
        c = Counter()
        for e in build(directory, 600, now=now):
            if e.event_id == 4624:
                u = directory.user(data(e)["TargetUserName"])
                c["service" if u.role == "service" else ("interactive" if data(e)["LogonType"] in ("2", "7", "11") else "network")] += 1
        return c
    day, night = mix(BUSINESS), mix(NIGHT)
    assert day["interactive"] > day["service"] * 2
    assert night["service"] > night["interactive"] * 2


def test_logon_types_and_places(directory):
    events = build(directory, 800)
    types = Counter(data(e)["LogonType"] for e in events if e.event_id == 4624)
    assert {"2", "3", "10"} <= set(types) and {"7", "11"} & set(types)
    by_host = {h.fqdn: h for h in directory.hosts}
    for e in events:
        if e.event_id == 4624 and data(e)["LogonType"] == "10":
            assert by_host[e.computer].role in ("server", "dc")
        if e.event_id == 4624 and data(e)["LogonType"] == "3":
            # servers and DCs, plus the tool server a service account (the vulnerability scanner's) runs on
            assert by_host[e.computer].role in ("server", "dc", "security")
    assert all(e.channel == "Security" for e in events)


def test_rendered_events_are_real_and_never_use_probe_names(directory):
    rendered = winevent.render_all(build(directory, 300))
    assert len(rendered) == 300
    assert not any("PHTM-WEC" in r.xml.upper() for r in rendered)
    kinds = {r.event_id for r in rendered}
    assert kinds == {4624, 4634, 4672}
    assert all("An account" in r.xml or "Special privileges" in r.xml for r in rendered)


def test_registry_and_errors(directory):
    assert profiles.get("WINDOWS") is windows
    with pytest.raises(ValueError, match="choose one of"):
        profiles.get("okta")
    with pytest.raises(ValueError, match="baseline_logons"):
        windows.build_events("nope", 5, directory=directory, now=BUSINESS)
    with pytest.raises(ValueError):
        windows.build_events("baseline_logons", 0, directory=directory, now=BUSINESS)


def test_tiny_windows_and_counts_still_work(directory):
    for count in (1, 2, 3):
        assert len(windows.build_events("baseline_logons", count, directory=directory, now=BUSINESS, spread_seconds=0, seed=1)) == count


def test_test_logon_carries_its_id_in_logon_guid(directory):
    ev = windows.synthetic_test_logon(directory, f"{directory.test_computer()}.{directory.dns}", "abcdef01-2345-6789-abcd-ef0123456789", BUSINESS)
    assert data(ev)["LogonGuid"] == "{ABCDEF01-2345-6789-ABCD-EF0123456789}"
    assert ev.event_id == 4624 and ev.computer.startswith(directory.test_computer())


@pytest.mark.parametrize("count", range(1, 40))
def test_at_most_one_open_session_and_the_count_is_exact(count, directory):
    events = build(directory, count, seed=count, spread_seconds=120)
    assert len(events) == count
    logons = {(e.computer, data(e)["TargetLogonId"]) for e in events if e.event_id == 4624}
    logoffs = {(e.computer, data(e)["TargetLogonId"]) for e in events if e.event_id == 4634}
    assert logoffs <= logons and len(logons - logoffs) <= 1
    admin_logons = {(e.computer, data(e)["TargetLogonId"]) for e in events if e.event_id == 4624 and directory.user(data(e)["TargetUserName"]).role == "admin"}
    specials = {(e.computer, data(e)["SubjectLogonId"]) for e in events if e.event_id == 4672}
    assert specials == admin_logons, "an administrator logon always has its 4672 and nothing else does"


def test_logoffs_are_spread_in_a_short_window_not_piled_on_the_end(directory):
    events = build(directory, 400, spread_seconds=60, seed=11)
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


def test_test_logoff_pairs_with_its_logon(directory):
    logon = windows.synthetic_test_logon(directory, f"T1.{directory.dns}", "abcdef01-2345-6789-abcd-ef0123456789", BUSINESS)
    off = windows.synthetic_test_logoff(logon, BUSINESS + timedelta(seconds=2))
    assert off.event_id == 4634 and off.computer == logon.computer
    assert data(off)["TargetLogonId"] == data(logon)["TargetLogonId"] and data(off)["TargetUserName"] == data(logon)["TargetUserName"]
