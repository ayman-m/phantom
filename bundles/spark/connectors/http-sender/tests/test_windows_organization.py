"""The `windows` profile reads the active organization instead of a roster of its own. These are the permanent regression tests
of that move.

(a) The organization that reproduces the old roster (tests/cut_organization.py, from tests/fixtures/pre_organization_windows_baseline.json)
    produces BYTE-IDENTICAL events for every scenario, seed and variant, and the same directory: the profile derives
    everything it used to hard-code (SIDs from rids, lsass pids from names, home workstations, roles, order, the fresh
    host prefix and address range) from the organization and nothing else. The one exception is weak_service_tickets: its skill
    was rewritten after the baseline was captured to spread over the organization's own servers (it used to name SQL02..05,
    FS02..04, web01..07 and PHDC03, which no organization holds), so it follows the skill and the old roster, which has no mail,
    backup or endpoint-management server, cannot carry it.
(b) The full bundled organization produces the same events for the 13 attack scenarios whose identities are all fresh, and for
    privileged_certificate_request once the one name that differs is mapped back (the baseline's certificate authority was
    "PHCA01"; the bundled organization's is "PHSRV-CA01"). The benign scenarios grew with the population (50 people) and are
    checked for what they must be: organization identities only, never the leaver or the break-glass account.
(c) What the profile needs from the organization, and the clear error when it is missing.
(d) A renamed organization leaves no trace of Phantom Lab in any scenario.
"""
from __future__ import annotations

import copy
import ipaddress
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[0]))
sys.path.insert(0, str(HERE))

from runtime import organization_view as ov  # noqa: E402
from runtime.organization_reader import OrganizationUnavailable  # noqa: E402
from src import connector, windows_events  # noqa: E402
from src.profiles import windows  # noqa: E402

import cut_organization as cut  # noqa: E402

NOW = datetime(2026, 10, 6, 9, 0, 0, tzinfo=timezone.utc)
FIXTURE = cut.load_fixture()
OLD_CA = FIXTURE["extra_hosts"][0]["name"]            # the certificate authority the skills name
ATTACKS = windows.ATTACKS
CERT = "privileged_certificate_request"


def use(doc) -> ov.OrganizationView:
    """Make `doc` the active organization and return its view."""
    ov.set_organization_loader(lambda pinned: doc)
    return ov.get_view()


def keyed(scenario: str) -> list[str]:
    return [k for k in FIXTURE["hashes"] if k.startswith(scenario + ".")]


# -- (a) the organization that reproduces the old roster ---------------------------------------------------------------------

def test_the_fixture_is_the_complete_baseline():
    scenarios = {k.rsplit(".", 2)[0] for k in FIXTURE["hashes"] if k != "sample"}
    assert scenarios == set(windows.SCENARIOS) and len(FIXTURE["hashes"]) == 17 * 4 + 1
    assert len(FIXTURE["directory"]["hosts"]) == 32 and len(FIXTURE["directory"]["users"]) == 30


def test_every_scenario_seed_and_variant_is_byte_identical_for_the_organization_that_reproduces_the_old_roster():
    view = use(cut.cut_organization())
    produced = cut.outputs(windows, view)
    assert set(produced) == set(FIXTURE["hashes"])
    followed = tuple(s + "." for s in cut.FOLLOWS_THE_SKILL)
    compared = [k for k in produced if not k.startswith(followed)]
    assert len(compared) == 16 * 4 + 1
    assert [k for k in compared if cut.digest(produced[k]) != FIXTURE["hashes"][k]] == []
    assert not any(isinstance(produced[k], dict) and "error" in produced[k] for k in compared)
    for key in set(produced) - set(compared):
        # The old roster has no mail, backup or endpoint-management server: a clear error, not a guess.
        assert "error" in produced[key] and "has no" in produced[key]["error"], produced[key]


