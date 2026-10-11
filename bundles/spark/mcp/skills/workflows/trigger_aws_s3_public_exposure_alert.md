---
name: trigger_aws_s3_public_exposure_alert
displayName: Trigger the Cortex "AWS S3 bucket was exposed to public access" analytics alert
category: workflows
description: 'Fire Cortex XSIAM''s native "AWS S3 bucket was exposed to public access" analytics alert (Low, T1685 Disable or Modify Tools) by sending three synthetic AWS CloudTrail records for one new IAM user through the http-sender connector''s Cribl mode (generate_events, profile aws_cloudtrail, scenario s3_public_exposure, destination cribl_aws_audit, dataset amazon_aws_raw): PutBucketPolicy with Principal *, PutBucketAcl granting the AllUsers group, then DeletePublicAccessBlock. Use when the operator asks to trigger, demo, prove or reproduce a public S3 bucket, an exposed bucket, an open bucket policy or public access on cloud storage. One call, no arguments to fill in.'
icon: cloud
source: platform
loadingMode: on-demand
locked: false
---

# Skill: Trigger the "AWS S3 bucket was exposed to public access" alert

## When this skill applies

The operator wants the **native Cortex Analytics S3 public-exposure detector** to fire, for example: *"trigger a public S3 bucket alert"*, *"show a bucket being made public"*, *"prove a cloud data-exposure alert fires from CloudTrail"*. It is Cortex's own Cloud analytics over the AWS audit feed, not a correlation rule, so the events must go through the Cribl integration under the AWS audit source's dedicated identifier (what `http-sender` does for the `aws_cloudtrail` profile).


## What the detector looks for (Cortex doc: "AWS S3 bucket was exposed to public access")

| Property | Value |
|---|---|
| Alert name | `AWS S3 bucket was exposed to public access` (Low)  |
| Source | a Cloud analytics detector (XDR Analytics), Cloud Data Asset Public Exposure |
| MITRE technique as shown on the alert | `T1685 - Disable or Modify Tools` |
| Alert tags | `DS:Amazon/AWS` (data source), `DOM:Security`, `DT:Cloud Data Asset Exfiltration`, `DT:Data Detection & Response`, `DT:Cloud Data Asset Public Exposure` |
| Required data | AWS Audit Log (CloudTrail): the `cribl_aws_audit` source on the tenant, dataset `amazon_aws_raw` |
| Activation / training (doc) | 14 days / 30 days; in practice the alert typically arrives within a minute or two of its events |
| Test period | single event |
| Deduplication (doc) | 1 day. The catalog lists two variations: *by admin cloud identity* (Informational, invisible in the issue view) and *containing sensitive information* (High). The recipe uses an ordinary IAM user, so the Low alert is the one that appears |
| What the alert text says | *"The S3 bucket acme-reports-<hex> was publicly shared. The action performed by <user>. The resource is exposed to any identity outside the organization"* |

The recipe is three CloudTrail records by one **IAM user** on one new bucket (`acme-reports-<hex>`), about 60 seconds apart: `PutBucketPolicy` with `Principal: *` and `s3:GetObject`, `PutBucketAcl` granting the `AllUsers` group READ, and `DeletePublicAccessBlock`. Which of the three the detector needs is **not isolated**; send all three.

## Preconditions: check these BEFORE sending

| # | Must be true | How to check |
|---|---|---|
| 1 | The `http-sender` instance is running with the Cribl settings: the `criblUrl` config and the `criblToken` secret. The call below has **no `destination` argument**: the `aws_cloudtrail` profile goes to **`cribl_aws_audit`** (the tenant's Cribl integration under the AWS audit source's dedicated UUID, dataset `amazon_aws_raw`) and refuses to send when Cribl is not configured. It never falls back to an HTTP collector | `http-sender.list_destinations` shows `cribl_aws_audit` with `mode: cribl` and `ready: true` |
| 2 | Nothing else to choose: every call invents a fresh AWS account id, a fresh IAM principal and session and fresh resource ids, so the actor is always a first-time actor and **you never hand-build events** | the call result lists `sample_ids` (the CloudTrail `eventID`s) and the first and last `eventTime` |
| 3 | Do **not** pass `destination`, `target_user`, `source_ip` or `spread_seconds`: the recipe below is the supported one | n/a |

## Expected result

