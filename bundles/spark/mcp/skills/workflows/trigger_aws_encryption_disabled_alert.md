---
name: trigger_aws_encryption_disabled_alert
displayName: Trigger the Cortex "Disable encryption operations" analytics alert
category: workflows
description: 'Fire Cortex XSIAM''s native "Disable encryption operations" analytics alert (Low, T1565 Data Manipulation) by sending one synthetic AWS CloudTrail DisableEbsEncryptionByDefault record from a fresh assumed role through the http-sender connector''s Cribl mode (generate_events, profile aws_cloudtrail, scenario ebs_encryption_disabled, destination cribl_aws_audit, dataset amazon_aws_raw). Use when the operator asks to trigger, demo, prove or reproduce disabled EBS encryption, encryption turned off on EC2 storage, or a cloud data-protection tampering alert. One call, no arguments to fill in.'
icon: no_encryption
source: platform
loadingMode: on-demand
locked: false
---

# Skill: Trigger the "Disable encryption operations" alert

## When this skill applies

The operator wants the **native Cortex Analytics disable-encryption detector** to fire, for example: *"trigger a disable encryption alert"*, *"show EBS default encryption being turned off"*, *"prove cloud data-protection tampering fires from CloudTrail"*. It is Cortex's own Cloud analytics over the AWS audit feed, not a correlation rule, so the events must go through the Cribl integration under the AWS audit source's dedicated identifier (what `http-sender` does for the `aws_cloudtrail` profile).


## What the detector looks for (Cortex doc: "Disable encryption operations")

| Property | Value |
|---|---|
| Alert name | `Disable encryption operations` (Low)  |
| Source | a Cloud analytics detector (XDR Analytics), Data Detection & Response |
| MITRE technique as shown on the alert | `T1565 - Data Manipulation` |
| Alert tags | `DS:Amazon/AWS` (data source), `DOM:Security`, `DT:Data Detection & Response`, `DT:Cloud Data Asset Protection Tampering` |
| Required data | AWS Audit Log (CloudTrail): the `cribl_aws_audit` source on the tenant, dataset `amazon_aws_raw` |
| Activation / training (doc) | 14 days / 30 days in the documentation; in practice the alert typically arrives seconds to a minute after the events |
| Test period | single event |
| Deduplication (doc) | 1 day |
| What the alert text says | *"The cloud identity arn:aws:sts::<account>:assumed-role/DevOpsEngineer-<hex>/<session> has executed an API call. The executed API call is DisableEbsEncryptionByDefault. The operation was performed on AWS/<account>"* |

The doc describes encryption disabled on the servers that host EC2 instances. The recipe is one CloudTrail `DisableEbsEncryptionByDefault` call (`eventSource ec2.amazonaws.com`, response `ebsEncryptionByDefault: false`) by an **assumed role** (`DevOpsEngineer-<hex>`).

## Preconditions: check these BEFORE sending

| # | Must be true | How to check |
|---|---|---|
| 1 | The `http-sender` instance is running with the Cribl settings: the `criblUrl` config and the `criblToken` secret. The call below has **no `destination` argument**: the `aws_cloudtrail` profile goes to **`cribl_aws_audit`** (the tenant's Cribl integration under the AWS audit source's dedicated UUID, dataset `amazon_aws_raw`) and refuses to send when Cribl is not configured. It never falls back to an HTTP collector | `http-sender.list_destinations` shows `cribl_aws_audit` with `mode: cribl` and `ready: true` |
| 2 | Nothing else to choose: every call invents a fresh AWS account id, a fresh IAM principal and session and fresh resource ids, so the actor is always a first-time actor and **you never hand-build events** | the call result lists `sample_ids` (the CloudTrail `eventID`s) and the first and last `eventTime` |
| 3 | Do **not** pass `destination`, `target_user`, `source_ip` or `spread_seconds`: the recipe below is the verified one | n/a |

## Expected result

