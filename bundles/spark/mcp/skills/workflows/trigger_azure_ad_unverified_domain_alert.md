---
name: trigger_azure_ad_unverified_domain_alert
displayName: Trigger the Cortex "Rare unverified domain addition to Azure AD" analytics alert
category: workflows
description: 'Fire Cortex XSIAM''s native "Rare unverified domain addition to Azure AD" analytics alert (Azure AD / Entra ID, Low, T1098.001) by sending one synthetic Microsoft Graph directoryAudit event, "Add unverified domain" for a new domain name, by a new admin, through the http-sender connector''s Cribl mode (default destination cribl_azure_ad_audit, dataset msft_azure_ad_audit_raw). Use when the operator asks to trigger, demo, prove or reproduce an unverified domain being added to Azure AD or Entra ID, the first step of a federation backdoor. One generate_events call with profile azure_ad_audit and scenario unverified_domain_added; no placeholders. Typically fires within a minute or two. Without the Entra ID pack, xdm is empty; check the landing with raw columns.'
icon: domain_add
source: platform
loadingMode: on-demand
locked: false
---

# Skill: Trigger the "Rare unverified domain addition to Azure AD" alert

## When this skill applies

The operator wants the **native Cortex Analytics unverified-domain detector** to fire, for example: *"trigger the rare unverified domain addition alert"*, *"show an admin adding an unverified domain to the tenant"*, *"prove T1098.001 fires from Azure AD audit logs"*.

It is Cortex's own analytics (not a correlation rule). The call below sends **one built-in `http-sender` scenario** through the Cribl path to the tenant's dedicated Azure AD audit source; nothing needs installing on the tenant.

> **Entra ID pack.** Without the Microsoft Entra ID content pack installed (its dependencies can fail to install), `xdm.*` is **empty** for `msft_azure_ad_audit_raw`. The detector does not need it: it reads the native Azure AD audit feed that the dedicated Cribl source creates (`_collector_type = "Azure AD_AUDIT"`). Never judge the landing with a `datamodel` query for this dataset; it returns nothing and says nothing about the detector. Step 2 reads the raw columns.


## What the detector looks for

| Property | Value |
|---|---|
| Alert name | `Rare unverified domain addition to Azure AD` |
| Severity | Low |
| Source | Cortex Analytics BIOC: the `alert_source` column shows `XDR_ANALYTICS_BIOC` (stored enum `ANALYTICS_BIOC`) |
| MITRE (as shown on the alert) | T1098.001 - Account Manipulation: Additional Cloud Credentials |
| Data-source tag on the alert | `DS:msft/Azure AD Audit` (also `DT:Identity Threat`, `DOM:Security`) |
| What triggers it | One Azure AD audit record `Add unverified domain` (category `DirectoryManagement`, service `Core Directory`, operation `Add`, result `success`) naming a domain never seen before (`<word>-<hex>.example`, new on every call), by an admin who has not done it. "Rare" is counted over 30 days across the organization: the alert text states how many users did it. |
| What the alert text says | *"The account <name>.<hex>.adm@phantom.lab has added an unverified domain to Azure AD. The operation attempted was a: SUCCESS. The domain <word>-<hex>.example was added. In the past 30 days, 1 users performed this operation in the organization"* |

**Rarity is a count.** The description ends "In the past 30 days, N users performed this operation in the organization". It says N = 1 for the recipe's new admin and the alert fires with it each time; the count does not rise with repeated sends, and a higher N is not covered by this recipe.


## Preconditions: check these BEFORE sending

