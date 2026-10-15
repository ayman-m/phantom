"""The Cribl profiles (`aws_cloudtrail`, `gcp_audit`, `azure_ad_audit`) and the okta `tor_signin` / `fastpass_phishing`
scenarios: unit tests. No network, no files.

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

from runtime.organization_view import get_view  # noqa: E402
from src import connector, cribl, profiles  # noqa: E402
from src.profiles import _org, aws_cloudtrail as aws, azure_ad_audit as azure, gcp_audit as gcp, ippools, okta  # noqa: E402

NOW = datetime(2026, 10, 4, 12, 0, 0, tzinfo=timezone.utc)
CLOUD = (aws, gcp, azure)
TOR = {e.ip for e in ippools.ALL_TOR_EXITS}
OKTA_TOR = {e.ip for e in ippools.TOR_EXITS}
CLOUD_TOR = {e.ip for e in ippools.CLOUD_TOR_EXITS}

# The detectors that fire on a Cortex tenant through the Cribl endpoint:
# detector name -> the (profile, scenario) pairs that reproduce it.
DETECTORS = {
    # Okta (3)
    "A successful SSO sign-in from TOR": [("okta", "tor_signin")],
    "Okta FastPass reported phishing attack suspected": [("okta", "fastpass_phishing")],
    "Multiple Okta MFA requests": [("okta", "mfa_fatigue")],
    # AWS (15 names)
    "AWS Guard-Duty detector deletion": [("aws_cloudtrail", "guardduty_detector_deleted")],
    "AWS S3 bucket was exposed to public access": [("aws_cloudtrail", "s3_public_exposure")],
    "AWS Bedrock model invocation logging deleted": [("aws_cloudtrail", "bedrock_logging_deleted")],
    "AWS Route53 DNS Resolver query logging deleted by a non-admin": [("aws_cloudtrail", "route53_logging_deleted")],
    "AWS Security Group remote access from an unknown external IP": [("aws_cloudtrail", "security_group_open")],
    "Cloud snapshot configured for public access": [("aws_cloudtrail", "snapshot_public_share")],
    "Cloud snapshot publicly shared": [("aws_cloudtrail", "snapshot_public_share")],
    "Cloud snapshot shared public": [("aws_cloudtrail", "snapshot_public_share")],
    "Disable encryption operations": [("aws_cloudtrail", "ebs_encryption_disabled")],
    "Cloud penetration testing tool activity": [("aws_cloudtrail", "pentest_tool")],
    "A Backup vault policy was modified": [("aws_cloudtrail", "backup_vault_policy_modified")],
    "Suspicious API call from a Tor exit node": [("aws_cloudtrail", "tor_api_call"), ("gcp_audit", "tor_api_call")],
    "Cloud activity from an unusual high-risk IP": [("aws_cloudtrail", "tor_api_call"), ("gcp_audit", "tor_api_call")],
    "New cloud identity created with administrative policy": [("aws_cloudtrail", "iam_new_admin_identity"),
                                                              ("gcp_audit", "new_admin_service_account")],
    "Administrative IAM User Created with Credentials": [("aws_cloudtrail", "iam_admin_user_credentials")],
    # GCP only (4)
    "GCP data asset shared public": [("gcp_audit", "data_asset_public")],
    "GCP sensitive role granted to group": [("gcp_audit", "sensitive_role_to_group")],
    "A Kubernetes API operation was successfully invoked by an anonymous user outside the cluster": [("gcp_audit", "k8s_anonymous")],
    "External Kubernetes vulnerability scanning tool usage": [("gcp_audit", "k8s_vuln_scanner")],
    # Azure AD audit (5)
    "Conditional Access policy removed": [("azure_ad_audit", "ca_policy_deleted")],
    "Azure AD PIM alert disabled": [("azure_ad_audit", "pim_alert_disabled")],
    "A successful Azure domain federation settings modification": [("azure_ad_audit", "federation_modified")],
    "Azure AD PIM role settings change": [("azure_ad_audit", "pim_role_setting_changed")],
    "Rare unverified domain addition to Azure AD": [("azure_ad_audit", "unverified_domain_added")],
}


def build(mod, scenario, count=None, **kw):
    count = count or max(getattr(mod, "MIN_COUNT", {}).get(scenario, 1), 2)
    kw.setdefault("seed", 7)
    return mod.build_events(scenario, count, view=get_view(), now=NOW, **kw)


def domain():
    return get_view().email_domain


def person(login):
    return get_view().person(login)


def when(mod, ev):
    """An event's time as a datetime truncated to the field's own precision."""
    if mod is aws:
        return datetime.strptime(ev["eventTime"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    if mod is gcp:
        return datetime.strptime(ev["timestamp"][:26] + "Z", "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
    if mod is azure:
        return datetime.strptime(ev["activityDateTime"][:26] + "Z", "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
    return datetime.strptime(ev["published"], "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)


def ips(mod, events):
    if mod is aws:
        return {e["sourceIPAddress"] for e in events}
    if mod is gcp:
        return {e["protoPayload"]["requestMetadata"]["callerIp"] for e in events}
    if mod is azure:
        return {e["initiatedBy"]["user"]["ipAddress"] for e in events}
    return {e["client"]["ipAddress"] for e in events}


def identities(mod, events):
    """Every identifier of the ACTOR a replay would be recognised by. The account and project are the organization's and
    the same on every call, so they are not part of an actor's identity."""
    out: set[str] = set()
    for e in events:
        if mod is aws:
            ui = e["userIdentity"]
            out |= {ui["arn"], ui["accessKeyId"], ui["principalId"]}
        elif mod is gcp:
            out |= {e["protoPayload"]["authenticationInfo"]["principalEmail"]}
        elif mod is azure:
            user = e["initiatedBy"]["user"]
            out |= {user["userPrincipalName"], user["id"]}
    out.discard("")
    out.discard("system:anonymous")  # the anonymous Kubernetes caller is the same by definition
    return out


