---
name: trigger_cloud_new_admin_identity_alert
displayName: Trigger the Cortex "New cloud identity created with administrative policy" analytics alert (AWS and GCP)
category: workflows
description: 'Fire Cortex XSIAM''s native "New cloud identity created with administrative policy" analytics alert (Low, T1136.003 / T1098.001) on AWS and on GCP by sending synthetic cloud audit events through the http-sender connector in Cribl mode. AWS: an IAM user creates a role and a user and gives the user full administrator rights (5 CloudTrail records). GCP: a user creates a service account and grants it roles/owner on the project (2 Cloud Audit entries). Use when the operator asks to trigger, demo, prove or reproduce a new admin identity, a new administrator IAM user, a service account given owner, or privilege escalation through a new cloud identity. Two http-sender generate_events calls with no other argument, in order: aws_cloudtrail.iam_new_admin_identity (to cribl_aws_audit), then gcp_audit.new_admin_service_account (to cribl_gcp_cloud_logging); either may be sent alone. The alert can arrive from about a minute to several minutes after the last event (AWS is slower and more variable): wait up to 15 minutes. The instance must have criblUrl and the criblToken secret.'
icon: admin_panel_settings
source: platform
loadingMode: on-demand
locked: false
---

# Skill: Trigger the "New cloud identity created with administrative policy" alert (AWS and GCP)

## When this skill applies

The operator wants the **native Cortex Analytics cloud detector for a new identity with an administrative policy** to fire, for example:
*"trigger a new cloud admin identity alert"*, *"show an admin IAM user being created in AWS"*, *"show a service account given owner in GCP"*, *"prove T1136.003 fires from cloud audit logs"*.

It is not a correlation rule; it is Cortex's own analytics (Cloud module, `XDR Analytics`), and nothing needs installing on the tenant. The same alert name is raised for both clouds, and there are **two calls, one per cloud, in this order**. **Either may be sent alone** (the AWS call for AWS, the GCP call for GCP); the two do not depend on each other.

> **It needs the Cribl route.** The destinations are `cribl_aws_audit` (AWS CloudTrail source, dataset `amazon_aws_raw`) and `cribl_gcp_cloud_logging` (GCP Cloud Logging source, dataset `google_cloud_logging_raw`): the tenant's Cribl integration under each source's dedicated identifier, which gives the rows the native feed's treatment (normalized audit rows and the out-of-the-box Cloud detectors). The `http-sender` instance must have `criblUrl` and the `criblToken` secret set; without them the calls are refused with a clear message and nothing is sent.

## What the detector looks for (Cortex doc: "New cloud identity created with administrative policy")

| Property | Value |
|---|---|
| Alert name | `New cloud identity created with administrative policy` (**Low**). A variation, `Administrative IAM User Created with Credentials` (Low), is a different recipe (an assumed role creating a user and an access key); it is **not** raised by these calls, see the warning below |
| Source | `XDR Analytics`, Cloud module; MITRE shown on the alert: `T1136.003 - Create Account: Cloud Account`, `T1136 - Create Account` and `T1098.001 - Account Manipulation: Additional Cloud Credentials`; alert tags `DS:Amazon/AWS` (AWS) or `DS:Google/Cloud Logging` (GCP), plus `DOM:Security` |
| Required data (doc) | AWS Audit Log OR GCP Audit Log |
| Activation / training (doc) | 14 days / 30 days. In practice the alert arrives within minutes (see Expected result) |
| Test period (doc) | **1 hour**: the creation and the administrative grant must fall inside it. Both calls place all their events in the last 2 minutes |
| Deduplication (doc) | 1 day. Every call invents new users, accounts and projects, so a repeat fires again |
| What the alert text says | AWS: *"The identity audit-bot-<hex> was created by <name>.<hex>. The newly created identity was assigned administrative policy. The operation was performed on AWS/<account>"*. GCP: *"The identity deploy-bot-<hex>@<project id>.iam.gserviceaccount.com was created by <name>.<hex>@phantom.lab. The newly created identity was assigned administrative policy. The operation was performed on GCP/<project id: the organization's, `phantom-lab-prod` on Phantom Lab>"* |

**Attribution warning.** The same minutes can raise `Administrative IAM User Created with Credentials` from the AWS-only recipe `iam_admin_user_credentials`, and other runs on the tenant raise this alert name too. Credit an alert to your call only when the **identity named in its `user_name` and `description` is the one your events carry** (Step 2): the actor of every call is new.

## Preconditions: check these BEFORE sending

| # | Must be true | How to check |
|---|---|---|
| 1 | The `http-sender` instance is running with Cribl configured: `list_destinations` shows **`cribl_aws_audit`** and/or **`cribl_gcp_cloud_logging`** with `ready: true` (whichever cloud you send) | `http-sender.list_destinations` |
| 2 | You pass **no** `destination`, `target_user`, `source_ip` or `count`. Each profile's default destination is its Cribl one. The default `count` is the recipe's step count (AWS 5, GCP 2) and a smaller one is refused. The actors (an IAM user `<name>.<hex>` in the organization's AWS account; a user `<name>.<hex>@phantom.lab` in the organization's GCP project) are invented per call, from the Saudi home pool | read the calls below |
| 3 | The steps of one call are spread over the last 2 minutes and end at the moment of the call | none |

## Expected result

