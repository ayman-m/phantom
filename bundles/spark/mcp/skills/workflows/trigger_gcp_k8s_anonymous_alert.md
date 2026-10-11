---
name: trigger_gcp_k8s_anonymous_alert
displayName: Trigger the Cortex "A Kubernetes API operation was successfully invoked by an anonymous user outside the cluster" analytics alert
category: workflows
description: 'Fire Cortex XSIAM''s native "A Kubernetes API operation was successfully invoked by an anonymous user outside the cluster" analytics BIOC (High, T1078.001, Kubernetes - API) by sending ONE synthetic Google Cloud Audit log entry through the http-sender connector in Cribl mode: system:anonymous listing the namespaces of a GKE cluster from an outside public address. Use when the operator asks to trigger, demo, prove or reproduce anonymous access to a Kubernetes API server, system:anonymous or unauthenticated Kubernetes API calls on GCP. One http-sender generate_events call (profile gcp_audit, scenario k8s_anonymous) with no other argument, to the cribl_gcp_cloud_logging destination (the instance must have criblUrl and the criblToken secret). The detector is deduplicated for 5 days on the same anonymous identity and cluster, so check the dedup window (Step 0) before sending and expect no alert while an earlier alert of this name is less than 5 days old.'
icon: no_accounts
source: platform
loadingMode: on-demand
locked: false
---

# Skill: Trigger the "Kubernetes API operation invoked by an anonymous user outside the cluster" alert

## Deduplication window (read first)

The Cortex documentation gives this detector a **5-day deduplication period**, and the actor of the recipe is always the same identity (`system:anonymous`, cluster `phantom-gke-1`). While an alert of this name for that identity and cluster is less than 5 days old, a new call lands its rows in `google_cloud_logging_raw` correctly but raises **no alert**, and changing the caller address (`source_ip`) does not break the deduplication. After the window has passed, the call below fires again.

Do Step 0 first. If an alert of this name is less than 5 days old, tell the operator that the detector is in its deduplication window and do not send the call over and over (it adds rows and no alert).

## When this skill applies

The operator wants the **native Cortex Analytics Kubernetes anonymous-access detector** to fire on GCP data, for example:
*"trigger an anonymous Kubernetes API alert"*, *"show system:anonymous calling the API server"*, *"prove T1078.001 default-account abuse is detected on GKE"*.

It is not a correlation rule; it is Cortex's own analytics (Cloud module, `XDR Analytics BIOC`), and nothing needs installing on the tenant.

> **It needs the Cribl route.** The destination is `cribl_gcp_cloud_logging`: the tenant's Cribl integration under the GCP Cloud Logging source's dedicated identifier, which gives the rows the native feed's treatment (collector type `GCP Pub/Sub`, normalized audit rows, the out-of-the-box Cloud detectors). The `http-sender` instance must have `criblUrl` and the `criblToken` secret set; without them the call is refused with a clear message and nothing is sent.

## What the detector looks for (Cortex doc: "A Kubernetes API operation was successfully invoked by an anonymous user")

| Property | Value |
|---|---|
| Alert name | `A Kubernetes API operation was successfully invoked by an anonymous user outside the cluster` (**High**); the base alert `A Kubernetes API operation was successfully invoked by an anonymous user` is Medium |
| Source | `XDR Analytics BIOC`, Cloud module; MITRE shown on the alert: `T1078.001 - Valid Accounts: Default Accounts`; alert tags `DS:Google/Cloud Logging`, `DT:Kubernetes - API` |
| Required data (doc) | one of AWS Audit Log, Azure Audit Log, GCP Audit Log, Kubernetes Audit Logs |
| Activation / training (doc) | 14 days / 30 days. In practice the alert typically arrives within a minute or two |
| Test period | single event |
| Deduplication (doc) | **5 days** |
| What the alert text says | *"An anonymous user system:anonymous executed Kubernetes API calls on phantom-gke-1 from <caller ip>. The operation was performed in GCP within phantom-lab-<hex> project. The activity was seen from an external IP address located in <country>"* |

## Step 0: check the deduplication window BEFORE sending

```text
config timeframe = 7d | dataset = alerts
| filter alert_name = "A Kubernetes API operation was successfully invoked by an anonymous user outside the cluster"
| fields alert_arrival_timestamp, alert_id, user_name, host_ip, description
| sort desc alert_arrival_timestamp
| limit 5
```