# The detector recipes (fresh identities, one measured shape each). The benign scenarios have their own tests in
# test_benign_scenarios.py: their identities are stable by design.
CASES = [(m, s) for m in CLOUD for s in m.SCENARIOS if s not in m.BENIGN_SCENARIOS]
IDS = [f"{m.NAME}.{s}" for m, s in CASES]


# -- interface ----------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("mod", CLOUD)
def test_the_profile_interface_is_complete_and_registered(mod):
    assert profiles.get(mod.NAME) is mod
    assert mod.EXPECTED_DATASET == mod.EXPECTED_DATASETS[0] and mod.CRIBL_ONLY is True
    assert mod.DEFAULT_DESTINATION in mod.CRIBL_DESTINATIONS == mod.EXPECTED_DATASETS
    alias = mod.DEFAULT_DESTINATION.removeprefix(cribl.PREFIX)
    assert alias in cribl.SOURCES and profiles.for_destination(mod.DEFAULT_DESTINATION) is mod
    assert set(mod.MIN_COUNT) <= set(mod.SCENARIOS) and mod.DESCRIPTION
    ev = mod.sample_event(view=get_view(), now=NOW)
    assert connector._field(ev, mod.TEST_ID_FIELD) and connector._field(ev, mod.TIME_FIELD)
    assert when(mod, ev) <= NOW and NOW - when(mod, ev) < timedelta(seconds=2)
    assert mod.sample_event(view=get_view(), now=NOW) != ev  # a fresh id and identity every time


def test_every_detector_that_fired_is_reachable_through_an_existing_scenario():
    assert len(DETECTORS) == 27  # the research note's names, the three snapshot ones counted separately
    reachable = {(m.NAME, s) for m in (okta, *CLOUD) for s in m.SCENARIOS}
    for name, pairs in DETECTORS.items():
        assert pairs and all(p in reachable for p in pairs), name
    attacks = {m.NAME: set(m.SCENARIOS) - set(m.BENIGN_SCENARIOS) for m in CLOUD}
    assert {s for _, s in (p for ps in DETECTORS.values() for p in ps) if s in aws.SCENARIOS} == attacks["aws_cloudtrail"]
    assert {p[1] for ps in DETECTORS.values() for p in ps if p[0] == "gcp_audit"} == attacks["gcp_audit"]
    assert {p[1] for ps in DETECTORS.values() for p in ps if p[0] == "azure_ad_audit"} == attacks["azure_ad_audit"]


@pytest.mark.parametrize("mod,scenario", CASES, ids=IDS)
def test_unknown_scenarios_and_counts_below_the_recipe_are_refused(mod, scenario):
    with pytest.raises(ValueError):
        mod.build_events("ransomware", 3, view=get_view(), now=NOW)
    with pytest.raises(ValueError):
        mod.build_events(scenario, 0, view=get_view(), now=NOW)
    need = mod.MIN_COUNT.get(scenario, 1)
    if need > 1:
        with pytest.raises(ValueError, match=f"needs count >= {need}"):
            mod.build_events(scenario, need - 1, view=get_view(), now=NOW)
    assert len(mod.build_events(scenario, need, view=get_view(), now=NOW)) == need


