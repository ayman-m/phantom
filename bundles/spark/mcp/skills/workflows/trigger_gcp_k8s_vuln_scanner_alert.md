---
name: trigger_gcp_k8s_vuln_scanner_alert
displayName: Trigger the Cortex "External Kubernetes vulnerability scanning tool usage" analytics alert
category: workflows
description: 'Fire Cortex XSIAM''s native "External Kubernetes vulnerability scanning tool usage" analytics BIOC (Medium, T1610 / T1613, Kubernetes - API) by sending 4 synthetic Google Cloud Audit log entries through the http-sender connector in Cribl mode: a GKE service account listing the pods of a cluster from an outside address, once with each of four well-known scanner user agents (kube-hunter, kubescape, Trivy, kube-bench). Use when the operator asks to trigger, demo, prove or reproduce a Kubernetes vulnerability scanner, kube-hunter or Kubescape activity against a cluster, or a Kubernetes reconnaissance alert on GCP. One http-sender generate_events call (profile gcp_audit, scenario k8s_vuln_scanner) with no other argument: it goes to the cribl_gcp_cloud_logging destination, invents a fresh service account, project and caller address on every call, and the alert typically arrives within about 15 seconds of the last event. The instance must have criblUrl and the criblToken secret.'
icon: bug_report
source: platform
loadingMode: on-demand
locked: false
---

# Skill: Trigger the "External Kubernetes vulnerability scanning tool usage" alert

## When this skill applies

The operator wants the **native Cortex Analytics Kubernetes scanner detector** to fire on GCP data, for example:
*"trigger a Kubernetes vulnerability scanner alert"*, *"show kube-hunter or Kubescape being used against a GKE cluster"*, *"prove the Kubernetes - API analytics fire from GCP audit logs"*.

It is not a correlation rule; it is Cortex's own analytics (Cloud module, `XDR Analytics BIOC`), and nothing needs installing on the tenant. It fired **2 of 2** with two different fresh identities.

> **It needs the Cribl route.** The destination is `cribl_gcp_cloud_logging`: the tenant's Cribl integration under the GCP Cloud Logging source's dedicated identifier, which gives the rows the native feed's treatment (collector type `GCP Pub/Sub`, normalized audit rows, the out-of-the-box Cloud detectors). The `http-sender` instance must have `criblUrl` and the `criblToken` secret set; without them the call is refused with a clear message and nothing is sent.

## What the detector looks for (Cortex doc: "Kubernetes vulnerability scanning tool usage")

| Property | Value |
|---|---|
| Alert name | `External Kubernetes vulnerability scanning tool usage` (**Medium**). The sibling variation `Kubernetes vulnerability scanning tool usage within a pod` did not appear: the caller here is outside the cluster |
| Source | `XDR Analytics BIOC`, Cloud module; MITRE shown on the alert: `T1610 - Deploy Container` and `T1613 - Container and Resource Discovery`; alert tags `DS:Google/Cloud Logging`, `DT:Kubernetes - API` |
| Required data (doc) | one of AWS Audit Log, Azure Audit Log, GCP Audit Log, Kubernetes Audit Logs |
| Activation / training (doc) | 14 days / 30 days in the documentation; in practice the alert arrives within seconds |
| Test period | single event |
| Deduplication (doc) | 5 days. Every call invents a new service account, project and address, so a repeat fires again |
| What the alert text says | *"gke-reader-<hex>@<project id>.iam.gserviceaccount.com has used a known vulnerability scanning tool within cluster phantom-gke-1. The identity operated from <caller address>. The tool that was used was Kubescape. The operation was performed on GCP/<project id: the organization's, `phantom-lab-prod` on Phantom Lab>"* |

## Preconditions: check these BEFORE sending

| # | Must be true | How to check |
|---|---|---|
| 1 | The `http-sender` instance is running with Cribl configured: `list_destinations` shows **`cribl_gcp_cloud_logging`** with `ready: true` (dataset `google_cloud_logging_raw`) | `http-sender.list_destinations` |
| 2 | You pass **no** `destination`, `target_user`, `source_ip` or `count`. The default `count` is the recipe's 4 steps (the minimum; a smaller one is refused). The service account (`gke-reader-<hex>@<project id>.iam.gserviceaccount.com`) and the outside caller address are invented per call; the project is the organization's GCP project (`phantom-lab-prod` on Phantom Lab) | read the call below |
| 3 | The 4 events are spread over the last 2 minutes and end at the moment of the call, nothing in the future | none |

