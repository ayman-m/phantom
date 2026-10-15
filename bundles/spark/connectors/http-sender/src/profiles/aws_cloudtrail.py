"""The `aws_cloudtrail` event profile: synthetic AWS CloudTrail records (eventVersion 1.11).

Each event is one CloudTrail record object, the vendor shape the Cortex `aws_audit` Cribl source parses into
`amazon_aws_raw` and normalizes into `cloud_audit_logs`. It is meant for the `cribl_aws_audit` destination:
the dedicated Source-Identifier makes Cortex treat the records as a native AWS feed, which is what the Cloud
analytics detectors read (measured on a Cortex tenant: 15 alerts for 13 detectors). The generic HTTP
collector does not give that treatment.

Every scenario replays ONE measured detector shape (the variant that fired, not the ones that stayed silent: the
backup-vault policy fired for an IAM user with a foreign-account principal and stayed silent through an assumed
role; "new identity with an administrative policy" needs an IAM user, not a role). A scenario is a short recipe of
1-5 steps by one actor; `count` repeats it with fresh resource ids.

The account and region are the organization's (`cloud.aws`). Everything else is generated per call: the IAM user / role /
session names of an actor the recipe mints, access keys, principal ids, bucket and resource ids, and the unrelated foreign
account an attack names. A replay therefore looks like a first-time actor. Addresses are real: ordinary actors come
from the Saudi home pool, a pen-testing tool from an out-of-country range, and the Tor scenario from a Tor exit.
`eventTime` is UTC at second precision, as CloudTrail writes it. `target_user` names one of the organization's people (login,
email or the part before the @); the IAM user or role session then carries the email's local part and the calls come from
that person's own home address.

`benign_activity` is the baseline the attack scenarios contrast with, and its rule is the opposite: the identities are
STABLE. The organization's people who may log on and have AWS access (`cloud_access`) as IAM users, one home address each
(`home_ip`), and four ordinary roles, in the organization's account, every name, principal id and access key a pure function
of the name, so the same people appear on every call. Their calls are ordinary and read-heavy (console sign-in, S3 list and
read, EC2/RDS/Lambda describe, IAM list, GetCallerIdentity, AssumeRole into their usual roles); none of them is a shape one
of the detectors above fired on.
"""
from __future__ import annotations

import json
import random
import urllib.parse
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from runtime.organization_view import OrganizationView

from . import _fresh, _org, ippools
from . import okta
from .okta import _times

# The profile interface (see profiles/__init__.py).
NAME = "aws_cloudtrail"
DESCRIPTION = ("AWS CloudTrail records for the cribl_aws_audit destination: GuardDuty/Bedrock/Route53 logging removed, "
               "public S3 / snapshots, open security group, backup policy, pen-test tool, Tor API call, admin IAM identities; "
               "benign_activity is a stable pool of users and roles doing ordinary read-heavy calls.")
EXPECTED_DATASET = "cribl_aws_audit"
EXPECTED_DATASETS = ("cribl_aws_audit",)
# Cribl destinations that suit this profile; CRIBL_ONLY: never fall back to a non-Cribl primary destination.
CRIBL_DESTINATIONS = ("cribl_aws_audit",)
DEFAULT_DESTINATION = "cribl_aws_audit"
CRIBL_ONLY = True
TEST_ID_FIELD = "eventID"
TIME_FIELD = "eventTime"

_UA_SDK = ("Boto3/1.34.69 md/Botocore#1.34.69 ua/2.0 os/linux#{os} md/arch#x86_64 lang/python#3.11.8 md/pyimpl#CPython "
           "cfg/retry-mode#legacy Botocore/1.34.69")
_PENTEST_UAS = (
    _UA_SDK.format(os="6.5.0-kali3-amd64"),
    _UA_SDK.format(os="6.5.0-parrot1-amd64"),
    _UA_SDK.format(os="6.5.0") + " Pacu/1.5.4",
    _UA_SDK.format(os="6.5.0") + " APN/1.0 PRV/1.0 Prowler/4.2.1",
    _UA_SDK.format(os="6.5.0") + " Scout Suite/5.13.0",
    "aws-sdk-go-v2/1.26.1 os/linux lang/go#1.22.1 md/GOOS#linux md/GOARCH#amd64 api/iam#1.32.0 cloudfox",
)