The recipe fires from a plain IAM user on a fresh bucket; the alert typically arrives within a minute or two of the call. The alert is credited to a call by the principal in its `user_name` and description (and the bucket name), never by time alone: the Step 3 query below also returns earlier alerts of the hour, so match the principal.

## Step 1: send the events (exactly this call)

Call **`http-sender.generate_events`** once with this argument object. Nothing needs replacing.

```json
{"profile": "aws_cloudtrail", "scenario": "s3_public_exposure", "count": 3}
```

Three CloudTrail records for one new IAM user and one new bucket, spread over the default 2-minute window that ends now (the first about two minutes earlier, the last at now). The result shows `num_records: 3`, `batch_status: [200]` and three `sample_ids`.

## Step 2: confirm the events landed (a few seconds to a minute after Step 1)

```text
config timeframe = 1h | dataset = amazon_aws_raw
| filter _collector_name = "phantom-http-sender" and eventName in ("PutBucketPolicy", "PutBucketAcl", "DeletePublicAccessBlock")
| alter who = json_extract_scalar(userIdentity, "$.arn")
| fields _time, eventName, who, sourceIPAddress, recipientAccountId, eventID
| sort desc _time
| limit 10
```

Pass when **3 rows** return for your call with the same `who` (an `arn:aws:iam::<account>:user/<name>`) and the same `sourceIPAddress`: `PutBucketPolicy`, `PutBucketAcl`, `DeletePublicAccessBlock`, with `eventID`s equal to the Step 1 `sample_ids`. The query covers the last hour, so earlier calls show too, and the rows are **not** guaranteed newest first: match on the Step 1 `sample_ids`. Expect 3 rows for your IAM user from one `sourceIPAddress`, with the three event names and `eventID`s equal to the result's `sample_ids`.

## Step 3: wait, then check for the alert

Check **15 seconds** after the call, then every 15 seconds for up to **10 minutes** (it typically arrives within a minute or two).

```text
config timeframe = 1h | dataset = alerts
| filter alert_source in ("MAGNIFIER","ANALYTICS_BIOC") and alert_name = "AWS S3 bucket was exposed to public access"
| fields alert_id, alert_name, severity, user_name, mitre_attack_technique, alert_arrival_timestamp, description
| sort desc alert_arrival_timestamp
| limit 10
```

Pass when a **new** row appears whose description names the bucket `acme-reports-<hex>` and whose `user_name` is the IAM user name of Step 2 (a bare user name, not an ARN). Severity `LOW`, technique `T1685 - Disable or Modify Tools`, tags include `DS:Amazon/AWS`, `DT:Cloud Data Asset Public Exposure`. The alert's `event_timestamp` is the first event (the policy), not the last.

If nothing arrives in 10 minutes: re-run Step 2 (the events must be in `amazon_aws_raw`), confirm `list_destinations` still shows `cribl_aws_audit` ready, then call Step 1 **once more** (a new call is a new first-time actor). Do not edit the events.

## Notes and limits

- **One alert for the three events.** The recipe raised one alert, not three.
- **Actor type matters.** The catalog's *by admin cloud identity* variation is Informational and not shown as an issue; the recipe's actor is a plain IAM user, which is the one that raises the Low alert. Do not pass `target_user` with an admin-looking name.
- **Alert source filter.** Cortex stores Analytics alerts as `MAGNIFIER` and `ANALYTICS_BIOC`; the displayed names `XDR_ANALYTICS` and `XDR_ANALYTICS_BIOC` match nothing in XQL.
- **Calling it again.** Re-running is **not** blocked by deduplication: the call is invented fresh each time, and a second call sent minutes after the first raises its own new alert for its new identity. The rows of the earlier calls stay in the 1-hour query results, so match on the Step 1 `sample_ids` and the principal.
- **`count`.** The minimum is 3 (one full recipe, as above); a larger `count` repeats the recipe with fresh resource ids for the same actor. A smaller one is refused (profile code). A larger `count` is not covered by this recipe.
- **Modeling.** Without the AWS CloudTrail modeling pack installed, `xdm.*` stays empty for this source; Step 2 therefore checks the raw dataset.

## Report back to the operator

State the IAM user, the bucket name, the account id, the Step 2 result (3 rows) and either the alert id with name, severity (Low) and latency or that nothing arrived in 10 minutes and what you checked.