# -- events: validity, time, addresses, freshness -----------------------------------------------------------------

@pytest.mark.parametrize("mod,scenario", CASES, ids=IDS)
def test_events_are_complete_json_objects_with_unique_ids(mod, scenario):
    events = build(mod, scenario, count=max(mod.MIN_COUNT.get(scenario, 1), 2) * 2)
    for ev in events:
        assert isinstance(ev, dict) and json.loads(json.dumps(ev)) == ev
        assert connector._field(ev, mod.TEST_ID_FIELD) and connector._field(ev, mod.TIME_FIELD)
    ids = [connector._field(e, mod.TEST_ID_FIELD) for e in events]
    assert len(set(ids)) == len(ids)


@pytest.mark.parametrize("mod,scenario", CASES, ids=IDS)
@pytest.mark.parametrize("spread,offset", [(120, 0), (900, 45)])
def test_times_are_ascending_inside_the_requested_window_and_never_after_now(mod, scenario, spread, offset):
    count = max(mod.MIN_COUNT.get(scenario, 1), 5)
    events = build(mod, scenario, count=count, spread_seconds=spread, start_offset_minutes=offset)
    end = NOW - timedelta(minutes=offset)
    times = [when(mod, e) for e in events]
    assert times == sorted(times)
    assert times[-1] <= end and times[-1] >= end - timedelta(seconds=1)
    assert times[0] >= end - timedelta(seconds=spread + 1)
    assert all(t <= NOW for t in times)


@pytest.mark.parametrize("mod,scenario", CASES, ids=IDS)
def test_addresses_are_real_public_ips_from_the_pools(mod, scenario):
    for seed in range(5):
        for ip in ips(mod, build(mod, scenario, seed=seed)):
            addr = ipaddress.ip_address(ip)
            assert addr.is_global and not addr.is_private, ip
            assert ippools.range_of(ip) is not None or ip in TOR, f"{ip} is in no pool"


@pytest.mark.parametrize("mod,scenario", CASES, ids=IDS)
def test_two_calls_share_no_identity(mod, scenario):
    first = identities(mod, build(mod, scenario, seed=None))
    second = identities(mod, build(mod, scenario, seed=None))
    if scenario == "k8s_anonymous":  # the anonymous caller is the same by definition, and the project is the organization's
        assert not first and not second
        return
    assert first and second and not (first & second), first & second
    assert not (identities(mod, build(mod, scenario, seed=1)) & identities(mod, build(mod, scenario, seed=2)))


@pytest.mark.parametrize("mod,scenario", CASES, ids=IDS)
def test_a_seed_makes_a_call_reproducible(mod, scenario):
    assert build(mod, scenario, seed=3) == build(mod, scenario, seed=3)


@pytest.mark.parametrize("mod,scenario", CASES, ids=IDS)
def test_dry_run_through_the_tool_sends_nothing(mod, scenario, monkeypatch):
    sent = []
    monkeypatch.setattr(connector, "_settings", lambda: {"url": "", "key": "", "vendor": "Okta", "product": "SSO", "extra": "",
                                                         "extra_keys": "", "organization": "", "verify_tls": True, "timeout": 5.0})
    monkeypatch.setattr(connector.cribl, "post", lambda *a, **k: sent.append(a))
    monkeypatch.setattr(connector.collector, "post_events", lambda *a, **k: sent.append(a))
    result = connector.phantom_generate_events(mod.NAME, scenario, count=mod.MIN_COUNT.get(scenario, 1), dry_run=True)
    assert result["ok"] and result["dry_run"] and result["sent"] == 0 and sent == []
    assert result["destination"] == mod.DEFAULT_DESTINATION and result["events"]