def _iso(ts: datetime) -> str:
    return ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _legacy(ts: datetime) -> str:
    """The `createDate` form IAM responses carry in CloudTrail: `Oct 4, 2026 5:40:00 PM`."""
    return f"{ts:%b} {ts.day}, {ts.year} {ts.hour % 12 or 12}:{ts:%M:%S} {ts:%p}"


def _policy(doc: dict[str, Any]) -> str:
    """CloudTrail URL-encodes policy documents it records."""
    return urllib.parse.quote(json.dumps(doc, indent=2))


class _Principal:
    """A synthetic IAM user, or an assumed role with its session."""

    def __init__(self, c: "_Ctx", kind: str, name: str, session: str | None = None,
                 person: dict[str, Any] | None = None) -> None:
        self.c, self.kind, self.name, self.session = c, kind, name, session
        user = kind == "IAMUser"
        self.pid = ("AIDA" if user else "AROA") + _fresh.rid(c.rng, 17)
        self.key = ("AKIA" if user else "ASIA") + _fresh.rid(c.rng, 16)
        self.ip = c.home_ip()  # drawn even for a named person, so every other value of a seeded call is the same either way
        if person is not None:
            self.ip = _org.home(person)[0]
        self.mfa = "false"

    def ui(self) -> dict[str, Any]:
        c = self.c
        attrs = {"creationDate": _iso(c.session_start), "mfaAuthenticated": self.mfa}
        if self.kind == "IAMUser":
            return {"type": "IAMUser", "principalId": self.pid, "arn": f"arn:aws:iam::{c.acct}:user/{self.name}",
                    "accountId": c.acct, "accessKeyId": self.key, "userName": self.name,
                    "sessionContext": {"attributes": attrs}}
        sess = self.session or f"{self.name}-session"
        return {"type": "AssumedRole", "principalId": f"{self.pid}:{sess}",
                "arn": f"arn:aws:sts::{c.acct}:assumed-role/{self.name}/{sess}", "accountId": c.acct,
                "accessKeyId": self.key,
                "sessionContext": {"sessionIssuer": {"type": "Role", "principalId": self.pid,
                                                      "arn": f"arn:aws:iam::{c.acct}:role/{self.name}",
                                                      "accountId": c.acct, "userName": self.name},
                                   "attributes": attrs}}


