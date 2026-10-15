---
name: trigger_cloud_tor_api_call_alerts
displayName: Trigger the Cortex "Suspicious API call from a Tor exit node" and "Cloud activity from an unusual high-risk IP" analytics alerts (AWS and GCP)
category: workflows
description: 'Fire two of Cortex XSIAM''s native cloud analytics alerts from one recipe, on AWS and on GCP: "Suspicious API call from a Tor exit node" (High, T1090.003 / T1078.004) and "Cloud activity from an unusual high-risk IP" (Low, T1090.003 / T1078), by sending synthetic cloud audit events through the http-sender connector in Cribl mode: a new cloud user calling read-only APIs from a Tor exit node (AWS: ListUsers and ListBuckets; GCP: storage.objects.get). Use when the operator asks to trigger, demo, prove or reproduce an API call from Tor, a cloud login or activity from an anonymizing proxy, or a high-risk IP in AWS or GCP. Two http-sender generate_events calls with no other argument, in order: aws_cloudtrail.tor_api_call (to cribl_aws_audit), then gcp_audit.tor_api_call (to cribl_gcp_cloud_logging); either may be sent alone. Each cloud typically raises both alerts within about 15 seconds of the event; an occasional call stays silent when the drawn Tor exit has left the network (see the gotchas). The instance must have criblUrl and the criblToken secret.'
icon: vpn_lock
source: platform
loadingMode: on-demand
locked: false
---

# Skill: Trigger the "Suspicious API call from a Tor exit node" and "Cloud activity from an unusual high-risk IP" alerts (AWS and GCP)

## When this skill applies

The operator wants the **native Cortex Analytics cloud Tor detectors** to fire, for example:
*"trigger a Tor API call alert in AWS"*, *"show a cloud user calling the API from a Tor exit"*, *"prove T1090.003 is detected on GCP audit logs"*, *"raise a high-risk IP alert"*.

One recipe raises **two alerts per cloud** from the same events: `Suspicious API call from a Tor exit node` (High) and `Cloud activity from an unusual high-risk IP` (Low). They are not correlation rules; they are Cortex's own analytics (Cloud module, `XDR Analytics BIOC`), and nothing needs installing on the tenant. There are **two calls, one per cloud, in this order**: AWS, then GCP. **Either may be sent alone**; they do not depend on each other.

> **It needs the Cribl route.** The destinations are `cribl_aws_audit` (AWS CloudTrail source, dataset `amazon_aws_raw`) and `cribl_gcp_cloud_logging` (GCP Cloud Logging source, dataset `google_cloud_logging_raw`): the tenant's Cribl integration under each source's dedicated identifier, which gives the rows the native feed's treatment (normalized audit rows and the out-of-the-box Cloud detectors). The `http-sender` instance must have `criblUrl` and the `criblToken` secret set; without them the calls are refused with a clear message and nothing is sent.

## What the detectors look for (Cortex docs)

| Property | `Suspicious API call from a Tor exit node` | `Cloud activity from an unusual high-risk IP` |
|---|---|---|
| Severity | **High** (an informational sibling for failed calls exists and did not appear) | **Low** (the base detector, "Cloud activity from a high-risk IP address", is Informational) |
| Source | `XDR Analytics BIOC`, Cloud module | `XDR Analytics BIOC`, Cloud module |
| MITRE shown on the alert | `T1090.003 - Proxy: Multi-hop Proxy`, `T1078.004 - Valid Accounts: Cloud Accounts` | `T1090.003 - Proxy: Multi-hop Proxy`, `T1078 - Valid Accounts` |
| Alert tags | `DS:Amazon/AWS` or `DS:Google/Cloud Logging`, `DT:OCI Analytics`, `DT:Kubernetes - API`, `DOM:Security` | `DS:Amazon/AWS` or `DS:Google/Cloud Logging`, `DT:OCI Analytics`, `DOM:Security` |
| Required data (doc) | AWS, Azure or GCP Audit Log, or Kubernetes Audit Logs | AWS, Azure or GCP Audit Log |
| Activation / training (doc) | 14 days / 30 days in the documentation; in practice the alerts arrive within seconds | same |
| Test period | single event | single event |
| Deduplication (doc) | 1 day | 5 days |
| What the alert text says | *"The cloud user <name>.<hex> has called an API from <Tor exit>. This IP address is known as a Tor exit node's IP address in the last 36 hours"* | *"The identity <name>.<hex> executed ListUsers from high-risk IP address <Tor exit>. The associated country is: <country> and the ASN is: <ASN>. This activity was performed on AWS/<account>"* |

## Preconditions: check these BEFORE sending

| # | Must be true | How to check |
|---|---|---|
| 1 | The `http-sender` instance is running with Cribl configured: `list_destinations` shows **`cribl_aws_audit`** and/or **`cribl_gcp_cloud_logging`** with `ready: true` (whichever cloud you send) | `http-sender.list_destinations` |
| 2 | You pass **no** `destination`, `target_user` or `count` (AWS: 2 records, `ListUsers` then `ListBuckets`, 2 minutes apart; GCP: 1 entry). The actor (a new IAM user in the organization's AWS account; a new user in the organization's GCP project) and the **Tor exit** are chosen by the call, so every call is a first-time actor | read the calls below |
| 3 | The Tor exit comes from the connector's snapshot of seven exits. Exits leave the network and an address that left stops being flagged, so a silent result may be a departed exit (see the gotchas) | the `source_ip` of the Step 2 row |

## Expected result

