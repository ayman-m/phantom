"""The `windows` profile (0.6.0): `baseline_logons` and `admin_activity` (benign, a stable domain) and one attack scenario per
Windows trigger skill, each producing the SAME events as the skill's JSON block with every identity new. No network: the
endpoint is an httpx MockTransport.

What is compared, and against what:
  * the embedded `windows_recipes.json` against the first JSON block of each of the 15 skill files (drift guard);
  * for each attack scenario, the XML rendered from the scenario's events against the XML rendered from the skill block filled
    with the same generated values (the parity the brief asks for);
  * `baseline_logons` against wec-sender's own profile, loaded by path, byte for byte;
  * identities: stable for the benign scenarios, new and pairwise disjoint for the attack ones.

The profile reads the active organization; tests/conftest.py makes that the bundled Phantom Lab. The proof that the move to the
organization changed nothing is in tests/test_windows_organization.py (byte-identical outputs from the organization that
reproduces the old roster, against tests/fixtures/pre_organization_windows_baseline.json).

Run from the connector directory:  python3 -m pytest -x
"""
from __future__ import annotations

import importlib
import importlib.util
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[0]))

from src import connector, cribl, profiles, windows_events  # noqa: E402
from src.profiles import windows  # noqa: E402
from src.profiles.windows import active_view  # noqa: E402

REPO = HERE.parents[4]
LAB = yaml.safe_load((REPO / "bundles/spark/organization/phantom-lab.yaml").read_text(encoding="utf-8"))
# The skills name Phantom Lab's hosts; the bundled organization's certificate authority is the host whose purpose says so.
CA_NAME = next(h["name"] for h in LAB["hosts"] if "certificate authority" in (h.get("purpose") or "").lower())
WEC_SRC = REPO / "bundles/spark/connectors/wec-sender/src"
SKILLS = REPO / "bundles/spark/mcp/skills/workflows"
NOW = datetime(2026, 10, 6, 9, 0, 0, tzinfo=timezone.utc)      # a Tuesday, 12:00 Saudi time (business hours)
NIGHT = datetime(2026, 10, 6, 0, 30, 0, tzinfo=timezone.utc)   # 03:30 Saudi time
DNS = "phantom.lab"
URL = "https://api-tenant.example.test/logs/v1/integrated/cribl/data"
TOKEN = "test-token-not-real"
ATTACKS = windows.ATTACKS
PLACEHOLDER = re.compile(r"<CHANGE: ([^>]+)>")


def load_wec():
    """wec-sender's own package (profile and renderer), loaded by path under a private name (it also has a `src` package)."""
    if "wec_sender_src" not in sys.modules:
        spec = importlib.util.spec_from_file_location("wec_sender_src", WEC_SRC / "__init__.py",
                                                      submodule_search_locations=[str(WEC_SRC)])
        module = importlib.util.module_from_spec(spec)
        sys.modules["wec_sender_src"] = module
        keep, sys.dont_write_bytecode = sys.dont_write_bytecode, True  # never write a __pycache__ into wec-sender
        try:
            spec.loader.exec_module(module)
        finally:
            sys.dont_write_bytecode = keep
    keep, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        return importlib.import_module("wec_sender_src.profiles.windows"), importlib.import_module("wec_sender_src.winevent")
    finally:
        sys.dont_write_bytecode = keep


wec_profile, wec_winevent = load_wec()


def _normalise_now_tokens(text: str) -> str:
    """The skills write an event time as the literal `"now-310s"` (the connector resolves it); the profile's recipes keep the
    older `<CHANGE: now minus 310 s>` label form. Compare them in that one form."""
    return re.sub(r'"now-(\d+)s"', r'"<CHANGE: now minus \1 s>"', text)


def skill_block(scenario: str) -> list[dict]:
    """The events of the FIRST json block of the skill (unfilled)."""
    text = (SKILLS / f"trigger_{scenario}_alert.md").read_text()
    return json.loads(_normalise_now_tokens(re.findall(r"```json\n(.*?)\n```", text, re.S)[0]))["events"]


def fill_skill(scenario: str, values: dict[str, str]) -> list[dict]:
    """The skill's block with its `<CHANGE: label>` placeholders replaced (an independent copy of the
    profile's fill logic: the profile's own `fill` is not used here)."""
    def sub(node):
        if isinstance(node, dict):
            return {k: sub(v) for k, v in node.items()}
        if isinstance(node, list):
            return [sub(v) for v in node]
        if isinstance(node, str):
            return PLACEHOLDER.sub(lambda m: values[m.group(1)], node)
        return node

    filled = sub(skill_block(scenario))
    assert "<CHANGE" not in json.dumps(filled)
    return filled


