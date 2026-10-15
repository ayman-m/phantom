"""The `gcp_audit` event profile: synthetic Google Cloud Audit LogEntry objects (the Pub/Sub export shape).

Each event is a complete Cloud Logging LogEntry (`logName`, `resource`, `timestamp`, `receiveTimestamp`, `severity`,
`insertId`, `protoPayload` of type AuditLog) as the `gcp_cloud_logging` Cribl source parses it into
`google_cloud_logging_raw` and normalizes it into `cloud_audit_logs`. It is meant for the `cribl_gcp_cloud_logging`
destination (measured on a Cortex tenant: 7 alerts from the Cloud analytics detectors).

Every scenario replays ONE measured detector shape; the shapes that stayed silent (billing-admin removal, deny policy,
external CMEK key, heavy compute, serverless CLI, pen-test user agents) are not here. A scenario is a short recipe
of 1-4 steps; `count` repeats it with fresh resource ids.

The project id, project number and region are the organization's (`cloud.gcp`); the users a recipe mints, the groups,
service accounts and ids are generated per call, so a replay looks like a first-time actor. `target_user` names one of the
organization's people (login, email or the part before the @), whose home address the calls then come from. Addresses are
real: ordinary actors come from the Saudi home pool, an anonymous or scanning caller from an out-of-country range, and the
Tor scenario from a Tor exit. `timestamp` is UTC with nanoseconds; the `receiveTimestamp` follows it but is never after `now`.

`benign_activity` is the baseline and its identities are STABLE: the organization's project, the organization's people who
may log on and have GCP access (`cloud_access`), one home address each (`home_ip`), and four service accounts that call from
the organization's public egress addresses. Its calls are ordinary Data Access reads (object list and get, bucket list,
instance list, service account get, log reads, IAM policy reads); none of them is a shape one of the detectors above fired on.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta
from typing import Any, Callable

from runtime.organization_view import OrganizationView

from . import _fresh, _org, ippools
from .okta import _times

# The profile interface (see profiles/__init__.py).
NAME = "gcp_audit"
DESCRIPTION = ("Google Cloud Audit log entries for the cribl_gcp_cloud_logging destination: public bucket, owner role to a group, "
               "anonymous / scanner Kubernetes calls, Tor API call, new admin service account; benign_activity is a stable pool "
               "of users and service accounts doing ordinary reads.")
EXPECTED_DATASET = "cribl_gcp_cloud_logging"
EXPECTED_DATASETS = ("cribl_gcp_cloud_logging",)
CRIBL_DESTINATIONS = ("cribl_gcp_cloud_logging",)
DEFAULT_DESTINATION = "cribl_gcp_cloud_logging"
CRIBL_ONLY = True
TEST_ID_FIELD = "insertId"
TIME_FIELD = "timestamp"

_UA_CONSOLE = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36,gzip(gfe)"
_UA_GCLOUD = ("google-cloud-sdk gcloud/512.0.0 command/gcloud.{cmd} invocation-id/{inv} environment/None environment-version/None "
              "client-os/LINUX client-os-ver/6.8.0 interactive/False from-script/True python/3.12.7 term/xterm (Linux 6.8.0-1015-gcp),gzip(gfe)")
_SCANNER_UAS = ("kube-hunter/0.6.8", "kubescape/v3.0.8", "Trivy/0.50.1", "kube-bench/0.7.3")


def _stamp_text(ts: datetime, rng: random.Random) -> str:
    return ts.strftime("%Y-%m-%dT%H:%M:%S.") + "%09dZ" % (ts.microsecond * 1000 + rng.randint(0, 999))


class _Ctx:
    """Per-call state: the organization, the random source, its project and region, and the window's end."""

    def __init__(self, view: OrganizationView, seed: int | None, now: datetime) -> None:
        self.rng = random.Random(seed)
        self.view = view
        self.domain = view.email_domain  # the domain of the users and groups a recipe mints
        self.now = now
        cloud = _org.cloud(view, "gcp", "project_id", "project_number", "region")
        _fresh.hexs(self.rng, 6), _fresh.digits(self.rng, 12)  # the project id and number this call used to invent: the draws stay so a seeded call's other values do not move
        self.project, self.number, self.region = cloud["project_id"], cloud["project_number"], cloud["region"]
        self.prefix = _org.bucket_prefix(view)
        self.buckets = {f"{self.prefix}-{name}": keys for name, keys in _BUCKET_OBJECTS.items()}
        self._by_email = {p["email"].lower(): p for p in view.people}
        self.tor = ippools.tor_exits(self.rng, len(ippools.CLOUD_TOR_EXITS), ippools.CLOUD_TOR_EXITS)  # drawn once: a different exit per repetition

    def hexs(self, n: int) -> str:
        return _fresh.hexs(self.rng, n)

    def home_ip(self) -> str:
        return ippools.home_for(self.rng.randrange(len(ippools.HOME)))[0]

    def actor_ip(self, who: str) -> str:
        """Where `who` calls from: the home address of the organization's person it is, else a random home-pool address
        (the draw is made either way, so a seeded call's other values are the same)."""
        ip = self.home_ip()
        person = self._by_email.get(who.lower())
        return _org.home(person)[0] if person else ip

    def abroad_ip(self) -> str:
        return ippools.abroad_pick(self.rng)[0]

    def user(self, person: dict[str, Any] | None = None) -> str:
        """The organization's `person`, by email, or a user the recipe mints fresh."""
        return _org.email(person) if person else f"{_fresh.handle(self.rng)}@{self.domain}"

    def sa(self, prefix: str, name: str | None = None) -> str:
        return f"{name or prefix + '-' + self.hexs(6)}@{self.project}.iam.gserviceaccount.com"

    def entry(self, *, who: str, method: str, service: str, resource_name: str, rtype: str, rlabels: dict[str, Any],
              ip: str, ua: str = _UA_CONSOLE, request: Any = None, response: Any = None, service_data: Any = None,
              authz: list[str] | None = None, severity: str = "NOTICE", log: str = "activity",
              who_type: str = "user") -> dict[str, Any]:
        proto: dict[str, Any] = {
            "@type": "type.googleapis.com/google.cloud.audit.AuditLog",
            "status": {},
            "authenticationInfo": {"principalEmail": who, "principalSubject": f"{'serviceAccount' if who_type == 'sa' else 'user'}:{who}"},
            "requestMetadata": {"callerIp": ip, "callerSuppliedUserAgent": ua,
                                "requestAttributes": {"time": "", "auth": {}}, "destinationAttributes": {}},
            "serviceName": service, "methodName": method,
            "authorizationInfo": [{"resource": resource_name, "permission": p, "granted": True, "resourceAttributes": {}}
                                  for p in (authz or [])],
            "resourceName": resource_name,
        }
        for key, value in (("request", request), ("response", response), ("serviceData", service_data)):
            if value is not None:
                proto[key] = value
        return {"protoPayload": proto, "insertId": self.hexs(14), "resource": {"type": rtype, "labels": rlabels},
                "timestamp": "", "severity": severity, "receiveTimestamp": "",
                "logName": f"projects/{self.project}/logs/cloudaudit.googleapis.com%2F{log}"}

    def k8s(self, method: str, resource: str, who: str, ip: str, ua: str, *, who_type: str,
            groups: list[str] | None = None) -> dict[str, Any]:
        event = self.entry(who=who, method=method, service="k8s.io", resource_name=resource, rtype="k8s_cluster",
                           rlabels={"project_id": self.project, "cluster_name": "phantom-gke-1", "location": self.region},
                           ip=ip, ua=ua, who_type=who_type, log="data_access")
        auth = event["protoPayload"]["authenticationInfo"]
        del auth["principalSubject"]  # Kubernetes callers carry no principalSubject
        if groups:
            auth["authoritySelector"] = ",".join(groups)
        event["protoPayload"]["authorizationInfo"] = [
            {"resource": resource, "permission": method.replace("io.k8s.", ""), "granted": True}]
        return event

    def set_iam(self, who: str, ip: str, resource_name: str, rtype: str, rlabels: dict[str, Any], action: str, role: str,
                member: str, *, service: str = "cloudresourcemanager.googleapis.com", method: str = "SetIamPolicy",
                bucket: bool = False) -> dict[str, Any]:
        bindings = [{"role": role, "members": [member]}]
        return self.entry(
            who=who, method=method, service=service, resource_name=resource_name, rtype=rtype, rlabels=rlabels, ip=ip,
            request={"@type": "type.googleapis.com/google.iam.v1.SetIamPolicyRequest", "resource": resource_name,
                     "policy": {"version": 3, "bindings": bindings, "etag": "BwYx" + self.hexs(6)}},
            response={"version": 3, "bindings": bindings, "etag": "BwYx" + self.hexs(6)},
            service_data={"@type": "type.googleapis.com/google.iam.v1.logging.AuditData",
                          "policyDelta": {"bindingDeltas": [{"action": action, "role": role, "member": member}]}},
            authz=["storage.buckets.setIamPolicy" if bucket else "resourcemanager.projects.setIamPolicy"])