def test_target_user_and_source_ip_overrides_are_honoured():
    ev = build(aws, "tor_api_call", target_user="DOMAIN\\Khalid.Alotaibi", source_ip="203.0.113.9")
    assert {e["userIdentity"]["userName"] for e in ev} == {"khalid.alotaibi"} and ips(aws, ev) == {"203.0.113.9"}
    ev = build(gcp, "data_asset_public", target_user="Sara.Almutairi", source_ip="198.51.100.4")
    assert {e["protoPayload"]["authenticationInfo"]["principalEmail"] for e in ev} == {person("salmutairi")["email"]}
    assert ips(gcp, ev) == {"198.51.100.4"}
    ev = build(azure, "pim_alert_disabled", target_user="reem.aldosari", source_ip="198.51.100.4")
    assert {e["initiatedBy"]["user"]["userPrincipalName"] for e in ev} == {f"reem.aldosari.adm@{domain()}"}
    assert ips(azure, ev) == {"198.51.100.4"}


def test_a_named_actor_acts_from_their_own_home_address_and_a_stranger_is_refused():
    home = person("kalotaibi")["home_ip"]
    # no source_ip: the calls come from the named person's own home address (a recipe whose every step has its own address,
    # like pentest_tool or tor_api_call, never uses it)
    assert ips(aws, build(aws, "guardduty_detector_deleted", target_user="kalotaibi")) == {home}
    assert ips(gcp, build(gcp, "data_asset_public", target_user="khalid.alotaibi")) == {home}
    assert ips(azure, build(azure, "ca_policy_deleted", target_user="Khalid.Alotaibi@" + domain())) == {home}
    for mod, scenario in ((aws, "guardduty_detector_deleted"), (gcp, "data_asset_public"), (azure, "ca_policy_deleted")):
        with pytest.raises(ValueError, match="nobody in the organization") as err:
            build(mod, scenario, target_user="mallory.nobody")
        assert person("nalharbi")["email"] in str(err.value)  # the valid choices are listed


def test_ordinary_actors_come_from_the_saudi_home_pool_not_from_an_attacker_range():
    for mod, scenario in ((aws, "guardduty_detector_deleted"), (gcp, "sensitive_role_to_group"), (azure, "ca_policy_deleted")):
        for ip in ips(mod, build(mod, scenario, seed=11)):
            pool = ippools.range_of(ip)
            assert pool is not None and pool.country == "Saudi Arabia", (mod.NAME, ip)


# -- the Tor snapshot ---------------------------------------------------------------------------------------------

def test_the_tor_snapshots_are_dated_global_unique_and_outside_the_verified_pools():
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", ippools.TOR_EXITS_SNAPSHOT)
    assert len(ippools.TOR_EXITS) == 19 and len(ippools.CLOUD_TOR_EXITS) == 6
    addrs = [e.ip for e in ippools.ALL_TOR_EXITS]
    assert len(addrs) == len(set(addrs)) == 25  # the two lists do not overlap
    for exit_ in ippools.ALL_TOR_EXITS:
        assert ipaddress.ip_address(exit_.ip).is_global and exit_.country and exit_.org
        assert ippools.range_of(exit_.ip) is None, "a Tor exit must not sit in a HOME or ABROAD range"


def test_tor_exits_are_distinct_while_they_fit_and_seeded():
    import random

    picks = ippools.tor_exits(random.Random(1), 10)
    assert len({p.ip for p in picks}) == 10
    assert ippools.tor_exits(random.Random(1), 10) == picks
    assert len(ippools.tor_exits(random.Random(1), len(ippools.TOR_EXITS) + 3)) == len(ippools.TOR_EXITS) + 3
    assert ippools.tor_exits(random.Random(1), 0) == []
    cloud = ippools.tor_exits(random.Random(1), 6, ippools.CLOUD_TOR_EXITS)
    assert {e.ip for e in cloud} == CLOUD_TOR and {e.ip for e in ippools.tor_exits(random.Random(1), 19)} == OKTA_TOR


# -- aws_cloudtrail: each detector's measured shape ---------------------------------------------------------------

def names(events):
    return [e["eventName"] for e in events]


def test_aws_records_are_cloudtrail_shaped():
    for ev in build(aws, "s3_public_exposure", count=6):
        assert {"eventVersion", "userIdentity", "eventTime", "eventSource", "eventName", "awsRegion", "sourceIPAddress",
                "userAgent", "requestParameters", "responseElements", "requestID", "eventID", "readOnly", "eventType",
                "managementEvent", "recipientAccountId", "eventCategory", "tlsDetails"} <= ev.keys()
        assert ev["eventVersion"] == "1.11" and re.fullmatch(r"\d{12}", ev["recipientAccountId"])
        assert ev["userIdentity"]["accountId"] == ev["recipientAccountId"] == get_view().doc["cloud"]["aws"]["account_id"]
        assert ev["awsRegion"] == get_view().doc["cloud"]["aws"]["region"]


