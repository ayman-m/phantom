---
name: trigger_identity_analytics
displayName: Trigger Cortex identity analytics alerts from Entra ID sign-in logs
category: workflows
description: 'Fire Cortex XSIAM''s identity / SSO analytics detectors (TOR sign-in, SSO brute force, impossible traveler) from synthetic Microsoft Entra ID sign-in logs, via the proven 26-field msft/azure_ad CEF schema. Use when the operator asks to trigger, demo or reproduce identity analytics alerts — cloud SSO brute force, impossible travel, TOR/anonymizer sign-ins. Gives the exact worker shape, three attack recipes, the independent-sampling gotcha that silently flattens impossible-traveler legs, and the 30-day training-window expectation.'
icon: passkey
source: platform
loadingMode: on-demand
locked: false
---

# Skill: Trigger identity analytics alerts from Entra ID sign-in logs

## When this skill applies

The operator wants **identity / SSO analytics detectors** to fire from cloud sign-in data:
*"simulate an impossible traveler"*, *"trigger a brute-force alert on Entra"*, *"a sign-in from
a TOR exit node"*.

For on-prem identity (Windows 4624/4625/4768/4769, Duo MFA, AD enumeration) use
`simulate_identity_telemetry` instead — this skill is the **cloud SSO** route via
`msft_azure_ad_raw`.

## The proven event shape

```yaml
xlog.create_data_worker:
  type:    CEF
  vendor:  msft
  product: azure_ad
  count:   <events>
  duration_seconds: 120
  max_events: <events>
  destination: logdest:<id from log_destinations_list>
  schema_override:           # exactly these 26 fields
    - {name: ProcessingTimeInMilliseconds, type: integer}
    - {name: appDisplayName,    type: string}
    - {name: appId,             type: string_short}
    - {name: authenticationRequirement, type: string}
    - {name: clientAppUsed,     type: string_short}
    - {name: conditionalAccessStatus, type: enum}
    - {name: correlationId,     type: string_short}
    - {name: createdDateTime,   type: datetime}
    - {name: deviceDetail,      type: json}
    - {name: deviceDetail.browser,        type: string_short}
    - {name: deviceDetail.isCompliant,    type: boolean}
    - {name: deviceDetail.isManaged,      type: boolean}
    - {name: deviceDetail.operatingSystem, type: string_short}
    - {name: ipAddress,         type: ipv4}
    - {name: isInteractive,     type: boolean}
    - {name: location,          type: json}
    - {name: location.city,     type: string_short}
    - {name: location.countryOrRegion, type: country_code}
    - {name: resourceDisplayName, type: string}
    - {name: riskLevelAggregated, type: enum}
    - {name: riskState,         type: enum}
    - {name: status,            type: json}
    - {name: status.additionalDetails, type: string}
    - {name: status.errorCode,  type: integer}
    - {name: userDisplayName,   type: string}
    - {name: userPrincipalName, type: email}
  observables_dict:          # see recipe
```

**The gotcha that silently flattens attacks**: `observables_dict` lists sample **independently
per field**. One worker with `location.countryOrRegion: ["SA","US"]` does NOT produce coherent
SA-then-US rows — each field draws on its own, so geography decorrelates from everything else.
Any recipe where fields must move **together** (the two legs of an impossible trip) MUST be
split into one worker per leg, both pinned to the same `userPrincipalName`.

## Attack recipes (all land and model in XDM)

### 1. TOR exit-node sign-in

```yaml
observables_dict:
  userPrincipalName: ["noura.alharbi@phantom.lab"]   # an organization person (Finance) the baseline sign-in job covers
  userDisplayName:   ["Noura Alharbi"]
  ipAddress:         ["171.25.193.25"]          # a REAL Tor exit node
  location.countryOrRegion: ["DE"]
  location.city:     ["Frankfurt"]
  appDisplayName:    ["Office 365 Exchange Online"]
  resourceDisplayName: ["Office 365 Exchange Online"]
  conditionalAccessStatus: ["success"]
  riskLevelAggregated: ["none"]
  riskState:         ["none"]
  isInteractive:     ["true"]
```

3 events are enough. Use a real, currently-listed Tor exit — the detector enriches against
threat intel, so a made-up "suspicious" IP is just an IP.

### 2. SSO brute force

Same shape, but: one user, one source IP, **~150 events**,
`status.errorCode: ["50126"]` (invalid username or password),
`status.additionalDetails: ["Invalid username or password..."]`,
`conditionalAccessStatus: ["failure"]`, `isInteractive: ["true"]`.

### 3. Impossible traveler — TWO workers

- **Leg 1**: `location.city: ["Riyadh"]`, `location.countryOrRegion: ["SA"]`,
  `ipAddress: ["<the person's home_ip: 144.86.80.11 for noura.alharbi>"]`, `createdDateTime` now.
- **Leg 2**: `location.city: ["San Francisco"]`, `location.countryOrRegion: ["US"]`,
  `ipAddress: ["<US egress>"]`, `createdDateTime` minutes later.

Same `userPrincipalName` on both. Do NOT merge them into one worker (see the gotcha).

## Detector timing expectation

Identity analytics detectors carry a **30-day Training period** counted from when the dataset
first receives data (here `msft_azure_ad_raw`). Until it completes, the three recipes above land
and model but produce **no alerts**: that is expected inside the training window, not a delivery
failure.

**Seed the baseline early**: a daily benign sign-in job per persona (normal apps, normal
geography, `status.errorCode: ["0"]` ~97% of the time) gives the detectors their "normal" and
makes the attack legs stand out when training completes. See `baseline_normal_activity` for the
phantom-jobs pattern. The persona is an organization person (`organization_get section=people`; Phantom Lab example `noura.alharbi@phantom.lab`) and the baseline job must sign in that same person, from their `home_ip`; the attack legs above must name the same UPN. The impossible-traveler recipe needs that prior normal location, so replay-verify against the organization hosts before relying on this skill.

## Landing check (before any alert check)

```
datamodel dataset = msft_azure_ad_raw
| filter xdm.source.user.upn = "<the persona UPN>"
| fields xdm.source.user.upn, xdm.source.ipv4, xdm.source.location.country,
         xdm.event.outcome, xdm.target.resource.name
| limit 10
```

## Alert check

```
dataset = alerts
| filter alert_source in ("MAGNIFIER", "ANALYTICS_BIOC")
| fields alert_name, alert_id, original_tags, _time
| sort desc _time
| limit 20
```

Use the stored enum names `MAGNIFIER` and `ANALYTICS_BIOC`: the displayed names `XDR_ANALYTICS` and `XDR_ANALYTICS_BIOC` match nothing in a filter.

`original_tags` carries `DS:msft/azure_ad` when the alert was driven by this feed. Note: the
tenant's custom correlation rules (e.g. a rule literally named "Impossible traveller") are NOT
Palo Alto analytics detectors — check `alert_source` before claiming a fire.
