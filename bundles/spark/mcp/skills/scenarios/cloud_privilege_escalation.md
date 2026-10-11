---
name: cloud_privilege_escalation
displayName: Cloud privilege escalation
category: scenarios
description: 'Three-stage cloud-IAM attack chain. Stage 1: suspicious identity creates a new service account with broad permissions. Stage 2: IAM role binding grants the new SA Editor or Owner. Stage 3: data access from a previously-unseen region using the new SA''s key. Vendor-agnostic — agent resolves vendor/product from the operator''s installed data sources at runtime. Triggers 3 XSIAM rules: Cloud IAM Key Creation, Cloud Privilege Escalation Role Binding, Anomalous Cloud Region Access. Use when you want to validate cloud-side detection independently of identity-provider compromise (Stage 1 assumes the actor is already authenticated, however they got there).'
icon: cloud_circle
source: platform
loadingMode: on-demand
locked: false
attack:
  - 'TA0001: Initial Access (T1078.004 Cloud Accounts)'
  - 'TA0003: Persistence (T1098.001 Additional Cloud Credentials, T1136.003 Create Cloud Account)'
  - 'TA0004: Privilege Escalation (T1098.003 Additional Cloud Roles)'
  - 'TA0009: Collection (T1530 Data from Cloud Storage Object)'
---

# Skill: Cloud privilege escalation chain

## Category

scenarios

## Attack Type

Pure cloud-IAM attack post-foothold. Models what happens AFTER the attacker has gotten cloud-platform access (via OAuth abuse from `phishing_to_cloud_takeover`, or via leaked credentials, or via a CI/CD pipeline compromise). They establish persistence by creating their own service account with their own key, escalate that SA to Owner, and start exfiltrating data using the new identity from a region they control.

This skill is intentionally cloud-only — no proxy / firewall / EDR data classes — to validate that cloud audit telemetry alone catches the chain.

## MITRE ATT&CK Tactics

- TA0001: Initial Access (T1078.004 Cloud Accounts)
- TA0003: Persistence (T1098.001 Additional Cloud Credentials, T1136.003 Create Cloud Account)
- TA0004: Privilege Escalation (T1098.003 Additional Cloud Roles)
- TA0009: Collection (T1530 Data from Cloud Storage Object)

## XSIAM analytics rules triggered

| # | Rule | Stage |
|---|---|---|
| 17 | Cloud IAM Key Creation (suspicious identity) | Stage 1 |
| 18 | Cloud Privilege Escalation Role Binding | Stage 2 |
| 4 | Anomalous Cloud Region Access (variant: cross-region access from new SA) | Stage 3 |

## Data classes used

| Stage | Data class | If missing |
|---|---|---|
| 1, 2, 3 | `cloud` | Required — entire skill is cloud-audit-telemetry-only |

## Pre-flight

**Resolve the destination as a store reference.** Call `log_destinations_list` once and take the
`id` of the operator's default (or only) destination, then pass `destination: "logdest:<id>"`.
The platform resolves the reference server-side and injects any credentials, so secrets never
cross the agent surface. **Never pass a destination's `type` (`syslog`) — that is not an accepted
value** — and never hardcode a broker host/port. Accepted forms are `logdest:<id>` (preferred),
a raw `udp:host:port` for a one-shot the operator names explicitly, or `XSIAM_WEBHOOK` (legacy).
Destination selection is independent of the data-source vendor/product lookup below.

**Make the events vendor-faithful.** For each class you will emit, call
`data_sources_get_schema(<entry>.data_source_id, compact=true)` and pass the returned `fields[]`
verbatim as `schema_override` on that stage's worker. Without it the worker emits generic
observables that the vendor's modeling rule cannot map, so events land raw and `xdm.*` stays
empty. `compact=true` is lossless for this purpose and keeps the payload inside the tool-result cap.

Call `data_sources_installed_as_vendors`. Group `vendors[]` by `data_source_class`. Verify `cloud` is present. If missing, stop and tell the operator no `cloud` data source is installed — install one from the Marketplace, or chain this skill with `phishing_to_cloud_takeover` instead, which models the SaaS → cloud pivot earlier in the kill chain (its Stage 6).

## Narrative thread

- **Compromised cloud user:** `cicd-deployer@corp.example` (CI/CD service-account-like user with platform admin)
- **Source IP for the malicious activity:** `194.165.16.45` (anomalous — the CI/CD pipeline normally runs from `10.10.0.0/8` internal egress)
- **Source country:** `RU`
- **Cloud project:** `gcp-prod-ExampleCorp`
- **New SA created:** `data-export-svc@gcp-prod-ExampleCorp.iam.gserviceaccount.com`
- **New SA key ID:** `8f3a91d2c4b7e5a8d6f9b2c1e4a7d3f5b8c2e9a1`
- **Targeted bucket:** `gs://ExampleCorp-prod-claims-data` (multi-TB customer claims data)
- **Baseline access region (legitimate CI/CD):** `us-west1`
- **Anomalous access region (post-escalation):** `us-east4` (then `europe-west1`)
- **Wall-clock time:** Stage 1 ~3 min (SA + key creation). Stage 2 ~5 min (role escalation). Stage 3 ~15 min (data access).