def test_aws_single_step_scenarios():
    assert [(e["eventSource"], e["eventName"]) for e in build(aws, "guardduty_detector_deleted", 1)] == [("guardduty.amazonaws.com", "DeleteDetector")]
    assert names(build(aws, "bedrock_logging_deleted", 1)) == ["DeleteModelInvocationLoggingConfiguration"]
    assert names(build(aws, "ebs_encryption_disabled", 1)) == ["DisableEbsEncryptionByDefault"]
    (route53,) = build(aws, "route53_logging_deleted", 1)
    assert route53["eventName"] == "DeleteResolverQueryLogConfig"
    assert re.search(r"assumed-role/ci-deploy-runner-[0-9a-f]{6}/", route53["userIdentity"]["arn"])  # a non-admin role


def test_aws_s3_public_exposure_is_policy_acl_and_block_removal_on_one_bucket():
    events = build(aws, "s3_public_exposure", 3)
    assert names(events) == ["PutBucketPolicy", "PutBucketAcl", "DeletePublicAccessBlock"]
    assert len({e["requestParameters"]["bucketName"] for e in events}) == 1
    assert events[0]["requestParameters"]["bucketPolicy"]["Statement"][0]["Principal"] == "*"
    assert "AllUsers" in json.dumps(events[1]["requestParameters"])
    two_reps = build(aws, "s3_public_exposure", 6)
    assert len({e["requestParameters"]["bucketName"] for e in two_reps}) == 2  # fresh resource per repetition
    assert len({e["userIdentity"]["arn"] for e in two_reps}) == 1  # by one actor


def test_aws_security_group_opens_ssh_to_one_external_32_and_rdp_to_the_world():
    ssh, rdp = build(aws, "security_group_open", 2, source_ip="203.0.113.77")
    rules = [e["requestParameters"]["ipPermissions"]["items"][0] for e in (ssh, rdp)]
    assert (rules[0]["fromPort"], rules[0]["ipRanges"]["items"][0]["cidrIp"]) == (22, "203.0.113.77/32")
    assert (rules[1]["fromPort"], rules[1]["ipRanges"]["items"][0]["cidrIp"]) == (3389, "0.0.0.0/0")
    default = build(aws, "security_group_open", 2)[0]["requestParameters"]["ipPermissions"]["items"][0]["ipRanges"]["items"][0]["cidrIp"]
    assert ippools.range_of(default.removesuffix("/32")) in ippools.ABROAD


def test_aws_backup_policy_is_a_foreign_principal_allow_by_an_iam_user():
    (ev,) = build(aws, "backup_vault_policy_modified", 1)
    assert ev["userIdentity"]["type"] == "IAMUser" and ev["eventName"] == "PutBackupVaultAccessPolicy"
    statement = json.loads(ev["requestParameters"]["policy"])["Statement"][0]
    foreign = statement["Principal"]["AWS"]
    assert statement["Effect"] == "Allow" and statement["Action"] == ["backup:CopyIntoBackupVault"]
    assert re.fullmatch(r"arn:aws:iam::\d{12}:root", foreign) and ev["recipientAccountId"] not in foreign


def test_aws_pentest_tool_is_six_list_roles_calls_with_six_tool_user_agents_from_abroad():
    events = build(aws, "pentest_tool", 6)
    assert names(events) == ["ListRoles"] * 6 and len({e["userAgent"] for e in events}) == 6
    tools = " ".join(e["userAgent"] for e in events)
    for needle in ("kali", "parrot", "Pacu", "Prowler", "Scout Suite", "cloudfox"):
        assert needle in tools
    (ip,) = ips(aws, events)
    assert ippools.range_of(ip) in ippools.ABROAD and all(e["readOnly"] for e in events)


def test_aws_snapshot_public_share_covers_the_ebs_and_the_rds_snapshot():
    ebs, rds = build(aws, "snapshot_public_share", 2)
    assert (ebs["eventName"], rds["eventName"]) == ("ModifySnapshotAttribute", "ModifyDBSnapshotAttribute")
    assert ebs["requestParameters"]["createVolumePermission"]["add"]["items"] == [{"group": "all"}]
    assert rds["requestParameters"]["valuesToAdd"] == ["all"]