| # | Must be true | How to check |
|---|---|---|
| 1 | `http-sender` is running **with Cribl mode configured** (the instance has `criblUrl` and the `criblToken` secret) and its destination **`cribl_azure_ad_audit`** shows `ready: true`. The generic HTTP collectors and syslog do not give Cortex the native Azure AD audit feed, and these detectors do not fire from them | `http-sender.list_destinations`: the row with `destination: "cribl_azure_ad_audit"`, `mode: "cribl"`, `ready: true`. If it is missing or not ready, stop and tell the operator the Cribl collector must be configured on the instance (the agent cannot set the token) |
| 2 | You do **not** pass a `destination`: the `azure_ad_audit` profile goes to `cribl_azure_ad_audit` by itself and refuses to send when Cribl is not configured (it never falls back to an HTTP collector) | the call in Step 1 has no `destination` |
| 3 | You do **not** build the events: every call invents a fresh admin (`<name>.<hex>.adm@<domain>`), object id, address (a real Saudi home-pool address) and target, so the detector sees a first-time actor each time | nothing to do; never reuse an identity from an earlier run |

## Expected result

The recipe fires from a new admin and a new domain on every call; each call is a new actor and fires again, so it can be repeated at once, and every description says `1 users performed this operation`. The alert typically arrives within a minute or two of the call.

## Step 1: send the events (exactly this call)

Call **`http-sender.generate_events`** once with this argument object. There is nothing to change: no placeholder, no destination, no `count` (an omitted `count` is one full recipe: 1 event). It uses the default destination `cribl_azure_ad_audit` (dataset `msft_azure_ad_audit_raw`).

```json
{"profile": "azure_ad_audit", "scenario": "unverified_domain_added"}
```

The result shows `ok: true`, `sent: 1`, `num_records: 1`, `batch_status: [200]`, `destination: "cribl_azure_ad_audit"`, `dataset: "msft_azure_ad_audit_raw"` and one id in `sample_ids`. Add `"dry_run": true` to preview without sending. Do **not** pass `target_user` (it names the admin, and a reused admin is no longer a first-time actor) and do not pass `count`.

## Step 2: confirm the events landed

About 20-30 seconds after the call (ingestion on this path takes seconds). Query the **raw columns**, never `datamodel` (without the Entra ID pack, `xdm.*` is empty):

```text
config timeframe = 1h
| dataset = msft_azure_ad_audit_raw
| filter _collector_name = "phantom-http-sender" and activityDisplayName = "Add unverified domain"
| fields _time, id, activityDisplayName, result, initiatedBy, targetResources
| sort desc _time
| limit 3
```

Pass when you see **one** row for your admin: `result` is `success`, `initiatedBy` contains `<name>.<hex>.adm@phantom.lab` and `targetResources` is a `Domain` named `<word>-<hex>.example`. Runs from the last hour (yours and earlier ones) also appear: read the newest row first.

## Step 3: wait, then check for the alert

Check at 30 seconds, then every 30 seconds for up to **6 minutes**. Match the name client-side with `~=` and filter the alert source by its **stored** enum names (`XDR_ANALYTICS` and `XDR_ANALYTICS_BIOC` as displayed match nothing):

```text
config timeframe = 1d
| dataset = alerts
| filter alert_source in ("MAGNIFIER", "ANALYTICS_BIOC") and alert_name ~= "Rare unverified domain addition"
| fields alert_id, alert_name, severity, user_name, mitre_attack_technique, original_tags, description, alert_arrival_timestamp
| sort desc alert_arrival_timestamp
| limit 5
```

Pass when a **new** row names the identity you saw in Step 2 (the admin's name in the alert's `user_name` as `phantom\<name>.adm`, and the new domain in the description); older alerts have other identities. The alert typically arrives within a minute or two of the event.

If nothing arrives in 6 minutes: re-run Step 2 (the events must be there and carry the right operation), confirm the instance's Cribl destination is still ready, and send the call **once more** (a new call is a new actor). Do not edit the events and do not switch to an HTTP collector or syslog.

## Report back to the operator

State the identity that appears in the alert description, the alert id, `Rare unverified domain addition to Azure AD`, its severity (Low), and the latency from the events to the alert (typically within a minute or two). If `xdm.*` is empty for this dataset (the Entra ID pack is not installed), say that this does not stop the detector. Say that each call uses a new identity so it can be repeated at once.

Note: the Cortex `user_name` prefix shown above (`phantom\`) is the first label of the organization's email domain (`phantom.lab`); it was `phantom-lab\` on the previous domain. It has not been re-measured on the tenant, so confirm it on the first replay.
