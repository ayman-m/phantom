---
name: trigger_gcp_sensitive_role_to_group_alert
displayName: Trigger the Cortex "GCP sensitive role granted to group" analytics alert
category: workflows
description: 'Fire Cortex XSIAM''s native "GCP sensitive role granted to group" analytics BIOC (Low, T1098.003 Additional Cloud Roles) by sending ONE synthetic Google Cloud Audit log entry through the http-sender connector in Cribl mode: a SetIamPolicy call on the organization''s GCP project that adds roles/owner for a Google group. Use when the operator asks to trigger, demo, prove or reproduce a privileged role granted to a group in GCP, an owner or admin role given to a group, or GCP IAM privilege escalation through a group. One http-sender generate_events call (profile gcp_audit, scenario sensitive_role_to_group) with no other argument: it goes to the cribl_gcp_cloud_logging destination, invents a fresh user, project and group on every call, and the alert typically arrives within about 15 seconds. The instance must have criblUrl and the criblToken secret.'
icon: group_add
source: platform
loadingMode: on-demand
locked: false
---

# Skill: Trigger the "GCP sensitive role granted to group" alert

## When this skill applies

The operator wants the **native Cortex Analytics cloud detector for a sensitive role granted to a group** to fire on GCP data, for example:
*"trigger a GCP owner-to-group alert"*, *"show a privileged role being granted to a group"*, *"prove T1098.003 fires from GCP audit logs"*.

It is not a correlation rule; it is Cortex's own analytics (Cloud module, `XDR Analytics BIOC`), and nothing needs installing on the tenant. It fired **2 of 2** with two different fresh identities.

> **It needs the Cribl route.** The destination is `cribl_gcp_cloud_logging`: the tenant's Cribl integration under the GCP Cloud Logging source's dedicated identifier, which gives the rows the native feed's treatment (collector type `GCP Pub/Sub`, normalized audit rows, the out-of-the-box Cloud detectors). The `http-sender` instance must have `criblUrl` and the `criblToken` secret set; without them the call is refused with a clear message and nothing is sent.

## What the detector looks for (Cortex doc: "GCP sensitive role granted to group")

| Property | Value |
|---|---|
| Alert name | `GCP sensitive role granted to group` (shown **Low**; the doc lists a Medium variation of the same name, which does not appear) |
| Source | `XDR Analytics BIOC`, Cloud module; MITRE shown on the alert: `T1098 - Account Manipulation` and `T1098.003 - Account Manipulation: Additional Cloud Roles`; alert tag `DS:Google/Cloud Logging` |
| Required data (doc) | GCP Audit Log |
| Activation / training (doc) | 14 days / 30 days in the documentation; in practice the alert arrives within seconds |
| Test period | single event |
| Deduplication (doc) | 5 days. Every call invents a new user, project and group, so a repeat is a new identity and fires again |
| What the alert text says | *"The identity <name>.<hex>@<domain> modified an IAM policy. The identity performed the following operation SetIamPolicy against the cloudresourcemanager.googleapis.com resource, which affected its policy bindings. The operation status was SUCCESS"* (it does not name the role or the group: read those from the event, Step 2) |

## Preconditions: check these BEFORE sending

| # | Must be true | How to check |
|---|---|---|
| 1 | The `http-sender` instance is running with Cribl configured: `list_destinations` shows **`cribl_gcp_cloud_logging`** with `ready: true` (dataset `google_cloud_logging_raw`) | `http-sender.list_destinations` |
| 2 | You pass **no** `destination`, `target_user`, `source_ip` or `count`. The scenario's default destination is the Cribl one, and the actor, the group (`eng-<hex>@phantom.lab`) and the caller address are invented per call; the project is the organization's GCP project (`phantom-lab-prod` on Phantom Lab) | read the call below |
| 3 | The call is one event (the recipe has 1 step). The event time is now | none |

## Expected result

Destination `cribl_gcp_cloud_logging`, one event, severity Low. Latency is counted from the event time the connector stamped: the alert typically arrives within about 15 seconds. The alert names the identity of its own event, so each call is attributed to its own alert. The recipe raises no alert other than the one named here.

