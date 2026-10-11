---
name: trigger_aws_admin_iam_user_alert
displayName: Trigger the Cortex "Administrative IAM User Created with Credentials" analytics alert
category: workflows
description: 'Fire Cortex XSIAM''s native "Administrative IAM User Created with Credentials" analytics alert (AWS IAM, Low, T1136.003, T1136 and T1098.001) by sending three synthetic CloudTrail records by a new assumed role session: CreateUser, AttachUserPolicy with AdministratorAccess, then CreateAccessKey for the new user, through the http-sender connector''s Cribl mode (default destination cribl_aws_audit, dataset amazon_aws_raw). Use when the operator asks to trigger, demo, prove or reproduce an AWS backdoor admin user, a new IAM user with administrator access and an access key, or persistence through a created cloud account. One generate_events call with profile aws_cloudtrail and scenario iam_admin_user_credentials; no placeholders. Typically fires within about 3 minutes of the last event. If the AWS CloudTrail pack is not installed, xdm is empty; check the landing with raw columns.'
icon: person_add
source: platform
loadingMode: on-demand
locked: false
---

# Skill: Trigger the "Administrative IAM User Created with Credentials" alert

## When this skill applies

The operator wants the **native Cortex Analytics admin-IAM-user detector** to fire, for example: *"trigger the administrative IAM user created with credentials alert"*, *"show an attacker creating a backdoor admin user in AWS"*, *"prove T1136.003 fires from CloudTrail"*. (A different recipe, `iam_new_admin_identity`, raises the separate "New cloud identity created with administrative policy" alert; this skill is not that one.)

It is Cortex's own analytics (not a correlation rule). The call below sends **one built-in `http-sender` scenario** through the Cribl path to the tenant's dedicated AWS audit source; nothing needs installing on the tenant.

> **AWS CloudTrail pack.** When the AWS CloudTrail content pack is **not installed** on the tenant, `xdm.*` is **empty** for `amazon_aws_raw` rows from this path. The detector does not need it: it reads the native AWS audit feed that the dedicated Cribl source creates (`_collector_type = "Amazon S3"`). Never judge the landing with a `datamodel` query for this dataset; Step 2 reads the raw columns.


## What the detector looks for

| Property | Value |
|---|---|
| Alert name | `Administrative IAM User Created with Credentials` |
| Severity | Low |
| Source | Cortex Analytics behavioural detector: the `alert_source` column shows `XDR_ANALYTICS` (stored enum `MAGNIFIER`) |
| MITRE (as shown on the alert) | T1136.003 - Create Account: Cloud Account, T1136 - Create Account and T1098.001 - Account Manipulation: Additional Cloud Credentials |
| Data-source tag on the alert | `DS:Amazon/AWS` (also `DOM:Security`) |
| What triggers it | A `PlatformAdmin-<hex>` **assumed-role session** runs `CreateUser` for `svc-<hex>`, `AttachUserPolicy` with `arn:aws:iam::aws:policy/AdministratorAccess` to that user, then `CreateAccessKey` for it: a new identity, administrative policy and credentials in one sequence. The three events are spread over 2 minutes, one minute apart. |
| What the alert text says | *"IAM identity svc-<hex> was created by arn:aws:sts::<account>:assumed-role/PlatformAdmin-<hex>/<name>.<hex>. The newly created identity was assigned administrative policy. There was a successful creation of access keys. The operation was performed on AWS/<account>"* |

**Slow detector.** This is the slowest of the Azure AD audit and AWS CloudTrail scenarios on this path (the others alert in seconds): the alert typically arrives one to three minutes after the last event. Do not conclude it failed before 6 minutes.


## Preconditions: check these BEFORE sending

| # | Must be true | How to check |
|---|---|---|
| 1 | `http-sender` is running **with Cribl mode configured** (the instance has `criblUrl` and the `criblToken` secret) and its destination **`cribl_aws_audit`** shows `ready: true`. The generic HTTP collectors and syslog do not give Cortex the native AWS CloudTrail feed | `http-sender.list_destinations`: the row with `destination: "cribl_aws_audit"`, `mode: "cribl"`, `ready: true`. If it is missing or not ready, stop and tell the operator the Cribl collector must be configured on the instance (the agent cannot set the token) |
| 2 | You do **not** pass a `destination`: the `aws_cloudtrail` profile goes to `cribl_aws_audit` by itself and refuses to send when Cribl is not configured (it never falls back to an HTTP collector) | the call in Step 1 has no `destination` |
| 3 | You do **not** build the events: every call invents a fresh AWS account id, principal, access key and resource names, so the detector sees a first-time actor each time | nothing to do; never reuse an identity from an earlier run |