def xml_of(events: list) -> list[str]:
    return [p.xml for p in windows_events.prepare(events, DNS)]


def build(scenario, count=None, *, now=NOW, **kw):
    kw.setdefault("seed", 7)
    count = count or windows.MIN_COUNT.get(scenario) or windows.DEFAULT_COUNT[scenario]
    return windows.build_events(scenario, count, view=active_view(), now=now, **kw)


def parse_time(text: str) -> datetime:
    return windows_events.parse_time(text)


# -- interface ----------------------------------------------------------------------------------------------------------------

def test_the_profile_is_registered_for_the_windows_cribl_destination_and_lists_its_scenarios(cfg):
    assert profiles.get("windows") is windows and profiles.for_destination("cribl_windows_events") is windows
    assert windows.CRIBL_ONLY and windows.WINDOWS_EVENTS and windows.DEFAULT_DESTINATION == "cribl_windows_events"
    assert windows.EXPECTED_DATASET == windows.EXPECTED_DATASETS[0] == "cribl_windows_events"
    assert windows.SCENARIOS == ("baseline_logons", "admin_activity", *ATTACKS) and len(ATTACKS) == 15
    assert windows.BENIGN_SCENARIOS == ("baseline_logons", "admin_activity")
    assert set(windows.MIN_COUNT) == set(ATTACKS) and set(windows.DEFAULT_COUNT) == set(windows.BENIGN_SCENARIOS)
    assert profiles.default_destination(windows, "dcsync") == "cribl_windows_events"
    assert "windows" in connector.phantom_list_destinations()["profiles"]


def test_every_attack_scenario_is_named_after_a_skill_and_has_the_skills_event_count():
    for name in ATTACKS:
        assert (SKILLS / f"trigger_{name}_alert.md").exists(), name
        assert windows.MIN_COUNT[name] == len(skill_block(name)), name
    assert {n: windows.MIN_COUNT[n] for n in ("dcsync", "weak_service_tickets", "excessive_lockouts", "multiple_account_deletions",
                                              "default_account_masquerade", "spoofed_samaccountname_tickets")} == {
        "dcsync": 5, "weak_service_tickets": 19, "excessive_lockouts": 16, "multiple_account_deletions": 6,
        "default_account_masquerade": 2, "spoofed_samaccountname_tickets": 4}


@pytest.mark.parametrize("name", ATTACKS)
def test_the_embedded_recipe_is_exactly_the_skills_first_json_block(name):
    assert windows.recipes()[name] == skill_block(name), f"windows_recipes.json drifted from trigger_{name}_alert.md: regenerate it"


def test_unknown_scenarios_and_bad_counts_are_refused():
    with pytest.raises(ValueError, match="choose one of baseline_logons, admin_activity"):
        windows.build_events("ransomware", 3, view=active_view(), now=NOW)
    for scenario in windows.SCENARIOS:
        with pytest.raises(ValueError):
            windows.build_events(scenario, 0, view=active_view(), now=NOW)


# -- the attack scenarios: parity with the skills -----------------------------------------------------------------------------

@pytest.mark.parametrize("name", ATTACKS)
@pytest.mark.parametrize("seed", [1, 2])
def test_the_rendered_xml_equals_the_filled_skill_block_for_the_same_identities(name, seed):
    values = windows.fresh_values(name, now=NOW, seed=seed)
    events = windows.build_events(name, windows.MIN_COUNT[name], view=active_view(), now=NOW, seed=seed)
    expected = xml_of(fill_skill(name, values))
    assert len(expected) == windows.MIN_COUNT[name] and xml_of(events) == expected
    # Every label of the block got a value, and the identity values really are in the events (not only in the values dict).
    assert set(values) == {label for text in [json.dumps(skill_block(name))] for label in PLACEHOLDER.findall(text)}
    blob = json.dumps(events)
    for label, value in values.items():
        assert label.startswith("now minus") or value in blob, (label, value)


@pytest.mark.parametrize("name", ATTACKS)
def test_events_are_structured_oldest_first_current_and_render_without_error(name):
    events = build(name)
    times = [parse_time(e["time"]) for e in events]
    assert times == sorted(times) and times[-1] <= NOW and times[0] >= NOW - timedelta(seconds=900)
    for e in events:
        assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", e["time"]) and "<CHANGE" not in json.dumps(e)
        assert json.loads(json.dumps(e)) == e
    assert len(windows_events.prepare(events, DNS)) == windows.MIN_COUNT[name]