# -- scenario recipes: (c, actor, repetition, source_ip) -> one repetition's events --------------------------------------

def _data_asset_public(c, who, k, src):
    bucket = f"{c.prefix}-public-" + c.hexs(6)
    return [c.set_iam(who, src or c.actor_ip(who), "projects/_/buckets/" + bucket, "gcs_bucket",
                      {"project_id": c.project, "bucket_name": bucket, "location": c.region},
                      "ADD", "roles/storage.objectViewer", "allUsers", service="storage.googleapis.com",
                      method="storage.setIamPermissions", bucket=True)]


def _sensitive_role_to_group(c, who, k, src):
    return [c.set_iam(who, src or c.actor_ip(who), "projects/" + c.project, "project", {"project_id": c.project},
                      "ADD", "roles/owner", f"group:eng-{c.hexs(5)}@{c.domain}")]


def _k8s_anonymous(c, who, k, src):
    return [c.k8s("io.k8s.core.v1.namespaces.list", "core/v1/namespaces", "system:anonymous", src or c.abroad_ip(),
                  "curl/8.4.0", who_type="anon", groups=["system:unauthenticated"])]


def _k8s_vuln_scanner(c, who, k, src):
    ip = src or c.abroad_ip()
    return [c.k8s("io.k8s.core.v1.pods.list", "core/v1/namespaces/default/pods", who, ip, ua, who_type="sa")
            for ua in _SCANNER_UAS]