## Expected result

The call in Step 1, unchanged, fires the alert for a new account, a new `PlatformAdmin-<hex>` role session and a new `svc-<hex>` user. The three events are one minute apart and the alert typically arrives within one to three minutes after the last event, so allow the full 6 minutes. A different recipe (`iam_new_admin_identity`, an IAM user acting) raises a separate alert and does not raise this one.

## Step 1: send the events (exactly this call)

Call **`http-sender.generate_events`** once with this argument object. There is nothing to change: no placeholder, no destination, no `count` (an omitted `count` is one full recipe: 3 events: CreateUser, AttachUserPolicy, CreateAccessKey). It uses the default destination `cribl_aws_audit` (dataset `amazon_aws_raw`).

```json
{"profile": "aws_cloudtrail", "scenario": "iam_admin_user_credentials"}
```

The result shows `ok: true`, `batch_status: [200]`, `num_records` equal to the number of events, `destination: "cribl_aws_audit"`, `dataset: "amazon_aws_raw"` and the event ids in `sample_ids`. Add `"dry_run": true` to preview without sending. Do **not** pass `target_user` (it names the principal, and a reused principal is no longer a first-time actor).

## Step 2: confirm the events landed

About 20-30 seconds after the call (ingestion on this path takes seconds). The AWS CloudTrail pack is not installed, so query the **raw columns**, never `datamodel`:

```text
config timeframe = 1h
| dataset = amazon_aws_raw
| filter _collector_name = "phantom-http-sender" and eventName in ("CreateUser", "AttachUserPolicy", "CreateAccessKey") and userIdentity ~= "PlatformAdmin"
| fields _time, eventID, eventName, userAgent, sourceIPAddress, userIdentity
| sort desc _time
| limit 6
```

Pass when you see **three** rows (the filter on `PlatformAdmin` keeps other scenarios' `CreateUser` and `AttachUserPolicy` out) from one `PlatformAdmin-<hex>/<name>.<hex>` assumed-role session: `CreateUser`, `AttachUserPolicy` (`requestParameters` has `AdministratorAccess`) and `CreateAccessKey`, all naming the same `svc-<hex>` user. Runs from the last hour (yours and earlier ones) also appear: read the newest row first.

## Step 3: wait, then check for the alert

Check at 30 seconds, then every 30 seconds for up to **6 minutes**. Match the name client-side with `~=` and filter the alert source by its **stored** enum names (`XDR_ANALYTICS` and `XDR_ANALYTICS_BIOC` as displayed match nothing):

```text
config timeframe = 1d
| dataset = alerts
| filter alert_source in ("MAGNIFIER", "ANALYTICS_BIOC") and alert_name ~= "Administrative IAM User Created with Credentials"
| fields alert_id, alert_name, severity, user_name, mitre_attack_technique, original_tags, description, alert_arrival_timestamp
| sort desc alert_arrival_timestamp
| limit 5
```

Pass when a **new** row names the identity you saw in Step 2 (the `PlatformAdmin-<hex>/<name>.<hex>` session and the `svc-<hex>` user in the description); older rows from other runs have other identities.

If nothing arrives in 6 minutes: re-run Step 2 (the events must be there and carry the right operation), confirm the instance's Cribl destination is still ready, and send the call **once more** (a new call is a new actor). Do not edit the events and do not switch to an HTTP collector or syslog.

## Report back to the operator

State the identity that appears in the alert description, the alert id, `Administrative IAM User Created with Credentials`, its severity (Low), and the latency from the events to the alert (typically 1-3 minutes after the last event). Say that `xdm.*` is empty for this dataset because the AWS CloudTrail pack is not installed and that this does not stop the detector, and that each call uses a new identity so it can be repeated at once.
