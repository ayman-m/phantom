---
name: trigger_aws_guardduty_detector_deleted_alert
displayName: Trigger the Cortex "AWS Guard-Duty detector deletion" analytics alert
category: workflows
description: 'Fire Cortex XSIAM''s native "AWS Guard-Duty detector deletion" analytics alert (Low, T1685 Disable or Modify Tools) by sending one synthetic AWS CloudTrail DeleteDetector record from a fresh, never-seen assumed-role identity through the http-sender connector''s Cribl mode (generate_events, profile aws_cloudtrail, scenario guardduty_detector_deleted, destination cribl_aws_audit, dataset amazon_aws_raw). Use when the operator asks to trigger, demo, prove or reproduce an AWS GuardDuty deletion, a disabled threat-detection service, defense evasion in AWS or a cloud analytics alert from CloudTrail. One call, no arguments to fill in, no hand-built events.'
icon: security
source: platform
loadingMode: on-demand
locked: false
---

# Skill: Trigger the "AWS Guard-Duty detector deletion" alert

## When this skill applies

The operator wants the **native Cortex Analytics detector for a deleted GuardDuty detector** to fire, for example: *"trigger an AWS GuardDuty deletion alert"*, *"show defense evasion in AWS"*, *"prove a cloud analytics alert fires from CloudTrail"*. It is not a correlation rule: it is Cortex's own Cloud analytics over the AWS audit feed, so the events must reach the tenant through the Cribl integration under the AWS audit source's dedicated identifier (what `http-sender` does for the `aws_cloudtrail` profile), not the generic HTTP collector or syslog.


## What the detector looks for (Cortex doc: "AWS Guard-Duty detector deletion")

| Property | Value |
|---|---|
| Alert name | `AWS Guard-Duty detector deletion` (Low)  |
| Source | a behavioural Cloud analytics detector (XDR Analytics), defense evasion |
| MITRE technique as shown on the alert | `T1685 - Disable or Modify Tools` |
| Alert tags | `DS:Amazon/AWS` (data source), `DOM:Security` |
| Required data | AWS Audit Log (CloudTrail): the `cribl_aws_audit` source on the tenant, dataset `amazon_aws_raw` |
| Activation / training (doc) | 14 days / 30 days in the documentation; in practice the alert typically arrives seconds to a minute after the events |
| Test period | single event |
| Deduplication (doc) | 1 day |
| What the alert text says | *"The cloud identity arn:aws:sts::<account>:assumed-role/DevOpsEngineer-<hex>/<session> has deleted a Guard-Duty detector. The executed API call is DeleteDetector. The operation was performed on AWS/<account>"* |

The goal the doc gives is evasion: deleting the detector stops GuardDuty findings. The recipe is one CloudTrail `DeleteDetector` call (`eventSource guardduty.amazonaws.com`) by an **assumed role** (`DevOpsEngineer-<hex>`) with a session name, from a Saudi home-pool address.

## Preconditions: check these BEFORE sending

| # | Must be true | How to check |
|---|---|---|
| 1 | The `http-sender` instance is running with the Cribl settings: the `criblUrl` config and the `criblToken` secret. The call below has **no `destination` argument**: the `aws_cloudtrail` profile goes to **`cribl_aws_audit`** (the tenant's Cribl integration under the AWS audit source's dedicated UUID, dataset `amazon_aws_raw`) and refuses to send when Cribl is not configured. It never falls back to an HTTP collector | `http-sender.list_destinations` shows `cribl_aws_audit` with `mode: cribl` and `ready: true` |
| 2 | Nothing else to choose: every call invents a fresh AWS account id, a fresh IAM principal and session and fresh resource ids, so the actor is always a first-time actor and **you never hand-build events** | the call result lists `sample_ids` (the CloudTrail `eventID`s) and the first and last `eventTime` |
| 3 | Do **not** pass `destination`, `target_user`, `source_ip` or `spread_seconds`: the recipe below is the verified one | n/a |

## Expected result

The call in Step 1, unchanged, fires the alert for a new assumed-role session in a new account; the alert typically arrives within seconds to about two minutes of the event. The Step 3 query also returns earlier alerts of the hour: credit an alert to your call by the principal in its `user_name` and description, never by time alone.