def test_times_are_relative_to_the_end_of_the_window_as_the_skills_say():
    one = build("machine_account_domain_admins")
    assert one[0]["time"] == (NOW - timedelta(seconds=120)).strftime("%Y-%m-%dT%H:%M:%SZ")
    shifted = build("machine_account_domain_admins", start_offset_minutes=10)
    assert shifted[0]["time"] == (NOW - timedelta(minutes=10, seconds=120)).strftime("%Y-%m-%dT%H:%M:%SZ")
    spoof = build("spoofed_samaccountname_tickets")
    assert [(NOW - parse_time(e["time"])).total_seconds() for e in spoof] == [300, 240, 220, 150]
    assert [(e["event_id"]) for e in spoof] == [4781, 4768, 4769, 4781]
    # spread_seconds does not stretch a recipe: its timing is the skill's.
    assert build("machine_account_domain_admins", spread_seconds=3000)[0]["time"] == one[0]["time"]


# -- the attack scenarios: fresh identities -----------------------------------------------------------------------------------

def identity_values(name, **kw):
    return {k: v for k, v in windows.fresh_values(name, now=NOW, **kw).items() if not k.startswith("now minus")}


@pytest.mark.parametrize("name", ATTACKS)
def test_every_call_has_new_identities_that_no_other_call_shares(name):
    seen: set[str] = set()
    for _ in range(25):
        values = identity_values(name)                    # unseeded: no two calls may share one value
        assert len(set(values.values())) == len(values), "two labels of one call share a value"
        assert not (set(values.values()) & seen), set(values.values()) & seen
        seen |= set(values.values())
    first, second = identity_values(name, seed=1), identity_values(name, seed=2)
    assert not set(first.values()) & set(second.values())


@pytest.mark.parametrize("name", ATTACKS)
def test_no_identity_is_one_of_the_benign_directorys(name):
    d = windows.directory()
    taken = ({h.name for h in d.hosts} | {u.login for u in d.users} | {u.sid.rsplit("-", 1)[1] for u in d.users}
             | {h.sid.rsplit("-", 1)[1] for h in d.hosts} | {sid.rsplit("-", 1)[1] for _, sid in d.groups})
    for _ in range(10):
        assert not set(identity_values(name).values()) & taken


def test_identity_values_follow_each_skills_placeholder_table():
    rid = re.compile(r"\d{6,8}")
    for name in ATTACKS:
        v = identity_values(name)
        for label, value in v.items():
            if label.endswith("RID") or " RID " in label:
                assert rid.fullmatch(value) and int(value) >= 4000, (name, label)   # 3300 / 3500 / 4000 or higher in the skills
            elif label == "actor":
                assert re.fullmatch(r"svc\.run[0-9a-f]{6}" if name == "weak_service_tickets" else r"adm\.run[0-9a-f]{6}", value)
            elif label == "actor logon id":
                assert re.fullmatch(r"0x[0-9A-F]{6}", value)
            elif label == "machine":
                pattern = {"hidden_user_created": r"svcprint\d{5}", "default_account_masquerade": r"PHSRV-WEB\d{4}"}.get(name, r"PHWS-\d{5}")
                assert re.fullmatch(pattern, value) and not value.endswith("$"), (name, value)
            elif label in ("attacker host", "caller host"):
                assert re.fullmatch(r"PHWS-\d{5}", value)
            elif label in ("attacker IP", "client IP"):
                assert re.fullmatch(r"10\.20\.1\d\d\.\d{2,3}", value)
            elif label == "member display name":
                assert re.fullmatch(r"Run Member \d{5}", value)
            elif label.startswith(("lockout user", "repeat lockout user")):
                assert re.fullmatch(r"l\.(u|rpt)[0-9a-f]{6}", value)
            elif label.startswith("deleted user"):
                assert re.fullmatch(r"tmp\.sw[0-9a-f]{6}", value)
            else:
                raise AssertionError(f"{name}: unchecked label {label!r}")


