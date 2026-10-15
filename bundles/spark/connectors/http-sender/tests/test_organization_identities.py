"""The six non-Windows profiles take every identity from the active organization (`view`), at call time, and from nowhere else.

Covers: who `target_user` may name, that only organization people (no leaver) appear in the baselines, that the domain, partner
domain, AWS account, GCP project, regions and egress addresses are the organization's (a different organization changes them
all), what happens when the organization lacks something, the connector's `organization` pin and its error path, and that no
source file of these profiles still carries a literal of the old rosters. The byte-for-byte comparison with the pre-organization
outputs is `test_pre_organization_equivalence.py`.

Run from the connector directory:  python3 -m pytest -x
"""
from __future__ import annotations

import copy
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runtime import organization_view as ov  # noqa: E402
from runtime.organization_reader import OrganizationUnavailable  # noqa: E402
from runtime.organization_view import OrganizationView, get_view  # noqa: E402
from src import connector, profiles  # noqa: E402
from src.profiles import _org, ippools  # noqa: E402

NOW = datetime(2026, 10, 4, 12, 0, 0, tzinfo=timezone.utc)
SIX = ("okta", "proofpoint_tap", "google_workspace", "aws_cloudtrail", "azure_ad_audit", "gcp_audit")
SRC = Path(__file__).resolve().parents[1] / "src"


def mod(name):
    return profiles.PROFILES[name]


def count_for(m, scenario):
    return max(getattr(m, "MIN_COUNT", {}).get(scenario, 0) or getattr(m, "DEFAULT_COUNT", {}).get(scenario, 0) or 12, 2)


def build(name, scenario, view=None, **kw):
    m = mod(name)
    kw.setdefault("seed", 4)
    return m.build_events(scenario, kw.pop("count", count_for(m, scenario)), view=view or get_view(), now=NOW, **kw)


ALL = [(name, scenario) for name in SIX for scenario in mod(name).SCENARIOS]
IDS = [f"{n}.{s}" for n, s in ALL]


def leaver():
    (person,) = [p for p in get_view().people if _org.is_leaver(p)]
    return person


def custom_doc():
    """A second organization that shares nothing with Phantom Lab: other domain, people, addresses and cloud accounts."""
    doc = copy.deepcopy(get_view().doc)
    doc["id"], doc["name"] = "northwind-test", "Northwind test organization"
    doc["domain"].update(dns="northwind.test", email_domain="northwind.test", partner_domain="supplier.test")
    for i, person in enumerate(doc["people"]):
        local = f"u{i}.person{i}"
        person.update(email=f"{local}@northwind.test", okta_id="00u" + f"{i:017d}", login=f"user{i}",
                      given_name=f"G{i}", family_name=f"F{i}", display_name=f"G{i} F{i}")
        person.pop("home_ip", None) if i % 5 == 4 else person.update(home_ip=ippools.home_for(30 + i)[0])
    doc["cloud"] = {"aws": {"account_id": "100200300400", "region": "eu-west-9"},
                    "azure": {"tenant_id": "11111111-2222-4333-8444-555555555555"},
                    "gcp": {"project_id": "northwind-prod", "project_number": "999", "region": "europe-test1"}}
    doc["egress"] = {"ruh_nat": "198.51.100.1", "nat": {"x": "198.51.100.2"}, "dmz_public": {"y": "198.51.100.3"}}
    return doc


# -- every scenario builds on the default organization ----------------------------------------------------------------------

@pytest.mark.parametrize("name,scenario", ALL, ids=IDS)
def test_every_scenario_builds_on_the_default_organization_with_and_without_a_target(name, scenario):
    m = mod(name)
    plain = build(name, scenario)
    named = build(name, scenario, target_user="khalid.alotaibi")
    assert plain and named and len(plain) == len(named) == count_for(m, scenario)
    assert json.loads(json.dumps(plain)) == plain


# -- target_user ---------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("spelling", ["kalotaibi", "KALOTAIBI", "khalid.alotaibi", "Khalid.Alotaibi", "khalid.alotaibi@phantom.lab",
                                      "PHANTOM\\kalotaibi", "phantom\\Khalid.Alotaibi", " kalotaibi "])
def test_target_user_resolves_a_login_an_email_or_its_local_part_to_the_person(spelling):
    assert _org.resolve(get_view(), spelling)["login"] == "kalotaibi"