def test_the_directory_is_the_old_directory():
    d = windows.directory(use(cut.cut_organization()))
    assert cut.digest({"hosts": [(h.name, h.fqdn, h.ip, h.role, h.sid, h.lsass_pid) for h in d.hosts],
                       "users": [(u.login, u.display, u.sid, u.role, u.home) for u in d.users]}) == FIXTURE["directory_hash"]
    assert [name for name, _ in d.groups] == ["SG-Finance", "SG-HR", "SG-Sales", "SG-Engineering", "SG-VPN-Users", "SG-Project-Atlas"]
    assert [sid.rsplit("-", 1)[1] for _, sid in d.groups] == ["2101", "2102", "2103", "2104", "2105", "2106"]


# -- (b) the full bundled organization ---------------------------------------------------------------------------------------

def test_the_attack_scenarios_are_unchanged_for_the_full_organization(bundled_organization):
    produced = cut.outputs(windows, use(bundled_organization))
    skip = (CERT, *cut.FOLLOWS_THE_SKILL)
    fresh = [k for k in FIXTURE["hashes"] if k.split(".")[0] in ATTACKS and k.split(".")[0] not in skip]
    assert len(fresh) == 13 * 4
    assert [k for k in fresh if cut.digest(produced[k]) != FIXTURE["hashes"][k]] == []


def test_the_certificate_request_differs_only_by_the_certificate_authoritys_name(bundled_organization):
    ca = next(h["name"] for h in bundled_organization["hosts"] if "certificate authority" in h.get("purpose", "").lower())
    assert ca != OLD_CA
    produced = cut.outputs(windows, use(bundled_organization))
    for key in keyed(CERT):
        text = json.dumps(produced[key])
        assert ca in text and OLD_CA not in text, key
        assert cut.digest(json.loads(text.replace(ca, OLD_CA))) == FIXTURE["hashes"][key], key


def organization_accounts(view):
    return {a.login: a for role in ("staff", "admin", "service") for a in view.accounts_by_role(role)}


def test_baseline_logons_use_only_organization_identities_and_never_the_leaver_or_the_break_glass_account(bundled_organization):
    view = use(bundled_organization)
    accounts = organization_accounts(view)
    excluded = {a.login for a in view.accounts if not a.active or a.kind == "break_glass"}
    assert "adm.breakglass" in excluded and len(excluded) >= 2
    hosts = {h["name"] for h in view.hosts}
    events = windows.build_events("baseline_logons", 6000, view=view, now=NOW, spread_seconds=7200, seed=11)
    seen_staff = set()
    for e in events:
        data = e["event_data"]
        assert e["computer"] in hosts and data.get("SubjectDomainName", view.netbios) == view.netbios
        login = data.get("TargetUserName") or data["SubjectUserName"]
        if e["event_id"] == 4672:
            login = data["SubjectUserName"]
        if login.endswith("$"):
            continue
        assert login in accounts and login not in excluded, login
        sid_field = "SubjectUserSid" if e["event_id"] == 4672 else "TargetUserSid"
        assert data[sid_field] == accounts[login].sid
        if accounts[login].role == "staff":
            seen_staff.add(login)
    assert len(seen_staff) > 22                                  # the population grew from 22 staff to 49
    assert {u.role for u in windows.directory(view).users} == {"staff", "admin", "service"}


def test_admin_activity_uses_the_organizations_admin_accounts_and_ordinary_groups(bundled_organization):
    view = use(bundled_organization)
    admins = {a.login for a in view.accounts_by_role("admin")}
    privileged = {g["name"] for g in bundled_organization["groups"] if g.get("privileged")}
    service_groups = {g for a in view.accounts_by_role("service") for g in a.groups}
    events = windows.build_events("admin_activity", 600, view=view, now=NOW, spread_seconds=3600, seed=5)
    subjects = {e["event_data"]["SubjectUserName"] for e in events}
    assert subjects <= admins and len(subjects) > 4              # more than the four old administrators
    assert "adm.breakglass" not in subjects
    groups = {e["event_data"]["TargetUserName"] for e in events if e["event_id"] in (4728, 4729)}
    assert groups and not groups & (privileged | service_groups)
    assert groups <= {g["name"] for g in bundled_organization["groups"]}
    staff = {a.login for a in view.accounts_by_role("staff")}
    assert {e["event_data"]["TargetUserName"] for e in events if e["event_id"] in (4724, 4767)} <= staff
    writable = {h["name"] for h in view.hosts_by_role("dc") if "read-only" not in h.get("purpose", "").lower()}
    assert {e["computer"] for e in events} == writable and "PHRODC-JED01" not in {e["computer"] for e in events}