def test_aws_tor_api_call_is_two_reads_from_a_tor_exit():
    events = build(aws, "tor_api_call", 2)
    assert names(events) == ["ListUsers", "ListBuckets"] and len(ips(aws, events)) == 1 and ips(aws, events) <= CLOUD_TOR
    for seed in range(25):
        repeated = ips(aws, build(aws, "tor_api_call", 8, seed=seed))  # four repetitions
        assert len(repeated) == 4 and repeated <= CLOUD_TOR, seed  # a new exit per repetition


def test_aws_admin_identity_sequences_use_the_actor_kind_that_fired():
    events = build(aws, "iam_new_admin_identity", 5)
    assert names(events) == ["CreateRole", "AttachRolePolicy", "CreateUser", "PutUserPolicy", "AttachUserPolicy"]
    assert {e["userIdentity"]["type"] for e in events} == {"IAMUser"}
    assert "AdministratorAccess" in events[1]["requestParameters"]["policyArn"]
    assert "AdministratorAccess" in events[4]["requestParameters"]["policyArn"]
    assert "%22Action%22%3A%20%22%2A%22" in events[3]["requestParameters"]["policyDocument"]  # Action "*", URL-encoded
    assert events[2]["requestParameters"]["userName"] == events[3]["requestParameters"]["userName"]
    assert re.fullmatch(r"[A-Z][a-z]{2} \d{1,2}, 2026 \d{1,2}:\d{2}:\d{2} [AP]M", events[2]["responseElements"]["user"]["createDate"])

    events = build(aws, "iam_admin_user_credentials", 3)
    assert names(events) == ["CreateUser", "AttachUserPolicy", "CreateAccessKey"]
    assert {e["userIdentity"]["type"] for e in events} == {"AssumedRole"}
    assert len({e["requestParameters"]["userName"] for e in events}) == 1
    assert events[2]["responseElements"]["accessKey"]["accessKeyId"].startswith("AKIA")


def test_aws_access_keys_and_principal_ids_have_aws_shapes():
    for ev in build(aws, "iam_admin_user_credentials", 3) + build(aws, "pentest_tool", 6):
        ui = ev["userIdentity"]
        assert re.fullmatch(r"(AKIA|ASIA)[A-Z0-9]{16}", ui["accessKeyId"])
        assert re.fullmatch(r"AIDA[A-Z0-9]{17}|AROA[A-Z0-9]{17}:.+", ui["principalId"])


# -- gcp_audit ----------------------------------------------------------------------------------------------------