## Step 1: send the event (exactly this call)

Call **`http-sender.generate_events`** once. There is nothing to replace.

```json
{"profile": "gcp_audit", "scenario": "sensitive_role_to_group"}
```

The answer carries `sent: 1`, `batch_status: [200]`, `destination: "cribl_gcp_cloud_logging"`, `dataset: "google_cloud_logging_raw"`, `sample_ids` (the entry's `insertId`) and `first_time` (the event time). Keep the `insertId` and the time.

What the one event is: a Cloud Audit `activity` log entry, `serviceName cloudresourcemanager.googleapis.com`, `methodName SetIamPolicy`, on `projects/<the organization's project id>`, whose `policyDelta` ADDs the role **`roles/owner`** for the member **`group:eng-<hex>@phantom.lab`**, by a new user from a Saudi home address. An owner role bound to a `group:` member is what the detector reads.

## Step 2: confirm the event landed (about 1 minute after Step 1)

```text
config timeframe = 1h | dataset = google_cloud_logging_raw
| filter _collector_name = "phantom-http-sender" and insertId = "<the sample_id>"
| alter method = json_extract_scalar(protoPayload, "$.methodName"), caller = json_extract_scalar(protoPayload, "$.authenticationInfo.principalEmail"), ip = json_extract_scalar(protoPayload, "$.requestMetadata.callerIp"), role = json_extract_scalar(protoPayload, "$.serviceData.policyDelta.bindingDeltas[0].role"), member = json_extract_scalar(protoPayload, "$.serviceData.policyDelta.bindingDeltas[0].member")
| fields _time, insertId, method, caller, ip, role, member, _collector_type
```

Pass when one row returns with `method = SetIamPolicy`, `role = roles/owner`, `member` starting `group:` and `_collector_type = GCP Pub/Sub`. On a tenant without the pack that carries the GCP modeling rule, the rows land without XDM; the detector does not need it, so do not wait for `xdm.*` fields.

## Step 3: wait, then check for the alert

Check **10 seconds** after the event, then every 10 seconds for up to **3 minutes** (the alert typically arrives within about 15 s). `<epoch ms>` is the time of the send in milliseconds:

```text
config timeframe = 1d | dataset = alerts
| filter alert_source in ("MAGNIFIER", "ANALYTICS_BIOC") and alert_name = "GCP sensitive role granted to group"
| filter alert_arrival_timestamp > <epoch ms>
| fields alert_arrival_timestamp, alert_id, alert_name, severity, user_name, host_ip, mitre_attack_technique, original_tags, description
| sort desc alert_arrival_timestamp
| limit 10
```

Use the stored enum names `MAGNIFIER` and `ANALYTICS_BIOC`: the displayed names `XDR_ANALYTICS` and `XDR_ANALYTICS_BIOC` match nothing in a filter.

Pass when a row names your identity (`user_name` shows `phantom\<local part>`) and `host_ip` is your caller IP. Expect `severity` LOW, `mitre_attack_technique` `T1098 - Account Manipulation|T1098.003 - Account Manipulation: Additional Cloud Roles` and `original_tags` with `DS:Google/Cloud Logging`.

If nothing arrives in 3 minutes: re-run Step 2 (the row must be in `google_cloud_logging_raw` with `_collector_type = GCP Pub/Sub`), confirm the destination was `cribl_gcp_cloud_logging`, then retry **once** with the same call (it generates a new identity).

## Report back to the operator

State the cloud identity, the project and the group (from the Step 2 row), the caller IP, the `insertId`, the Step 2 result and either the alert id with its arrival time and latency or that nothing arrived in 3 minutes and what you checked. Say that every call uses a new identity, so repeating it is safe.

Note: the Cortex `user_name` prefix shown above (`phantom\`) is the first label of the organization's email domain (`phantom.lab`); it was `phantom-lab\` on the previous domain. It has not been re-measured on the tenant, so confirm it on the first replay.