def test_an_admin_login_resolves_to_the_person_and_a_leaver_can_be_named():
    assert _org.resolve(get_view(), "adm.ialkhalifa")["login"] == "ialkhalifa"
    assert _org.resolve(get_view(), leaver()["email"])["login"] == leaver()["login"]  # an attack on a disabled account is legitimate


@pytest.mark.parametrize("name,scenario", [(n, s) for n, s in ALL if s in (
    "failed_then_success", "mfa_fatigue", "tor_signin", "phishing_url", "click_chain", "public_share", "sensitive_download",
    "impossible_travel_login", "tor_api_call", "guardduty_detector_deleted", "data_asset_public", "ca_policy_deleted")])
def test_an_unknown_target_user_is_an_error_that_lists_the_valid_choices(name, scenario):
    with pytest.raises(_org.UnknownUser) as err:
        build(name, scenario, target_user="mallory.nobody")
    assert isinstance(err.value, ValueError)
    message = str(err.value)
    assert "mallory.nobody" in message and get_view().name in message
    assert all(p["email"] in message for p in get_view().people[:5])


def test_a_long_list_of_choices_is_cut_and_says_how_many_more():
    doc = custom_doc()
    doc["people"] += [{**copy.deepcopy(doc["people"][0]), "login": f"x{i}", "email": f"x{i}@northwind.test"} for i in range(30)]
    with pytest.raises(_org.UnknownUser, match=r"and 20 more"):
        _org.resolve(OrganizationView(doc), "nobody")


# -- only the organization's identities --------------------------------------------------------------------------------------

def emails_in(events):
    return set(re.findall(r"[\w.+-]+@[\w.-]+", json.dumps(events)))


def test_okta_baseline_users_are_exactly_the_people_who_may_log_on():
    view = get_view()
    people = {p["email"]: p for p in _org.logon_people(view)}
    events = build("okta", "benign_logins", count=2 * len(people) + 20)
    assert {e["actor"]["alternateId"] for e in events} == set(people)
    for e in events:
        person = people[e["actor"]["alternateId"]]
        assert e["actor"]["id"] == person["okta_id"] and e["client"]["ipAddress"] == person["home_ip"]
        assert e["actor"]["displayName"] == person["display_name"]
    assert leaver()["email"] not in emails_in(events)


def test_no_baseline_ever_names_the_leaver_or_the_leavers_address_or_id():
    gone = leaver()
    for name, scenario in ALL:
        if scenario not in (set(getattr(mod(name), "BENIGN_SCENARIOS", ())) | {"benign_logins", "benign_mail", "benign_drive"}):
            continue
        text = json.dumps(build(name, scenario, count=2000))
        for needle in (gone["email"], gone["okta_id"], gone["home_ip"], gone["login"], _org.local_part(gone)):
            assert needle not in text, (name, needle)


def test_okta_password_spray_over_more_users_than_the_organization_has_repeats_its_people():
    people = _org.logon_people(get_view())
    events = build("okta", "password_spray", count=len(people) + 5)
    users = [e["actor"]["alternateId"] for e in events]
    assert set(users) == {p["email"] for p in people} and users[:5] == users[len(people):]


def test_okta_fastpass_phishing_mints_users_on_the_organizations_domain():
    events = build("okta", "fastpass_phishing", count=4)
    assert all(e["actor"]["alternateId"].endswith("@" + get_view().email_domain) for e in events)
    assert emails_in(events) .isdisjoint({p["email"] for p in get_view().people})  # fresh actors, not people


def test_proofpoint_baseline_recipients_and_clicks_are_the_organizations():
    people = {p["email"]: p for p in _org.logon_people(get_view())}
    events = build("proofpoint_tap", "benign_mail", count=60)
    assert {r for e in events for r in e["recipient"] + e["ccAddresses"]} <= set(people)
    clicks = build("proofpoint_tap", "click_chain", count=30)
    by_email = {p["email"]: p for p in get_view().people}
    assert all(e["clickIP"] == by_email[e["recipient"]]["home_ip"] for e in clicks if "clickIP" in e)


def test_google_workspace_actors_owners_and_addresses_are_the_organizations_and_the_share_goes_to_its_partner():
    view = get_view()
    people = {p["email"]: p for p in _org.logon_people(view)}
    events = build("google_workspace", "benign_drive", count=2 * len(people))
    assert {e["actor"]["email"] for e in events} <= set(people)
    for e in events:
        assert e["ipAddress"] == people[e["actor"]["email"]]["home_ip"] and e["ownerDomain"] == view.email_domain
        owner = next(p["value"] for p in e["events"][0]["parameters"] if p["name"] == "owner")
        assert owner in people
    shares = [p["value"] for e in events for p in e["events"][0]["parameters"] if p["name"] == "target_user"]
    assert shares and all(s.endswith("@" + view.partner_domain) for s in shares)