The query returns the previous alert of this name, if any (`user_name` `system:anonymous`, the earlier `host_ip`, its arrival time). If a row is **less than 5 days old**, stop and report that the detector is in its deduplication window.

## Preconditions: check these BEFORE sending

| # | Must be true | How to check |
|---|---|---|
| 1 | Step 0 shows no alert of this name in the last 5 days | the query above |
| 2 | The `http-sender` instance is running with Cribl configured: `list_destinations` shows **`cribl_gcp_cloud_logging`** with `ready: true` | `http-sender.list_destinations` |
| 3 | You pass **no** `destination`, `target_user` or `count` (the recipe is 1 event). The caller address is drawn from the out-of-country pool by default (`source_ip` overrides it, but it does not defeat the deduplication) and the project is invented per call | read the call below |

## Expected result

Outside the deduplication window, the call raises the High alert, typically within a minute or two. The alert's tags are `DS:Google/Cloud Logging`, `DOM:Security`, `DT:Kubernetes - API`; source `XDR_ANALYTICS_BIOC`; severity HIGH; MITRE `T1078.001 - Valid Accounts: Default Accounts`. The recipe raises no other alert. Inside the window the row lands but no alert is raised, even with a different caller address.

## Step 1: send the event (exactly this call)

Call **`http-sender.generate_events`** once. There is nothing to replace.

```json
{"profile": "gcp_audit", "scenario": "k8s_anonymous"}
```

The answer carries `sent: 1`, `batch_status: [200]`, `destination: "cribl_gcp_cloud_logging"`, `sample_ids` (the entry's `insertId`) and `first_time`. What the event is: a Cloud Audit `data_access` entry on the resource type `k8s_cluster` (cluster `phantom-gke-1`), `serviceName k8s.io`, `methodName io.k8s.core.v1.namespaces.list`, principal **`system:anonymous`** with `authoritySelector system:unauthenticated`, user agent `curl/8.4.0`, from a public address outside the country.

## Step 2: confirm the event landed (about 1 minute after Step 1)

```text
config timeframe = 1h | dataset = google_cloud_logging_raw
| filter _collector_name = "phantom-http-sender" and insertId = "<the sample_id>"
| alter method = json_extract_scalar(protoPayload, "$.methodName"), caller = json_extract_scalar(protoPayload, "$.authenticationInfo.principalEmail"), ip = json_extract_scalar(protoPayload, "$.requestMetadata.callerIp"), selector = json_extract_scalar(protoPayload, "$.authenticationInfo.authoritySelector")
| fields _time, insertId, method, caller, ip, selector, _collector_type
```

Pass when one row returns with `method = io.k8s.core.v1.namespaces.list`, `caller = system:anonymous`, `selector = system:unauthenticated` and `_collector_type = GCP Pub/Sub` Without the modeling pack the GCP rows land without XDM; the detector does not need it.

## Step 3: wait, then check for the alert

Check every 10 seconds for up to **3 minutes** (it typically arrives within a minute or two). `<epoch ms>` is the time of the send in milliseconds:

```text
config timeframe = 1d | dataset = alerts
| filter alert_source in ("MAGNIFIER", "ANALYTICS_BIOC") and alert_name = "A Kubernetes API operation was successfully invoked by an anonymous user outside the cluster"
| filter alert_arrival_timestamp > <epoch ms>
| fields alert_arrival_timestamp, alert_id, alert_name, severity, user_name, host_ip, mitre_attack_technique, original_tags, description
| sort desc alert_arrival_timestamp
| limit 10
```

Use the stored enum names `MAGNIFIER` and `ANALYTICS_BIOC`: the displayed names `XDR_ANALYTICS` and `XDR_ANALYTICS_BIOC` match nothing in a filter.

Pass when a row has `user_name` `system:anonymous` and `host_ip` your caller IP; expect `severity` HIGH. A silent result inside the 5-day window is expected (see the deduplication window above), not a fault of the connector.

## Report back to the operator

State whether Step 0 found an alert inside the 5-day window (and its id and time), the caller IP, the `insertId`, the Step 2 result and either the new alert id with its arrival time or that nothing arrived and that the detector is deduplicated for 5 days per its documentation. Do not claim the detector fired unless Step 3 returned a row for your event.
