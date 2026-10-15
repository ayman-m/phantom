---
name: trigger_azure_ad_federation_modified_alert
displayName: Trigger the Cortex "A successful Azure domain federation settings modification" analytics alert
category: workflows
description: 'Fire Cortex XSIAM''s native "A successful Azure domain federation settings modification" analytics alert (Azure AD / Entra ID, Medium, T1098.001 and T1484; the stored alert name ends with a trailing space) by sending one synthetic Microsoft Graph directoryAudit event, "Set federation settings on domain" switching a new domain from Managed to Federated with a new issuer URI, through the http-sender connector''s Cribl mode (default destination cribl_azure_ad_audit, dataset msft_azure_ad_audit_raw). Use when the operator asks to trigger, demo, prove or reproduce a domain federation change, a Golden SAML style rogue identity provider or a federated-domain backdoor in Azure AD. One generate_events call with profile azure_ad_audit and scenario federation_modified; no placeholders. Typically fires within seconds. If the Entra ID pack is not installed, xdm is empty; check the landing with raw columns.'
icon: vpn_key
source: platform
loadingMode: on-demand
locked: false
---

# Skill: Trigger the "A successful Azure domain federation settings modification" alert

## When this skill applies

The operator wants the **native Cortex Analytics federation-change detector** to fire, for example: *"trigger the Azure domain federation modification alert"*, *"show an admin federating a domain to a rogue identity provider"*, *"prove T1484 / T1098.001 fires from Azure AD audit logs"*.

It is Cortex's own analytics (not a correlation rule). The call below sends **one built-in `http-sender` scenario** through the Cribl path to the tenant's dedicated Azure AD audit source; nothing needs installing on the tenant.

> **Entra ID pack.** When the Microsoft Entra ID content pack is **not installed** on the tenant (its dependencies can fail to install), `xdm.*` is **empty** for `msft_azure_ad_audit_raw`. The detector does not need it: it reads the native Azure AD audit feed that the dedicated Cribl source creates (`_collector_type = "Azure AD_AUDIT"`). Never judge the landing with a `datamodel` query for this dataset; it returns nothing and says nothing about the detector. Step 2 reads the raw columns.


## What the detector looks for

| Property | Value |
|---|---|
| Alert name | `A successful Azure domain federation settings modification ` |
| Severity | Medium |
| Source | Cortex Analytics BIOC: the `alert_source` column shows `XDR_ANALYTICS_BIOC` (stored enum `ANALYTICS_BIOC`) |
| MITRE (as shown on the alert) | T1098.001 - Account Manipulation: Additional Cloud Credentials and T1484 - Domain or Tenant Policy Modification |
| Data-source tag on the alert | `DS:msft/Azure AD Audit` (also `DT:Identity Threat`, `DOM:Security`) |
| What triggers it | One Azure AD audit record `Set federation settings on domain` (category `DirectoryManagement`, service `Core Directory`, operation `Update`, result `success`) on a domain never seen before: `LiveType` changes `Managed` to `Federated` and a new `IssuerUri` (`http://sts-<hex>.example/adfs/services/trust`) appears. The domain name is new on every call. |
| What the alert text says | *"The account <name>.<hex>.adm@<domain> has successfully modified the federation settings of the domain. The operation name was: Set federation settings on domain. The operation status: SUCCESS. The activity originated from IP: <source address>. The new Issuer Uri is http://sts-<hex>.example/adfs/services/trust. The Live Type was Managed. The new Live Type is Federated. The user has performed this operation on 0 days over the last 30 days"* |

**The stored alert name ends with a space** (`A successful Azure domain federation settings modification `). An exact `alert_name = "..."` filter misses it unless it carries the trailing space; Step 3 matches it with `~=`.


## Preconditions: check these BEFORE sending