Both calls go through the Cribl destinations and raise the Low alert for the identity that acted. The latency is counted from the **last** event of the call (the creation and the grant are separate events): the GCP alert typically arrives within a minute or two, the AWS alert is slower and variable, from about a minute to several minutes. Do not conclude a failure before **15 minutes**. A second call of either recipe is a new actor and raises its own alert. The recipes raise no alert other than `New cloud identity created with administrative policy`: any `Administrative IAM User Created with Credentials` alerts in the same minutes belong to other users and the other recipe.

## Step 1: send the events (exactly these calls)

Call **`http-sender.generate_events`** with the first block (AWS), then with the second (GCP). Each block is one complete call; there is nothing to replace. Send only the one you need.

AWS: an IAM user creates a role with a foreign-account trust, attaches `AdministratorAccess` to it, creates a new IAM user, gives that user an all-allowed inline policy (`"Action": "*"`) and attaches `AdministratorAccess` to it:

```json
{"profile": "aws_cloudtrail", "scenario": "iam_new_admin_identity"}
```

The answer carries `sent: 5`, `destination: "cribl_aws_audit"`, `dataset: "amazon_aws_raw"`, five `sample_ids` (the records' `eventID`) and `first_time` / `last_time`. The five records are, in order, `CreateRole`, `AttachRolePolicy`, `CreateUser`, `PutUserPolicy`, `AttachUserPolicy`, 30 seconds apart, all by the same IAM user (an IAM user acting: the same sequence through an assumed role does not raise the alert).

GCP: a user creates a service account, then grants it `roles/owner` on the project:

```json
{"profile": "gcp_audit", "scenario": "new_admin_service_account"}
```

The answer carries `sent: 2`, `destination: "cribl_gcp_cloud_logging"`, `dataset: "google_cloud_logging_raw"`, two `sample_ids` (the entries' `insertId`) and `first_time` / `last_time`. The two entries are `google.iam.admin.v1.CreateServiceAccount` (`deploy-bot-<hex>`) and `SetIamPolicy` ADDing `roles/owner` for `serviceAccount:<that account>`, 2 minutes apart, by the same new user.

## Step 2: confirm the events landed (about 1 minute after Step 1)

AWS:

```text
config timeframe = 1h | dataset = amazon_aws_raw
| filter _collector_name = "phantom-http-sender" and eventID in ("<id 1>", "<id 2>", "<id 3>", "<id 4>", "<id 5>")
| alter who = json_extract_scalar(userIdentity, "$.arn")
| fields _time, eventName, sourceIPAddress, who
| sort asc _time
```

Pass when 5 rows return with the five event names above in order, one `who` (`arn:aws:iam::<account>:user/<name>.<hex>`) and one `sourceIPAddress`.

GCP:

```text
config timeframe = 1h | dataset = google_cloud_logging_raw
| filter _collector_name = "phantom-http-sender" and insertId in ("<id 1>", "<id 2>")
| alter method = json_extract_scalar(protoPayload, "$.methodName"), caller = json_extract_scalar(protoPayload, "$.authenticationInfo.principalEmail"), ip = json_extract_scalar(protoPayload, "$.requestMetadata.callerIp")
| fields _time, insertId, method, caller, ip, _collector_type
| sort asc _time
```

Pass when 2 rows return, `CreateServiceAccount` then `SetIamPolicy`, the same `caller` and `ip`, `_collector_type = GCP Pub/Sub`. Without the packs that carry the modeling rules installed, AWS and GCP rows land without XDM; the detector does not need it.

## Step 3: wait, then check for the alert

Check **1 minute** after the last event, then every minute for up to **15 minutes** (GCP typically arrives within a minute or two; AWS can take several minutes). `<epoch ms>` is the time of the send in milliseconds:

```text
config timeframe = 1d | dataset = alerts
| filter alert_source in ("MAGNIFIER", "ANALYTICS_BIOC") and alert_name = "New cloud identity created with administrative policy"
| filter alert_arrival_timestamp > <epoch ms>
| fields alert_arrival_timestamp, alert_id, alert_name, severity, user_name, host_ip, mitre_attack_technique, original_tags, description
| sort desc alert_arrival_timestamp
| limit 10
```

Use the stored enum names `MAGNIFIER` and `ANALYTICS_BIOC`: the displayed names `XDR_ANALYTICS` and `XDR_ANALYTICS_BIOC` match nothing in a filter.

Pass when a row's `user_name` and `description` name **your** acting identity and `host_ip` is your caller IP (AWS: `user_name` is the bare IAM user, e.g. `<name>.<hex>`; GCP: `phantom\<local part>`). Expect `severity` LOW and `original_tags` with `DS:Amazon/AWS` or `DS:Google/Cloud Logging`.

If nothing arrives in 15 minutes: re-run Step 2 (all 5 / both rows must be there), confirm the destination, then retry **once** with the same call (it generates new identities). Do not change the recipe: an assumed role instead of an IAM user does not raise the alert for AWS.

## Report back to the operator

State which cloud(s) you sent, the acting identity and account or project, the caller IP, the Step 2 result and, per cloud, either the alert id with its arrival time and latency or that nothing arrived in 15 minutes and what you checked. Say that every call uses new identities, so repeating it is safe, and that the AWS alert can take several minutes.

Note: the Cortex `user_name` prefix shown above (`phantom\`) is the first label of the organization's email domain (`phantom.lab`); it was `phantom-lab\` on the previous domain. It has not been re-measured on the tenant, so confirm it on the first replay.