def test_gcp_entries_are_complete_audit_log_entries():
    for ev in build(gcp, "new_admin_service_account", 4):
        assert {"protoPayload", "insertId", "resource", "timestamp", "severity", "logName", "receiveTimestamp"} <= ev.keys()
        proto = ev["protoPayload"]
        assert proto["@type"].endswith("google.cloud.audit.AuditLog")
        assert {"serviceName", "methodName", "resourceName", "authenticationInfo", "requestMetadata", "authorizationInfo"} <= proto.keys()
        assert proto["requestMetadata"]["requestAttributes"]["time"] == ev["timestamp"]
        project = ev["resource"]["labels"]["project_id"]
        assert ev["logName"].startswith(f"projects/{project}/logs/cloudaudit.googleapis.com%2F")
        received = datetime.strptime(ev["receiveTimestamp"][:26] + "Z", "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
        assert when(gcp, ev) <= received <= NOW


def delta(ev):
    return ev["protoPayload"]["serviceData"]["policyDelta"]["bindingDeltas"][0]


def test_gcp_public_bucket_and_group_role_are_the_iam_deltas_that_fired():
    (bucket,) = build(gcp, "data_asset_public", 1)
    assert bucket["protoPayload"]["methodName"] == "storage.setIamPermissions"
    assert (delta(bucket)["member"], delta(bucket)["role"], delta(bucket)["action"]) == ("allUsers", "roles/storage.objectViewer", "ADD")
    (group,) = build(gcp, "sensitive_role_to_group", 1)
    assert (delta(group)["role"], delta(group)["action"]) == ("roles/owner", "ADD") and delta(group)["member"].startswith("group:")


def test_gcp_kubernetes_scenarios():
    (anon,) = build(gcp, "k8s_anonymous", 1)
    assert anon["protoPayload"]["authenticationInfo"]["principalEmail"] == "system:anonymous"
    assert anon["protoPayload"]["serviceName"] == "k8s.io" and "principalSubject" not in anon["protoPayload"]["authenticationInfo"]
    assert ippools.range_of(anon["protoPayload"]["requestMetadata"]["callerIp"]) in ippools.ABROAD
    scans = build(gcp, "k8s_vuln_scanner", 4)
    uas = [e["protoPayload"]["requestMetadata"]["callerSuppliedUserAgent"] for e in scans]
    assert len(set(uas)) == 4 and all(any(t in u.lower() for t in ("kube-hunter", "kubescape", "trivy", "kube-bench")) for u in uas)
    assert all(e["protoPayload"]["methodName"] == "io.k8s.core.v1.pods.list" for e in scans)


def test_gcp_tor_api_call_comes_from_distinct_tor_exits():
    for seed in range(25):
        events = build(gcp, "tor_api_call", 4, seed=seed)
        assert ips(gcp, events) <= CLOUD_TOR and len(ips(gcp, events)) == 4, seed
    assert {e["protoPayload"]["methodName"] for e in events} == {"storage.objects.get"}


def test_gcp_new_admin_service_account_creates_it_then_grants_owner_to_that_account():
    create, grant = build(gcp, "new_admin_service_account", 2)
    email = create["protoPayload"]["response"]["email"]
    assert create["protoPayload"]["methodName"] == "google.iam.admin.v1.CreateServiceAccount"
    assert delta(grant) == {"action": "ADD", "role": "roles/owner", "member": f"serviceAccount:{email}"}
    assert create["protoPayload"]["authenticationInfo"] == {**grant["protoPayload"]["authenticationInfo"]}


# -- azure_ad_audit -----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("scenario,activity,category", [
    ("ca_policy_deleted", "Delete conditional access policy", "Policy"),
    ("pim_alert_disabled", "Disable PIM Alert", "RoleManagement"),
    ("pim_role_setting_changed", "Update role setting in PIM", "RoleManagement"),
    ("federation_modified", "Set federation settings on domain", "DirectoryManagement"),
    ("unverified_domain_added", "Add unverified domain", "DirectoryManagement"),
])
def test_azure_scenarios_are_one_directory_audit_operation(scenario, activity, category):
    for ev in build(azure, scenario, 3):
        assert ev["activityDisplayName"] == activity and ev["category"] == category and ev["result"] == "success"
        assert ev["initiatedBy"]["user"]["userPrincipalName"].endswith(f".adm@{domain()}") and ev["initiatedBy"]["app"] is None
        assert re.fullmatch(r"Directory_[0-9a-f-]{36}_\d{5}", ev["id"]) and ev["targetResources"]
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{7}Z", ev["activityDateTime"])


def test_azure_domain_scenarios_invent_a_new_domain_every_call():
    names_ = set()
    for _ in range(3):
        for scenario in ("federation_modified", "unverified_domain_added"):
            (ev,) = build(azure, scenario, 1, seed=None)
            names_.add(ev["targetResources"][0]["displayName"])
    assert len(names_) == 6 and all(n.endswith(".example") for n in names_)
    (fed,) = build(azure, "federation_modified", 1)
    props = {p["displayName"]: (p["oldValue"], p["newValue"]) for p in fed["targetResources"][0]["modifiedProperties"]}
    assert props["LiveType"] == ("Managed", "Federated") and props["IssuerUri"][0] is None


# -- okta: tor_signin and fastpass_phishing -----------------------------------------------------------------------

def okta_build(scenario, count=6, **kw):
    kw.setdefault("seed", 5)
    return okta.build_events(scenario, count, view=get_view(), now=NOW, **kw)


def test_the_okta_profile_lists_the_two_cribl_scenarios_and_their_destination():
    assert okta.SCENARIOS[-2:] == ("tor_signin", "fastpass_phishing")
    assert okta.SCENARIO_DESTINATION == {"tor_signin": "cribl_okta_sso", "fastpass_phishing": "cribl_okta_sso",
                                         "mfa_fatigue": "cribl_okta_sso", "failed_then_success": "cribl_okta_sso"}
    assert okta.CRIBL_ONLY_SCENARIOS == ("tor_signin", "fastpass_phishing")
    assert okta.CRIBL_DESTINATIONS == ("cribl_okta_sso",) and not getattr(okta, "CRIBL_ONLY", False)


