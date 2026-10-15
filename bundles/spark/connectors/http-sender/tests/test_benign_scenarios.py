"""The `benign_activity` scenarios of the cloud profiles (`aws_cloudtrail`, `gcp_audit`, `azure_ad_audit`): the baseline the
attack recipes contrast with. The attack recipes invent a first-time actor on every call; these do the opposite, so the tests
check that identities are STABLE across calls, that nothing is a shape one of the detectors fired on, and that the events are
valid, current and sent to the profile's Cribl destination. No network.

Run from the connector directory:  python3 -m pytest -x
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runtime.organization_view import get_view  # noqa: E402
from src import connector, cribl  # noqa: E402
from src.profiles import _org, aws_cloudtrail as aws, azure_ad_audit as azure, gcp_audit as gcp, ippools, okta  # noqa: E402

NOW = datetime(2026, 10, 6, 9, 0, 0, tzinfo=timezone.utc)
CLOUD = (aws, gcp, azure)
HOME = {r.cidr for r in ippools.HOME}
TOR = {e.ip for e in ippools.ALL_TOR_EXITS}
URL = "https://api-tenant.example.test/logs/v1/integrated/cribl/data"
TOKEN = "test-token-not-real"


def build(mod, count=40, **kw):
    kw.setdefault("seed", 11)
    return mod.build_events("benign_activity", count, view=get_view(), now=NOW, **kw)


def attack(mod, scenario, **kw):
    return mod.build_events(scenario, max(mod.MIN_COUNT.get(scenario, 1), 2), view=get_view(), now=NOW, seed=3, **kw)


def domain():
    return get_view().email_domain


def provider(mod):
    return {aws: "aws", gcp: "gcp", azure: "azure"}[mod]


def pool(mod):
    """The organization's people the baseline of `mod` is built from: who may log on and has that cloud."""
    return _org.cloud_people(get_view(), provider(mod))


