---
name: trigger_aws_snapshot_public_alerts
displayName: Trigger the three Cortex "Cloud snapshot ... public" analytics alerts (configured for public access, publicly shared, shared public)
category: workflows
description: 'Fire three Cortex XSIAM native analytics alerts with ONE recipe: "Cloud snapshot was configured for public access" (Low, T1537 Transfer Data to Cloud Account, T1578, T1530), "Cloud snapshot of a database or storage instance was publicly shared" (Medium, T1537) and "Cloud snapshot of a database or storage instance was shared public" (Low, T1537). The recipe sends two synthetic AWS CloudTrail records from a fresh assumed role through the http-sender connector''s Cribl mode (generate_events, profile aws_cloudtrail, scenario snapshot_public_share, destination cribl_aws_audit, dataset amazon_aws_raw): ModifySnapshotAttribute adding the group all to an EBS snapshot, then ModifyDBSnapshotAttribute adding all to an RDS snapshot. Use when the operator asks to trigger, demo, prove or reproduce a public EBS snapshot, a publicly shared RDS or database snapshot, snapshot exfiltration, or any of those three alert names. One call, no arguments to fill in.'
icon: share
source: platform
loadingMode: on-demand
locked: false
---

# Skill: Trigger the three Cloud snapshot public-access alerts

## When this skill applies

The operator wants any of the **three native Cortex Analytics snapshot-exposure detectors** to fire, for example: *"trigger a public snapshot alert"*, *"show an EBS snapshot shared with everyone"*, *"prove snapshot exfiltration (T1537) fires"*, or by alert name: *Cloud snapshot was configured for public access*, *Cloud snapshot of a database or storage instance was publicly shared*, *Cloud snapshot of a database or storage instance was shared public*. One recipe raises all three. They are Cortex's own Cloud analytics over the AWS audit feed, not correlation rules, so the events must go through the Cribl integration under the AWS audit source's dedicated identifier (what `http-sender` does for the `aws_cloudtrail` profile).


## What the detector looks for (Cortex doc: "Cloud snapshot created or modified", "A cloud snapshot of AWS database or storage was modified or shared", "Cloud snapshot of a database or storage instance was publicly shared")

| Property | Value |
|---|---|
| Alert `Cloud snapshot was configured for public access` | Low; variation of `Cloud snapshot created or modified` (Informational, invisible); raised by the EBS step; MITRE `T1537 - Transfer Data to Cloud Account`, `T1578 - Modify Cloud Compute Infrastructure`, `T1530 - Data from Cloud Storage`; deduplication 1 day; tags `DS:Amazon/AWS`, `DOM:Security`, `DT:Cloud Data Asset Disaster Recovery Risks`, `DT:Data Detection & Response`, `DT:Cloud Data Asset Configuration` |
| Alert `Cloud snapshot of a database or storage instance was publicly shared` | Medium; its own detector; raised by the RDS step; MITRE `T1537 - Transfer Data to Cloud Account`; deduplication 5 days; tags `DS:Amazon/AWS`, `DOM:Security`, `DT:Data Detection & Response`, `DT:Cloud Data Asset Public Exposure`, `DT:Cloud Data Asset Exfiltration` |
| Alert `Cloud snapshot of a database or storage instance was shared public` | Low; variation of `A cloud snapshot of AWS database or storage was modified or shared` (Informational, invisible); raised by the RDS step; MITRE `T1537 - Transfer Data to Cloud Account`; deduplication 1 day; tags `DS:Amazon/AWS`, `DOM:Security`, `DT:Cloud Data Asset Disaster Recovery Risks`, `DT:Data Detection & Response`, `DT:Cloud Data Asset Configuration` |
| Required data | AWS Audit Log (CloudTrail): the `cribl_aws_audit` source on the tenant, dataset `amazon_aws_raw` |
| Activation / training (doc) | 14 days / 30 days; in practice the alert typically arrives within a minute or two of its events |
| Test period | single event |
| Deduplication (doc) | 1 day for two of the rules, 5 days for the Medium one (see the rows above) |
| What the alert text says | *"The cloud identity arn:aws:sts::<account>:assumed-role/DevOpsEngineer-<hex>/<session> has created or modified a cloud snapshot. The snapshot name is snap-<17 hex>. The operation was performed on AWS/<account>. The snapshot was configured for public access"* (EBS step), *"... has publicly shared a snapshot of a database or storage instance. The snapshot name is prod-db-snap-<hex> ..."* (Medium) and *"... has publicly shared prod-db-snap-<hex> snapshot"* (shared public), both from the RDS step |

The recipe is two CloudTrail records by one **assumed role** (`DevOpsEngineer-<hex>`) from one Saudi home-pool address, about two minutes apart: `ModifySnapshotAttribute` (`eventSource ec2.amazonaws.com`, `CREATE_VOLUME_PERMISSION`, `add` the group `all`, on a new `snap-<17 hex>`) and `ModifyDBSnapshotAttribute` (`eventSource rds.amazonaws.com`, attribute `restore`, `valuesToAdd ["all"]`, on a new `prod-db-snap-<hex>`). Mapping: the EBS record raises *configured for public access*; the RDS record raises both *publicly shared* and *shared public*. The alerts are not distinguishable by identity, only by name and snapshot.

## Preconditions: check these BEFORE sending