def test_the_weak_service_ticket_spread_uses_only_the_organizations_servers_and_domain_controllers(bundled_organization):
    view = use(bundled_organization)
    names = [e["event_data"]["ServiceName"] for e in windows.build_events("weak_service_tickets", 19, view=view, now=NOW, seed=1)]
    hosts = {h["name"] for h in view.hosts if h["role"] in ("server", "dc")}
    assert len(set(names)) == 19
    assert {n.split("/")[1].split(".")[0].split(":")[0] for n in names} <= hosts
    assert all(n.split("/")[0] in ("MSSQLSvc", "HTTP", "CIFS", "LDAP") for n in names)
    assert len({n.split("/")[1].split(".")[0] for n in names}) >= 8                 # a spread over many hosts, not one


# -- (c) what the profile needs from the organization -------------------------------------------------------------------------

def without(doc, *, networks=None, hosts=None):
    other = copy.deepcopy(doc)
    if networks is not None:
        other["networks"] = [n for n in other["networks"] if n["kind"] not in networks]
    if hosts is not None:
        other["hosts"] = [h for h in other["hosts"] if not hosts(h)]
    return other


def purpose(word):
    return lambda h: word in (h.get("purpose") or "").lower()


def needs_an_address(name):
    return any(label in ("attacker IP", "client IP") for label in windows.labels(name))


def test_without_an_unmanaged_network_exactly_the_scenarios_that_mint_an_address_fail(bundled_organization):
    view = use(without(bundled_organization, networks={"unmanaged"}))
    for name in ATTACKS:
        if needs_an_address(name):
            with pytest.raises(OrganizationUnavailable, match="unmanaged"):
                windows.build_events(name, windows.MIN_COUNT[name], view=view, now=NOW, seed=1)
            # A caller who names the attacking address needs no pool.
            assert windows.build_events(name, windows.MIN_COUNT[name], view=view, now=NOW, seed=1, source_ip="10.20.77.7")
        else:
            assert windows.build_events(name, windows.MIN_COUNT[name], view=view, now=NOW, seed=1)
    assert windows.build_events("baseline_logons", 20, view=view, now=NOW, seed=1)
    assert windows.build_events("admin_activity", 20, view=view, now=NOW, seed=1)
    assert {n for n in ATTACKS if needs_an_address(n)} == {"dcsync", "weak_service_tickets", "spoofed_samaccountname_tickets"}


@pytest.mark.parametrize("scenario,drop,words,control", [
    (CERT, purpose("certificate authority"), "certificate authority", "samaccountname_change"),
    ("sms_admins", purpose("file server"), "file server", "samaccountname_change"),
    ("weak_service_tickets", purpose("sql"), "SQL server", "samaccountname_change"),
    ("weak_service_tickets", purpose("backup server"), "backup server", "samaccountname_change"),
    ("weak_service_tickets", lambda h: h["role"] == "dc" and "read-only" in h.get("purpose", "").lower(), "read-only domain controller",
     "samaccountname_change"),
    ("default_account_masquerade", purpose("web server"), "web server", "samaccountname_change"),
    ("machine_account_domain_admins", lambda h: h["role"] == "dc" and h["name"] != "PHDC01", "domain controller number 2",
     "guest_account_enabled"),
    ("spoofed_samaccountname_tickets", lambda h: h["role"] == "dc", "domain controller", "guest_account_enabled"),
    ("excessive_lockouts", lambda h: h["role"] == "workstation", "workstations", "guest_account_enabled"),
])
def test_a_missing_host_is_a_clear_error_naming_what_to_add_and_other_scenarios_still_work(
        scenario, drop, words, control, bundled_organization):
    view = use(without(bundled_organization, hosts=drop))
    with pytest.raises(OrganizationUnavailable, match=words):
        windows.build_events(scenario, windows.MIN_COUNT[scenario], view=view, now=NOW, seed=1)
    assert windows.build_events(control, windows.MIN_COUNT[control], view=view, now=NOW, seed=1)