def when(mod, ev):
    if mod is aws:
        return datetime.strptime(ev["eventTime"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    field = ev["timestamp"] if mod is gcp else ev["activityDateTime"]
    return datetime.strptime(field[:26] + "Z", "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)


def actors(mod, events):
    """{identity: attributes that must not change from one call to the next}."""
    out = {}
    for ev in events:
        if mod is aws:
            ui = ev["userIdentity"]
            out[ui["arn"]] = (ui["principalId"], ev["sourceIPAddress"])  # access keys: see the test below
        elif mod is gcp:
            out[ev["protoPayload"]["authenticationInfo"]["principalEmail"]] = (ev["protoPayload"]["requestMetadata"]["callerIp"],)
        else:
            user = ev["initiatedBy"]["user"]
            out[user["userPrincipalName"]] = (user["id"], user["ipAddress"])
    return out


# -- interface ----------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("mod", CLOUD)
def test_benign_activity_is_a_registered_scenario_with_a_default_count_and_no_recipe_length(mod):
    assert mod.BENIGN_SCENARIOS == ("benign_activity",) and "benign_activity" in mod.SCENARIOS
    assert mod.DEFAULT_COUNT["benign_activity"] == 20 and "benign_activity" not in mod.MIN_COUNT
    assert set(mod.BENIGN_SCENARIOS) | set(mod.MIN_COUNT) == set(mod.SCENARIOS)
    assert len(build(mod, 1)) == 1


@pytest.mark.parametrize("mod", CLOUD)
def test_the_requested_number_of_events_and_valid_complete_objects(mod):
    for count in (1, 2, 7, 60):
        events = build(mod, count)
        assert len(events) == count
        for ev in events:
            assert isinstance(ev, dict) and json.loads(json.dumps(ev)) == ev
            assert connector._field(ev, mod.TEST_ID_FIELD) and connector._field(ev, mod.TIME_FIELD)
        ids = [connector._field(e, mod.TEST_ID_FIELD) for e in events]
        assert len(set(ids)) == len(ids)
    with pytest.raises(ValueError):
        build(mod, 0)


@pytest.mark.parametrize("mod", CLOUD)
def test_every_event_has_every_key_of_the_vendors_sample_shape(mod):
    sample = mod.sample_event(view=get_view(), now=NOW)
    for ev in build(mod, 60):
        missing = set(sample) - set(ev)
        # A console sign-in record has no TLS details, and no log is written for the Azure sample's shape: nothing else may be missing.
        assert missing <= {"tlsDetails"}, missing


# -- time ---------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("mod", CLOUD)
@pytest.mark.parametrize("spread,offset", [(120, 0), (900, 45), (30, 0)])
def test_times_are_ascending_over_the_window_that_ends_now_and_never_after_now(mod, spread, offset):
    events = build(mod, 25, spread_seconds=spread, start_offset_minutes=offset)
    end = NOW - timedelta(minutes=offset)
    times = [when(mod, e) for e in events]
    assert times == sorted(times)
    assert end - timedelta(seconds=1) <= times[-1] <= end                 # the last event is at the window's end
    assert times[0] >= end - timedelta(seconds=spread + 1)               # and none before its start
    assert times[0] <= end - timedelta(seconds=spread - 1)               # the first is at its start: the window is covered
    assert all(t <= NOW for t in times)


@pytest.mark.parametrize("mod", CLOUD)
def test_the_times_are_not_evenly_spaced(mod):
    times = [when(mod, e).timestamp() for e in build(mod, 30, spread_seconds=600)]
    gaps = {round(b - a, 1) for a, b in zip(times, times[1:])}
    assert len(gaps) > 5


# -- stable identities --------------------------------------------------------------------------------------------------------

def identity_count(mod):
    """Identities of a large call: AWS every IAM user plus the sessions of their two usual roles each; GCP every user and the 4
    service accounts; Azure every IT administrator (as `.adm`) and every user (acting for themselves)."""
    people = len(pool(mod))
    if mod is aws:
        return people + people * 2
    if mod is gcp:
        return people + len(gcp.BENIGN_SERVICE_ACCOUNTS)
    return len(_org.administrators(pool(mod))) + people


# A deterministic large call: 4000 events reach every identity of the organization's pool for these seeds (the least frequent,
# an AWS role session, is drawn about 8 times; a seed that missed one would fail every run, never one in a while).
SEEDS = (1, 2, 5)


@pytest.mark.parametrize("mod", CLOUD)
def test_the_same_actors_with_the_same_ids_and_addresses_appear_on_every_call(mod):
    first, second, third = (actors(mod, build(mod, 4000, seed=seed)) for seed in SEEDS)
    assert first.keys() == second.keys() == third.keys()
    assert len(first) == identity_count(mod)
    assert first == second == third


def test_an_iam_users_access_key_is_the_same_on_every_call():
    keys = [{e["userIdentity"]["arn"]: e["userIdentity"]["accessKeyId"]
             for e in build(aws, 4000, seed=seed) if e["userIdentity"]["type"] == "IAMUser" and "accessKeyId" in e["userIdentity"]}
            for seed in (1, 2)]
    assert keys[0] == keys[1] and len(keys[0]) == len(pool(aws))


def test_aws_uses_the_organizations_account_and_region_in_the_baseline_and_in_every_attack():
    cloud = get_view().doc["cloud"]["aws"]
    for events in [build(aws, 100, seed=None)] + [attack(aws, scenario) for scenario in aws.MIN_COUNT]:
        assert {e["recipientAccountId"] for e in events} == {cloud["account_id"]}
        assert {e["userIdentity"]["accountId"] for e in events} == {cloud["account_id"]}
        assert {e["awsRegion"] for e in events} == {cloud["region"]}
        # Not every event type carries tlsDetails (a console login does not); every one that does names the region.
        assert all(f".{cloud['region']}." in e["tlsDetails"]["clientProvidedHostHeader"] for e in events if "tlsDetails" in e)


def test_gcp_uses_the_organizations_project_and_region_in_the_baseline_and_in_every_attack():
    cloud = get_view().doc["cloud"]["gcp"]
    for events in [build(gcp, 100, seed=None)] + [attack(gcp, scenario) for scenario in gcp.MIN_COUNT]:
        assert {e["resource"]["labels"]["project_id"] for e in events} == {cloud["project_id"]}
        assert all(f"projects/{cloud['project_id']}/" in e["logName"] for e in events)
    text = json.dumps(build(gcp, 400, seed=None))
    assert cloud["region"] in text and "us-central1" not in text


@pytest.mark.parametrize("mod", CLOUD)
def test_no_attack_scenario_shares_an_actor_with_the_baseline(mod):
    baseline = set(actors(mod, build(mod, 1500, seed=None)))
    for scenario in (s for s in mod.SCENARIOS if s not in mod.BENIGN_SCENARIOS):
        assert not (baseline & set(actors(mod, attack(mod, scenario)))), scenario


def test_the_pool_people_are_the_okta_users_with_the_same_home_addresses():
    """One person, one home address (the organization's `home_ip`) in every profile."""
    n = 2 * len(_org.logon_people(get_view()))
    okta_ip = {e["actor"]["alternateId"].split("@")[0]: e["client"]["ipAddress"] for e in okta.build_events(
        "benign_logins", n, view=get_view(), now=NOW, seed=1)}
    assert len(okta_ip) == len(_org.logon_people(get_view()))
    aws_ip = {e["userIdentity"]["userName"]: e["sourceIPAddress"] for e in build(aws, 4000, seed=1) if e["userIdentity"]["type"] == "IAMUser"}
    gcp_ip = {e["protoPayload"]["authenticationInfo"]["principalEmail"].split("@")[0]: e["protoPayload"]["requestMetadata"]["callerIp"]
              for e in build(gcp, 4000, seed=1) if "gserviceaccount" not in e["protoPayload"]["authenticationInfo"]["principalEmail"]}
    azure_ip = {e["initiatedBy"]["user"]["userPrincipalName"].split("@")[0]: e["initiatedBy"]["user"]["ipAddress"]
                for e in build(azure, 4000, seed=1) if not e["initiatedBy"]["user"]["userPrincipalName"].split("@")[0].endswith(".adm")}
    for mod, ips in ((aws, aws_ip), (gcp, gcp_ip), (azure, azure_ip)):
        assert len(ips) == len(pool(mod)) and all(okta_ip[name] == ip for name, ip in ips.items())
        assert set(ips) == {_org.local_part(p) for p in pool(mod)}  # exactly the people with that cloud, no leaver


@pytest.mark.parametrize("mod", CLOUD)
def test_every_address_is_a_home_pool_address_never_abroad_or_tor(mod):
    for ev in build(mod, 300, seed=None):
        ip = (ev.get("sourceIPAddress") or (ev.get("protoPayload") or {}).get("requestMetadata", {}).get("callerIp")
              or (ev.get("initiatedBy") or {}).get("user", {}).get("ipAddress"))
        rng = ippools.range_of(ip)
        assert rng is not None and rng in ippools.HOME and ip not in TOR, ip


# -- nothing a detector fired on ----------------------------------------------------------------------------------------------

def test_aws_calls_are_ordinary_reads_and_never_an_attack_shape():
    benign = build(aws, 600, seed=None)
    pairs = {(e["eventSource"], e["eventName"]) for e in benign}
    attacks = set()
    for scenario in aws.MIN_COUNT:
        attacks |= {(e["eventSource"], e["eventName"]) for e in attack(aws, scenario)}
    # ListUsers and ListBuckets are the two read calls of tor_api_call: it fires on the Tor address, which benign never has.
    assert pairs & attacks <= {("iam.amazonaws.com", "ListUsers"), ("s3.amazonaws.com", "ListBuckets")}
    text = json.dumps(benign)
    for marker in ("AllUsers", "0.0.0.0/0", "AdministratorAccess", '"Principal"', "PutBucketPolicy", "DeleteDetector", "kali", "Pacu"):
        assert marker not in text, marker
    assert all(e["readOnly"] for e in benign if e["eventName"] not in ("ConsoleLogin",))
    assert {e["userIdentity"]["type"] for e in benign} == {"IAMUser", "AssumedRole"}
    assert {"ConsoleLogin", "ListBuckets", "GetObject", "DescribeInstances", "ListUsers", "GetCallerIdentity", "AssumeRole"} <= {e["eventName"] for e in benign}


def test_aws_assume_role_goes_into_a_usual_role_of_that_user_and_the_role_calls_come_from_the_users_address():
    benign = build(aws, 800, seed=None)
    assumed = [e for e in benign if e["eventName"] == "AssumeRole"]
    assert assumed
    for e in assumed:
        role = e["requestParameters"]["roleArn"].rsplit("/", 1)[1]
        assert role in aws.BENIGN_ROLES and e["userIdentity"]["type"] == "IAMUser"
        assert e["responseElements"]["assumedRoleUser"]["arn"].endswith(f"assumed-role/{role}/{e['requestParameters']['roleSessionName']}")
    ip_of = {e["userIdentity"]["userName"]: e["sourceIPAddress"] for e in benign if e["userIdentity"]["type"] == "IAMUser"}
    for e in benign:
        if e["userIdentity"]["type"] == "AssumedRole":
            session = e["userIdentity"]["arn"].rsplit("/", 1)[1]
            assert e["sourceIPAddress"] == ip_of[session]
            assert e["userIdentity"]["sessionContext"]["sessionIssuer"]["userName"] in aws.BENIGN_ROLES
    # One role session keeps one temporary key within a call.
    keys = {}
    for e in benign:
        if e["userIdentity"]["type"] == "AssumedRole":
            keys.setdefault(e["userIdentity"]["arn"], set()).add(e["userIdentity"]["accessKeyId"])
    assert all(len(v) == 1 for v in keys.values())


def test_gcp_calls_are_ordinary_data_access_reads_and_never_an_attack_shape():
    benign = build(gcp, 600, seed=None)
    methods = {e["protoPayload"]["methodName"] for e in benign}
    attacks = set()
    for scenario in gcp.MIN_COUNT:
        attacks |= {e["protoPayload"]["methodName"] for e in attack(gcp, scenario)}
    assert methods & attacks <= {"storage.objects.get"}  # tor_api_call's read; it fires on the Tor address
    text = json.dumps(benign)
    for marker in ("allUsers", "roles/owner", "system:anonymous", "kube-hunter", "Trivy", "SetIamPolicy", "setIamPermissions", "CreateServiceAccount"):
        assert marker not in text, marker
    assert all(e["logName"].endswith("data_access") and e["severity"] == "INFO" for e in benign)
    assert {"storage.objects.get", "storage.objects.list", "v1.compute.instances.list", "google.iam.admin.v1.GetServiceAccount"} <= methods
    assert any("gserviceaccount.com" in e["protoPayload"]["authenticationInfo"]["principalEmail"] for e in benign)
    for e in benign:
        # Each call's authorization names the permission it exercised, and the receive time is never before the event or after now.
        assert e["protoPayload"]["authorizationInfo"] and e["receiveTimestamp"] >= e["timestamp"][:19]
        assert datetime.strptime(e["receiveTimestamp"][:26] + "Z", "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc) <= NOW


def test_azure_operations_are_ordinary_directory_work_and_never_an_attack_shape():
    benign = build(azure, 600, seed=None)
    names = {e["activityDisplayName"] for e in benign}
    attacks = set()
    for scenario in azure.MIN_COUNT:
        attacks |= {e["activityDisplayName"] for e in attack(azure, scenario)}
    assert not names & attacks
    assert {"Update user", "Add member to group", "Remove member from group", "Reset password (by admin)",
            "Change password (self-service)", "Add app role assignment grant to user", "Add user"} == names
    text = json.dumps(benign)
    for marker in ("Global Administrator", "PIM", "Conditional", "Federated", "unverified", "Delete", "RoleManagement"):
        assert marker not in text, marker
    assert {e["category"] for e in benign} <= {"UserManagement", "GroupManagement", "ApplicationManagement"}
    assert {g["displayName"] for e in benign for g in e["targetResources"] if g["type"] == "Group"} <= set(azure.BENIGN_GROUPS)


def test_azure_resets_are_done_by_the_helpdesk_administrator_on_an_ordinary_user():
    benign = build(azure, 600, seed=None)
    resets = [e for e in benign if e["activityDisplayName"] == "Reset password (by admin)"]
    assert resets
    admins = _org.administrators(pool(azure))
    first = _org.local_part(next(p for p in admins if "helpdesk" in p["title"].lower()))
    for e in resets:
        assert e["initiatedBy"]["user"]["userPrincipalName"] == f"{first}.adm@{domain()}"
        assert not e["targetResources"][0]["userPrincipalName"].split("@")[0].endswith(".adm")
    for e in benign:
        if e["activityDisplayName"] == "Change password (self-service)":
            assert e["initiatedBy"]["user"]["userPrincipalName"] == e["targetResources"][0]["userPrincipalName"]


@pytest.mark.parametrize("mod", CLOUD)
def test_target_user_and_source_ip_are_ignored_the_actors_are_the_pools(mod):
    plain = actors(mod, build(mod, 300, seed=2))
    forced = actors(mod, build(mod, 300, seed=2, target_user="someone.else", source_ip="203.0.113.9"))
    assert plain == forced and not any("someone" in k for k in forced)


@pytest.mark.parametrize("mod", CLOUD)
def test_a_seed_makes_the_call_reproducible_and_unseeded_calls_differ_only_in_event_ids(mod):
    assert build(mod, 30, seed=3) == build(mod, 30, seed=3)
    a, b = build(mod, 30, seed=None), build(mod, 30, seed=None)
    assert {connector._field(e, mod.TEST_ID_FIELD) for e in a}.isdisjoint({connector._field(e, mod.TEST_ID_FIELD) for e in b})


# -- through the tool -----------------------------------------------------------------------------------------------------------

@pytest.fixture
def cfg(monkeypatch):
    values = {"url": "https://api-tenant.example.test/logs/v1/event", "key": "k", "vendor": "Okta", "product": "SSO", "extra": "",
              "extra_keys": "", "organization": "", "verify_tls": True, "timeout": 5.0, "cribl_url": URL, "cribl_token": TOKEN,
              "cribl_integration": "wave-7", "windows_dns": "phantom.lab"}
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


@pytest.mark.parametrize("mod", CLOUD)
def test_the_tool_sends_to_the_profiles_cribl_destination_with_a_default_of_twenty(mod, wire):
    result = connector.phantom_generate_events(mod.NAME, "benign_activity")
    assert result["ok"] and result["sent"] == 20 and result["destination"] == mod.DEFAULT_DESTINATION
    assert result["scenario"] == "benign_activity" and "warning" not in result and len(result["sample_ids"]) == 5
    lines = [json.loads(x)["data"] for r in wire for x in r.content.decode().split("\n") if x]
    assert len(lines) == 20 and all(isinstance(e, dict) for e in lines)
    assert wire[0].headers["Source-Identifier"] == cribl.SOURCES[mod.DEFAULT_DESTINATION.removeprefix(cribl.PREFIX)].uuid


@pytest.mark.parametrize("mod", CLOUD)
def test_dry_run_sends_nothing_and_needs_no_cribl(mod, monkeypatch):
    sent = []
    monkeypatch.setattr(connector, "_settings", lambda: {"url": "", "key": "", "vendor": "Okta", "product": "SSO", "extra": "",
                                                         "extra_keys": "", "organization": "", "verify_tls": True, "timeout": 5.0})
    monkeypatch.setattr(connector.cribl, "post", lambda *a, **k: sent.append(a))
    monkeypatch.setattr(connector.collector, "post_events", lambda *a, **k: sent.append(a))
    result = connector.phantom_generate_events(mod.NAME, "benign_activity", count=5, dry_run=True)
    assert result["ok"] and result["dry_run"] and result["sent"] == 0 and sent == [] and len(result["events"]) == 3
    assert result["destination"] == mod.DEFAULT_DESTINATION
    refused = connector.phantom_generate_events(mod.NAME, "benign_activity")
    assert not refused["ok"] and "not configured" in refused["error"] and sent == []


@pytest.mark.parametrize("mod", CLOUD)
def test_a_tool_call_spreads_the_events_over_spread_seconds_ending_now(mod, wire):
    before = datetime.now(timezone.utc).replace(microsecond=0)
    result = connector.phantom_generate_events(mod.NAME, "benign_activity", count=15, spread_seconds=300)
    after = datetime.now(timezone.utc)
    lines = [json.loads(x)["data"] for r in wire for x in r.content.decode().split("\n") if x]
    times = [when(mod, e) for e in lines]
    assert result["ok"] and times == sorted(times)
    assert before - timedelta(seconds=1) <= times[-1] <= after
    assert 295 <= (times[-1] - times[0]).total_seconds() <= 301
