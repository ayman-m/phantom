---
name: trigger_aws_security_group_open_alert
displayName: Trigger the Cortex "AWS Security Group remote access allowed from an unknown external IP address" analytics alert
category: workflows
description: 'Fire Cortex XSIAM''s native "AWS Security Group remote access allowed from an unknown external IP address" analytics alert (Low, T1686.001 Disable or Modify System Firewall: Cloud Firewall) by sending two synthetic AWS CloudTrail AuthorizeSecurityGroupIngress records from a fresh assumed role through the http-sender connector''s Cribl mode (generate_events, profile aws_cloudtrail, scenario security_group_open, destination cribl_aws_audit, dataset amazon_aws_raw): SSH (22) from one external address as a /32, then RDP (3389) from 0.0.0.0/0. Use when the operator asks to trigger, demo, prove or reproduce an opened security group, SSH or RDP exposed to an external address, or a cloud firewall rule change. One call, no arguments to fill in.'
icon: lock_open
source: platform
loadingMode: on-demand
locked: false
---

# Skill: Trigger the "AWS Security Group remote access allowed from an unknown external IP address" alert

## When this skill applies

The operator wants the **native Cortex Analytics security-group detector** to fire, for example: *"trigger an AWS security group alert"*, *"show SSH opened to an unknown address"*, *"prove cloud firewall tampering fires from CloudTrail"*. It is Cortex's own Cloud analytics over the AWS audit feed, not a correlation rule, so the events must go through the Cribl integration under the AWS audit source's dedicated identifier (what `http-sender` does for the `aws_cloudtrail` profile).


## What the detector looks for (Cortex doc: "AWS Security Group remote access allowed from an unknown external IP address")

| Property | Value |
|---|---|
| Alert name | `AWS Security Group remote access allowed from an unknown external IP address` (Low)  |
| Source | a Cloud analytics detector (XDR Analytics), cloud firewall modification |
| MITRE technique as shown on the alert | `T1686.001 - Disable or Modify System Firewall: Cloud Firewall` |
| Alert tags | `DS:Amazon/AWS` (data source), `DOM:Security` |
| Required data | AWS Audit Log (CloudTrail): the `cribl_aws_audit` source on the tenant, dataset `amazon_aws_raw` |
| Activation / training (doc) | 14 days / 30 days; in practice the alert typically arrives within a minute or two of its events |
| Test period | single event |
| Deduplication (doc) | 1 day |
| What the alert text says | *"The cloud identity arn:aws:sts::<account>:assumed-role/DevOpsEngineer-<hex>/<session> has modified the ingress rules of the security group: sg-<17 hex>. The newly added ingress rules allow SSH or RDP connections from the following unfamiliar ip addresses:. <external address>. The operation was performed on AWS/<account>"* |

The recipe is two CloudTrail `AuthorizeSecurityGroupIngress` calls (`eventSource ec2.amazonaws.com`) on one new security group (`sg-<17 hex>`) by an **assumed role** (`DevOpsEngineer-<hex>`): port 22 from `<external address>/32` (the scenario picks an address from the abroad pool) with description `temp vendor access`, then port 3389 from `0.0.0.0/0` with description `rdp`. The alert names the **external /32 address** (the address that was granted SSH) as the unfamiliar one. Which of the two steps the detector needs was not isolated.

## Preconditions: check these BEFORE sending

| # | Must be true | How to check |
|---|---|---|
| 1 | The `http-sender` instance is running with the Cribl settings: the `criblUrl` config and the `criblToken` secret. The call below has **no `destination` argument**: the `aws_cloudtrail` profile goes to **`cribl_aws_audit`** (the tenant's Cribl integration under the AWS audit source's dedicated UUID, dataset `amazon_aws_raw`) and refuses to send when Cribl is not configured. It never falls back to an HTTP collector | `http-sender.list_destinations` shows `cribl_aws_audit` with `mode: cribl` and `ready: true` |
| 2 | Nothing else to choose: every call invents a fresh AWS account id, a fresh IAM principal and session and fresh resource ids, so the actor is always a first-time actor and **you never hand-build events** | the call result lists `sample_ids` (the CloudTrail `eventID`s) and the first and last `eventTime` |
| 3 | Do **not** pass `destination`, `target_user`, `source_ip` or `spread_seconds`: the recipe below is the supported one | n/a |

