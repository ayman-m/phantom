---
name: trigger_gcp_data_asset_public_alert
displayName: Trigger the Cortex "GCP data asset shared public" analytics alert
category: workflows
description: 'Fire Cortex XSIAM''s native "GCP data asset shared public" analytics BIOC (Low, Cloud Data Asset Public Exposure) by sending ONE synthetic Google Cloud Audit log entry through the http-sender connector in Cribl mode: a storage.setIamPermissions call that grants roles/storage.objectViewer to allUsers on a new bucket. Use when the operator asks to trigger, demo, prove or reproduce a public GCP bucket, a Cloud Storage bucket shared with allUsers, or a GCP data exposure alert. One http-sender generate_events call (profile gcp_audit, scenario data_asset_public) with no other argument: it goes to the cribl_gcp_cloud_logging destination, invents a fresh user, project and bucket on every call, and the alert typically arrives within a minute or two. The instance must have criblUrl and the criblToken secret.'
icon: cloud_off
source: platform
loadingMode: on-demand
locked: false
---

# Skill: Trigger the "GCP data asset shared public" alert

## When this skill applies

The operator wants the **native Cortex Analytics cloud detector for a publicly shared GCP asset** to fire, for example:
*"trigger a GCP public bucket alert"*, *"show a bucket being shared with allUsers"*, *"prove cloud data exposure is detected from GCP audit logs"*.

It is not a correlation rule; it is Cortex's own analytics (Cloud module, `XDR Analytics BIOC`), and nothing needs installing on the tenant.

> **It needs the Cribl route.** The destination is `cribl_gcp_cloud_logging`: the tenant's Cribl integration under the GCP Cloud Logging source's dedicated identifier, which gives the rows the native feed's treatment (collector type `GCP Pub/Sub`, normalized audit rows, the out-of-the-box Cloud detectors). The generic HTTP collector does not produce this alert. The `http-sender` instance must have `criblUrl` and the `criblToken` secret set; without them the call is refused with a clear message and nothing is sent.

## What the detector looks for (Cortex doc: "GCP data asset shared public")

| Property | Value |
|---|---|
| Alert name | `GCP data asset shared public` (**Low**) |
| Source | `XDR Analytics BIOC`, Cloud module; MITRE shown on the alert: `T1685 - Disable or Modify Tools`; alert tags `DS:Google/Cloud Logging`, `DT:Cloud Data Asset Public Exposure`, `DT:Data Detection & Response` |
| Required data (doc) | GCP Audit Log |
| Activation / training (doc) | 14 days / 30 days. In practice the alert typically arrives within a minute or two |
| Test period | single event |
| Deduplication (doc) | 5 days. Every call invents a new user, project and bucket, so a repeat is a new identity and fires again |
| What the alert text says | *"The cloud identity <name>.<hex>@phantom-lab.example has publicly shared projects/_/buckets/phantom-lab-public-<hex> storage. projects/_/buckets/phantom-lab-public-<hex> bucket can be accessed by identities outside of the organization. The operation was performed on GCP/phantom-lab-<hex>"* |

## Preconditions: check these BEFORE sending

| # | Must be true | How to check |
|---|---|---|
| 1 | The `http-sender` instance is running with Cribl configured: `list_destinations` shows **`cribl_gcp_cloud_logging`** with `ready: true` (dataset `google_cloud_logging_raw`) | `http-sender.list_destinations` |
| 2 | You pass **no** `destination`, `target_user`, `source_ip` or `count`. The scenario's default destination is the Cribl one, and the actor, the project (`phantom-lab-<hex>`), the bucket and the caller address are invented per call, so the detector sees a first-time actor each time | read the call below |
| 3 | The call is one event (the recipe has 1 step). The event time is now | none |

## Expected result

The recipe fires from a fresh cloud identity, project and bucket on every call, with destination `cribl_gcp_cloud_logging` and severity Low; the alert typically arrives within a minute or two of the event time the connector stamped. Each alert names the identity of its own event, so it is attributed to its own call. The recipe raises no alert other than `GCP data asset shared public`.

## Step 1: send the event (exactly this call)

Call **`http-sender.generate_events`** once. There is nothing to replace.

```json
{"profile": "gcp_audit", "scenario": "data_asset_public"}
```

The answer carries `sent: 1`, `batch_status: [200]`, `destination: "cribl_gcp_cloud_logging"`, `dataset: "google_cloud_logging_raw"`, `sample_ids` (the entry's `insertId`) and `first_time` (the event time). Keep the `insertId` and the time.

What the one event is: a Cloud Audit `activity` log entry, `serviceName storage.googleapis.com`, `methodName storage.setIamPermissions`, on a new `gcs_bucket`, whose `policyDelta` ADDs `roles/storage.objectViewer` for the member **`allUsers`**, by a new user from a Saudi home address. The `allUsers` member is what makes the bucket public.

## Step 2: confirm the event landed (about 1 minute after Step 1)

```text
config timeframe = 1h | dataset = google_cloud_logging_raw
| filter _collector_name = "phantom-http-sender" and insertId = "<the sample_id>"
| alter method = json_extract_scalar(protoPayload, "$.methodName"), caller = json_extract_scalar(protoPayload, "$.authenticationInfo.principalEmail"), ip = json_extract_scalar(protoPayload, "$.requestMetadata.callerIp"), member = json_extract_scalar(protoPayload, "$.serviceData.policyDelta.bindingDeltas[0].member")
| fields _time, insertId, method, caller, ip, member, _collector_type
```

Pass when one row returns with `method = storage.setIamPermissions`, `member = allUsers` and `_collector_type = GCP Pub/Sub` (caller `<name>.<hex>@phantom-lab.example`, your caller ip). Without the pack that carries the modeling rule installed, the GCP rows land without XDM; the detector does not need it, so do not wait for `xdm.*` fields.

## Step 3: wait, then check for the alert

Check **10 seconds** after the event, then every 10 seconds for up to **3 minutes** (it typically arrives within a minute or two). `<epoch ms>` is the time of the send in milliseconds:

```text
config timeframe = 1d | dataset = alerts
| filter alert_source in ("MAGNIFIER", "ANALYTICS_BIOC") and alert_name = "GCP data asset shared public"
| filter alert_arrival_timestamp > <epoch ms>
| fields alert_arrival_timestamp, alert_id, alert_name, severity, user_name, host_ip, mitre_attack_technique, original_tags, description
| sort desc alert_arrival_timestamp
| limit 10
```

Use the stored enum names `MAGNIFIER` and `ANALYTICS_BIOC`: the displayed names `XDR_ANALYTICS` and `XDR_ANALYTICS_BIOC` match nothing in a filter.

Pass when a row names your identity (`user_name` shows `phantom-lab\<local part>`; `description` shows the full address and the bucket) and `host_ip` is your caller IP. Expect `severity` LOW and `original_tags` with `DS:Google/Cloud Logging`.

If nothing arrives in 3 minutes: re-run Step 2 (the row must be in `google_cloud_logging_raw` with `_collector_type = GCP Pub/Sub`), confirm the destination was `cribl_gcp_cloud_logging`, then retry **once** with the same call (it generates a new identity).

## Report back to the operator

State the cloud identity, the bucket and project (from the alert description), the caller IP, the `insertId`, the Step 2 result and either the alert id with its arrival time and latency or that nothing arrived in 3 minutes and what you checked. Say that every call uses a new identity, so repeating it is safe: the documented 5-day deduplication does not suppress the repeat.