---

### Stage 1 — SA + key creation — 4 events over 2 minutes

The attacker creates a new service account in the project. Within seconds they create a USER_MANAGED key for it (a JSON key file they can download and use externally). The actor is the legitimate `cicd-deployer` user, but the IP is anomalous.

**Data class:** `cloud`

```yaml
xlog.create_data_worker:
  type:    CEF
  vendor:  <stack[cloud].vendor>
  product: <stack[cloud].product>
  count:    4
  interval: 30
  destination: logdest:<id from log_destinations_list>
  observables_dict:
    src:      ["194.165.16.45"]
    country:       ["RU"]
    act:        ["google.iam.admin.v1.CreateServiceAccount",
                    "google.iam.admin.v1.CreateServiceAccountKey"]
    apiEndpoint:  ["iam.googleapis.com"]
    requestMethod:    ["projects.serviceAccounts.create",
                    "projects.serviceAccounts.keys.create"]
    resourceName: ["projects/gcp-prod-ExampleCorp/serviceAccounts/data-export-svc@gcp-prod-ExampleCorp.iam.gserviceaccount.com",
                    "projects/gcp-prod-ExampleCorp/serviceAccounts/data-export-svc@gcp-prod-ExampleCorp.iam.gserviceaccount.com/keys/8f3a91d2c4b7e5a8d6f9b2c1e4a7d3f5b8c2e9a1"]
    suser:      ["data-export-svc@gcp-prod-ExampleCorp.iam.gserviceaccount.com"]
    keyId:     ["8f3a91d2c4b7e5a8d6f9b2c1e4a7d3f5b8c2e9a1"]
    keyType:   ["USER_MANAGED"]
    description: ["Data export service for nightly batch jobs"]
    authenticationMethod: ["oauth_token"]
    cefSeverity:      ["high", "critical"]
    requestClientApplication: ["google-cloud-sdk/470.0.0"]
    accessLevel:  ["roles/owner (inherited)"]
    actionStatus: ["SUCCESS"]
```

**Field semantics:**
- `actor_email: cicd-deployer@corp.example` — legitimate user; the anomaly is `actor_ip` and `country`
- `sa_email: data-export-svc@...` — innocuous-sounding name. Attackers typically pick names that blend in with existing infrastructure; "data-export-svc" sounds like a normal data-pipeline component
- `sa_description` — even more so; attackers fill in description fields to make the SA look legit
- `sa_key_type: USER_MANAGED` — the riskiest key type. Cloud-managed keys auto-rotate; user-managed are long-lived
- `caller_user_agent: google-cloud-sdk/470.0.0` — attacker is using gcloud CLI (vs the web console), suggesting scripted automation
- `access_level: roles/owner (inherited)` — the actor (cicd-deployer) has Owner; this is what gives them permission to create a new SA at all

**Why this fires Rule #17:** the IAM-key-creation event from anomalous `actor_ip` is high-fidelity in any modern cloud-detection ruleset. Even ignoring IP, USER_MANAGED key creation in a production project is rare and worth alerting on.

---

### Stage 2 — Role-binding privilege escalation — 3 events over 2 minutes

The attacker now grants the new SA broad permissions: `roles/owner` on the project, plus `roles/iam.serviceAccountTokenCreator` so the SA can impersonate other SAs (broadening attack surface).

**Data class:** `cloud`

```yaml
xlog.create_data_worker:
  type:    CEF
  vendor:  <stack[cloud].vendor>
  product: <stack[cloud].product>
  count:    3
  interval: 40
  destination: logdest:<id from log_destinations_list>
  observables_dict:
    src:      ["194.165.16.45"]
    country:       ["RU"]
    act:        ["google.cloud.resourcemanager.v1.SetIamPolicy",
                    "google.iam.admin.v1.SetIamPolicy"]
    apiEndpoint:  ["cloudresourcemanager.googleapis.com",
                    "iam.googleapis.com"]
    requestMethod:    ["projects.setIamPolicy",
                    "projects.serviceAccounts.setIamPolicy"]
    resourceName: ["projects/gcp-prod-ExampleCorp",
                    "projects/gcp-prod-ExampleCorp/serviceAccounts/data-export-svc@gcp-prod-ExampleCorp.iam.gserviceaccount.com"]
    accessLevel:  ["roles/owner",
                    "roles/iam.serviceAccountTokenCreator",
                    "roles/iam.serviceAccountUser"]
    authenticationMethod: ["oauth_token"]
    cefSeverity:      ["critical"]
    actionStatus: ["SUCCESS"]
    requestClientApplication: ["google-cloud-sdk/470.0.0"]
```