def test_a_label_has_one_value_everywhere_it_appears_and_the_distinct_counts_the_detectors_need_hold():
    lock = build("excessive_lockouts")
    users = [e["event_data"]["TargetUserName"] for e in lock]
    assert len(users) == 16 and len(set(users)) == 11 and max(users.count(u) for u in set(users)) == 6   # ten once, one six times
    assert len({e["event_data"]["TargetSid"] for e in lock}) == 11
    assert len({e["event_data"]["TargetDomainName"] for e in lock}) == 1        # one new caller host in every event
    dele = build("multiple_account_deletions")
    assert len({e["event_data"]["TargetUserName"] for e in dele}) == 6 and len({e["event_data"]["TargetSid"] for e in dele}) == 6
    assert len({e["event_data"]["SubjectUserName"] for e in dele}) == 1
    weak = build("weak_service_tickets")
    assert len({e["event_data"]["ServiceName"] for e in weak}) == 19 and len({e["event_data"]["TargetUserName"] for e in weak}) == 1
    assert all(e["event_data"]["TicketEncryptionType"] == "0x17" for e in weak)
    spoof = build("spoofed_samaccountname_tickets")
    assert len({e["computer"] for e in spoof}) == 1 and spoof[0]["computer"].startswith("PHDC")
    rid = windows.fresh_values("spoofed_samaccountname_tickets", now=NOW, seed=7)["actor RID"]
    assert spoof[0]["computer"] == f"PHDC{rid}"                                 # the DC is named after the actor RID, as the skill says
    dcs = build("dcsync")
    assert [e["event_id"] for e in dcs] == [4624, 4662, 4662, 4662, 4662] and not dcs[1]["event_data"]["SubjectUserName"].endswith("$")
    masq = build("default_account_masquerade")
    assert {e["computer"] for e in masq} == {e["event_data"]["TargetDomainName"] for e in masq} and len({e["computer"] for e in masq}) == 1
    assert [e["event_data"]["TargetUserName"] for e in masq] == ["DefaultAccount", "Guest"]
    hidden = build("hidden_user_created")[0]["event_data"]
    assert hidden["TargetUserName"].endswith("$") and hidden["TargetUserName"] == hidden["SamAccountName"]
    sam = build("samaccountname_change")[0]["event_data"]
    assert sam["OldTargetUserName"] == sam["NewTargetUserName"] + "$"
    cert = build("privileged_certificate_request")[0]["event_data"]
    assert cert["Attributes"].startswith("CertificateTemplate:DomainController") and cert["Requester"].startswith("PHANTOM\\PHWS-")
    assert build("privileged_certificate_request")[0]["computer"] == CA_NAME


def test_a_larger_count_is_a_whole_number_of_recipes_each_with_its_own_identities():
    events = windows.build_events("machine_account_domain_admins", 3, view=active_view(), now=NOW)
    assert len(events) == 3 and len({e["event_data"]["SubjectUserName"] for e in events}) == 3
    assert len({e["event_data"]["MemberName"] for e in events}) == 3
    five = windows.build_events("dcsync", 10, view=active_view(), now=NOW)
    assert len(five) == 10 and len({e["event_data"]["SubjectUserName"] for e in five if e["event_id"] == 4662}) == 2
    with pytest.raises(ValueError, match="multiple of 5"):
        windows.build_events("dcsync", 7, view=active_view(), now=NOW)
    seeded = windows.build_events("dcsync", 10, view=active_view(), now=NOW, seed=4)
    assert seeded == windows.build_events("dcsync", 10, view=active_view(), now=NOW, seed=4)


def test_target_user_names_the_acting_account_and_source_ip_the_attacking_host():
    for given in ("m.mallory", "DOMAIN\\m.mallory", "m.mallory@phantom.lab"):
        events = build("shadow_credentials", target_user=given)
        assert events[0]["event_data"]["SubjectUserName"] == "m.mallory" and "m.mallory" in events[0]["rendering"]["message"]
    for name, field in (("dcsync", "IpAddress"), ("weak_service_tickets", "IpAddress"), ("spoofed_samaccountname_tickets", "IpAddress")):
        events = build(name, source_ip="10.20.77.7")
        assert any("10.20.77.7" in str(e["event_data"].get(field)) for e in events), name
    for bad in ("evil$", "x" * 21, "a b", "<x>", "..", "-lead"):
        with pytest.raises(ValueError, match="target_user"):
            build("dcsync", target_user=bad)
    for bad in ("not-an-ip", "::1", "999.1.1.1"):
        with pytest.raises(ValueError, match="source_ip"):
            build("dcsync", source_ip=bad)
    # The attack scenarios act as a NEW account: an organization account (by login or as DOMAIN\\login / login@domain) is refused,
    # with the accounts in use listed, and so is nothing else. A scenario with no acting account does not look at the name.
    for given in ("kalotaibi", "PHANTOM\\kalotaibi", "kalotaibi@phantom.lab", "adm.ialkhalifa", "svc-sql", "adm.breakglass"):
        with pytest.raises(ValueError, match=r"is an account of organization 'phantom-lab'.*NEW account.*Accounts in use: nalharbi"):
            build("dcsync", target_user=given)
    assert build("excessive_lockouts", target_user="kalotaibi") == build("excessive_lockouts")
    assert build("privileged_certificate_request", target_user="kalotaibi") == build("privileged_certificate_request")
    # No acting account in the certificate recipe, and the baseline ignores both.
    assert build("privileged_certificate_request", target_user="x.y")[0]["event_data"]["Requester"].startswith("PHANTOM\\PHWS-")
    assert build("baseline_logons", target_user="x.y", source_ip="10.1.1.1") == build("baseline_logons")


