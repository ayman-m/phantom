"""The windows profile builds its domain from the active organization, and reproduces the old hard-coded roster exactly."""
from __future__ import annotations

import dataclasses
import hashlib
import ipaddress
import json
from datetime import datetime, timedelta, timezone

import pytest

from cut_organization import cut_organization, load_fixture
from runtime import organization_view as ov
from runtime.organization_reader import OrganizationUnavailable
from src import connector
from src.profiles import windows

NOW = datetime(2026, 10, 4, 12, 0, 0, tzinfo=timezone.utc)


def dump(events) -> str:
    """The exact serialisation the baseline capture used, so the hashes are comparable."""
    return json.dumps([dataclasses.asdict(e) for e in events], sort_keys=True, default=str, indent=1)


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


@pytest.fixture()
def cut_directory():
    return windows.Directory(ov.OrganizationView(cut_organization()))


# ── equivalence with the pre-organization roster ────────────────────────────────────────────────────────────────
def test_the_cut_organization_rebuilds_the_old_directory_exactly(cut_directory):
    old = load_fixture()["directory"]
    assert [[h.name, h.fqdn, h.ip, h.role, h.sid, h.lsass_pid] for h in cut_directory.hosts] == old["hosts"]
    assert [[u.login, u.display, u.sid, u.role, u.home] for u in cut_directory.users] == old["users"]


@pytest.mark.parametrize("seed", [1, 7])
def test_baseline_logons_are_byte_identical_to_the_pre_organization_output(cut_directory, seed):
    fx = load_fixture()
    events = windows.build_events("baseline_logons", fx["count"], directory=cut_directory, now=NOW, seed=seed)
    assert sha(dump(events)) == fx["hashes"][f"seed_{seed}"]


# ── the full default organization ───────────────────────────────────────────────────────────────────────────────
def test_default_organization_drives_the_profile(bundled_organization):
    view = ov.get_view()
    d = windows.directory()
    events = windows.build_events("baseline_logons", 1500, directory=d, now=NOW, seed=3, spread_seconds=7200)
    assert len(events) == 1500
    allowed = {a.login for role in ("staff", "admin", "service") for a in view.accounts_by_role(role)}
    names = {dict(e.data)["TargetUserName"] for e in events if e.event_id == 4624}
    assert names <= allowed, "only organization accounts appear"
    assert not names & {a.login for a in view.accounts if a.kind == "break_glass" or not a.active}, \
        "the leaver's and the break-glass account are findings, never baseline traffic"
    staff = {n for n in names if view.account(n).role == "staff"}
    assert len(staff) > 22, "more staff than the old 22-person roster"
    hosts = {h["name"].upper() for h in view.hosts}
    assert {e.computer.split(".")[0].upper() for e in events} <= hosts
    assert all(e.computer.endswith("." + view.dns) for e in events)
    for e in events:
        data = dict(e.data)
        if e.event_id == 4624:
            assert data["TargetUserSid"] == view.account(data["TargetUserName"]).sid
            assert data["TargetDomainName"] == view.netbios
            assert view.host(data["WorkstationName"])["ip"] == data["IpAddress"]
    # the extra servers and the branch DC take part, and the scanner's service account works from its own host
    assert len({e.computer for e in events}) > 32


def test_privileged_accounts_with_a_separate_admin_login_get_their_own_sid(bundled_organization):
    d = windows.directory()
    adm = d.user("adm.ialkhalifa")
    person = ov.get_view().person("ialkhalifa")
    assert adm.role == "admin" and adm.home == person["workstation"] and adm.sid.endswith("-1127")
    assert d.user("ialkhalifa").role == "admin" or d.user("ialkhalifa").role == "staff"
    assert [u.role for u in d.users] == sorted((u.role for u in d.users), key=["staff", "admin", "service"].index)


def test_server_weights_favour_the_first_servers_and_service_logons_come_from_the_application_server(bundled_organization):
    d = windows.directory()
    assert d.server_weights == [4, 2] + [1] * (len(d.servers) - 2)
    assert d.service_source.name == "PHSRV-APP01" and ov.get_view().host("PHSRV-APP01")["purpose"] == "Application server"


def test_directory_is_cached_per_organization_and_follows_a_new_document(bundled_organization):
    first = windows.directory()
    assert windows.directory() is first
    other = dict(bundled_organization, id="second-org", name="Second")
    ov.set_organization_loader(lambda pinned: other)
    second = windows.directory()
    assert second is not first and second.organization == "second-org"


def test_pinned_organization_is_passed_to_the_loader(bundled_organization):
    seen = []
    ov.set_organization_loader(lambda pinned: seen.append(pinned) or bundled_organization)
    windows.directory("phantom-lab")
    windows.directory("")
    assert seen == ["phantom-lab", None]


def test_nothing_is_read_at_import_and_a_missing_organization_is_a_clear_error():
    def boom(pinned):
        raise OrganizationUnavailable("no organization is active: open the Organization page and activate one")
    ov.set_organization_loader(boom)
    with pytest.raises(OrganizationUnavailable, match="no organization is active"):
        windows.directory()