def _tor_api_call(c, who, k, src):
    bucket = f"{c.prefix}-reports-" + c.hexs(4)
    return [c.entry(who=who, method="storage.objects.get", service="storage.googleapis.com",
                    resource_name=f"projects/_/buckets/{bucket}/objects/q3/summary.csv", rtype="gcs_bucket",
                    rlabels={"project_id": c.project, "bucket_name": bucket, "location": c.region},
                    ip=src or c.tor[k % len(c.tor)].ip, authz=["storage.objects.get"], log="data_access",
                    severity="INFO")]


def _new_admin_service_account(c, who, k, src):
    # CreateServiceAccount, then roles/owner on the project to that service account.
    ip = src or c.actor_ip(who)
    name = "deploy-bot-" + c.hexs(6)
    email, unique = c.sa("", name), str(c.rng.randint(10**20, 10**21 - 1))
    create = c.entry(
        who=who, method="google.iam.admin.v1.CreateServiceAccount", service="iam.googleapis.com", ip=ip,
        resource_name=f"projects/{c.project}/serviceAccounts/{email}", rtype="service_account",
        rlabels={"project_id": c.project, "email_id": email, "unique_id": unique},
        request={"@type": "type.googleapis.com/google.iam.admin.v1.CreateServiceAccountRequest",
                 "name": "projects/" + c.project, "account_id": name, "service_account": {"display_name": name}},
        response={"@type": "type.googleapis.com/google.iam.admin.v1.ServiceAccount",
                  "name": f"projects/{c.project}/serviceAccounts/{email}", "email": email, "unique_id": unique,
                  "project_id": c.project},
        authz=["iam.serviceAccounts.create"])
    grant = c.set_iam(who, ip, "projects/" + c.project, "project", {"project_id": c.project}, "ADD", "roles/owner",
                      "serviceAccount:" + email)
    return [create, grant]


def _stamp(c: _Ctx, event: dict[str, Any], when: datetime) -> None:
    received = min(when + timedelta(milliseconds=c.rng.randint(40, 600)), c.now)
    event["timestamp"] = _stamp_text(when, c.rng)
    event["receiveTimestamp"] = _stamp_text(received, c.rng)
    event["protoPayload"]["requestMetadata"]["requestAttributes"]["time"] = event["timestamp"]