## Expected result

Destination `cribl_gcp_cloud_logging`, 4 events 40 seconds apart, severity Medium. The four rows are ingested in one batch, so the latency is counted from the **last** event: the alert typically arrives within about 15 seconds. The alert names the service account of its own call, so each call is attributed to its own alert. The alert's own event time is the **second** event (the `kubescape/v3.0.8` one), and its description names Kubescape; whether the other three user agents are needed is not isolated (the recipe's minimum is the 4 events). The recipe raises no alert other than the one named here.

## Step 1: send the events (exactly this call)

Call **`http-sender.generate_events`** once. There is nothing to replace.

```json
{"profile": "gcp_audit", "scenario": "k8s_vuln_scanner"}
```

The answer carries `sent: 4`, `batch_status: [200]`, `destination: "cribl_gcp_cloud_logging"`, `dataset: "google_cloud_logging_raw"`, four `sample_ids` (the entries' `insertId`) and `first_time` / `last_time`. Keep the ids and the last time.

What the four events are: Cloud Audit `data_access` entries on the resource type `k8s_cluster` (cluster `phantom-gke-1`), `serviceName k8s.io`, `methodName io.k8s.core.v1.pods.list` on `core/v1/namespaces/default/pods`, all by the same new GKE service account from the same outside address, each carrying a different scanner user agent in order: `kube-hunter/0.6.8`, `kubescape/v3.0.8`, `Trivy/0.50.1`, `kube-bench/0.7.3`.

## Step 2: confirm the events landed (about 1 minute after Step 1)

```text
config timeframe = 1h | dataset = google_cloud_logging_raw
| filter _collector_name = "phantom-http-sender" and insertId in ("<id 1>", "<id 2>", "<id 3>", "<id 4>")
| alter method = json_extract_scalar(protoPayload, "$.methodName"), caller = json_extract_scalar(protoPayload, "$.authenticationInfo.principalEmail"), ip = json_extract_scalar(protoPayload, "$.requestMetadata.callerIp"), ua = json_extract_scalar(protoPayload, "$.requestMetadata.callerSuppliedUserAgent")
| fields _time, insertId, method, caller, ip, ua
| sort asc _time
```

Pass when 4 rows return, all with `method = io.k8s.core.v1.pods.list`, the same `caller` and `ip`, and the four user agents above in order On a tenant without the pack that carries the GCP modeling rule, the rows land without XDM; the detector does not need it.

## Step 3: wait, then check for the alert

Check **10 seconds** after the last event, then every 10 seconds for up to **3 minutes** (the alert typically arrives within about 15 s). `<epoch ms>` is the time of the send in milliseconds:

```text
config timeframe = 1d | dataset = alerts
| filter alert_source in ("MAGNIFIER", "ANALYTICS_BIOC") and alert_name = "External Kubernetes vulnerability scanning tool usage"
| filter alert_arrival_timestamp > <epoch ms>
| fields alert_arrival_timestamp, alert_id, alert_name, severity, user_name, host_ip, mitre_attack_technique, original_tags, description
| sort desc alert_arrival_timestamp
| limit 10
```

Use the stored enum names `MAGNIFIER` and `ANALYTICS_BIOC`: the displayed names `XDR_ANALYTICS` and `XDR_ANALYTICS_BIOC` match nothing in a filter.

Pass when a row names your service account in `user_name` and `host_ip` is your caller IP. Expect `severity` MEDIUM, `mitre_attack_technique` `T1610 - Deploy Container|T1613 - Container and Resource Discovery` and `original_tags` with `DS:Google/Cloud Logging` and `DT:Kubernetes - API`.

If nothing arrives in 3 minutes: re-run Step 2 (all 4 rows must be in `google_cloud_logging_raw`), confirm the destination was `cribl_gcp_cloud_logging`, then retry **once** with the same call (it generates a new service account and address).

## Report back to the operator

State the service account, the cluster (`phantom-gke-1`) and project, the caller IP, the 4 `insertId`s, the Step 2 result and either the alert id with its arrival time and latency or that nothing arrived in 3 minutes and what you checked. Say that every call uses a new service account and address, so repeating it is safe.