def test_benign_scenarios_say_what_the_organization_lacks(bundled_organization):
    for dropped, words in ((lambda h: h["role"] == "dc", "domain controller"), (lambda h: h["role"] == "server", "svc-sql")):
        view = use(without(bundled_organization, hosts=dropped))
        for name in ("baseline_logons", "admin_activity"):
            with pytest.raises(OrganizationUnavailable, match=words):
                windows.build_events(name, 5, view=view, now=NOW, seed=1)


def test_a_service_account_on_a_host_outside_the_domain_is_refused_not_guessed(bundled_organization):
    doc = copy.deepcopy(bundled_organization)
    doc["service_accounts"][0]["host"] = "PHDMZ-WEB01"
    with pytest.raises(OrganizationUnavailable, match="svc-sql"):
        windows.directory(use(doc))


def test_the_organization_is_read_at_call_time_and_an_edit_shows_on_the_next_call(bundled_organization):
    before = windows.directory(use(bundled_organization))
    assert windows.directory(ov.get_view()) is before                 # cached per view object
    other = copy.deepcopy(bundled_organization)
    other["id"], other["domain"]["netbios"] = "edited", "EDITED"
    assert windows.directory(use(other)).netbios == "EDITED"
    assert windows.directory(use(bundled_organization)).netbios == "PHANTOM"


def test_importing_the_profile_reads_no_organization(tmp_path):
    code = ("import sys; sys.path.insert(0, %r); sys.path.insert(0, %r); "
            "import src.profiles.windows as w, src.windows_events; print(sorted(w.MIN_COUNT)[:1])"
            % (str(HERE.parent), str(HERE.parents[4] / "phantom-connector-runtime")))
    out = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True,
                         env={"DATA_ROOT": str(tmp_path / "nothing-here")}, timeout=60)
    assert out.returncode == 0, out.stderr


# -- the tool layer ----------------------------------------------------------------------------------------------------------

@pytest.fixture
def cfg(monkeypatch):
    values = {"url": "https://api-tenant.example.test/logs/v1/event", "key": "k", "vendor": "Okta", "product": "SSO", "extra": "",
              "extra_keys": "", "organization": "", "verify_tls": True, "timeout": 5.0,
              "cribl_url": "https://api-tenant.example.test/logs/v1/integrated/cribl/data", "cribl_token": "test-token-not-real",
              "cribl_integration": "wave-7"}
    monkeypatch.setattr(connector, "_settings", lambda: dict(values))
    return values


def test_the_tool_returns_a_clear_error_when_there_is_no_organization(cfg):
    def broken(pinned):
        raise OrganizationUnavailable("organization.db not found at /app/data/organization.db")

    ov.set_organization_loader(broken)
    for scenario in ("baseline_logons", "dcsync"):
        result = connector.phantom_generate_events("windows", scenario, dry_run=True)
        assert result["ok"] is False and "organization.db not found" in result["error"]


def test_the_tool_names_the_missing_unmanaged_network(cfg, bundled_organization):
    use(without(bundled_organization, networks={"unmanaged"}))
    failed = connector.phantom_generate_events("windows", "dcsync", dry_run=True)
    assert failed["ok"] is False and "unmanaged" in failed["error"]
    assert connector.phantom_generate_events("windows", "dcsync", dry_run=True, source_ip="10.20.77.7")["ok"]
    assert connector.phantom_generate_events("windows", "machine_account_domain_admins", dry_run=True)["ok"]