**Field semantics:**
- `target_member` — the new SA being elevated
- `role_granted: roles/owner` — full project ownership; equivalent to giving the SA root in the cloud world
- `roles/iam.serviceAccountTokenCreator` — additional escalation: lets the SA mint tokens for OTHER SAs in the project, which the attacker can then use to access resources scoped to those other SAs (escape from any per-SA permissions boundary)
- `policy_change_diff` — the IAM-policy delta; modern cloud-detection rules can show "what changed" precisely

**Why this fires Rule #18:** granting `roles/owner` to a service account (any service account) is universally a high-severity alert. Granting it from an anomalous source IP, on a SA that was just created in the same window, is unmistakable.

---

### Stage 3 — Data access from new region using the new SA's key — ~30 events over 15 minutes

The attacker, now possessing a USER_MANAGED key for `data-export-svc` with `roles/owner`, exits the compromised user's session entirely. They authenticate to the cloud API with the SA key from their attacker infrastructure (in `us-east4`) and start downloading data from the production claims bucket. Each `storage.objects.get` call is a separate audit event.

**Data class:** `cloud`

```yaml
xlog.create_data_worker:
  type:    CEF
  vendor:  <stack[cloud].vendor>
  product: <stack[cloud].product>
  count:    30
  interval: 30
  destination: logdest:<id from log_destinations_list>
  observables_dict:
    src:      ["35.230.x.x", "104.196.x.x"]
    country:       ["US"]
    region:        ["us-east4", "europe-west1"]
    act:        ["storage.objects.get", "storage.objects.list",
                    "storage.buckets.get"]
    apiEndpoint:  ["storage.googleapis.com"]
    requestMethod:    ["objects.get", "objects.list"]
    resourceName: ["projects/_/buckets/ExampleCorp-prod-claims-data/objects/2024/Q1/claims-batch-001.parquet",
                    "projects/_/buckets/ExampleCorp-prod-claims-data/objects/2024/Q2/claims-batch-002.parquet",
                    "projects/_/buckets/ExampleCorp-prod-claims-data/objects/2024/Q3/claims-batch-003.parquet"]
    bucketName:   ["ExampleCorp-prod-claims-data"]
    objectSize:   ["524288000", "1073741824", "2147483648"]
    authenticationMethod: ["service_account_key"]
    keyId:     ["8f3a91d2c4b7e5a8d6f9b2c1e4a7d3f5b8c2e9a1"]
    cefSeverity:      ["high"]
    requestClientApplication: ["python-requests/2.31.0"]
    actionStatus: ["SUCCESS"]
```

**Field semantics:**
- `actor_email: data-export-svc@...` — NOT the original user. The actor is now the new SA (it authenticated with its key). This is exactly the persistence the attacker established
- `actor_ip: 35.230.x.x / 104.196.x.x` — public-internet GCP infrastructure IPs (us-east4); the attacker is calling the API from outside the ExampleCorp internal network entirely
- `region: us-east4 / europe-west1` — the SA was created in us-west1 normally; access from a NEW region for THIS SA is the anomaly signal
- `authentication_method: service_account_key` — explicit signal that the SA is being used with its USER_MANAGED key (vs OAuth token from another impersonator)
- `object_size: 500 MB - 2 GB per file` — production data files are large
- `caller_user_agent: python-requests/2.31.0` — a Python library, NOT gcloud CLI. Different tooling than Stage 1 — characteristic of the attacker now operating from their own infrastructure

**Why this fires Rule #4 (variant — cloud region anomaly):** the same SA accessing its expected resources but from a region it has no history in fires the cloud-equivalent of impossible-travel detection. Combined with the SA being newly-created (Stage 1) and recently-elevated (Stage 2), the SIEM scores this as a critical incident.

---

## Verification

| Indicator | Where to check |
|---|---|
| IAM SA key creation alert from `actor_ip=194.165.16.45` | XSIAM Issues |
| IAM role-binding-grants-owner alert | XSIAM Issues |
| Cloud cross-region anomalous access by `data-export-svc@...` | XSIAM Issues |
| Pivotable: filter by `project=gcp-prod-ExampleCorp` + actor IN (`cicd-deployer`, `data-export-svc`), see all 3 stages | XQL: `config timeframe = 24h \| dataset = google_cloud_audit_logs \| filter resource.labels.project_id = "gcp-prod-ExampleCorp" \| limit 20` |

## Tear-down

```yaml
xlog.list_workers:
xlog.kill_worker:
  worker_id: <each>
```

## Adapting per deployment

The cloud-provider-specific action names (`google.iam.admin.v1.CreateServiceAccount`) only match GCP. For AWS, equivalents are `iam.amazonaws.com:CreateUser` + `iam.amazonaws.com:CreateAccessKey` + `sts.amazonaws.com:AssumeRole`. For Azure, `Microsoft.Authorization/roleAssignments/write`. The skill should be retargeted to whichever cloud the operator's stack `cloud` entry references — the chain shape (create identity → escalate → use → access from new location) is universal across providers.