class _Ctx:
    """Per-call state: the organization, the random source, the account ids, and the window the events fall in."""

    def __init__(self, seed: int | None, end: datetime, spread_seconds: int, view: OrganizationView) -> None:
        self.view = view
        self.rng = random.Random(seed)
        cloud = _org.cloud(view, "aws", "account_id", "region")
        _fresh.digits(self.rng, 12)  # the account id this call used to invent: the draw stays so a seeded call's other values do not move
        self.acct = cloud["account_id"]  # the organization's account
        self.region = cloud["region"]
        prefix = _org.bucket_prefix(view)
        self.buckets = {f"{prefix}-{name}": keys for name, keys in _BUCKET_OBJECTS.items()}
        self.sessions: dict[tuple[int, str], _Principal] = {}  # (user index, role) -> the role session: it keeps its temporary key for the whole call
        self.foreign = _fresh.digits(self.rng, 12)  # an unrelated external account
        self.tor = ippools.tor_exits(self.rng, len(ippools.CLOUD_TOR_EXITS), ippools.CLOUD_TOR_EXITS)  # drawn once: a different exit per repetition
        # The actors' sessions began before the first event of the window.
        self.session_start = end - timedelta(seconds=max(spread_seconds, 0) + 900)

    def hexs(self, n: int) -> str:
        return _fresh.hexs(self.rng, n)

    def guid(self) -> str:
        return _fresh.guid(self.rng)

    def home_ip(self) -> str:
        return ippools.home_for(self.rng.randrange(len(ippools.HOME)))[0]

    def user(self, person: dict[str, Any] | None, prefix: str | None = None) -> _Principal:
        """The acting IAM user: the organization's `person` named by the caller, else one the recipe mints fresh."""
        name = _org.local_part(person) if person else None
        return _Principal(self, "IAMUser", name or (f"{prefix}-{self.hexs(6)}" if prefix else _fresh.handle(self.rng)), person=person)

    def role(self, base: str, person: dict[str, Any] | None) -> _Principal:
        """A session of role `base`: named after the organization's `person` the caller named, else after a fresh one."""
        session = _org.local_part(person) if person else None
        return _Principal(self, "AssumedRole", f"{base}-{self.hexs(6)}", session=session or _fresh.handle(self.rng), person=person)

    def rec(self, who: _Principal, source: str, name: str, params: Any = None, resp: Any = None, *,
            ip: str | None = None, ua: str | None = None, read_only: bool = False,
            extra: dict[str, Any] | None = None, region: str | None = None) -> dict[str, Any]:
        service = source.split(".")[0]
        region = region or self.region
        event = {
            "eventVersion": "1.11", "userIdentity": who.ui(), "eventTime": "", "eventSource": source, "eventName": name,
            "awsRegion": region, "sourceIPAddress": ip or who.ip,
            "userAgent": ua or ("aws-cli/2.15.30 md/awscrt#0.19.19 ua/2.0 os/macos#23.4.0 md/arch#arm64 lang/python#3.11.8 "
                                f"md/pyimpl#CPython cfg/retry-mode#standard md/installer#exe md/prompt#off md/command#{service}.{name}"),
            "requestParameters": params, "responseElements": resp, "requestID": self.guid(), "eventID": self.guid(),
            "readOnly": read_only, "eventType": "AwsApiCall", "managementEvent": True, "recipientAccountId": self.acct,
            "eventCategory": "Management",
            "tlsDetails": {"tlsVersion": "TLSv1.3", "cipherSuite": "TLS_AES_128_GCM_SHA256",
                           "clientProvidedHostHeader": f"{service}.{region}.amazonaws.com"},
        }
        if extra:
            event.update(extra)
        return event


# -- scenario recipes: (c, actor, repetition, source_ip) -> one repetition's events --------------------------------------

def _guardduty_detector_deleted(c, who, k, src):
    return [c.rec(who, "guardduty.amazonaws.com", "DeleteDetector", {"detectorId": c.hexs(32)})]


def _s3_public_exposure(c, who, k, src):
    bucket = "acme-reports-" + c.hexs(6)
    host = f"{bucket}.s3.{c.region}.amazonaws.com"
    return [
        c.rec(who, "s3.amazonaws.com", "PutBucketPolicy",
              {"bucketName": bucket, "Host": host, "bucketPolicy": {"Version": "2012-10-17", "Statement": [
                  {"Sid": "PublicRead", "Effect": "Allow", "Principal": "*", "Action": "s3:GetObject",
                   "Resource": f"arn:aws:s3:::{bucket}/*"}]}}, None,
              extra={"additionalEventData": {"SignatureVersion": "SigV4", "CipherSuite": "TLS_AES_128_GCM_SHA256",
                                             "bytesTransferredIn": 342, "AuthenticationMethod": "AuthHeader",
                                             "x-amz-id-2": c.hexs(24), "bytesTransferredOut": 0}}),
        c.rec(who, "s3.amazonaws.com", "PutBucketAcl",
              {"bucketName": bucket, "Host": host, "acl": {"AccessControlPolicy": {"AccessControlList": {"Grant": [
                  {"Grantee": {"xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance", "xsi:type": "Group",
                               "URI": "http://acs.amazonaws.com/groups/global/AllUsers"}, "Permission": "READ"}]},
                  "xmlns": "http://s3.amazonaws.com/doc/2006-03-01/"}}}, None),
        c.rec(who, "s3.amazonaws.com", "DeletePublicAccessBlock", {"bucketName": bucket, "Host": host, "publicAccessBlock": ""}, None),
    ]