def test_the_tool_follows_the_pinned_organization(cfg, bundled_organization):
    other = copy.deepcopy(bundled_organization)
    other["id"], other["domain"]["netbios"] = "pinned", "PINNED"

    def loader(pinned):
        return other if pinned == "pinned" else bundled_organization

    ov.set_organization_loader(loader)
    cfg["organization"] = "pinned"
    pinned = connector.phantom_generate_events("windows", "privileged_group_add", dry_run=True)
    assert pinned["ok"] and pinned["events"][0]["event_data"]["SubjectDomainName"] == "PINNED"
    cfg["organization"] = ""
    assert connector.phantom_generate_events("windows", "privileged_group_add", dry_run=True)["events"][0][
        "event_data"]["SubjectDomainName"] == "PHANTOM"


# -- (d) a renamed organization leaves no trace of Phantom Lab ---------------------------------------------------------------

PHANTOM_LAB_TRACES = re.compile(r"phantom|PHDC|PHSRV|PHWS|PHCA|PHRODC|3623811015|10\.20\.|10\.21\.", re.I)


def renamed(doc):
    """The bundled organization on another domain, with other host names, addresses and SID base."""
    text = json.dumps(doc)
    for old, new in (("phantom-lab", "acme"), ("phantom.lab", "acme.example"), ("PHANTOM", "ACME"), ("Phantom Lab", "Acme"),
                     ("S-1-5-21-3623811015-3361044348-30300820", "S-1-5-21-11-22-33"), ("10.20.", "10.77."), ("10.21.", "10.78.")):
        text = text.replace(old, new)
    text = re.sub(r"\bPH(?=[A-Z])", "AC", text)
    return json.loads(text)


def test_a_renamed_organization_appears_in_every_scenario_and_phantom_lab_in_none(bundled_organization):
    doc = renamed(bundled_organization)
    assert not PHANTOM_LAB_TRACES.search(json.dumps({k: v for k, v in doc.items() if k not in ("people", "cloud", "cortex", "egress")})
                                         .replace("Acme", ""))
    view = use(doc)
    assert (view.dns, view.netbios, view.sid_base) == ("acme.example", "ACME", "S-1-5-21-11-22-33")
    for name in windows.SCENARIOS:
        count = windows.MIN_COUNT.get(name) or 40
        for seed in (1, 2):
            events = windows.build_events(name, count, view=view, now=NOW, seed=seed)
            text = json.dumps(events)
            assert not PHANTOM_LAB_TRACES.search(text), (name, PHANTOM_LAB_TRACES.search(text).group(0))
            assert "acme" in text.lower() or "ACME" in text
    # And the same scenario on the renamed organization has the same SHAPE as on Phantom Lab (events, ids, times).
    for name in ATTACKS:
        a = windows.build_events(name, windows.MIN_COUNT[name], view=view, now=NOW, seed=3)
        b = windows.build_events(name, windows.MIN_COUNT[name], view=use(bundled_organization), now=NOW, seed=3)
        assert [(e["event_id"], e["time"]) for e in a] == [(e["event_id"], e["time"]) for e in b]
        use(doc)


def in_another_locale(bundled_organization):
    """The bundled organization on UTC-5, Monday to Friday, 09:00 to 18:00."""
    doc = renamed(bundled_organization)
    doc["locale"].update(utc_offset_hours=-5, workweek=["mon", "tue", "wed", "thu", "fri"], timezone="America/New_York",
                         work_hours={"start": "09:00", "end": "18:00"})
    return doc


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_baseline_logons_stay_equal_to_wec_senders_for_an_organization_in_another_locale(seed, bundled_organization):
    """Both connectors read the same locale, so the same seed gives the same events in any time zone."""
    from test_windows_profile import wec_profile, wec_winevent

    view = use(in_another_locale(bundled_organization))
    for now in (datetime(2026, 10, 5, 16, 0, tzinfo=timezone.utc), datetime(2026, 10, 4, 16, 0, tzinfo=timezone.utc),
                datetime(2026, 10, 5, 13, 0, tzinfo=timezone.utc)):
        mine = windows.build_events("baseline_logons", 200, view=view, now=now, spread_seconds=7200, seed=seed)
        theirs = wec_profile.build_events("baseline_logons", 200, directory=wec_profile.directory(), now=now,
                                          spread_seconds=7200, seed=seed)
        assert [p.xml for p in windows_events.prepare(mine, view.dns)] == [r.xml for r in wec_winevent.render_all(theirs)]