def test_tor_signin_is_successful_sso_by_baseline_users_from_distinct_tor_exits_and_new_apps():
    events = okta_build("tor_signin", 8)
    assert {e["eventType"] for e in events} == {"user.authentication.sso"} and {e["outcome"]["result"] for e in events} == {"SUCCESS"}
    assert ips(okta, events) <= OKTA_TOR and len(ips(okta, events)) == 8
    pool = {p["email"] for p in _org.logon_people(get_view())}
    assert {e["actor"]["alternateId"] for e in events} <= pool and len({e["actor"]["alternateId"] for e in events}) > 1
    for ev in events:
        assert ev["securityContext"]["isProxy"] is True and ev["securityContext"]["domain"] == "torproject.org"
        assert ev["client"]["userAgent"]["browser"] == "CHROME" and ev["client"]["device"] == "Computer"
        assert ev["target"][0]["type"] == "AppInstance"
    apps = [e["target"][0]["displayName"] for e in events]
    assert len(set(apps)) == 8 and not set(apps) & set(okta._APPS)
    assert not set(apps) & {e["target"][0]["displayName"] for e in okta_build("tor_signin", 8, seed=6)}  # fresh apps per call


def test_tor_signin_target_user_and_source_ip_overrides():
    events = okta_build("tor_signin", 3, target_user="DOMAIN\\Mona.Alessa", source_ip="185.220.101.140")
    assert {e["actor"]["alternateId"] for e in events} == {person("malessa")["email"]} and ips(okta, events) == {"185.220.101.140"}
    other = okta_build("tor_signin", 3, source_ip="203.0.113.5")  # an exit that is not in the snapshot still gets the Tor flags
    assert other[0]["securityContext"]["isProxy"] is True and ips(okta, other) == {"203.0.113.5"}


def test_fastpass_phishing_is_the_measured_blocked_phishing_shape_with_a_new_user_and_exit_each_time():
    events = okta_build("fastpass_phishing", 6)
    assert len({e["actor"]["alternateId"] for e in events}) == 6 and len(ips(okta, events)) == 6 and ips(okta, events) <= OKTA_TOR
    for ev in events:
        assert ev["eventType"] == "user.authentication.auth_via_mfa" and ev["outcome"] == {
            "result": "FAILURE", "reason": "FastPass declined phishing attempt"}
        assert ev["actor"]["alternateId"].startswith("fastpass.phishing.") and ev["actor"]["alternateId"].endswith(f"@{domain()}")
        dbg = ev["debugContext"]["debugData"]
        assert dbg["threatSuspected"] == "true" and dbg["risk"] == "{level=HIGH}" and dbg["factor"] == "SIGNED_NONCE"
        assert json.loads(dbg["threatDetections"]) == {"Phishing Attempt Blocked": "HIGH"}  # JSON-encoded STRINGS, as measured
        assert json.loads(dbg["logOnlySecurityData"])["originCheckResult"] == "MISMATCH"
        assert len(dbg["dtHash"]) == 64 and len(dbg["deviceFingerprint"]) == 32
        assert ev["authenticationContext"]["credentialType"] == "SIGNED_NONCE"
        assert ev["authenticationContext"]["authenticationProvider"] == "FACTOR_PROVIDER"
        assert ev["device"]["id"].startswith("guo") and len(ev["device"]["id"]) == 22
        assert ev["securityContext"]["isProxy"] is True and ev["client"]["geographicalContext"]["country"]
        assert "login-okta-verify.co/" not in dbg["logOnlySecurityData"]  # only a reserved, non-resolving host
    other = okta_build("fastpass_phishing", 6, seed=6)
    assert not {e["actor"]["alternateId"] for e in events} & {e["actor"]["alternateId"] for e in other}


@pytest.mark.parametrize("scenario", ["tor_signin", "fastpass_phishing"])
def test_the_okta_cribl_scenarios_honour_the_time_window(scenario):
    events = okta_build(scenario, 10, spread_seconds=600, start_offset_minutes=30)
    times = [when(okta, e) for e in events]
    end = NOW - timedelta(minutes=30)
    assert times == sorted(times) and times[-1] == end and times[0] == end - timedelta(seconds=600)
    assert len({e["uuid"] for e in events}) == 10


# -- hygiene ------------------------------------------------------------------------------------------------------

def test_no_real_tenant_names_or_credentials_in_the_source():
    banned = ("xlabpov", "x-lab", "acme-pov", "ACME_CRIBL", "ACME_XSIAM", "PHANTOM_KEY", "BEGIN PRIVATE KEY")
    for path in (Path(__file__).resolve().parents[1] / "src").rglob("*.py"):
        text = path.read_text()
        for needle in banned:
            assert needle not in text, f"{needle!r} in {path.name}"