def test_cloud_baselines_use_only_the_people_with_that_clouds_access():
    view = get_view()
    cloud = view.doc["cloud"]
    aws = build("aws_cloudtrail", "benign_activity", count=800, seed=1)
    assert {e["userIdentity"]["userName"] for e in aws if e["userIdentity"]["type"] == "IAMUser"} <= {
        _org.local_part(p) for p in _org.cloud_people(view, "aws")}
    assert {e["recipientAccountId"] for e in aws} == {cloud["aws"]["account_id"]}
    gcp = build("gcp_audit", "benign_activity", count=800, seed=1)
    users = {e["protoPayload"]["authenticationInfo"]["principalEmail"] for e in gcp}
    assert {u for u in users if "gserviceaccount" not in u} <= {p["email"] for p in _org.cloud_people(view, "gcp")}
    assert {e["resource"]["labels"]["project_id"] for e in gcp} == {cloud["gcp"]["project_id"]}
    egress = set(_org.egress(view))
    sa_ips = {e["protoPayload"]["requestMetadata"]["callerIp"] for e in gcp if "gserviceaccount" in e["protoPayload"]["authenticationInfo"]["principalEmail"]}
    assert sa_ips and sa_ips <= egress  # service accounts call from the organization's public addresses
    azure = build("azure_ad_audit", "benign_activity", count=800, seed=1)
    admins = {f"{_org.local_part(p)}.adm@{view.email_domain}" for p in _org.administrators(_org.cloud_people(view, "azure"))}
    actors = {e["initiatedBy"]["user"]["userPrincipalName"] for e in azure}
    assert actors <= admins | {p["email"] for p in _org.cloud_people(view, "azure")}
    assert actors & admins


def test_the_azure_manager_change_names_the_users_manager_in_the_organization():
    view = get_view()
    events = [e for e in build("azure_ad_audit", "benign_activity", count=3000, seed=2) if e["activityDisplayName"] == "Update user"]
    managers = [m for e in events for r in e["targetResources"] for m in r["modifiedProperties"] if m["displayName"] == "Manager"]
    assert managers
    names = {p["display_name"] for p in view.people}
    assert all(json.loads(m["newValue"]) in names for m in managers)


# -- nothing is hard-coded: another organization changes every identity ---------------------------------------------------------

# The names a recipe mints for an actor the organization has never seen are not the organization's and are not a leak: a fresh
# handle (`<first>.<last>.<6 hex>`, `_fresh.handle`) and an Azure new hire (`azure_ad_audit._NEW_HIRES`). Both are drawn from
# name lists of their own, so they are cut out before the scan.
FRESH_ACTORS = re.compile(r"\b(?:[a-z]+\.){2}[0-9a-f]{6}\b|\b(?:hanan|salman|mona|rakan|aisha|badr)\.al[a-z]+@northwind\.test")
OLD_ORGANIZATION = ["phantom.lab", "external-partner.example", "lab.test", "phantom-lab-prod", "481516234201", "704382915306",
                    "me-central", "noura", "alharbi", "alotaibi", "khalid", "00ujHfeOQz"]


@pytest.mark.parametrize("name,scenario", ALL, ids=IDS)
def test_another_organization_changes_every_identity_and_leaves_no_trace_of_phantom_lab(name, scenario):
    view = OrganizationView(custom_doc())
    for seed in range(12):  # fresh handles are drawn from a name list: no seed may let a Phantom Lab name through
        events = build(name, scenario, view=view, seed=seed,
                       count=60 if scenario.startswith("benign") else count_for(mod(name), scenario))
        text = FRESH_ACTORS.sub("<fresh>", json.dumps(events))
        for old in OLD_ORGANIZATION:
            assert old not in text, f"{old!r} leaked into {name}.{scenario} (seed {seed})"


