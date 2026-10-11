---
name: trigger_aws_route53_logging_deleted_alert
displayName: Trigger the Cortex "Successful AWS Route53 DNS Resolver query logging configuration deletion by a non-admin identity" analytics alert
category: workflows
description: 'Fire Cortex XSIAM''s native "Successful AWS Route53 DNS Resolver query logging configuration deletion by a non-admin identity" analytics alert (the AWS Route53 DNS Resolver query logging deletion detector, Medium, T1685.002 Disable or Modify Cloud Log) by sending one synthetic AWS CloudTrail DeleteResolverQueryLogConfig record from a fresh ci-deploy-runner assumed role through the http-sender connector''s Cribl mode (generate_events, profile aws_cloudtrail, scenario route53_logging_deleted, destination cribl_aws_audit, dataset amazon_aws_raw). Use when the operator asks to trigger, demo, prove or reproduce a deleted DNS query log, Route 53 Resolver logging turned off, or DNS log tampering by a non-admin identity. One call, no arguments to fill in.'
icon: dns
source: platform
loadingMode: on-demand
locked: false
---

# Skill: Trigger the "Successful AWS Route53 DNS Resolver query logging configuration deletion by a non-admin identity" alert

## When this skill applies

The operator wants the **native Cortex Analytics Route 53 query-logging deletion detector** to fire, for example: *"trigger a Route53 logging deleted alert"*, *"show DNS logging being turned off in AWS"*, *"prove cloud log tampering fires for a non-admin"*. It is Cortex's own Cloud analytics over the AWS audit feed, not a correlation rule, so the events must go through the Cribl integration under the AWS audit source's dedicated identifier (what `http-sender` does for the `aws_cloudtrail` profile).


## What the detector looks for (Cortex doc: "AWS Route53 DNS Resolver query logging configuration deletion")

| Property | Value |
|---|---|
| Alert name | `Successful AWS Route53 DNS Resolver query logging configuration deletion by a non-admin identity` (Medium)  |
| Source | a Cloud analytics detector (XDR Analytics), the non-admin variation of `AWS Route53 DNS Resolver query logging configuration deletion` (Low) |
| MITRE technique as shown on the alert | `T1685.002 - Disable or Modify Tools: Disable or Modify Cloud Log` |
| Alert tags | `DS:Amazon/AWS` (data source), `DOM:Security`, `DT:Cloud Log Tampering Analytics` |
| Required data | AWS Audit Log (CloudTrail): the `cribl_aws_audit` source on the tenant, dataset `amazon_aws_raw` |
| Activation / training (doc) | 14 days / 30 days; in practice the alert typically arrives within a minute or two of its events |
| Test period | single event |
| Deduplication (doc) | 1 day |
| What the alert text says | *"The cloud identity arn:aws:sts::<account>:assumed-role/ci-deploy-runner-<hex>/<session> deleted Route53 DNS Resolver query logging configuration. The executed API call is DeleteResolverQueryLogConfig. The operation was performed on AWS/<account>. This identity does not usually perform this operation and is not classified as DevOps or admin"* |

The recipe is one CloudTrail `DeleteResolverQueryLogConfig` call (`eventSource route53resolver.amazonaws.com`) with a realistic response (`status DELETING`, a query-log config named `vpc-dns-query-logs` writing to an S3 bucket), by an **assumed role named `ci-deploy-runner-<hex>`**. That role name is what makes the actor a **non-admin**: the alert text says the identity "is not classified as DevOps or admin". Whether a `DevOpsEngineer-...` role (the actor of the GuardDuty scenario) would raise the base Low alert instead is not covered by this recipe.

## Preconditions: check these BEFORE sending

| # | Must be true | How to check |
|---|---|---|
| 1 | The `http-sender` instance is running with the Cribl settings: the `criblUrl` config and the `criblToken` secret. The call below has **no `destination` argument**: the `aws_cloudtrail` profile goes to **`cribl_aws_audit`** (the tenant's Cribl integration under the AWS audit source's dedicated UUID, dataset `amazon_aws_raw`) and refuses to send when Cribl is not configured. It never falls back to an HTTP collector | `http-sender.list_destinations` shows `cribl_aws_audit` with `mode: cribl` and `ready: true` |
| 2 | Nothing else to choose: every call invents a fresh AWS account id, a fresh IAM principal and session and fresh resource ids, so the actor is always a first-time actor and **you never hand-build events** | the call result lists `sample_ids` (the CloudTrail `eventID`s) and the first and last `eventTime` |
| 3 | Do **not** pass `destination`, `target_user`, `source_ip` or `spread_seconds`: the recipe below is the supported one | n/a |