def test_the_tool_refuses_an_organization_account_as_the_acting_account(cfg):
    refused = connector.phantom_generate_events("windows", "dcsync", target_user="kalotaibi", dry_run=True)
    assert refused["ok"] is False and "NEW account" in refused["error"] and "kalotaibi" in refused["error"]
    accepted = connector.phantom_generate_events("windows", "dcsync", target_user="adm.run1", dry_run=True)
    assert accepted["ok"] and accepted["actors"] == ["adm.run1"]


def test_the_scenarios_are_reproducible_with_a_seed():
    for name in ATTACKS:
        assert build(name, seed=3) == build(name, seed=3) and build(name, seed=3) != build(name, seed=4)


# -- baseline_logons: a port of wec-sender's ---------------------------------------------------------------------------------

def test_the_directory_is_wec_senders_directory():
    mine, theirs = windows.directory(), wec_profile.directory()
    assert [(h.name, h.fqdn, h.ip, h.role, h.sid, h.lsass_pid) for h in mine.hosts] == [
        (h.name, h.fqdn, h.ip, h.role, h.sid, h.lsass_pid) for h in theirs.hosts]
    assert [(u.login, u.display, u.sid, u.role, u.home) for u in mine.users] == [
        (u.login, u.display, u.sid, u.role, u.home) for u in theirs.users]
    assert (mine.netbios, mine.dns) == (theirs.netbios, theirs.dns)
    assert len(mine.staff) > 22 and len(mine.workstations) == 50 and len(mine.admins) >= 4


@pytest.mark.parametrize("now", [NOW, NIGHT], ids=["business-hours", "night"])
@pytest.mark.parametrize("count,spread,offset", [(1, 120, 0), (2, 120, 0), (3, 90, 0), (10, 300, 0), (41, 3600, 0), (30, 900, 30)])
@pytest.mark.parametrize("seed", [1, 2, 3])
def test_baseline_logons_render_to_the_same_xml_as_wec_senders_for_the_same_seed(now, count, spread, offset, seed):
    mine = windows.build_events("baseline_logons", count, view=active_view(), now=now, spread_seconds=spread, start_offset_minutes=offset, seed=seed)
    theirs = wec_profile.build_events("baseline_logons", count, directory=wec_profile.directory(), now=now,
                                      spread_seconds=spread, start_offset_minutes=offset, seed=seed)
    assert len(mine) == count
    assert xml_of(mine) == [r.xml for r in wec_winevent.render_all(theirs)]


def test_baseline_logons_are_whole_sessions_of_directory_users_inside_the_window():
    d = windows.directory()
    events = build("baseline_logons", 120, spread_seconds=1800, seed=None)
    assert len(events) == 120
    times = [parse_time(e["time"]) for e in events]
    assert times == sorted(times) and times[-1] <= NOW and times[0] >= NOW - timedelta(seconds=1800)
    logins = {u.login: u for u in d.users}
    opened: dict[tuple, dict] = {}
    for e in events:
        data = e["event_data"]
        assert e["event_id"] in (4624, 4672, 4634) and e["computer"].split(".")[0] in {h.name for h in d.hosts}
        who = data.get("TargetUserName") or data["SubjectUserName"]
        if e["event_id"] == 4624:
            assert who in logins and data["TargetUserSid"] == logins[who].sid
            opened[(e["computer"], data["TargetLogonId"])] = data
        elif e["event_id"] == 4672:
            assert logins[data["SubjectUserName"]].role == "admin" and (e["computer"], data["SubjectLogonId"]) in opened
        else:
            assert (e["computer"], data["TargetLogonId"]) in opened and data["TargetUserName"] == opened[(e["computer"], data["TargetLogonId"])]["TargetUserName"]
    assert any(e["event_id"] == 4672 for e in build("baseline_logons", 400, spread_seconds=3600, seed=2))