def test_another_organizations_domain_partner_account_project_and_region_reach_the_events():
    view = OrganizationView(custom_doc())
    okta = build("okta", "benign_logins", view=view, count=10)
    assert {e["actor"]["alternateId"] for e in okta} <= {p["email"] for p in view.people}
    drive = build("google_workspace", "benign_drive", view=view, count=40)
    assert {e["ownerDomain"] for e in drive} == {"northwind.test"}
    assert any(p["value"].endswith("@supplier.test") for e in drive for p in e["events"][0]["parameters"] if p["name"] == "target_user")
    aws = build("aws_cloudtrail", "s3_public_exposure", view=view, count=3)
    assert {e["recipientAccountId"] for e in aws} == {"100200300400"} and {e["awsRegion"] for e in aws} == {"eu-west-9"}
    assert "s3.eu-west-9.amazonaws.com" in json.dumps(aws) and "northwind-test-" not in json.dumps(aws)  # attack buckets are not the baseline's
    gcp = build("gcp_audit", "data_asset_public", view=view, count=1)
    assert gcp[0]["resource"]["labels"]["project_id"] == "northwind-prod" and gcp[0]["resource"]["labels"]["location"] == "europe-test1"
    assert "northwind-test-public-" in json.dumps(gcp)  # the bucket prefix is the organization's id
    mail = build("proofpoint_tap", "bec_impostor", view=view, count=2)
    assert all(e["sender"].endswith("@northwind-secure.example") for e in mail)  # the lookalike of the organization's domain


def test_a_person_without_a_home_address_gets_a_stable_derived_one_in_every_profile():
    doc = custom_doc()
    person = doc["people"][4]
    assert "home_ip" not in person
    view = OrganizationView(doc)
    expected = ippools.home_of(person)[0]
    okta = build("okta", "benign_logins", view=view, count=2 * len(_org.logon_people(view)))
    assert {e["client"]["ipAddress"] for e in okta if e["actor"]["alternateId"] == person["email"]} == {expected}
    drive = build("google_workspace", "benign_drive", view=view, count=2 * len(_org.logon_people(view)))
    assert {e["ipAddress"] for e in drive if e["actor"]["email"] == person["email"]} == {expected}


def test_the_locale_of_the_organization_does_not_move_a_single_timestamp():
    # None of these profiles shapes traffic by working hours: their windows end at `now`. If one ever does, it must read the
    # view's locale (utc_offset_hours, workweek, work hours), and this test is the place to prove it.
    other = custom_doc()
    other["locale"] = {"timezone": "Pacific/Auckland", "utc_offset_hours": 12, "workweek": ["tue"], "work_hours": {"start": "01:00", "end": "02:00"}}
    for name, scenario in ALL:
        a = build(name, scenario, count=8)
        b = build(name, scenario, view=OrganizationView(other), count=8)
        field = mod(name).TIME_FIELD
        assert [connector._field(e, field) for e in a] == [connector._field(e, field) for e in b], (name, scenario)


# -- an organization that lacks something is a broken install -----------------------------------------------------------------

def broken(edit):
    doc = copy.deepcopy(get_view().doc)
    edit(doc)
    return OrganizationView(doc)


@pytest.mark.parametrize("edit,name,scenario,needle", [
    (lambda d: d["domain"].pop("partner_domain"), "google_workspace", "benign_drive", "partner_domain"),
    (lambda d: d["cloud"].pop("aws"), "aws_cloudtrail", "guardduty_detector_deleted", "cloud.aws"),
    (lambda d: d["cloud"]["aws"].pop("region"), "aws_cloudtrail", "benign_activity", "cloud.aws.region"),
    (lambda d: d["cloud"].pop("gcp"), "gcp_audit", "benign_activity", "cloud.gcp"),
    (lambda d: d.pop("egress"), "gcp_audit", "benign_activity", "egress"),
    (lambda d: [p.pop("cloud_access", None) for p in d["people"]], "aws_cloudtrail", "benign_activity", "cloud_access"),
    (lambda d: [p.update(department="Sales") for p in d["people"] if p["department"] == "IT"], "azure_ad_audit", "benign_activity", "department IT"),
    (lambda d: [p.setdefault("flags", []).append("leaver") for p in d["people"]], "okta", "benign_logins", "nobody who may log on"),
])
def test_missing_organization_data_raises_organization_unavailable_naming_what_to_add(edit, name, scenario, needle):
    with pytest.raises(OrganizationUnavailable, match=needle):
        build(name, scenario, view=broken(edit), count=5)


# -- the connector: pin and error path ---------------------------------------------------------------------------------------

@pytest.fixture
def cfg(monkeypatch):
    values = {"url": "", "key": "", "vendor": "Okta", "product": "SSO", "extra": "", "extra_keys": "", "organization": "",
              "verify_tls": True, "timeout": 5.0}
    monkeypatch.setattr(connector, "_settings", lambda: dict(values))
    return values


