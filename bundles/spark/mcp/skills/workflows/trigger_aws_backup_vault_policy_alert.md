---
name: trigger_aws_backup_vault_policy_alert
displayName: Trigger the Cortex "A Backup vault policy was modified" analytics alert
category: workflows
description: 'Fire Cortex XSIAM''s native "A Backup vault policy was modified" analytics alert (AWS Backup, Low, T1537) by sending one synthetic CloudTrail PutBackupVaultAccessPolicy record by a new IAM user whose vault policy allows a foreign AWS account to copy backups into the vault, through the http-sender connector''s Cribl mode (default destination cribl_aws_audit, dataset amazon_aws_raw). Use when the operator asks to trigger, demo, prove or reproduce an AWS Backup vault access policy change, cross-account backup exfiltration or a backup vault shared with an outside account. One generate_events call with profile aws_cloudtrail and scenario backup_vault_policy_modified; no placeholders. Typically fires within seconds. If the AWS CloudTrail pack is not installed, xdm is empty; check the landing with raw columns.'
icon: backup
source: platform
loadingMode: on-demand
locked: false
---

# Skill: Trigger the "A Backup vault policy was modified" alert

## When this skill applies

The operator wants the **native Cortex Analytics Backup-vault detector** to fire, for example: *"trigger the backup vault policy modified alert"*, *"show a backup vault being shared with another AWS account"*, *"prove T1537 fires from CloudTrail"*.

It is Cortex's own analytics (not a correlation rule). The call below sends **one built-in `http-sender` scenario** through the Cribl path to the tenant's dedicated AWS audit source; nothing needs installing on the tenant.

> **AWS CloudTrail pack.** When the AWS CloudTrail content pack is **not installed** on the tenant, `xdm.*` is **empty** for `amazon_aws_raw` rows from this path. The detector does not need it: it reads the native AWS audit feed that the dedicated Cribl source creates (`_collector_type = "Amazon S3"`). Never judge the landing with a `datamodel` query for this dataset; Step 2 reads the raw columns.


## What the detector looks for

| Property | Value |
|---|---|
| Alert name | `A Backup vault policy was modified` |
| Severity | Low |
| Source | Cortex Analytics BIOC: the `alert_source` column shows `XDR_ANALYTICS_BIOC` (stored enum `ANALYTICS_BIOC`) |
| MITRE (as shown on the alert) | T1537 - Transfer Data to Cloud Account |
| Data-source tag on the alert | `DS:Amazon/AWS` (also `DT:Cloud Data Asset Configuration`, `DT:Data Detection & Response`, `DOM:Security`) |
| What triggers it | One CloudTrail `PutBackupVaultAccessPolicy` (`backup.amazonaws.com`) by an **IAM user** (not an assumed role) whose policy gives another AWS account's root `Allow` on `backup:CopyIntoBackupVault`. The recipe is a single event; the vault is `finance-vault-<hex>`. The same policy put through an assumed role stays silent, as do a `*` principal and a deny-all. |
| What the alert text says | *"The cloud identity <name>.<hex> has modified Backup Vault access policy. The Backup vault name is finance-vault-<hex>. The operation was performed on AWS/<account>"* |


## Preconditions: check these BEFORE sending

| # | Must be true | How to check |
|---|---|---|
| 1 | `http-sender` is running **with Cribl mode configured** (the instance has `criblUrl` and the `criblToken` secret) and its destination **`cribl_aws_audit`** shows `ready: true`. The generic HTTP collectors and syslog do not give Cortex the native AWS CloudTrail feed | `http-sender.list_destinations`: the row with `destination: "cribl_aws_audit"`, `mode: "cribl"`, `ready: true`. If it is missing or not ready, stop and tell the operator the Cribl collector must be configured on the instance (the agent cannot set the token) |
| 2 | You do **not** pass a `destination`: the `aws_cloudtrail` profile goes to `cribl_aws_audit` by itself and refuses to send when Cribl is not configured (it never falls back to an HTTP collector) | the call in Step 1 has no `destination` |
| 3 | You do **not** build the events: every call invents a fresh AWS account id, principal, access key and resource names, so the detector sees a first-time actor each time | nothing to do; never reuse an identity from an earlier run |

## Expected result

The call in Step 1, unchanged, fires the alert for a new IAM user in a new account with a new `finance-vault-<hex>`, typically within seconds of the event. The same policy put by an assumed role stays silent, which is why the actor here is an IAM user; do not pass `target_user` expecting a role. The recipe is verified at the default `count` only.

## Step 1: send the events (exactly this call)

Call **`http-sender.generate_events`** once with this argument object. There is nothing to change: no placeholder, no destination, no `count` (an omitted `count` is one full recipe: 1 event). It uses the default destination `cribl_aws_audit` (dataset `amazon_aws_raw`).

```json
{"profile": "aws_cloudtrail", "scenario": "backup_vault_policy_modified"}
```

The result shows `ok: true`, `batch_status: [200]`, `num_records` equal to the number of events, `destination: "cribl_aws_audit"`, `dataset: "amazon_aws_raw"` and the event ids in `sample_ids`. Add `"dry_run": true` to preview without sending. Do **not** pass `target_user` (it names the principal, and a reused principal is no longer a first-time actor).

## Step 2: confirm the events landed

About 20-30 seconds after the call (ingestion on this path takes seconds). The AWS CloudTrail pack is not installed, so query the **raw columns**, never `datamodel`:

```text
config timeframe = 1h
| dataset = amazon_aws_raw
| filter _collector_name = "phantom-http-sender" and eventName = "PutBackupVaultAccessPolicy"
| fields _time, eventID, eventName, userAgent, sourceIPAddress, userIdentity
| sort desc _time
| limit 3
```

Pass when you see **one** row for your principal: `userIdentity.type` is `IAMUser` (`userName` `<name>.<hex>`), `eventSource` is `backup.amazonaws.com` and `requestParameters` holds the vault name `finance-vault-<hex>` and a policy `Allow` for `arn:aws:iam::<another account>:root`. Runs from the last hour (yours and earlier ones) also appear: read the newest row first.

## Step 3: wait, then check for the alert

Check at 30 seconds, then every 30 seconds for up to **6 minutes**. Match the name client-side with `~=` and filter the alert source by its **stored** enum names (`XDR_ANALYTICS` and `XDR_ANALYTICS_BIOC` as displayed match nothing):

```text
config timeframe = 1d
| dataset = alerts
| filter alert_source in ("MAGNIFIER", "ANALYTICS_BIOC") and alert_name ~= "A Backup vault policy was modified"
| fields alert_id, alert_name, severity, user_name, mitre_attack_technique, original_tags, description, alert_arrival_timestamp
| sort desc alert_arrival_timestamp
| limit 5
```

Pass when a **new** row names the identity you saw in Step 2 (the IAM user name `<name>.<hex>` and the vault name in the description); older rows from other runs have other identities. The alert typically arrives within seconds of the event.

If nothing arrives in 6 minutes: re-run Step 2 (the events must be there and carry the right operation), confirm the instance's Cribl destination is still ready, and send the call **once more** (a new call is a new actor). Do not edit the events and do not switch to an HTTP collector or syslog.

## Report back to the operator

State the identity that appears in the alert description, the alert id, `A Backup vault policy was modified`, its severity (Low), and the latency from the events to the alert (typically within seconds). Say that `xdm.*` is empty for this dataset because the AWS CloudTrail pack is not installed and that this does not stop the detector, and that each call uses a new identity so it can be repeated at once.