| # | Must be true | How to check |
|---|---|---|
| 1 | The `http-sender` instance is running with the Cribl settings: the `criblUrl` config and the `criblToken` secret. The call below has **no `destination` argument**: the `aws_cloudtrail` profile goes to **`cribl_aws_audit`** (the tenant's Cribl integration under the AWS audit source's dedicated UUID, dataset `amazon_aws_raw`) and refuses to send when Cribl is not configured. It never falls back to an HTTP collector | `http-sender.list_destinations` shows `cribl_aws_audit` with `mode: cribl` and `ready: true` |
| 2 | Nothing else to choose: every call invents a fresh AWS account id, a fresh IAM principal and session and fresh resource ids, so the actor is always a first-time actor and **you never hand-build events** | the call result lists `sample_ids` (the CloudTrail `eventID`s) and the first and last `eventTime` |
| 3 | Do **not** pass `destination`, `target_user`, `source_ip` or `spread_seconds`: the recipe below is the supported one | n/a |

## Expected result

The recipe fires from a fresh assumed role named `DevOpsEngineer-<hex>` and raises three alerts (see the names in Step 3); they typically arrive within a minute or two of the call, a few seconds apart. The alerts are credited to a call by the principal in their `user_name` and description (and the snapshot name), never by time alone: the Step 3 query below also returns earlier alerts of the hour, so match the principal.

## Step 1: send the events (exactly this call)

Call **`http-sender.generate_events`** once with this argument object. Nothing needs replacing.

```json
{"profile": "aws_cloudtrail", "scenario": "snapshot_public_share", "count": 2}
```

Two CloudTrail records (EBS then RDS) by one fresh assumed role, two minutes apart (the second at now). The result shows `num_records: 2`, `batch_status: [200]` and two `sample_ids`.

## Step 2: confirm the events landed (a few seconds to a minute after Step 1)

```text
config timeframe = 1h | dataset = amazon_aws_raw
| filter _collector_name = "phantom-http-sender" and eventName in ("ModifySnapshotAttribute", "ModifyDBSnapshotAttribute")
| alter who = json_extract_scalar(userIdentity, "$.arn")
| fields _time, eventName, who, sourceIPAddress, recipientAccountId, eventID
| sort desc _time
| limit 10
```

Pass when **2 rows** return for your call with the same `who` (an `arn:aws:sts::<account>:assumed-role/DevOpsEngineer-<hex>/<session>`): `ModifySnapshotAttribute` and `ModifyDBSnapshotAttribute`, with `eventID`s equal to the Step 1 `sample_ids`. The query covers the last hour, so earlier calls show too, and the rows are **not** guaranteed newest first: match on the Step 1 `sample_ids`. Expect 2 rows for your principal from one address, `ModifySnapshotAttribute` then `ModifyDBSnapshotAttribute`, with `eventID`s equal to `sample_ids`.

## Step 3: wait, then check for the alert

Check **30 seconds** after the call, then every 30 seconds for up to **10 minutes** (the three alerts typically arrive within a minute or two, a few seconds apart).

```text
config timeframe = 1h | dataset = alerts
| filter alert_source in ("MAGNIFIER","ANALYTICS_BIOC") and alert_name in ("Cloud snapshot was configured for public access", "Cloud snapshot of a database or storage instance was publicly shared", "Cloud snapshot of a database or storage instance was shared public")
| fields alert_id, alert_name, severity, user_name, mitre_attack_technique, alert_arrival_timestamp, description
| sort desc alert_arrival_timestamp
| limit 10
```

Pass when **three** new rows appear whose `user_name` is the `who` of Step 2: one for each name above. Severities `LOW`, `MEDIUM`, `LOW`; `original_tags` contains `DS:Amazon/AWS` on each. Report all three alert ids. If only some appear, wait the full 10 minutes before reporting the rest missing.

If nothing arrives in 10 minutes: re-run Step 2 (the events must be in `amazon_aws_raw`), confirm `list_destinations` still shows `cribl_aws_audit` ready, then call Step 1 **once more** (a new call is a new first-time actor). Do not edit the events.

## Notes and limits

- **One recipe, three alerts.** Do not call the scenario three times: one call raises all three, and a second call raises three more (a new identity).
- **Which step raises which** is read from the alert descriptions and `event_timestamp`; the steps have not been sent separately.
- **Alert source filter.** Cortex stores Analytics alerts as `MAGNIFIER` and `ANALYTICS_BIOC`; the displayed names `XDR_ANALYTICS` and `XDR_ANALYTICS_BIOC` match nothing in XQL.
- **Calling it again.** Re-running is **not** blocked by deduplication: the call is invented fresh each time, and a second call sent minutes after the first raises its own new alert for its new identity. The rows of the earlier calls stay in the 1-hour query results, so match on the Step 1 `sample_ids` and the principal.
- **`count`.** The minimum is 2 (one full recipe, as above); a larger `count` repeats the recipe with fresh resource ids for the same actor. A smaller one is refused (profile code). A larger `count` is not covered by this recipe.
- **Modeling.** Without the AWS CloudTrail modeling pack installed, `xdm.*` stays empty for this source; Step 2 therefore checks the raw dataset.

## Report back to the operator

State the role ARN, the two snapshot ids, the Step 2 result (2 rows) and the **three** alert ids with their names, severities (Low, Medium, Low) and latencies, or which of the three did not arrive in 10 minutes and what you checked.