The call in Step 1, unchanged, fires the alert for a new assumed-role session in a new account; the alert typically arrives within seconds of the event. The Step 3 query also returns earlier alerts of the hour: credit an alert to your call by the principal in its `user_name` and description, never by time alone.

## Step 1: send the events (exactly this call)

Call **`http-sender.generate_events`** once with this argument object. Nothing needs replacing.

```json
{"profile": "aws_cloudtrail", "scenario": "ebs_encryption_disabled", "count": 1}
```

One CloudTrail record stamped now by a fresh assumed role in a fresh account. The result shows `num_records: 1`, `batch_status: [200]` and one `sample_id`.

## Step 2: confirm the events landed (a few seconds to a minute after Step 1)

```text
config timeframe = 1h | dataset = amazon_aws_raw
| filter _collector_name = "phantom-http-sender" and eventName = "DisableEbsEncryptionByDefault"
| alter who = json_extract_scalar(userIdentity, "$.arn")
| fields _time, eventName, who, sourceIPAddress, recipientAccountId, eventID
| sort desc _time
| limit 10
```

Pass when **1 row** returns for your call, `eventName` `DisableEbsEncryptionByDefault`, `who` an `arn:aws:sts::<account>:assumed-role/DevOpsEngineer-<hex>/<session>`, and an `eventID` equal to the Step 1 `sample_ids` value. The query covers the last hour, so earlier calls show too, and the rows are **not** guaranteed newest first: match on the Step 1 `sample_ids`. Expect the row for your assumed-role session from a Saudi home-pool address, with an `eventID` equal to `sample_ids`.

## Step 3: wait, then check for the alert

Check **15 seconds** after the call, then every 15 seconds for up to **10 minutes** (the alert typically arrives within seconds of the event).

```text
config timeframe = 1h | dataset = alerts
| filter alert_source in ("MAGNIFIER","ANALYTICS_BIOC") and alert_name = "Disable encryption operations"
| fields alert_id, alert_name, severity, user_name, mitre_attack_technique, alert_arrival_timestamp, description
| sort desc alert_arrival_timestamp
| limit 10
```

Pass when a **new** row appears whose `user_name` is the `who` of Step 2 and whose description says *"The executed API call is DisableEbsEncryptionByDefault"*. Severity `LOW`, technique `T1565 - Data Manipulation`, tags include `DS:Amazon/AWS` and `DT:Cloud Data Asset Protection Tampering`.

If nothing arrives in 10 minutes: re-run Step 2 (the events must be in `amazon_aws_raw`), confirm `list_destinations` still shows `cribl_aws_audit` ready, then call Step 1 **once more** (a new call is a new first-time actor). Do not edit the events.

## Notes and limits

- **The alert text is generic** ("has executed an API call"): identify it by the principal and the API name, not by wording.
- **Other encryption-disable calls were not tried.** The recipe covers the EBS default-encryption call only.
- **Alert source filter.** Cortex stores Analytics alerts as `MAGNIFIER` and `ANALYTICS_BIOC`; the displayed names `XDR_ANALYTICS` and `XDR_ANALYTICS_BIOC` match nothing in XQL.
- **Calling it again.** Re-running is **not** blocked by deduplication: the call is invented fresh each time, and a second call sent minutes after the first raises its own new alert for its new identity. The rows of the earlier calls stay in the 1-hour query results, so match on the Step 1 `sample_ids` and the principal.
- **`count`.** The minimum is 1 (one full recipe, as above); a larger `count` repeats the recipe with fresh resource ids for the same actor. A smaller one is refused (profile code). The recipe is verified at the default `count` only.
- **Modeling.** When the AWS CloudTrail modeling pack is not installed on the tenant, `xdm.*` stays empty for this source; Step 2 therefore checks the raw dataset.

## Report back to the operator

State the role ARN, the account id, the Step 2 result and either the alert id with name, severity (Low) and latency or that nothing arrived in 10 minutes and what you checked.