def test_baseline_identities_are_the_same_on_every_call():
    def who(events):
        return {(e["event_data"]["TargetUserName"], e["event_data"]["TargetUserSid"]) for e in events if e["event_id"] == 4624}
    first, second = who(build("baseline_logons", 2000, spread_seconds=3600, seed=None)), who(build("baseline_logons", 2000, spread_seconds=3600, seed=None))
    pool = {(u.login, u.sid) for u in windows.directory().users}
    assert first <= pool and second <= pool and len(first & second) == len(pool)
    # No fresh attack identity ever appears in the baseline.
    assert not {login for login, _ in first} & {v for v in identity_values("dcsync").values()}


# -- admin_activity -------------------------------------------------------------------------------------------------------------

PRIVILEGED = {"Domain Admins", "Enterprise Admins", "Schema Admins", "Administrators", "Account Operators", "Backup Operators",
              "Server Operators", "Print Operators", "Helpdesk Admins", "SMS Admins", "Group Policy Creator Owners", "Domain Controllers"}


def test_admin_activity_is_ordinary_administration_by_the_it_administrators_on_the_domain_controllers():
    d = windows.directory()
    events = build("admin_activity", 300, spread_seconds=3600, seed=None)
    assert len(events) == 300
    admins = {u.login: u for u in d.admins}
    staff = {u.login: u for u in d.staff}
    dcs = {h.name for h in d.dcs}
    assert {e["event_id"] for e in events} == {4720, 4724, 4728, 4729, 4738, 4767}
    groups = {name for name, _ in d.groups}
    for e in events:
        data = e["event_data"]
        assert e["computer"] in dcs and data["SubjectUserName"] in admins and data["SubjectUserSid"] == admins[data["SubjectUserName"]].sid
        assert not data["SubjectUserName"].endswith("$") and data["SubjectDomainName"] == "PHANTOM"
        assert e["provider"] == windows.PROVIDER and e["rendering"]["message"] and e["rendering"]["task"]
        assert data["SubjectUserName"] in e["rendering"]["message"] and "<" not in e["rendering"]["message"] and "{" not in e["rendering"]["message"]
        if e["event_id"] in (4724, 4767, 4738):
            assert data["TargetUserName"] in staff and data["TargetSid"] == staff[data["TargetUserName"]].sid   # an ordinary user
        if e["event_id"] in (4728, 4729):
            assert data["TargetUserName"] in groups and data["TargetUserName"] not in PRIVILEGED
            assert data["TargetSid"] in {sid for _, sid in d.groups}
            assert data["MemberSid"] in {u.sid for u in staff.values()}
        if e["event_id"] == 4720:
            login = data["TargetUserName"]
            assert not login.endswith("$") and login not in ("guest", "defaultaccount", "administrator") and login not in staff
            assert data["SamAccountName"] == login and data["UserPrincipalName"] == f"{login}@phantom.lab" and data["DisplayName"] != "-"
            assert data["TargetSid"].startswith(d.domain_sid + "-") and "$" not in data["TargetSid"]
        if e["event_id"] == 4738:
            assert data["AllowedToDelegateTo"] == "-" and data["OldUacValue"] == "-" and data["NewUacValue"] == "-"
    # Resets and unlocks are the helpdesk's (the first half of the administrators); account creation and groups are the
    # directory team's (the other half).
    half = len(d.admins) // 2
    helpdesk = {u.login for u in d.admins[:half]}
    assert {e["event_data"]["SubjectUserName"] for e in events if e["event_id"] in (4724, 4767)} <= helpdesk
    assert {e["event_data"]["SubjectUserName"] for e in events if e["event_id"] in (4720, 4728, 4729)} <= {u.login for u in d.admins[half:]}
    assert {e["event_data"]["SubjectUserName"] for e in events if e["event_id"] in (4724, 4767, 4720, 4728, 4729)} == {u.login for u in d.admins}
    assert len(windows_events.prepare(events, DNS)) == 300


def test_admin_activity_times_and_stable_identities():
    events = build("admin_activity", 80, spread_seconds=600, seed=None)
    times = [parse_time(e["time"]) for e in events]
    assert times == sorted(times) and times[-1] <= NOW and times[0] >= NOW - timedelta(seconds=600)
    again = build("admin_activity", 80, spread_seconds=600, seed=None)
    assert {e["event_data"]["SubjectUserName"] for e in events} == {e["event_data"]["SubjectUserName"] for e in again}
    # An administrator's logon id is one value per (domain controller, UTC day): a long session, the same on every call.
    ids = {}
    for e in events + again:
        ids.setdefault((e["computer"], e["event_data"]["SubjectUserName"]), set()).add(e["event_data"]["SubjectLogonId"])
    assert all(len(v) == 1 for v in ids.values())
    # No fresh attack identity appears here either.
    assert not {e["event_data"]["SubjectUserName"] for e in events} & set(identity_values("privileged_group_add").values())