Destinations `cribl_aws_audit` and `cribl_gcp_cloud_logging`, severities High (Tor) and Low (high-risk). Each cloud raises both alerts from the same events, typically within seconds to about 15 s of the last event the connector stamped. Every alert's description names the identity and the exit address of its own call, so the alerts attribute cleanly even when calls overlap. The recipe raises no alert other than the two named here. Occasionally a call stays silent when the drawn exit has left the Tor network (see the gotchas).

## Gotchas

- **The exit is drawn at random from seven snapshot addresses** (`185.220.101.140`, `185.220.101.34`, `185.220.101.45`, `185.220.102.8`, `171.25.193.20`, `171.25.193.25`, `199.249.230.87`), so repeated calls use different ones. A silent call usually means the drawn exit (`199.249.230.87` is the one with the thinnest evidence) is no longer flagged. If an AWS or GCP call is silent for more than 3 minutes, read the exit from the Step 2 row and **repeat the call once** (a new exit is drawn). If the silence persists, pass one more key, `"source_ip": "185.220.101.140"` (a snapshot exit) or a current exit from the bulk list `https://check.torproject.org/torbulkexitlist`, in the same call. The `source_ip` override is unverified.
- **Both alerts come from the same events.** There is no separate call for the high-risk alert; if only one of the two appears, the other is still due for a few seconds, then check the exit as above.
- **A repeat is a new identity.** Every call invents a new user and account or project, so running it again right away raises new alerts despite the documented deduplication of 1 and 5 days.
- **No XDM without the packs.** When the packs that carry their modeling rules are not installed, AWS and GCP rows land without `xdm.*` fields; the detectors do not need it.

## Step 1: send the events (exactly these calls)

Call **`http-sender.generate_events`** with the first block (AWS), then with the second (GCP). Each block is one complete call; there is nothing to replace. Send only the one you need.

AWS: a new IAM user lists the account's users and buckets from a Tor exit:

```json
{"profile": "aws_cloudtrail", "scenario": "tor_api_call"}
```

The answer carries `sent: 2`, `destination: "cribl_aws_audit"`, `dataset: "amazon_aws_raw"`, two `sample_ids` (the records' `eventID`) and `first_time` / `last_time`. The records are `iam.amazonaws.com ListUsers` and `s3.amazonaws.com ListBuckets`, read-only, 2 minutes apart, from one Tor exit.

GCP: a new user reads a Cloud Storage object from a Tor exit:

```json
{"profile": "gcp_audit", "scenario": "tor_api_call"}
```

The answer carries `sent: 1`, `destination: "cribl_gcp_cloud_logging"`, `dataset: "google_cloud_logging_raw"`, one `sample_ids` (the entry's `insertId`) and the event time. The entry is a `data_access` log, `storage.googleapis.com`, `storage.objects.get`, from one Tor exit.

## Step 2: confirm the events landed (about 1 minute after Step 1)

AWS:

```text
config timeframe = 1h | dataset = amazon_aws_raw
| filter _collector_name = "phantom-http-sender" and eventID in ("<id 1>", "<id 2>")
| alter who = json_extract_scalar(userIdentity, "$.arn")
| fields _time, eventName, sourceIPAddress, who
| sort asc _time
```

Pass when 2 rows return (`ListUsers`, `ListBuckets`) with one `sourceIPAddress` (the Tor exit) and one `who`.

GCP:

```text
config timeframe = 1h | dataset = google_cloud_logging_raw
| filter _collector_name = "phantom-http-sender" and insertId = "<the sample_id>"
| alter method = json_extract_scalar(protoPayload, "$.methodName"), caller = json_extract_scalar(protoPayload, "$.authenticationInfo.principalEmail"), ip = json_extract_scalar(protoPayload, "$.requestMetadata.callerIp")
| fields _time, insertId, method, caller, ip, _collector_type
```

Pass when one row returns with `method = storage.objects.get`, a Tor exit in `ip` and `_collector_type = GCP Pub/Sub`. Note the exit: it is the address the alerts will name.

## Step 3: wait, then check for the alerts

Check **10 seconds** after the last event, then every 10 seconds for up to **3 minutes** (the alerts typically arrive within about 15 s). `<epoch ms>` is the time of the send in milliseconds:

```text
config timeframe = 1d | dataset = alerts
| filter alert_source in ("MAGNIFIER", "ANALYTICS_BIOC") and alert_name in ("Suspicious API call from a Tor exit node", "Cloud activity from an unusual high-risk IP")
| filter alert_arrival_timestamp > <epoch ms>
| fields alert_arrival_timestamp, alert_id, alert_name, severity, user_name, host_ip, mitre_attack_technique, original_tags, description
| sort desc alert_arrival_timestamp
| limit 10
```

Use the stored enum names `MAGNIFIER` and `ANALYTICS_BIOC`: the displayed names `XDR_ANALYTICS` and `XDR_ANALYTICS_BIOC` match nothing in a filter.

Pass when two rows name your identity (AWS: `user_name` is the bare IAM user; GCP: `phantom\<local part>`) and `host_ip` is your Tor exit: `Suspicious API call from a Tor exit node` (HIGH) and `Cloud activity from an unusual high-risk IP` (LOW). If nothing arrives in 3 minutes, follow the first gotcha.

## Report back to the operator

State which cloud(s) you sent, the acting identity and account or project, the Tor exit, the Step 2 result and, per cloud, the alert ids (Tor and high-risk) with their arrival times and latency, or that nothing arrived and what you checked (the exit, the landed rows). Say that every call uses a new identity, so repeating it is safe.

Note: the Cortex `user_name` prefix shown above (`phantom\`) is the first label of the organization's email domain (`phantom.lab`); it was `phantom-lab\` on the previous domain. It has not been re-measured on the tenant, so confirm it on the first replay.