## Step 1: send the events (exactly this call)

Call **`http-sender.generate_events`** once with this argument object. Nothing needs replacing.

```json
{"profile": "aws_cloudtrail", "scenario": "guardduty_detector_deleted", "count": 1}
```

One CloudTrail record, `DeleteDetector` on a random 32-hex `detectorId`, stamped now, by a fresh assumed role in a fresh 12-digit account. The result carries `ok`, `destination: cribl_aws_audit`, `dataset: amazon_aws_raw`, `num_records: 1`, `batch_status: [200]` and the `sample_ids` of the events.

## Step 2: confirm the events landed (a few seconds to a minute after Step 1)

```text
config timeframe = 1h | dataset = amazon_aws_raw
| filter _collector_name = "phantom-http-sender" and eventName = "DeleteDetector"
| alter who = json_extract_scalar(userIdentity, "$.arn")
| fields _time, eventName, who, sourceIPAddress, recipientAccountId, eventID
| sort desc _time
| limit 10
```

Pass when **1 row** returns for your call, with `eventName` `DeleteDetector`, `who` an `arn:aws:sts::<account>:assumed-role/DevOpsEngineer-<hex>/<session>` and an `eventID` equal to the `sample_ids` value of the Step 1 result. The query covers the last hour, so earlier calls show too, and the rows are **not** guaranteed newest first: match on the Step 1 `sample_ids`. Expect the row for your assumed-role session with a Saudi home-pool `sourceIPAddress` and an `eventID` equal to the result's `sample_ids` value; earlier calls of the hour also appear.

## Step 3: wait, then check for the alert

Check **30 seconds** after the call, then every 30 seconds for up to **10 minutes** (the alert typically arrives within seconds to about two minutes of the event).

```text
config timeframe = 1h | dataset = alerts
| filter alert_source in ("MAGNIFIER","ANALYTICS_BIOC") and alert_name = "AWS Guard-Duty detector deletion"
| fields alert_id, alert_name, severity, user_name, mitre_attack_technique, alert_arrival_timestamp, description
| sort desc alert_arrival_timestamp
| limit 10
```

Pass when a **new** row appears whose `user_name` is the `who` of Step 2 (the principal ARN) and whose description says *"has deleted a Guard-Duty detector"*. Severity `LOW`, technique `T1685 - Disable or Modify Tools`, `original_tags` contains `DS:Amazon/AWS`. Ignore rows for other principals: other callers may raise the same alert name at the same time.

If nothing arrives in 10 minutes: re-run Step 2 (the events must be in `amazon_aws_raw`), confirm `list_destinations` still shows `cribl_aws_audit` ready, then call Step 1 **once more** (a new call is a new first-time actor). Do not edit the events.

## Notes and limits

- **The identity is the key.** The alert text names the assumed-role ARN and the account id, which the call invents; match on that, not on the time.
- **No Tor, no foreign address needed.** The actor works from an ordinary Saudi home-pool address.
- **Alert source filter.** Cortex stores Analytics alerts as `MAGNIFIER` and `ANALYTICS_BIOC`; the displayed names `XDR_ANALYTICS` and `XDR_ANALYTICS_BIOC` match nothing in XQL.
- **Calling it again.** Re-running is **not** blocked by deduplication: the call is invented fresh each time, and a second call sent minutes after the first raises its own new alert for its new identity. The rows of the earlier calls stay in the 1-hour query results, so match on the Step 1 `sample_ids` and the principal.
- **`count`.** The minimum is 1 (one full recipe, as above); a larger `count` repeats the recipe with fresh resource ids for the same actor. A smaller one is refused (profile code). The recipe is verified at the default `count` only.
- **Modeling.** When the AWS CloudTrail modeling pack is not installed on the tenant, `xdm.*` stays empty for this source; Step 2 therefore checks the raw dataset.

## Report back to the operator

State the principal ARN and account id, the number of events sent, the Step 2 result and either the alert id with its name, severity (Low) and arrival latency or that nothing arrived in 10 minutes and what you checked. Say that the identity is invented per call, so a repeat call raises a new alert.
