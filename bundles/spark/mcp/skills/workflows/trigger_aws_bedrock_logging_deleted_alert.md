---
name: trigger_aws_bedrock_logging_deleted_alert
displayName: Trigger the Cortex "AWS Bedrock model invocation logging was successfully deleted" analytics alert
category: workflows
description: 'Fire Cortex XSIAM''s native "AWS Bedrock model invocation logging was successfully deleted" analytics alert (the AWS Bedrock model invocation logging deletion detector, Low, T1685.002 Disable or Modify Cloud Log) by sending one synthetic AWS CloudTrail DeleteModelInvocationLoggingConfiguration record from a new IAM user through the http-sender connector''s Cribl mode (generate_events, profile aws_cloudtrail, scenario bedrock_logging_deleted, destination cribl_aws_audit, dataset amazon_aws_raw). Use when the operator asks to trigger, demo, prove or reproduce a deleted Bedrock log, AI model logging turned off, or cloud log tampering around generative AI services. One call, no arguments to fill in.'
icon: psychology
source: platform
loadingMode: on-demand
locked: false
---

# Skill: Trigger the "AWS Bedrock model invocation logging was successfully deleted" alert

## When this skill applies

The operator wants the **native Cortex Analytics Bedrock logging-deletion detector** to fire, for example: *"trigger a Bedrock logging deleted alert"*, *"show someone turning off AI model logging in AWS"*, *"prove cloud AI infrastructure analytics fire"*. It is Cortex's own Cloud analytics over the AWS audit feed, not a correlation rule, so the events must go through the Cribl integration under the AWS audit source's dedicated identifier (what `http-sender` does for the `aws_cloudtrail` profile).


## What the detector looks for (Cortex doc: "AWS Bedrock model invocation logging deletion")

| Property | Value |
|---|---|
| Alert name | `AWS Bedrock model invocation logging was successfully deleted` (Low)  |
| Source | a Cloud analytics detector (XDR Analytics), variation of `AWS Bedrock model invocation logging deletion` |
| MITRE technique as shown on the alert | `T1685.002 - Disable or Modify Tools: Disable or Modify Cloud Log` |
| Alert tags | `DS:Amazon/AWS` (data source), `DOM:Security`, `DT:Cloud AI Infrastructure Analytics` |
| Required data | AWS Audit Log (CloudTrail): the `cribl_aws_audit` source on the tenant, dataset `amazon_aws_raw` |
| Activation / training (doc) | 14 days / 30 days in the documentation; in practice the alert typically arrives seconds to a minute after the events |
| Test period | single event |
| Deduplication (doc) | 5 days. The catalog lists a second variation, *by an identity with administrative activity* (Informational, invisible in the issue view); the recipe's actor is a fresh IAM user with no history, so the Low alert is the one that appears |
| What the alert text says | *"The cloud identity <name>.<hex> deleted the model invocation logging. The operation status was SUCCESS. The operation was performed from <source address> on AWS/<account>"* |

The recipe is one CloudTrail `DeleteModelInvocationLoggingConfiguration` call (`eventSource bedrock.amazonaws.com`, no request parameters) by an **IAM user**, from a Saudi home-pool address.

## Preconditions: check these BEFORE sending

| # | Must be true | How to check |
|---|---|---|
| 1 | The `http-sender` instance is running with the Cribl settings: the `criblUrl` config and the `criblToken` secret. The call below has **no `destination` argument**: the `aws_cloudtrail` profile goes to **`cribl_aws_audit`** (the tenant's Cribl integration under the AWS audit source's dedicated UUID, dataset `amazon_aws_raw`) and refuses to send when Cribl is not configured. It never falls back to an HTTP collector | `http-sender.list_destinations` shows `cribl_aws_audit` with `mode: cribl` and `ready: true` |
| 2 | Nothing else to choose: every call invents a fresh AWS account id, a fresh IAM principal and session and fresh resource ids, so the actor is always a first-time actor and **you never hand-build events** | the call result lists `sample_ids` (the CloudTrail `eventID`s) and the first and last `eventTime` |
| 3 | Do **not** pass `destination`, `target_user`, `source_ip` or `spread_seconds`: the recipe below is the verified one | n/a |