# scenario -> (who acts, recipe, steps in one repetition)
_person = lambda c, person: c.user(person)  # noqa: E731
_scanner = lambda c, person: c.sa("gke-reader", _org.local_part(person) if person else None)  # noqa: E731
_TABLE: dict[str, tuple[Callable, Callable, int]] = {
    "data_asset_public": (_person, _data_asset_public, 1),
    "sensitive_role_to_group": (_person, _sensitive_role_to_group, 1),
    "k8s_anonymous": (_person, _k8s_anonymous, 1),
    "k8s_vuln_scanner": (_scanner, _k8s_vuln_scanner, len(_SCANNER_UAS)),
    "tor_api_call": (_person, _tor_api_call, 1),
    "new_admin_service_account": (_person, _new_admin_service_account, 2),
}
BENIGN_SCENARIOS = ("benign_activity",)
SCENARIOS = tuple(_TABLE) + BENIGN_SCENARIOS
# The fewest events that make a scenario's recipe complete (a larger count repeats the recipe). Benign: any count.
MIN_COUNT = {name: steps for name, (_, _, steps) in _TABLE.items()}
# What an omitted `count` means for a scenario that is not a recipe.
DEFAULT_COUNT = {"benign_activity": 20}

# -- benign_activity: a stable pool, ordinary reads ------------------------------------------------------------------------

BENIGN_SERVICE_ACCOUNTS = ("app-backend", "data-pipeline", "ci-runner", "log-exporter")
# The buckets of the stable pool by name suffix; the organization's id is the prefix (`phantom-lab-reports`).
_BUCKET_OBJECTS = {
    "reports": ("q3/summary.csv", "q3/headcount.xlsx", "q4/forecast.pdf"),
    "datalake": ("sales/2026/09/part-0001.parquet", "sales/2026/09/part-0002.parquet", "web/2026/09/clicks.parquet"),
    "app-assets": ("img/logo.png", "css/site.min.css", "js/app.bundle.js"),
}
_BENIGN_OPS = (("storage.objects.get", 22), ("storage.objects.list", 18), ("compute.instances.list", 14),
               ("logging.entries.list", 14), ("iam.serviceAccounts.get", 10), ("storage.buckets.list", 10),
               ("resourcemanager.getIamPolicy", 6), ("storage.buckets.get", 6))
_UA_API_CLIENT = "google-api-python-client/2.126.0 (gzip)"


def _benign_actor(c: _Ctx, index: int | None) -> tuple[str, str, str, str]:
    """(email, caller address, user agent, who_type) of a pool member: person number `index` of the pool, or (None) a service
    account. A service account calls from one of the organization's public egress addresses (an office NAT, as far as Cortex
    can tell), one per account."""
    if index is not None:
        person = c.pool[index]
        user = c.user(person)
        ua = _UA_CONSOLE if index % 2 else _UA_GCLOUD.format(cmd="storage.ls", inv=_fresh.stable(f"gcp|inv|{user}", 32))
        return user, _org.home(person)[0], ua, "user"
    slot = c.rng.randrange(len(BENIGN_SERVICE_ACCOUNTS))
    return c.sa("", BENIGN_SERVICE_ACCOUNTS[slot]), c.egress[slot % len(c.egress)], _UA_API_CLIENT, "sa"


def _benign_entry(c: _Ctx, op: str, who: str, ip: str, ua: str, who_type: str) -> dict[str, Any]:
    p = c.project
    common = {"who": who, "ip": ip, "ua": ua, "who_type": who_type, "log": "data_access", "severity": "INFO"}
    bucket = c.rng.choice(sorted(c.buckets))
    labels = {"project_id": p, "bucket_name": bucket, "location": c.region}
    if op in ("storage.objects.get", "storage.objects.list"):
        resource = f"projects/_/buckets/{bucket}" + ("/objects/" + c.rng.choice(c.buckets[bucket]) if op.endswith("get") else "")
        return c.entry(method=op, service="storage.googleapis.com", resource_name=resource, rtype="gcs_bucket", rlabels=labels,
                       authz=[op], **common)
    if op == "storage.buckets.get":
        return c.entry(method=op, service="storage.googleapis.com", resource_name=f"projects/_/buckets/{bucket}", rtype="gcs_bucket",
                       rlabels=labels, authz=[op], **common)
    if op == "storage.buckets.list":
        return c.entry(method=op, service="storage.googleapis.com", resource_name=f"projects/{p}", rtype="project",
                       rlabels={"project_id": p}, authz=[op], **common)
    if op == "compute.instances.list":
        zone = c.rng.choice((f"{c.region}-a", f"{c.region}-b"))
        return c.entry(method="v1.compute.instances.list", service="compute.googleapis.com",
                       resource_name=f"projects/{p}/zones/{zone}/instances", rtype="gce_instance",
                       rlabels={"project_id": p, "zone": zone, "instance_id": ""}, authz=["compute.instances.list"], **common)
    if op == "iam.serviceAccounts.get":
        email = c.sa("", c.rng.choice(BENIGN_SERVICE_ACCOUNTS))
        return c.entry(method="google.iam.admin.v1.GetServiceAccount", service="iam.googleapis.com",
                       resource_name=f"projects/{p}/serviceAccounts/{email}", rtype="service_account",
                       rlabels={"project_id": p, "email_id": email, "unique_id": _fresh.stable(f"gcp|sa|{email}", 21, "0123456789")},
                       authz=["iam.serviceAccounts.get"], **common)
    if op == "logging.entries.list":
        return c.entry(method="google.logging.v2.LoggingServiceV2.ListLogEntries", service="logging.googleapis.com",
                       resource_name=f"projects/{p}", rtype="project", rlabels={"project_id": p},
                       authz=["logging.logEntries.list"], **common)
    return c.entry(method="GetIamPolicy", service="cloudresourcemanager.googleapis.com", resource_name=f"projects/{p}",
                   rtype="project", rlabels={"project_id": p}, authz=["resourcemanager.projects.getIamPolicy"], **common)