def _security_group_open(c, who, k, src):
    group = "sg-" + c.hexs(17)
    external = src or ippools.abroad_pick(c.rng)[0]

    def ingress(port: int, cidr: str, description: str) -> dict[str, Any]:
        rule = {"ipProtocol": "tcp", "fromPort": port, "toPort": port}
        return c.rec(
            who, "ec2.amazonaws.com", "AuthorizeSecurityGroupIngress",
            {"groupId": group, "ipPermissions": {"items": [{**rule, "groups": {}, "ipRanges": {
                "items": [{"cidrIp": cidr, "description": description}]}, "ipv6Ranges": {}, "prefixListIds": {}}]}},
            {"requestId": c.guid(), "_return": True, "securityGroupRuleSet": {"items": [{
                "groupOwnerId": c.acct, "groupId": group, "securityGroupRuleId": "sgr-" + c.hexs(17),
                "isEgress": False, **rule, "cidrIpv4": cidr}]}})

    return [ingress(22, f"{external}/32", "temp vendor access"), ingress(3389, "0.0.0.0/0", "rdp")]


def _bedrock_logging_deleted(c, who, k, src):
    return [c.rec(who, "bedrock.amazonaws.com", "DeleteModelInvocationLoggingConfiguration")]


def _route53_logging_deleted(c, who, k, src):
    config = "rslvr-qlc-" + c.hexs(17)
    return [c.rec(who, "route53resolver.amazonaws.com", "DeleteResolverQueryLogConfig", {"resolverQueryLogConfigId": config},
                  {"resolverQueryLogConfig": {
                      "id": config, "ownerId": c.acct, "status": "DELETING", "shareStatus": "NOT_SHARED", "associationCount": 0,
                      "arn": f"arn:aws:route53resolver:{c.region}:{c.acct}:resolver-query-log-config/{config}",
                      "name": "vpc-dns-query-logs", "destinationArn": "arn:aws:s3:::acme-dns-logs-" + c.hexs(6),
                      "creatorRequestId": c.hexs(32), "creationTime": _iso(c.session_start - timedelta(days=30))[:-1] + ".123Z"}})]


def _backup_vault_policy_modified(c, who, k, src):
    # A foreign-account principal allowed to copy into the vault. The same policy through an assumed role, a
    # Principal "*" Allow and a Deny-all stayed silent, so the actor is an IAM user.
    policy = {"Version": "2012-10-17", "Statement": [{"Sid": "x", "Effect": "Allow", "Principal": {
        "AWS": f"arn:aws:iam::{c.foreign}:root"}, "Action": ["backup:CopyIntoBackupVault"], "Resource": "*"}]}
    return [c.rec(who, "backup.amazonaws.com", "PutBackupVaultAccessPolicy",
                  {"backupVaultName": "finance-vault-" + c.hexs(4), "policy": json.dumps(policy)})]


def _pentest_tool(c, who, k, src):
    ip = src or ippools.abroad_pick(c.rng)[0]
    return [c.rec(who, "iam.amazonaws.com", "ListRoles", ua=ua, ip=ip, read_only=True) for ua in _PENTEST_UAS]


def _snapshot_public_share(c, who, k, src):
    # One EBS and one RDS snapshot shared with `all`: the three "snapshot ... public" detectors read these two.
    snap = "prod-db-snap-" + c.hexs(6)
    return [
        c.rec(who, "ec2.amazonaws.com", "ModifySnapshotAttribute",
              {"snapshotId": "snap-" + c.hexs(17), "attributeType": "CREATE_VOLUME_PERMISSION",
               "createVolumePermission": {"add": {"items": [{"group": "all"}]}}}, {"requestId": c.guid(), "_return": True}),
        c.rec(who, "rds.amazonaws.com", "ModifyDBSnapshotAttribute",
              {"dBSnapshotIdentifier": snap, "attributeName": "restore", "valuesToAdd": ["all"]},
              {"dBSnapshotAttributesResult": {"dBSnapshotIdentifier": snap, "dBSnapshotAttributes": [
                  {"attributeName": "restore", "attributeValues": ["all"]}]}}),
    ]