## Expected result

The recipe fires from a fresh assumed role named `DevOpsEngineer-<hex>`; the alert typically arrives within a minute or two of the call. The alert is credited to a call by the principal in its `user_name` and description (and the security group name), never by time alone: the Step 3 query below also returns earlier alerts of the hour, so match the principal.

## Step 1: send the events (exactly this call)

Call **`http-sender.generate_events`** once with this argument object. Nothing needs replacing.

```json
{"profile": "aws_cloudtrail", "scenario": "security_group_open", "count": 2}
```

Two CloudTrail records by one fresh assumed role on one new security group, two minutes apart (the second at now). The external address for the SSH rule is picked per call. The result shows `num_records: 2`, `batch_status: [200]` and two `sample_ids`.

## Step 2: confirm the events landed (a few seconds to a minute after Step 1)

```text
config timeframe = 1h | dataset = amazon_aws_raw
| filter _collector_name = "phantom-http-sender" and eventName = "AuthorizeSecurityGroupIngress"
| alter who = json_extract_scalar(userIdentity, "$.arn")
| fields _time, eventName, who, sourceIPAddress, recipientAccountId, eventID
| sort desc _time
| limit 10
```

Pass when **2 rows** return for your call with the same `who` (an `arn:aws:sts::<account>:assumed-role/DevOpsEngineer-<hex>/<session>`) and `eventID`s equal to the Step 1 `sample_ids`. The query covers the last hour, so earlier calls show too, and the rows are **not** guaranteed newest first: match on the Step 1 `sample_ids`. Expect 2 rows for your principal from one address, 120 s apart, with `eventID`s equal to `sample_ids`.

## Step 3: wait, then check for the alert

Check **15 seconds** after the call, then every 15 seconds for up to **10 minutes** (it typically arrives within a minute or two).

```text
config timeframe = 1h | dataset = alerts
| filter alert_source in ("MAGNIFIER","ANALYTICS_BIOC") and alert_name = "AWS Security Group remote access allowed from an unknown external IP address"
| fields alert_id, alert_name, severity, user_name, mitre_attack_technique, alert_arrival_timestamp, description
| sort desc alert_arrival_timestamp
| limit 10
```

Pass when a **new** row appears whose `user_name` is the `who` of Step 2 and whose description names `sg-<17 hex>` and the external /32 address as the *unfamiliar ip address*. Severity `LOW`, technique `T1686.001 - Disable or Modify System Firewall: Cloud Firewall`, tags include `DS:Amazon/AWS`. The alert's `host_ip` is the event's source address, not the external address in the rule.

If nothing arrives in 10 minutes: re-run Step 2 (the events must be in `amazon_aws_raw`), confirm `list_destinations` still shows `cribl_aws_audit` ready, then call Step 1 **once more** (a new call is a new first-time actor). Do not edit the events.

## Notes and limits

- **`source_ip` is the rule's external address, not the caller's.** Passing it chooses which address gets SSH access (the scenario picks one from the abroad pool by itself); the supported recipe passes nothing.
- **The caller's own address is an ordinary Saudi one**; only the address inside the rule is foreign.
- **Alert source filter.** Cortex stores Analytics alerts as `MAGNIFIER` and `ANALYTICS_BIOC`; the displayed names `XDR_ANALYTICS` and `XDR_ANALYTICS_BIOC` match nothing in XQL.
- **Calling it again.** Re-running is **not** blocked by deduplication: the call is invented fresh each time, and a second call sent minutes after the first raises its own new alert for its new identity. The rows of the earlier calls stay in the 1-hour query results, so match on the Step 1 `sample_ids` and the principal.
- **`count`.** The minimum is 2 (one full recipe, as above); a larger `count` repeats the recipe with fresh resource ids for the same actor. A smaller one is refused (profile code). A larger `count` is not covered by this recipe.
- **Modeling.** Without the AWS CloudTrail modeling pack installed, `xdm.*` stays empty for this source; Step 2 therefore checks the raw dataset.

## Report back to the operator

State the role ARN, the security group id, the external address granted SSH, the Step 2 result (2 rows) and either the alert id with name, severity (Low) and latency or that nothing arrived in 10 minutes and what you checked.