| # | Must be true | How to check |
|---|---|---|
| 1 | `http-sender` is running **with Cribl mode configured** (the instance has `criblUrl` and the `criblToken` secret) and its destination **`cribl_azure_ad_audit`** shows `ready: true`. The generic HTTP collectors and syslog do not give Cortex the native Azure AD audit feed, and these detectors never fired from them | `http-sender.list_destinations`: the row with `destination: "cribl_azure_ad_audit"`, `mode: "cribl"`, `ready: true`. If it is missing or not ready, stop and tell the operator the Cribl collector must be configured on the instance (the agent cannot set the token) |
| 2 | You do **not** pass a `destination`: the `azure_ad_audit` profile goes to `cribl_azure_ad_audit` by itself and refuses to send when Cribl is not configured (it never falls back to an HTTP collector) | the call in Step 1 has no `destination` |
| 3 | You do **not** build the events: every call invents a fresh admin (`<name>.<hex>.adm@<domain>`), object id, address (a real Saudi home-pool address) and target, so the detector sees a first-time actor each time | nothing to do; never reuse an identity from an earlier run |

## Expected result

The call in Step 1, unchanged, fires the alert for a new domain and a new admin, typically within seconds of the event. The alert text includes the admin's source address (a Saudi home-pool address) and the new `Issuer Uri`. The recipe is verified at the default `count` only.

## Step 1: send the events (exactly this call)

Call **`http-sender.generate_events`** once with this argument object. There is nothing to change: no placeholder, no destination, no `count` (an omitted `count` is one full recipe: 1 event). It uses the default destination `cribl_azure_ad_audit` (dataset `msft_azure_ad_audit_raw`).

```json
{"profile": "azure_ad_audit", "scenario": "federation_modified"}
```

The result shows `ok: true`, `sent: 1`, `num_records: 1`, `batch_status: [200]`, `destination: "cribl_azure_ad_audit"`, `dataset: "msft_azure_ad_audit_raw"` and one id in `sample_ids`. Add `"dry_run": true` to preview without sending. Do **not** pass `target_user` (it names the admin, and a reused admin is no longer a first-time actor) and do not pass `count`.

## Step 2: confirm the events landed

About 20-30 seconds after the call (ingestion on this path takes seconds). The Entra ID pack is not installed, so query the **raw columns**, never `datamodel`:

```text
config timeframe = 1h
| dataset = msft_azure_ad_audit_raw
| filter _collector_name = "phantom-http-sender" and activityDisplayName = "Set federation settings on domain"
| fields _time, id, activityDisplayName, result, initiatedBy, targetResources
| sort desc _time
| limit 3
```

Pass when you see **one** row for your admin: `result` is `success`, `initiatedBy` contains `<name>.<hex>.adm@phantom.lab` and `targetResources` is a `Domain` named `<word>-<hex>.example` whose `modifiedProperties` show `LiveType` `Managed` to `Federated` and a new `IssuerUri`. Runs from the last hour (yours and earlier ones) also appear: read the newest row first.

## Step 3: wait, then check for the alert

Check at 30 seconds, then every 30 seconds for up to **6 minutes**. Match the name client-side with `~=` and filter the alert source by its **stored** enum names (`XDR_ANALYTICS` and `XDR_ANALYTICS_BIOC` as displayed match nothing):

```text
config timeframe = 1d
| dataset = alerts
| filter alert_source in ("MAGNIFIER", "ANALYTICS_BIOC") and alert_name ~= "federation settings modification"
| fields alert_id, alert_name, severity, user_name, mitre_attack_technique, original_tags, description, alert_arrival_timestamp
| sort desc alert_arrival_timestamp
| limit 5
```

Pass when a **new** row names the identity you saw in Step 2 (the admin's name in the alert's `user_name` as `phantom\<name>.adm`, and the new Issuer Uri in the description); older rows from other runs have other identities. The alert typically arrives within seconds of the event.

If nothing arrives in 6 minutes: re-run Step 2 (the events must be there and carry the right operation), confirm the instance's Cribl destination is still ready, and send the call **once more** (a new call is a new actor). Do not edit the events and do not switch to an HTTP collector or syslog.

## Report back to the operator

State the identity that appears in the alert description, the alert id, `A successful Azure domain federation settings modification`, its severity (Medium), and the latency from the events to the alert (typically within seconds). Say that `xdm.*` is empty for this dataset because the Entra ID pack is not installed and that this does not stop the detector, and that each call uses a new identity so it can be repeated at once.

Note: the Cortex `user_name` prefix shown above (`phantom\`) is the first label of the organization's email domain (`phantom.lab`); it was `phantom-lab\` on the previous domain. It has not been re-measured on the tenant, so confirm it on the first replay.