def _ebs_encryption_disabled(c, who, k, src):
    return [c.rec(who, "ec2.amazonaws.com", "DisableEbsEncryptionByDefault", {"DisableEbsEncryptionByDefaultRequest": ""},
                  {"requestId": c.guid(), "ebsEncryptionByDefault": False})]


def _tor_api_call(c, who, k, src):
    # Two read calls from a Tor exit; fires both "Suspicious API call from a Tor exit node" and the high-risk-IP detector.
    ip = src or c.tor[k % len(c.tor)].ip
    return [c.rec(who, "iam.amazonaws.com", "ListUsers", ip=ip, read_only=True),
            c.rec(who, "s3.amazonaws.com", "ListBuckets", ip=ip, read_only=True)]


def _iam_new_admin_identity(c, who, k, src):
    # The sequence that fired "New cloud identity created with administrative policy" (an IAM user acting).
    foreign_trust = {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Principal": {
        "AWS": f"arn:aws:iam::{c.foreign}:root"}, "Action": "sts:AssumeRole"}]}
    role, user = "external-audit-" + c.hexs(4), "audit-bot-" + c.hexs(4)
    created = _legacy(c.session_start + timedelta(minutes=14))
    return [
        c.rec(who, "iam.amazonaws.com", "CreateRole",
              {"roleName": role, "assumeRolePolicyDocument": _policy(foreign_trust), "description": "external audit access"},
              {"role": {"path": "/", "roleName": role, "roleId": "AROA" + _fresh.rid(c.rng, 17),
                        "arn": f"arn:aws:iam::{c.acct}:role/{role}", "createDate": created,
                        "assumeRolePolicyDocument": _policy(foreign_trust)}}, ua=_UA_SDK.format(os="5.15.0")),
        c.rec(who, "iam.amazonaws.com", "AttachRolePolicy", {"roleName": role, "policyArn": "arn:aws:iam::aws:policy/AdministratorAccess"}),
        c.rec(who, "iam.amazonaws.com", "CreateUser", {"userName": user},
              {"user": {"path": "/", "userName": user, "userId": "AIDA" + _fresh.rid(c.rng, 17),
                        "arn": f"arn:aws:iam::{c.acct}:user/{user}", "createDate": created}}),
        c.rec(who, "iam.amazonaws.com", "PutUserPolicy",
              {"userName": user, "policyName": "full", "policyDocument": _policy(
                  {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": "*", "Resource": "*"}]})}),
        c.rec(who, "iam.amazonaws.com", "AttachUserPolicy", {"userName": user, "policyArn": "arn:aws:iam::aws:policy/AdministratorAccess"}),
    ]


def _iam_admin_user_credentials(c, who, k, src):
    # An assumed role creates a user, gives it AdministratorAccess and mints an access key for it.
    user = "svc-" + c.hexs(5)
    return [
        c.rec(who, "iam.amazonaws.com", "CreateUser", {"userName": user},
              {"user": {"path": "/", "userName": user, "userId": "AIDA" + _fresh.rid(c.rng, 17),
                        "arn": f"arn:aws:iam::{c.acct}:user/{user}", "createDate": _legacy(c.session_start + timedelta(minutes=14))}}),
        c.rec(who, "iam.amazonaws.com", "AttachUserPolicy", {"userName": user, "policyArn": "arn:aws:iam::aws:policy/AdministratorAccess"}),
        c.rec(who, "iam.amazonaws.com", "CreateAccessKey", {"userName": user},
              {"accessKey": {"accessKeyId": "AKIA" + _fresh.rid(c.rng, 16), "status": "Active", "userName": user,
                             "createDate": _legacy(c.session_start + timedelta(minutes=14))}}),
    ]


def _stamp(event: dict[str, Any], when: datetime) -> None:
    event["eventTime"] = _iso(when)


# -- benign_activity: a stable pool, ordinary calls ------------------------------------------------------------------------

BENIGN_SCENARIOS = ("benign_activity",)
BENIGN_ROLES = ("DataAnalyst", "ReadOnlyAuditor", "AppSupport", "BillingViewer")
# The buckets of the stable pool by name suffix; the organization's id is the prefix (`phantom-lab-reports`).
_BUCKET_OBJECTS = {
    "reports": ("reports/q3/summary.csv", "reports/q3/headcount.xlsx", "reports/q4/forecast.pdf"),
    "datalake": ("sales/2026/09/part-0001.parquet", "sales/2026/09/part-0002.parquet", "web/2026/09/clicks.parquet"),
    "app-assets": ("img/logo.png", "css/site.min.css", "js/app.bundle.js"),
    "exports": ("daily/orders.csv", "daily/returns.csv", "weekly/inventory.csv"),
}
_BENIGN_OPS = (("GetObject", 18), ("ListBuckets", 12), ("DescribeInstances", 12), ("GetCallerIdentity", 10),
               ("ListObjectsV2", 10), ("ConsoleLogin", 8), ("AssumeRole", 8), ("ListUsers", 5), ("DescribeSecurityGroups", 5),
               ("DescribeVolumes", 4), ("GetBucketLocation", 3), ("ListFunctions", 3), ("DescribeDBInstances", 2))
# Operations an assumed role does not do: the sign-in is a person's, and a role does not assume a role here.
_USER_ONLY = ("ConsoleLogin", "AssumeRole")
_BROWSERS = tuple(agent[0] for agent in okta._AGENTS[:2])


def _benign_user(c: _Ctx, index: int) -> _Principal:
    """IAM user number `index` of the stable pool (a person of the organization): name, principal id, access key and home
    address are pure functions of the person."""
    person = c.pool[index]
    name = _org.local_part(person)
    who = _Principal(c, "IAMUser", name)
    who.pid = "AIDA" + _fresh.stable(f"aws|user|{name}", 17, _fresh.UPPER_DIGITS)
    who.key = "AKIA" + _fresh.stable(f"aws|key|{name}", 16, _fresh.UPPER_DIGITS)
    who.ip = _org.home(person)[0]
    who.mfa = "true" if index % 3 else "false"
    return who


def _benign_role(c: _Ctx, user: _Principal, index: int, role: str) -> _Principal:
    """`user` acting through `role`: the role's id is stable, the session is named after the person, the credentials are
    temporary (new per call, as a real session's are, but one key per session within a call)."""
    who = _Principal(c, "AssumedRole", role, session=user.name)
    who.pid = "AROA" + _fresh.stable(f"aws|role|{role}", 17, _fresh.UPPER_DIGITS)
    who.ip = user.ip
    who.mfa = user.mfa
    return who


def _usual_roles(index: int) -> tuple[str, str]:
    return BENIGN_ROLES[index % len(BENIGN_ROLES)], BENIGN_ROLES[(index + 1) % len(BENIGN_ROLES)]


def _benign_call(c: _Ctx, op: str, index: int, user: _Principal) -> dict[str, Any]:
    """One ordinary call. `ConsoleLogin` and `AssumeRole` are the person's own; the rest are done by the person or by a
    session of one of their usual roles."""
    if op == "ConsoleLogin":
        mfa = "Yes" if user.mfa == "true" else "No"
        identity = {"type": "IAMUser", "principalId": user.pid, "arn": f"arn:aws:iam::{c.acct}:user/{user.name}",
                    "accountId": c.acct, "userName": user.name}
        event = c.rec(user, "signin.amazonaws.com", "ConsoleLogin", None, {"ConsoleLogin": "Success"}, ua=_BROWSERS[index % 2],
                      extra={"userIdentity": identity, "eventType": "AwsConsoleSignIn",
                             "additionalEventData": {"LoginTo": f"https://console.aws.amazon.com/console/home?state=hashArgsFromTB_{c.region}_" + c.hexs(16),
                                                     "MobileVersion": "No", "MFAUsed": mfa}})
        del event["tlsDetails"]  # a console sign-in record carries none
        return event
    if op == "AssumeRole":
        role = c.rng.choice(_usual_roles(index))
        role_id = "AROA" + _fresh.stable(f"aws|role|{role}", 17, _fresh.UPPER_DIGITS)
        expires = _legacy(c.session_start + timedelta(hours=1, minutes=15))
        return c.rec(user, "sts.amazonaws.com", "AssumeRole",
                     {"roleArn": f"arn:aws:iam::{c.acct}:role/{role}", "roleSessionName": user.name, "durationSeconds": 3600},
                     {"credentials": {"accessKeyId": "ASIA" + _fresh.rid(c.rng, 16), "sessionToken": c.hexs(48), "expiration": expires},
                      "assumedRoleUser": {"assumedRoleId": f"{role_id}:{user.name}",
                                          "arn": f"arn:aws:sts::{c.acct}:assumed-role/{role}/{user.name}"}}, read_only=True)
    # A person acts as themself two times in three, otherwise through one of their usual roles.
    who = user
    if c.rng.random() >= 0.65:
        role = c.rng.choice(_usual_roles(index))
        who = c.sessions.get((index, role)) or c.sessions.setdefault((index, role), _benign_role(c, user, index, role))
    bucket = c.rng.choice(sorted(c.buckets))
    host = f"{bucket}.s3.{c.region}.amazonaws.com"
    if op == "GetObject":
        key = c.rng.choice(c.buckets[bucket])
        return c.rec(who, "s3.amazonaws.com", "GetObject", {"bucketName": bucket, "Host": host, "key": key}, None, read_only=True,
                     extra={"managementEvent": False, "eventCategory": "Data",
                            "resources": [{"type": "AWS::S3::Object", "ARN": f"arn:aws:s3:::{bucket}/{key}"},
                                          {"accountId": c.acct, "type": "AWS::S3::Bucket", "ARN": f"arn:aws:s3:::{bucket}"}],
                            "additionalEventData": {"SignatureVersion": "SigV4", "CipherSuite": "TLS_AES_128_GCM_SHA256",
                                                    "bytesTransferredIn": 0, "AuthenticationMethod": "AuthHeader",
                                                    "x-amz-id-2": c.hexs(24), "bytesTransferredOut": c.rng.randint(2_000, 900_000)}})
    if op == "ListObjectsV2":
        return c.rec(who, "s3.amazonaws.com", "ListObjects", {"list-type": "2", "bucketName": bucket, "Host": host, "prefix": "", "delimiter": "/"},
                     None, read_only=True)
    if op == "GetBucketLocation":
        return c.rec(who, "s3.amazonaws.com", "GetBucketLocation", {"bucketName": bucket, "Host": host, "location": ""}, None, read_only=True)
    if op == "ListBuckets":
        return c.rec(who, "s3.amazonaws.com", "ListBuckets", read_only=True)
    if op == "ListUsers":
        return c.rec(who, "iam.amazonaws.com", "ListUsers", read_only=True)
    if op == "GetCallerIdentity":
        return c.rec(who, "sts.amazonaws.com", "GetCallerIdentity", read_only=True)
    if op == "DescribeInstances":
        return c.rec(who, "ec2.amazonaws.com", "DescribeInstances", {"instancesSet": {}, "filterSet": {}}, None, read_only=True)
    if op == "DescribeSecurityGroups":
        return c.rec(who, "ec2.amazonaws.com", "DescribeSecurityGroups", {"securityGroupSet": {}, "securityGroupIdSet": {}, "filterSet": {}},
                     None, read_only=True)
    if op == "DescribeVolumes":
        return c.rec(who, "ec2.amazonaws.com", "DescribeVolumes", {"volumeSet": {}, "filterSet": {}}, None, read_only=True)
    if op == "ListFunctions":
        return c.rec(who, "lambda.amazonaws.com", "ListFunctions20150331", None, None, read_only=True)
    return c.rec(who, "rds.amazonaws.com", "DescribeDBInstances", {}, None, read_only=True)


def _benign_activity(c: _Ctx, count: int, end: datetime, spread_seconds: int) -> list[dict[str, Any]]:
    """`count` ordinary calls by the stable pool, at random moments of the window (the first at its start, the last at `end`)."""
    c.pool = _org.cloud_people(c.view, "aws")
    out = []
    for _ in range(count):
        index = c.rng.randrange(len(c.pool))
        op = _fresh.weighted(c.rng, _BENIGN_OPS)
        out.append(_benign_call(c, op, index, _benign_user(c, index)))
    for event, when in zip(out, _fresh.jittered_times(c.rng, end, count, spread_seconds)):
        _stamp(event, when)
    return out


# scenario -> (who acts, recipe, steps in one repetition)
_user = lambda prefix=None: (lambda c, person: c.user(person, prefix))  # noqa: E731
_role = lambda base: (lambda c, person: c.role(base, person))  # noqa: E731
_TABLE: dict[str, tuple[Callable, Callable, int]] = {
    "guardduty_detector_deleted": (_role("DevOpsEngineer"), _guardduty_detector_deleted, 1),
    "s3_public_exposure": (_user(), _s3_public_exposure, 3),
    "security_group_open": (_role("DevOpsEngineer"), _security_group_open, 2),
    "bedrock_logging_deleted": (_user(), _bedrock_logging_deleted, 1),
    "route53_logging_deleted": (_role("ci-deploy-runner"), _route53_logging_deleted, 1),
    "backup_vault_policy_modified": (_user(), _backup_vault_policy_modified, 1),
    "pentest_tool": (_user("svc-audit"), _pentest_tool, len(_PENTEST_UAS)),
    "snapshot_public_share": (_role("DevOpsEngineer"), _snapshot_public_share, 2),
    "ebs_encryption_disabled": (_role("DevOpsEngineer"), _ebs_encryption_disabled, 1),
    "tor_api_call": (_user(), _tor_api_call, 2),
    "iam_new_admin_identity": (_user(), _iam_new_admin_identity, 5),
    "iam_admin_user_credentials": (_role("PlatformAdmin"), _iam_admin_user_credentials, 3),
}
SCENARIOS = tuple(_TABLE) + BENIGN_SCENARIOS
# The fewest events that make a scenario's recipe complete (a larger count repeats the recipe). Benign: any count.
MIN_COUNT = {name: steps for name, (_, _, steps) in _TABLE.items()}
# What an omitted `count` means for a scenario that is not a recipe.
DEFAULT_COUNT = {"benign_activity": 20}


def build_events(
    scenario: str, count: int, *, view: OrganizationView, now: datetime,
    spread_seconds: int = 120, start_offset_minutes: int = 0,
    target_user: str | None = None, source_ip: str | None = None, seed: int | None = None,
) -> list[dict[str, Any]]:
    """Build `count` CloudTrail records for `scenario`, oldest first.

    The window ends `start_offset_minutes` before `now` and is `spread_seconds` wide; nothing is dated after `now`.
    `target_user` names the acting IAM user (or the role session): one of the organization's people (`view`), whose home
    address the calls then come from; `source_ip` is the external address of the scenarios that have one
    (security_group_open, pentest_tool, tor_api_call). `benign_activity` ignores `target_user` and `source_ip`: its actors
    and addresses are the stable pool's.
    """
    if scenario not in SCENARIOS:
        raise ValueError(f"unknown scenario {scenario!r}; choose one of {', '.join(SCENARIOS)}")
    if count < 1:
        raise ValueError("count must be at least 1")
    if count < MIN_COUNT.get(scenario, 1):
        raise ValueError(f"{scenario} needs count >= {MIN_COUNT[scenario]}")
    end = now - timedelta(minutes=max(start_offset_minutes, 0))
    c = _Ctx(seed, end, spread_seconds, view)
    if scenario == "benign_activity":
        return _benign_activity(c, count, end, spread_seconds)
    actor, recipe, _ = _TABLE[scenario]
    who = actor(c, _org.resolve(view, target_user) if _fresh.bare_name(target_user) else None)
    return _fresh.run_recipe(lambda k: recipe(c, who, k, source_ip), count, _times(end, count, spread_seconds), _stamp)


def sample_event(*, view: OrganizationView, now: datetime) -> dict[str, Any]:
    """One benign, read-only call by a fresh IAM user of the organization's account, for proving the Cribl path."""
    c = _Ctx(None, now, 0, view)
    event = c.rec(c.user(None), "sts.amazonaws.com", "GetCallerIdentity", read_only=True)
    event["eventTime"] = _iso(now)
    return event