## Expected result

The call in Step 1, unchanged, fires the alert for a new IAM user in a new account; the alert typically arrives within seconds of the event. The Step 3 query also returns earlier alerts of the hour: credit an alert to your call by the principal in its `user_name` and description, never by time alone.

## Step 1: send the events (exactly this call)

Call **`http-sender.generate_events`** once with this argument object. Nothing needs replacing.

```json
{"profile": "aws_cloudtrail", "scenario": "bedrock_logging_deleted", "count": 1}
```

One CloudTrail record stamped now by a new IAM user (`<first>.<last>.<hex>`) in a new 12-digit account. The result shows `num_records: 1`, `batch_status: [200]` and one `sample_id`.

## Step 2: confirm the events landed (a few seconds to a minute after Step 1)

```text
config timeframe = 1h | dataset = amazon_aws_raw
| filter _collector_name = "phantom-http-sender" and eventName = "DeleteModelInvocationLoggingConfiguration"
| alter who = json_extract_scalar(userIdentity, "$.arn")
| fields _time, eventName, who, sourceIPAddress, recipientAccountId, eventID
| sort desc _time
| limit 10
```

Pass when **1 row** returns for your call, `eventName` `DeleteModelInvocationLoggingConfiguration`, `who` an `arn:aws:iam::<account>:user/<name>`, and an `eventID` equal to the Step 1 `sample_ids` value. The query covers the last hour, so earlier calls show too, and the rows are **not** guaranteed newest first: match on the Step 1 `sample_ids`. Expect the row for your principal from a Saudi home-pool address, with an `eventID` equal to `sample_ids`.

## Step 3: wait, then check for the alert

Check **15 seconds** after the call, then every 15 seconds for up to **10 minutes** (the alert typically arrives within seconds of the event).

```text
config timeframe = 1h | dataset = alerts
| filter alert_source in ("MAGNIFIER","ANALYTICS_BIOC") and alert_name = "AWS Bedrock model invocation logging was successfully deleted"
| fields alert_id, alert_name, severity, user_name, mitre_attack_technique, alert_arrival_timestamp, description
| sort desc alert_arrival_timestamp
| limit 10
```

Pass when a **new** row appears whose `user_name` is the IAM user **name** of Step 2 (a bare name, not an ARN) and whose description says *"deleted the model invocation logging"*. Severity `LOW`, technique `T1685.002 - Disable or Modify Tools: Disable or Modify Cloud Log`, tags include `DS:Amazon/AWS` and `DT:Cloud AI Infrastructure Analytics`.

If nothing arrives in 10 minutes: re-run Step 2 (the events must be in `amazon_aws_raw`), confirm `list_destinations` still shows `cribl_aws_audit` ready, then call Step 1 **once more** (a new call is a new first-time actor). Do not edit the events.

## Notes and limits

- **Deduplication is 5 days** (doc), longer than the other AWS detectors; each call invents a new IAM user, and the repeat-call result is in the note below.
- **An ordinary home-pool address was enough:** the alert's `host_ip` is the event's source address (a Saudi home-pool address).
- **Alert source filter.** Cortex stores Analytics alerts as `MAGNIFIER` and `ANALYTICS_BIOC`; the displayed names `XDR_ANALYTICS` and `XDR_ANALYTICS_BIOC` match nothing in XQL.
- **Calling it again.** Re-running is **not** blocked by deduplication: the call is invented fresh each time, and a second call sent minutes after the first raises its own new alert for its new identity. The rows of the earlier calls stay in the 1-hour query results, so match on the Step 1 `sample_ids` and the principal.
- **`count`.** The minimum is 1 (one full recipe, as above); a larger `count` repeats the recipe with fresh resource ids for the same actor. A smaller one is refused (profile code). The recipe is verified at the default `count` only.
- **Modeling.** When the AWS CloudTrail modeling pack is not installed on the tenant, `xdm.*` stays empty for this source; Step 2 therefore checks the raw dataset.

## Report back to the operator

State the IAM user name, the account id, the source address, the Step 2 result and either the alert id with name, severity (Low) and latency or that nothing arrived in 10 minutes and what you checked.