def test_admin_activity_has_no_event_a_detector_skill_fires_on():
    attack_shapes = set()
    for name in ATTACKS:
        for e in windows.recipes()[name]:
            attack_shapes.add((e["event_id"], e["event_data"].get("TargetUserName", "").split("<")[0], e["event_data"].get("AllowedToDelegateTo")))
    for e in build("admin_activity", 400, spread_seconds=3600, seed=None):
        data = e["event_data"]
        assert data.get("TargetUserName") not in ("Domain Admins", "Guest", "DefaultAccount", "SMS Admins", "krbtgt")
        assert data.get("AllowedToDelegateTo", "-") == "-" and "msDS-KeyCredentialLink" not in json.dumps(e)
        assert e["event_id"] not in (4722, 4726, 4732, 4740, 4781, 4662, 4768, 4769, 5136, 4887)


# -- through the tool -----------------------------------------------------------------------------------------------------------

@pytest.fixture
def cfg(monkeypatch):
    values = {"url": "https://api-tenant.example.test/logs/v1/event", "key": "k", "vendor": "Okta", "product": "SSO", "extra": "",
              "extra_keys": "", "domain": "lab.test", "verify_tls": True, "timeout": 5.0, "cribl_url": URL, "cribl_token": TOKEN,
              "cribl_integration": "wave-7"}
    monkeypatch.setattr(connector, "_settings", lambda: dict(values))
    return values


@pytest.fixture
def wire(cfg, monkeypatch):
    seen: list[httpx.Request] = []

    def handler(request):
        seen.append(request)
        lines = [x for x in request.content.decode().split("\n") if x]
        return httpx.Response(200, json={"num_records": len(lines), "success": "true"})

    real = cribl.post
    monkeypatch.setattr(connector.cribl, "post", lambda *a, **k: real(*a, transport=httpx.MockTransport(handler), **k))
    return seen


def lines_of(seen) -> list:
    return [json.loads(x)["data"] for r in seen for x in r.content.decode().split("\n") if x]


@pytest.mark.parametrize("scenario", windows.SCENARIOS)
def test_the_tool_sends_every_scenario_to_the_windows_destination_as_plain_xml_strings(scenario, wire):
    result = connector.phantom_generate_events("windows", scenario)
    expected = windows.MIN_COUNT.get(scenario) or windows.DEFAULT_COUNT[scenario]
    assert result["ok"], result
    assert result["sent"] == expected and result["events"] == expected and result["destination"] == "cribl_windows_events"
    assert result["dataset"] == "microsoft_windows_raw" and result["profile"] == "windows" and result["scenario"] == scenario
    assert "warning" not in result and result["actors"] and result["first_time"] <= result["last_time"]
    assert len(result["sample_ids"]) == min(5, expected) and result["num_records"] == expected
    posted = lines_of(wire)
    assert len(posted) == expected and all(isinstance(x, str) and x.startswith("<Event xmlns=") for x in posted)
    assert wire[0].headers["Source-Identifier"] == cribl.SOURCES["windows_events"].uuid
    assert all("<CHANGE" not in x for x in posted)


def test_default_counts(wire):
    assert connector.phantom_generate_events("windows", "baseline_logons")["sent"] == 30
    assert connector.phantom_generate_events("windows", "admin_activity")["sent"] == 10
    assert connector.phantom_generate_events("windows", "dcsync")["sent"] == 5
    assert connector.phantom_generate_events("windows", "dcsync", count=10)["sent"] == 10
    below = connector.phantom_generate_events("windows", "dcsync", count=4)
    assert below["ok"] and below["sent"] == 5 and below["count_raised"] == {"asked": 4, "used": 5, "why": "dcsync needs at least 5 event(s) to form its pattern"}
    odd = connector.phantom_generate_events("windows", "dcsync", count=7)
    assert not odd["ok"] and "multiple of 5" in odd["error"]
    n = len(wire)
    assert not connector.phantom_generate_events("windows", "no_such")["ok"] and len(wire) == n