def test_the_organizations_locale_shapes_the_business_hours(bundled_organization):
    """Monday 11:00 New York is a business hour (workstation sign-ins dominate); Sunday 11:00 (not a working day), Monday 08:00
    (before the office opens) and Monday 18:30 (after it closes) are quiet (service accounts dominate)."""
    view = use(in_another_locale(bundled_organization))
    services = {u.login for u in windows.directory(view).services}

    def mix(now):
        events = windows.build_events("baseline_logons", 600, view=view, now=now, spread_seconds=1800, seed=4)
        logons = [e["event_data"] for e in events if e["event_id"] == 4624]
        interactive = sum(d["LogonType"] in ("2", "7", "11") for d in logons)
        return interactive, sum(d["TargetUserName"] in services for d in logons)

    for hour_utc, day, busy in ((16, 5, True), (16, 4, False), (13, 5, False), (23, 5, False), (22, 5, True)):
        interactive, service = mix(datetime(2026, 10, day, hour_utc, 30, tzinfo=timezone.utc))
        assert (interactive > service * 2) if busy else (service > interactive * 2), (hour_utc, day, interactive, service)
    # The bundled organization (UTC+3, Sunday to Thursday, 08:00 to 17:00) says the opposite for the same instants.
    other = windows.directory(use(bundled_organization))
    assert other.is_business_time(datetime(2026, 10, 4, 8, 0, tzinfo=timezone.utc)) is True       # Sunday 11:00 Riyadh
    assert windows.directory(use(in_another_locale(bundled_organization))).is_business_time(
        datetime(2026, 10, 4, 8, 0, tzinfo=timezone.utc)) is False


def test_fresh_hosts_and_addresses_follow_the_organizations_naming_and_pool(bundled_organization):
    doc = renamed(bundled_organization)
    for n in doc["networks"]:
        if n["kind"] == "unmanaged":
            n.pop("range", None)
            n["cidr"] = "172.30.8.0/22"
    view = use(doc)
    low, high = view.fresh_ip_range()
    prefix = view.fresh_host_prefix()
    assert prefix == "ACWS-"
    for name in ("excessive_lockouts", "dcsync", "weak_service_tickets", "spoofed_samaccountname_tickets"):
        text = json.dumps(windows.build_events(name, windows.MIN_COUNT[name], view=view, now=NOW, seed=9))
        hosts = set(re.findall(r"\b(?:ACWS|PHWS)-\d+\b", text))
        if any(label in ("machine", "attacker host", "caller host") for label in windows.labels(name)):
            assert hosts and all(h.startswith(prefix) and len(h) == len(prefix) + 5 for h in hosts)
        else:
            assert not hosts
        for ip in re.findall(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", text):
            assert low <= int(ipaddress.ip_address(ip)) <= high or ip.startswith("10.77."), (name, ip)
    ips = {v for k, v in windows.fresh_values("dcsync", now=NOW, seed=4, view=view).items() if k.endswith("IP")}
    assert ips and all(low <= int(ipaddress.ip_address(i)) <= high and int(ipaddress.ip_address(i)) & 255 in range(20, 251) for i in ips)


def test_the_test_event_routes_its_domain_through_the_organization(bundled_organization):
    view = use(renamed(bundled_organization))
    event, facts = windows_events.build_test_event(view, "11111111-2222-3333-4444-555555555555", NOW)
    assert not PHANTOM_LAB_TRACES.search(json.dumps(event).replace("phantom.test", ""))
    assert event["computer"] == "ACME-CRIBLTEST01.acme.example" == facts["computer"]
    assert event["event_data"]["TargetUserSid"].startswith("S-1-5-21-11-22-33-")
    assert ipaddress.ip_address(event["event_data"]["IpAddress"]) in ipaddress.ip_network("10.77.0.0/16")