## Expected result

The recipe fires from a fresh assumed role named `ci-deploy-runner-<hex>`; the alert typically arrives within a minute or two of the call. The alert is credited to a call by the principal in its `user_name` and description, never by time alone: the Step 3 query below also returns earlier alerts of the hour, so match the principal.

## Step 1: send the events (exactly this call)

Call **`http-sender.generate_events`** once with this argument object. Nothing needs replacing.

```json
{"profile": "aws_cloudtrail", "scenario": "route53_logging_deleted", "count": 1}
```

One CloudTrail record stamped now by a fresh `ci-deploy-runner-<hex>` assumed role in a fresh account. The result shows `num_records: 1`, `batch_status: [200]` and one `sample_id`.

## Step 2: confirm the events landed (a few seconds to a minute after Step 1)

```text
config timeframe = 1h | dataset = amazon_aws_raw
| filter _collector_name = "phantom-http-sender" and eventName = "DeleteResolverQueryLogConfig"
| alter who = json_extract_scalar(userIdentity, "$.arn")
| fields _time, eventName, who, sourceIPAddress, recipientAccountId, eventID
| sort desc _time
| limit 10
```

Pass when **1 row** returns for your call, `eventName` `DeleteResolverQueryLogConfig`, `who` an `arn:aws:sts::<account>:assumed-role/ci-deploy-runner-<hex>/<session>`, and an `eventID` equal to the Step 1 `sample_ids` value. The query covers the last hour, so earlier calls show too, and the rows are **not** guaranteed newest first: match on the Step 1 `sample_ids`. Expect the row for your principal, with an `eventID` equal to `sample_ids`.

## Step 3: wait, then check for the alert

Check **15 seconds** after the call, then every 15 seconds for up to **10 minutes** (it typically arrives within a minute or two).

```text
config timeframe = 1h | dataset = alerts
| filter alert_source in ("MAGNIFIER","ANALYTICS_BIOC") and alert_name = "Successful AWS Route53 DNS Resolver query logging configuration deletion by a non-admin identity"
| fields alert_id, alert_name, severity, user_name, mitre_attack_technique, alert_arrival_timestamp, description
| sort desc alert_arrival_timestamp
| limit 10
```

Pass when a **new** row appears whose `user_name` is the `who` of Step 2 and whose description ends *"is not classified as DevOps or admin"*. Severity `MEDIUM`, technique `T1685.002 - Disable or Modify Tools: Disable or Modify Cloud Log`, tags include `DS:Amazon/AWS` and `DT:Cloud Log Tampering Analytics`.

If nothing arrives in 10 minutes: re-run Step 2 (the events must be in `amazon_aws_raw`), confirm `list_destinations` still shows `cribl_aws_audit` ready, then call Step 1 **once more** (a new call is a new first-time actor). Do not edit the events.

## Notes and limits

- **The role name carries the meaning.** Do not pass `target_user`: the scenario names the role itself (`ci-deploy-runner-<hex>`) and only the session name is the argument.
- **The base detector (Low) is not what appears:** the alert you see is the Medium non-admin variation.
- **Alert source filter.** Cortex stores Analytics alerts as `MAGNIFIER` and `ANALYTICS_BIOC`; the displayed names `XDR_ANALYTICS` and `XDR_ANALYTICS_BIOC` match nothing in XQL.
- **Calling it again.** Re-running is **not** blocked by deduplication: the call is invented fresh each time, and a second call sent minutes after the first raises its own new alert for its new identity. The rows of the earlier calls stay in the 1-hour query results, so match on the Step 1 `sample_ids` and the principal.
- **`count`.** The minimum is 1 (one full recipe, as above); a larger `count` repeats the recipe with fresh resource ids for the same actor. A smaller one is refused (profile code). A larger `count` is not covered by this recipe.
- **Modeling.** Without the AWS CloudTrail modeling pack installed, `xdm.*` stays empty for this source; Step 2 therefore checks the raw dataset.

## Report back to the operator

State the role ARN, the account id, the Step 2 result and either the alert id with name, severity (Medium) and latency or that nothing arrived in 10 minutes and what you checked.