def test_an_empty_organization_setting_follows_the_active_one_and_an_id_pins_one(cfg, monkeypatch):
    asked = []
    real = ov.get_view

    def spy(pinned_id=None):
        asked.append(pinned_id)
        return real(pinned_id)

    monkeypatch.setattr(connector, "get_view", spy)
    assert connector.phantom_generate_events("okta", "benign_logins", count=2, dry_run=True)["ok"]
    cfg["organization"] = "phantom-lab"
    assert connector.phantom_generate_events("okta", "benign_logins", count=2, dry_run=True)["ok"]
    assert asked == [None, "phantom-lab"]


def test_no_organization_is_an_error_result_not_an_exception_for_every_tool_that_needs_one(cfg):
    def gone(pinned):
        raise OrganizationUnavailable("no organization is active: open the Organization page and activate one")

    ov.set_organization_loader(gone)
    result = connector.phantom_generate_events("okta", "benign_logins", count=2, dry_run=True)
    assert result["ok"] is False and "no organization is active" in result["error"]
    assert not connector.phantom_generate_events("aws_cloudtrail", "benign_activity", dry_run=True)["ok"]
    cfg["url"], cfg["key"] = "https://api-tenant.example.test/logs/v1/event", "k"
    test_event = connector.phantom_send_test_event(profile="okta")
    assert test_event["ok"] is False and "no organization is active" in test_event["error"]
    pinned_missing = None

    def no_such(pinned):
        raise OrganizationUnavailable(f"no organization with id {pinned!r}: fix the Organization setting on this connector instance")

    ov.set_organization_loader(no_such)
    cfg["organization"] = "ghost"
    pinned_missing = connector.phantom_generate_events("okta", "benign_logins", count=2, dry_run=True)
    assert pinned_missing["ok"] is False and "ghost" in pinned_missing["error"]


def test_the_windows_tool_paths_return_the_error_too_when_there_is_no_organization(cfg):
    cfg.update(cribl_url="https://api-tenant.example.test/logs/v1/integrated/cribl/data", cribl_token="test-token-not-real",
               cribl_integration="phantom-http-sender")

    def gone(pinned):
        raise OrganizationUnavailable("no organization is active: open the Organization page and activate one")

    ov.set_organization_loader(gone)
    for result in (
        connector.phantom_send_test_event(destination="cribl_windows_events"),
        connector.phantom_send_events([{"event_id": 4624, "computer": "HOST01", "event_data": {}}], destination="cribl_windows_events"),
        connector.phantom_generate_events("windows", "baseline_logons", destination="cribl_windows_events", dry_run=True),
    ):
        assert result["ok"] is False and "no organization is active" in result["error"], result


def test_an_unknown_target_user_through_the_tool_is_an_error_with_the_choices_and_no_scenario_list(cfg):
    result = connector.phantom_generate_events("okta", "failed_then_success", count=3, target_user="mallory", dry_run=True)
    assert result["ok"] is False and "mallory" in result["error"] and get_view().people[0]["email"] in result["error"]
    assert "scenarios" not in result
    assert connector.phantom_generate_events("okta", "failed_then_success", count=3, target_user="kalotaibi", dry_run=True)["ok"]


# -- no leftover rosters or literals ------------------------------------------------------------------------------------------

OWNED = ["profiles/okta.py", "profiles/aws_cloudtrail.py", "profiles/azure_ad_audit.py", "profiles/gcp_audit.py",
         "profiles/google_workspace.py", "profiles/proofpoint_tap.py", "profiles/ippools.py", "profiles/_org.py", "connector.py"]
LITERALS = (r"example\.com", r"phantom-lab\.example", r"lab\.test", r"phantom\.lab", r"(?<![\d.])10\.20\.", "PHDC", "PHWS",
            r"external-partner\.example", "512907433106", "412087653319", "userDomain", "Noura", "Khalid", "Alharbi", "Alotaibi",
            "noura", "khalid")
# connector.py also carries the windows profile's agent-facing documentation (its domain, hosts and example events), which the
# windows profile owns.
WINDOWS_DOCS = {"connector.py": (r"phantom\.lab", "PHDC", "PHWS")}


@pytest.mark.parametrize("relative", OWNED)
def test_no_roster_name_domain_account_or_organization_literal_is_left_in_the_source(relative):
    text = (SRC / relative).read_text(encoding="utf-8")
    for literal in LITERALS:
        if literal in WINDOWS_DOCS.get(relative, ()):
            continue
        assert not re.search(literal, text), f"{literal!r} is still in {relative}"