@pytest.mark.parametrize("breakage,fragment", [
    (lambda d: d.update(hosts=[h for h in d["hosts"] if h["role"] != "dc"]), "domain controller"),
    (lambda d: d.update(hosts=[h for h in d["hosts"] if h["role"] != "server"]), "not a domain-joined host"),
    (lambda d: d.update(hosts=[h for h in d["hosts"] if h["role"] != "server"], service_accounts=[]), "no domain-joined server"),
    (lambda d: d.update(service_accounts=[]), "service account"),
    (lambda d: d["people"][0].pop("rid"), "no rid"),
    (lambda d: d["service_accounts"][0].update(host="NOWHERE-01"), "NOWHERE-01"),
])
def test_an_organization_that_cannot_carry_the_profile_names_the_problem(bundled_organization, breakage, fragment):
    import copy
    doc = copy.deepcopy(bundled_organization)
    breakage(doc)
    with pytest.raises(OrganizationUnavailable, match=fragment):
        windows.Directory(ov.OrganizationView(doc))


# ── the synthetic test logon ────────────────────────────────────────────────────────────────────────────────────
def test_test_logon_takes_its_address_and_domain_from_the_organization(bundled_organization):
    d = windows.directory()
    view = ov.get_view()
    low, high = view.fresh_ip_range()
    ev = windows.synthetic_test_logon(d, f"{d.test_computer()}.{d.dns}", "abcdef01-2345-6789-abcd-ef0123456789", NOW)
    data = dict(ev.data)
    assert low <= int(ipaddress.ip_address(data["IpAddress"])) <= high and not view.host(data["WorkstationName"])
    assert data["IpAddress"] == d.test_ip() == windows.directory().test_ip(), "stable across calls"
    assert data["TargetDomainName"] == view.netbios and data["TargetUserSid"].startswith(view.sid_base + "-")
    assert d.test_computer() == f"{view.netbios}-WECTEST01" and ev.computer.endswith("." + view.dns)


def test_test_address_follows_the_organizations_unmanaged_pool(bundled_organization):
    import copy
    doc = copy.deepcopy(bundled_organization)
    for n in doc["networks"]:
        if n["kind"] == "unmanaged":
            n.pop("range")
            n["cidr"] = "198.51.100.0/24"
    d = windows.Directory(ov.OrganizationView(doc))
    assert ipaddress.ip_address(d.test_ip()) in ipaddress.ip_network("198.51.100.0/24")
    doc["networks"] = [n for n in doc["networks"] if n["kind"] != "unmanaged"]
    with pytest.raises(OrganizationUnavailable, match="unmanaged"):
        windows.Directory(ov.OrganizationView(doc)).test_ip()


# ── tools surface the organization error ────────────────────────────────────────────────────────────────────────
@pytest.fixture()
def no_secrets(monkeypatch):
    settings = {"url": "", "sender": "x", "timeout": 5.0, "organization": "", "pfx": "", "pfx_password": ""}
    monkeypatch.setattr(connector, "_settings", lambda: settings)
    return settings


def _broken(pinned):
    raise OrganizationUnavailable("organization.db not found at /app/data/organization.db")


def test_generate_events_dry_run_reports_a_missing_organization(no_secrets):
    ov.set_organization_loader(_broken)
    r = connector.phantom_generate_events(count=5, dry_run=True)
    assert r["ok"] is False and "organization" in r["error"] and "organization.db not found" in r["error"]
    assert "unexpected" not in r["error"]


def test_send_events_and_send_test_event_report_a_missing_organization(no_secrets):
    ov.set_organization_loader(_broken)
    r = connector.phantom_send_events([{"event_id": 4624, "computer": "a1"}])
    assert r["ok"] is False and "organization.db not found" in r["error"]


def test_the_pinned_organization_setting_reaches_the_loader(no_secrets, bundled_organization):
    seen = []
    ov.set_organization_loader(lambda pinned: seen.append(pinned) or bundled_organization)
    no_secrets["organization"] = "phantom-lab"
    assert connector.phantom_generate_events(count=5, dry_run=True)["ok"]
    assert seen[-1] == "phantom-lab"


# ── locale ──────────────────────────────────────────────────────────────────────────────────────────────────────
def _in_another_locale(doc):
    """The bundled organization on UTC-5, Monday to Friday, 09:00 to 18:00."""
    import copy
    other = copy.deepcopy(doc)
    other["locale"].update(utc_offset_hours=-5, workweek=["mon", "tue", "wed", "thu", "fri"], timezone="America/New_York",
                           work_hours={"start": "09:00", "end": "18:00"})
    return other


def test_the_organizations_locale_shapes_the_business_hours(bundled_organization):
    """Monday 11:00 New York is a business hour (workstation sign-ins dominate); Sunday 11:00 (not a working day), Monday 08:00
    (before the office opens) and Monday 18:30 (after it closes) are quiet (service accounts dominate)."""
    d = windows.Directory(ov.OrganizationView(_in_another_locale(bundled_organization)))
    services = {u.login for u in d.services}

    def mix(now):
        events = windows.build_events("baseline_logons", 600, directory=d, now=now, spread_seconds=1800, seed=4)
        logons = [dict(e.data) for e in events if e.event_id == 4624]
        interactive = sum(x["LogonType"] in ("2", "7", "11") for x in logons)
        return interactive, sum(x["TargetUserName"] in services for x in logons)

    for hour_utc, day, busy in ((16, 5, True), (16, 4, False), (13, 5, False), (23, 5, False), (22, 5, True)):
        interactive, service = mix(datetime(2026, 10, day, hour_utc, 30, tzinfo=timezone.utc))
        assert (interactive > service * 2) if busy else (service > interactive * 2), (hour_utc, day, interactive, service)
    default = windows.Directory(ov.OrganizationView(bundled_organization))
    sunday_11_riyadh = datetime(2026, 10, 4, 8, 0, tzinfo=timezone.utc)
    assert windows._is_business_time(default, sunday_11_riyadh) and not windows._is_business_time(d, sunday_11_riyadh)