def test_the_rows_reach_cortex_as_the_rendering_of_what_dry_run_shows(wire):
    dry = connector.phantom_generate_events("windows", "shadow_credentials", dry_run=True)
    assert dry["ok"] and dry["dry_run"] and dry["sent"] == 0 and wire == [] and dry["events"][0]["event_id"] == 5136
    assert dry["actors"] == [dry["events"][0]["event_data"]["SubjectUserName"]] and dry["destination"] == "cribl_windows_events"
    assert json.loads(json.dumps(dry["events"])) == dry["events"]


@pytest.mark.parametrize("scenario", windows.SCENARIOS)
def test_dry_run_of_every_scenario_sends_nothing_and_returns_renderable_events(scenario, wire):
    dry = connector.phantom_generate_events("windows", scenario, dry_run=True)
    assert dry["ok"] and dry["dry_run"] and dry["sent"] == 0 and wire == [] and 1 <= len(dry["events"]) <= 3
    assert windows_events.prepare(dry["events"], DNS) and json.loads(json.dumps(dry["events"])) == dry["events"]


def test_dry_run_sends_nothing_and_needs_no_cribl_while_a_real_send_refuses_without_it(cfg, monkeypatch):
    sent = []
    monkeypatch.setattr(connector.cribl, "post", lambda *a, **k: sent.append(a))
    monkeypatch.setattr(connector.collector, "post_events", lambda *a, **k: sent.append(a))
    cfg.update(cribl_url="", cribl_token="")
    dry = connector.phantom_generate_events("windows", "baseline_logons", dry_run=True)
    assert dry["ok"] and dry["destination"] == "cribl_windows_events" and dry["dataset"] == "microsoft_windows_raw" and len(dry["events"]) == 3
    refused = connector.phantom_generate_events("windows", "baseline_logons")
    assert not refused["ok"] and "cribl_windows_events" in refused["error"] and "not configured" in refused["error"]
    assert sent == []


def test_another_destination_is_refused_with_a_clear_error_and_nothing_is_sent(cfg, wire, monkeypatch):
    http = []
    monkeypatch.setattr(connector.collector, "post_events", lambda *a, **k: http.append(a))
    for destination in ("okta_sso", "cribl_aws_audit"):
        for dry_run in (False, True):
            result = connector.phantom_generate_events("windows", "dcsync", destination=destination, dry_run=dry_run)
            assert not result["ok"] and "cribl_windows_events" in result["error"] and "Windows" in result["error"]
    assert wire == [] and http == []
    explicit = connector.phantom_generate_events("windows", "dcsync", destination="cribl_windows_events")
    assert explicit["ok"] and explicit["sent"] == 5


def test_send_test_event_refuses_the_windows_profile_for_any_destination(wire):
    for destination in (None, "okta_sso", "cribl_aws_audit"):
        result = connector.phantom_send_test_event(destination, "windows")
        assert not result["ok"] and "cribl_windows_events" in result["error"]
    assert wire == []
    assert connector.phantom_send_test_event("cribl_windows_events")["ok"]   # the existing Windows test event is unchanged


def test_other_profiles_are_untouched_by_the_windows_hooks(wire):
    result = connector.phantom_generate_events("aws_cloudtrail", "guardduty_detector_deleted")
    assert result["ok"] and result["sent"] == 1 and "actors" not in result and len(result["sample_ids"]) == 1


def test_two_scheduled_calls_use_different_actors_but_the_same_baseline_users(wire):
    one = connector.phantom_generate_events("windows", "privileged_group_add")
    two = connector.phantom_generate_events("windows", "privileged_group_add")
    assert one["ok"] and two["ok"] and not set(one["actors"]) & set(two["actors"])
    a = connector.phantom_generate_events("windows", "baseline_logons", count=60, spread_seconds=3600)
    b = connector.phantom_generate_events("windows", "baseline_logons", count=60, spread_seconds=3600)
    assert a["ok"] and b["ok"] and set(a["actors"]) | set(b["actors"]) <= {u.login for u in windows.directory().users} | {
        h.account for h in windows.directory().hosts}


def test_the_tool_documentation_names_every_new_scenario():
    import yaml

    spec = yaml.safe_load((HERE.parent / "connector.yaml").read_text())
    tools = {t["name"]: t for t in spec["spec"]["tools"]}
    scenario_arg = next(a for a in tools["generate_events"]["args"] if a["name"] == "scenario")["description"]
    docs = [connector.phantom_generate_events.__doc__, tools["generate_events"]["description"], scenario_arg]
    names = list(ATTACKS) + list(windows.BENIGN_SCENARIOS) + ["benign_activity"]
    for text in docs:
        for name in names:
            assert name in text, (name, text[:60])
    for text in docs[:2]:
        assert "windows" in text