def _benign_activity(c: _Ctx, count: int, end: datetime, spread_seconds: int) -> list[dict[str, Any]]:
    """`count` ordinary reads by the stable pool, at random moments of the window (the first at its start, the last at `end`)."""
    c.pool, c.egress = _org.cloud_people(c.view, "gcp"), _org.egress(c.view)
    out = []
    for _ in range(count):
        # Nine calls in ten are a person's; the rest are a service account's.
        index = c.rng.randrange(len(c.pool)) if c.rng.random() < 0.9 else None
        who, ip, ua, who_type = _benign_actor(c, index)
        out.append(_benign_entry(c, _fresh.weighted(c.rng, _BENIGN_OPS), who, ip, ua, who_type))
    for event, when in zip(out, _fresh.jittered_times(c.rng, end, count, spread_seconds)):
        _stamp(c, event, when)
    return out


def build_events(
    scenario: str, count: int, *, view: OrganizationView, now: datetime,
    spread_seconds: int = 120, start_offset_minutes: int = 0,
    target_user: str | None = None, source_ip: str | None = None, seed: int | None = None,
) -> list[dict[str, Any]]:
    """Build `count` LogEntry objects for `scenario`, oldest first.

    The window ends `start_offset_minutes` before `now` and is `spread_seconds` wide; nothing is dated after `now`.
    `target_user` names the acting user (one of the organization's people, `view`) or, for k8s_vuln_scanner, the person
    whose name the scanner service account carries; `source_ip` is the caller address. `benign_activity` ignores both: its actors and addresses are the stable pool's.
    """
    if scenario not in SCENARIOS:
        raise ValueError(f"unknown scenario {scenario!r}; choose one of {', '.join(SCENARIOS)}")
    if count < 1:
        raise ValueError("count must be at least 1")
    if count < MIN_COUNT.get(scenario, 1):
        raise ValueError(f"{scenario} needs count >= {MIN_COUNT[scenario]}")
    end = now - timedelta(minutes=max(start_offset_minutes, 0))
    c = _Ctx(view, seed, end)
    if scenario == "benign_activity":
        return _benign_activity(c, count, end, spread_seconds)
    actor, recipe, _ = _TABLE[scenario]
    who = actor(c, _org.resolve(view, target_user) if _fresh.bare_name(target_user) else None)
    return _fresh.run_recipe(lambda k: recipe(c, who, k, source_ip), count, _times(end, count, spread_seconds),
                             lambda event, when: _stamp(c, event, when))


def sample_event(*, view: OrganizationView, now: datetime) -> dict[str, Any]:
    """One benign object read by a fresh user of the organization's project, for proving the Cribl path."""
    c = _Ctx(view, None, now)
    bucket = f"{c.prefix}-reports-" + c.hexs(4)
    event = c.entry(who=c.user(), method="storage.objects.get", service="storage.googleapis.com",
                    resource_name=f"projects/_/buckets/{bucket}/objects/q3/summary.csv", rtype="gcs_bucket",
                    rlabels={"project_id": c.project, "bucket_name": bucket, "location": c.region},
                    ip=c.home_ip(), authz=["storage.objects.get"], log="data_access", severity="INFO")
    _stamp(c, event, now)
    return event
