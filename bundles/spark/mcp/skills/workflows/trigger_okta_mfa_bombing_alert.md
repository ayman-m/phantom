---
name: trigger_okta_mfa_bombing_alert
displayName: Trigger the Cortex "Multiple Okta MFA requests sent to a user with unusual characteristics" analytics alert
category: workflows
description: 'Fire Cortex XSIAM''s native "Multiple Okta MFA requests sent to a user with unusual characteristics" analytics alert (MFA fatigue / push bombing, T1586) by sending synthetic Okta System Log events through the http-sender connector to the okta_sso collector: ONE failed SSO login for a baseline user from a live Tor exit in a country the organization has never seen, then, within minutes and from the same address, a flood of 11-20 Okta Verify push challenges that the user keeps rejecting. Use when the operator asks to trigger, demo, prove or reproduce MFA fatigue, push bombing, MFA bombing or a flood of MFA prompts. Easiest route: two http-sender generate_events scenarios (failed_then_success, then mfa_fatigue) for one baseline user; the hand-built Tor route is documented below. The failed login BEFORE the flood is what makes the alert appear: floods without it are silent.'
icon: notifications_active
source: platform
loadingMode: on-demand
locked: false
---

# Skill: Trigger the "Multiple Okta MFA requests sent to a user with unusual characteristics" alert

## When this skill applies

The operator wants the **native Cortex Analytics MFA-fatigue detector** to fire, for example:
*"trigger an MFA bombing alert"*, *"show push fatigue against a user"*, *"prove T1586 fires from Okta logs"*.

It fires only when one ingredient is present (below): a failed login shortly before the flood. It is not a correlation rule.

> **Two routes.**
>
> **Route B (recommended): the built-in scenarios.** `http-sender.generate_events` twice for the same baseline user (`failed_then_success`, then `mfa_fatigue`); the alert typically arrives within one to two minutes of the second call. No Tor exit and no hand-built JSON: the scenarios pick a real out-of-country address themselves. **Both calls are needed:** each scenario alone, on a fresh baseline user, stays silent.
>
> **Route A: the hand-built Tor route** below fires too, but the call carries 24-42 events of about 2 KB each, which is the most error-prone thing here for an agent to author. Use Route B unless a specific Tor exit or country is required.

## What the detector looks for (Cortex doc: "Multiple Okta MFA requests sent to a user")

| Property | Value |
|---|---|
| Alert name | `Multiple Okta MFA requests sent to a user with unusual characteristics` (Low). The base `Multiple Okta MFA requests sent to a user` is **Informational** and is invisible in the Issues view |
| Source | `XDR Analytics` (a behavioural detector, not a BIOC), category Credential Access, MITRE T1586 Compromise Accounts |
| Required data | Okta |
| Test period | **30 minutes**: the push flood and the failed login must fall inside the same window |
| Deduplication | **1 day** per user |
| What the alert text says | *"The user phantom-lab\<user> received a total of 11 MFA authentication requests during the alert period. Additionally, there were 0 successful and 1 failed logon attempts. The user rejected 11 requests. A user attempted to log in from a rare country for the organization. This authentication attempt was flagged as suspicious due to these characteristics ..."* |

## The two conditions that make it fire

1. **A failed SSO login for the same user shortly before the flood**: one `user.authentication.sso` FAILURE (reason `INVALID_CREDENTIALS`) from a **live Tor exit**, so the alert text can say "1 failed logon attempt". Send it **4 minutes before** the flood and **from the same address**; a failed login about 15 minutes before, from a different Tor address, works as well.
2. **A rare country**: the address must resolve to a country with almost no earlier traffic in the organization. Sweden, Hungary and (as Cortex resolved it) France work; the organization's authentication history, counted by the **country label** in the events, is dominated by its home country, with these countries at few or no events.

Floods that have **no failed login in the previous 30 minutes** are silent: US and German Tor exits (common countries), a Thai non-Tor address and Luxembourg and Romania Tor exits (the last three have **no earlier events in the organization by label**, so a rare country alone is not enough: the failed login is what separates the firing floods from the silent ones).
A **successful** SSO login about 29 minutes before the flood does not help either: the ingredient is a **failed** login, not just any logon, and it must fall inside the 30-minute window.
Whether the Tor address is required (a non-Tor foreign address with a preceding failure) is **untested**.

## Route B: the two built-in scenarios (use this first)

Two calls to **`http-sender.generate_events`** for the **same baseline user**, one right after the other. The baseline users are the twelve of the Okta profile (`noura.alharbi`, `khalid.alotaibi`, `abdullah.alzahrani`, `sara.almutairi`, `faisal.alqahtani`, `reem.aldosari`, `omar.alshehri`, `huda.alghamdi`, `yousef.alharthi`, `layla.almalki`, `tariq.alsubaie`, `dana.alanazi`); pick one with **no `Multiple Okta MFA requests ...` alert in the last 24 hours**.

1. The failed logins, then a success (29 failures and one success from one real out-of-country address):

```json
{"profile": "okta", "scenario": "failed_then_success", "destination": "okta_sso", "count": 30, "spread_seconds": 900, "target_user": "<CHANGE: baseline login, bare name, e.g. reem.aldosari>"}
```

2. The push flood (12 pushes, 12 denials and one approval, from another real out-of-country address):

```json
{"profile": "okta", "scenario": "mfa_fatigue", "destination": "okta_sso", "count": 25, "spread_seconds": 600, "target_user": "<CHANGE: the same login>"}
```

Both windows end at the moment of the call, so the 29 failures start 15 minutes earlier and the flood 10 minutes earlier: that is what puts the failed logins **before** the flood inside the 30-minute test window. Do not pass `source_ip` (the scenarios choose an address abroad themselves) and do not use `okta_okta` as the destination.

Expect an alert like: *"The user phantom-lab\<user> received a total of 12 MFA authentication requests during the alert period. Additionally, there were 0 successful and 29 failed logon attempts. The user rejected 12 requests. The user attempted to log in from a new country at least once. A user attempted to log in from a rare country for the organization. This authentication attempt was flagged as suspicious due to these characteristics"*. The alert's address is the one the failed logins came from.

Check as in Step 3 below (the alert source shows as `XDR_ANALYTICS`; match the name client-side). Step 2's landing check applies too: `dataset = okta_sso_raw | filter actor ~= "<login>" | comp count() by eventtype` should show 30 `user.session.start`, 12 `system.push.send_factor_verify_push`, 12 `user.mfa.okta_verify.deny_push` and 1 `user.authentication.auth_via_mfa`.

Route A (the hand-built Tor route) starts here.

## Preconditions: check these BEFORE sending

| # | Must be true | How to check |
|---|---|---|
| 1 | `http-sender` is running with a destination **`okta_sso`** (`ready: true`); the detector reads `okta_sso_raw` | `http-sender.list_destinations` |
| 2 | You have **today's live Tor exit list** (`https://check.torproject.org/torbulkexitlist`, plain text) via the `web` connector (`navigate`, then `get_text` with `mode: "body"`) or the operator, and pick **one exit in a country the organization has not seen** | (a) the organization's countries by label: `config timeframe = 30d \| datamodel dataset = okta_sso_raw \| filter xdm.event.type = "authentication" \| comp count() by xdm.source.location.country`; (b) the exit's real country, which Cortex resolves itself and which can differ from a label: `dataset = okta_sso_raw \| limit 1 \| alter ips = arraycreate("<exit>") \| arrayexpand ips \| iploc ips \| fields ips, loc_country`. Both must be absent or tiny in (a) |
| 3 | The user is a **baseline user** (an account with ordinary history on `okta_sso_raw`), and you know the Okta `actor.id` they carry **now**. Take the id of the **newest** event, never an arbitrary one | `dataset = okta_sso_raw \| filter actor ~= "<login>" \| sort desc _insert_time \| limit 1 \| fields _insert_time, actor` |
| 4 | No `Multiple Okta MFA requests ...` alert for that user in 24 h | Step 4 without the time filter |
| 5 | You will send **the failed login first, then the flood**, in **one `send_events` call**, ascending `published`, the failure about 3-4 minutes before the first push and the last event at **now** | Step 1 |
| 6 | Every event uses **the same IP** (the exit), the same user and, inside the flood, the same `externalSessionId` | Step 1 |

## Expected result (Route A)

With a **failed login for the same user shortly before the flood**, from a live Tor exit in a country the organization has never seen, a flood of 11 to 20 pushes and rejections fires the alert (for example "20 requests ... 1 successful and 1 failed logon", "11 requests ... 0 successful and 1 failed"), typically about 6 minutes after the last event.

Does **not** fire: a flood with no failed login in the previous 30 minutes (US and German Tor exits, a Thai non-Tor address, and Luxembourg and Romania Tor exits), or the same flood after only a **successful** SSO login about 29 minutes earlier.

The user agent does not matter: a mobile "Okta Mobile" agent, `HashiCorp Terraform` on the failure with `Nmap Scripting Engine` in the flood, and an iPhone agent on the failure with an Android agent in the flood all work.

## Step 1: send the failure and then the flood (one call)

Call **`http-sender.send_events`** with `destination: "okta_sso"`. The `events` array is **1 failed SSO event, 1 verify event, then N pairs of (push sent, push rejected)**, N between **11 and 20** (11, 19 and 20 are verified; fewer are untried).

**Timing rule** (all `published` values ascending, UTC, millisecond ISO with `Z`, nothing in the future):

- failed SSO login: **now minus 4 minutes**;
- verify: **now minus 60 seconds**;
- then push, rejection, push, rejection ... each event 0.5-4 seconds after the previous one, the **last event at now**.

**Identity rule**: every event carries the **same user, the same `client.ipAddress` and the same `request.ipChain[0].ip` (the live Tor exit)**, the same country label and the same `securityContext`. Inside the flood (verify, pushes, rejections)
the user agent is also the same and the `externalSessionId` is the same; the failed login has its own `externalSessionId` and may use a different user agent (for example `HashiCorp Terraform/1.6.0` on the failure and `Nmap Scripting Engine` in the flood).
`securityContext` is `{"asNumber": <any integer>, "asOrg": "<ISP>", "domain": "torproject.org", "isProxy": true, "isp": "<same ISP>"}` in every event. Use a new `transaction.id` and new `requestId`/`dtHash`/`deviceFingerprint` per event.

The four event templates below were built from events that fire. Replace every `<CHANGE: ...>` and nothing else. **Event 1, the failed login:**

```json
{
  "uuid": "<CHANGE: new UUID v4>",
  "published": "<CHANGE: ISO ms Z timestamp, see the timing rule>",
  "eventType": "user.authentication.sso",
  "legacyEventType": "app.auth.sso",
  "version": "0",
  "severity": "WARN",
  "displayMessage": "SSO authentication to <CHANGE: the same app> failed",
  "actor": {"id": "<CHANGE: the user's existing actor.id>", "type": "User", "alternateId": "<CHANGE: the user's login>", "displayName": "<CHANGE: display name>", "detailEntry": null},
  "client": {"id": null, "device": "Computer", "userAgent": {"rawUserAgent": "<CHANGE: a user-agent string, e.g. HashiCorp Terraform/1.6.0>", "os": "Unknown", "browser": "UNKNOWN"}, "ipAddress": "<CHANGE: the live Tor exit>", "geographicalContext": {"city": null, "state": null, "country": "<CHANGE: country name>", "postalCode": null, "geolocation": {"lat": "<CHANGE: any>", "lon": "<CHANGE: any>"}}, "zone": "null"},
  "outcome": {"result": "FAILURE", "reason": "INVALID_CREDENTIALS"},
  "target": [{"id": "<CHANGE: '0oa' + 17 chars>", "type": "AppInstance", "displayName": "<CHANGE: an app the user normally uses>", "alternateId": "<CHANGE: same app>", "detailEntry": {"signOnModeType": "SAML_2_0"}}, {"id": "<CHANGE: '0ua' + 17 hex>", "type": "AppUser", "displayName": "<CHANGE: display name>", "alternateId": "<CHANGE: the user's login>", "detailEntry": null}],
  "device": {"id": "<CHANGE: 'guo' + 19 hex>", "name": "Unknown Device", "os_platform": "UNKNOWN", "os_version": "Unknown", "managed": true, "registered": true, "status": "ACTIVE", "screenLockType": "PASSCODE"},
  "request": {"ipChain": [{"ip": "<CHANGE: the live Tor exit>", "geographicalContext": {"city": null, "state": null, "country": "<CHANGE: country name>", "postalCode": null, "geolocation": {"lat": "<CHANGE: any>", "lon": "<CHANGE: any>"}}, "version": "V4", "source": null}]},
  "transaction": {"type": "WEB", "id": "<CHANGE: new 32 hex>", "detail": {}},
  "authenticationContext": {"authenticationProvider": null, "credentialProvider": null, "credentialType": null, "externalSessionId": "<CHANGE: ext-session-<uuid>; shared by verify, pushes and rejections, different for the failed login>", "authnContextClassRef": null, "issuer": null, "interface": null, "authenticationStep": 0},
  "securityContext": {"asNumber": "<CHANGE: any integer AS number>", "asOrg": "<CHANGE: ISP name>", "domain": "torproject.org", "isProxy": true, "isp": "<CHANGE: ISP name>"},
  "debugContext": {"debugData": {"requestId": "<CHANGE: new random hex, 32>", "dtHash": "<CHANGE: new random hex, 64>", "deviceFingerprint": "<CHANGE: new random hex, 32>", "requestUri": "/app/salesforce/sso/saml", "url": "/app/salesforce/sso/saml", "threatSuspected": "true", "risk": "{level=HIGH}", "authnRequestId": "<CHANGE: new random hex, 32>"}}
}
```

**Event 2, the verify** (one):

```json
{
  "uuid": "<CHANGE: new UUID v4>",
  "published": "<CHANGE: ISO ms Z timestamp, see the timing rule>",
  "eventType": "user.authentication.verify",
  "legacyEventType": null,
  "version": "0",
  "severity": "INFO",
  "displayMessage": "Verify user identity",
  "actor": {"id": "<CHANGE: the user's existing actor.id>", "type": "User", "alternateId": "<CHANGE: the user's login>", "displayName": "<CHANGE: display name>", "detailEntry": null},
  "client": {"id": null, "device": "Computer", "userAgent": {"rawUserAgent": "<CHANGE: one user-agent string per flood, e.g. Nmap Scripting Engine>", "os": "Unknown", "browser": "UNKNOWN"}, "ipAddress": "<CHANGE: the live Tor exit>", "geographicalContext": {"city": null, "state": null, "country": "<CHANGE: country name>", "postalCode": null, "geolocation": {"lat": "<CHANGE: any>", "lon": "<CHANGE: any>"}}, "zone": "null"},
  "outcome": {"result": "SUCCESS", "reason": null},
  "target": [],
  "device": {"id": "<CHANGE: 'guo' + 19 hex>", "name": "Unknown Device", "os_platform": "UNKNOWN", "os_version": "Unknown", "managed": true, "registered": true, "status": "ACTIVE", "screenLockType": "PASSCODE"},
  "request": {"ipChain": [{"ip": "<CHANGE: the live Tor exit>", "geographicalContext": {"city": null, "state": null, "country": "<CHANGE: country name>", "postalCode": null, "geolocation": {"lat": "<CHANGE: any>", "lon": "<CHANGE: any>"}}, "version": "V4", "source": null}]},
  "transaction": {"type": "WEB", "id": "<CHANGE: new 32 hex>", "detail": {}},
  "authenticationContext": {"authenticationProvider": "FACTOR_PROVIDER", "credentialProvider": "OKTA_CREDENTIAL_PROVIDER", "credentialType": "OIE_OKTA_VERIFY_PUSH", "externalSessionId": "<CHANGE: ext-session-<uuid>; shared by verify, pushes and rejections, different for the failed login>", "authnContextClassRef": "urn:oasis:names:tc:SAML:2.0:ac:classes:TimeSyncToken", "issuer": null, "interface": null, "authenticationStep": 0},
  "securityContext": {"asNumber": "<CHANGE: any integer AS number>", "asOrg": "<CHANGE: ISP name>", "domain": "torproject.org", "isProxy": true, "isp": "<CHANGE: ISP name>"},
  "debugContext": {"debugData": {"requestId": "<CHANGE: new random hex, 32>", "dtHash": "<CHANGE: new random hex, 64>", "deviceFingerprint": "<CHANGE: new random hex, 32>", "requestUri": "/oauth2/v1/userinfo", "url": "/oauth2/v1/userinfo?"}}
}
```

**Event 3, push sent** (repeat N times):

```json
{
  "uuid": "<CHANGE: new UUID v4>",
  "published": "<CHANGE: ISO ms Z timestamp, see the timing rule>",
  "eventType": "system.push.send_factor_verify_push",
  "legacyEventType": null,
  "version": "0",
  "severity": "INFO",
  "displayMessage": "MFA push challenge sent",
  "actor": {"id": "<CHANGE: the user's existing actor.id>", "type": "User", "alternateId": "<CHANGE: the user's login>", "displayName": "<CHANGE: display name>", "detailEntry": null},
  "client": {"id": null, "device": "Computer", "userAgent": {"rawUserAgent": "<CHANGE: one user-agent string per flood, e.g. Nmap Scripting Engine>", "os": "Unknown", "browser": "UNKNOWN"}, "ipAddress": "<CHANGE: the live Tor exit>", "geographicalContext": {"city": null, "state": null, "country": "<CHANGE: country name>", "postalCode": null, "geolocation": {"lat": "<CHANGE: any>", "lon": "<CHANGE: any>"}}, "zone": "null"},
  "outcome": {"result": "SUCCESS", "reason": null},
  "target": [],
  "device": null,
  "request": {"ipChain": [{"ip": "<CHANGE: the live Tor exit>", "geographicalContext": {"city": null, "state": null, "country": "<CHANGE: country name>", "postalCode": null, "geolocation": {"lat": "<CHANGE: any>", "lon": "<CHANGE: any>"}}, "version": "V4", "source": null}]},
  "transaction": {"type": "WEB", "id": "<CHANGE: new 32 hex>", "detail": {}},
  "authenticationContext": {"authenticationProvider": "FACTOR_PROVIDER", "credentialProvider": "OKTA_CREDENTIAL_PROVIDER", "credentialType": "OIE_OKTA_VERIFY_PUSH", "externalSessionId": "<CHANGE: ext-session-<uuid>; shared by verify, pushes and rejections, different for the failed login>", "authnContextClassRef": "urn:oasis:names:tc:SAML:2.0:ac:classes:TimeSyncToken", "issuer": null, "interface": null, "authenticationStep": 0},
  "securityContext": {"asNumber": "<CHANGE: any integer AS number>", "asOrg": "<CHANGE: ISP name>", "domain": "torproject.org", "isProxy": true, "isp": "<CHANGE: ISP name>"},
  "debugContext": {"debugData": {"requestId": "<CHANGE: new random hex, 32>", "dtHash": "<CHANGE: new random hex, 64>", "deviceFingerprint": "<CHANGE: new random hex, 32>", "requestUri": "/app/servicenow/sso/saml", "url": "/app/servicenow/sso/saml"}}
}
```

**Event 4, push rejected** (repeat N times, each right after its push):

```json
{
  "uuid": "<CHANGE: new UUID v4>",
  "published": "<CHANGE: ISO ms Z timestamp, see the timing rule>",
  "eventType": "user.mfa.okta_verify.deny_push",
  "legacyEventType": null,
  "version": "0",
  "severity": "WARN",
  "displayMessage": "User rejected Okta Verify push notification",
  "actor": {"id": "<CHANGE: the user's existing actor.id>", "type": "User", "alternateId": "<CHANGE: the user's login>", "displayName": "<CHANGE: display name>", "detailEntry": null},
  "client": {"id": null, "device": "Computer", "userAgent": {"rawUserAgent": "<CHANGE: one user-agent string per flood, e.g. Nmap Scripting Engine>", "os": "Unknown", "browser": "UNKNOWN"}, "ipAddress": "<CHANGE: the live Tor exit>", "geographicalContext": {"city": null, "state": null, "country": "<CHANGE: country name>", "postalCode": null, "geolocation": {"lat": "<CHANGE: any>", "lon": "<CHANGE: any>"}}, "zone": "null"},
  "outcome": {"result": "FAILURE", "reason": "USER_REJECTED_OKTA_VERIFY_PUSH"},
  "target": [],
  "device": null,
  "request": {"ipChain": [{"ip": "<CHANGE: the live Tor exit>", "geographicalContext": {"city": null, "state": null, "country": "<CHANGE: country name>", "postalCode": null, "geolocation": {"lat": "<CHANGE: any>", "lon": "<CHANGE: any>"}}, "version": "V4", "source": null}]},
  "transaction": {"type": "WEB", "id": "<CHANGE: new 32 hex>", "detail": {}},
  "authenticationContext": {"authenticationProvider": "FACTOR_PROVIDER", "credentialProvider": "OKTA_CREDENTIAL_PROVIDER", "credentialType": "OIE_OKTA_VERIFY_PUSH", "externalSessionId": "<CHANGE: ext-session-<uuid>; shared by verify, pushes and rejections, different for the failed login>", "authnContextClassRef": "urn:oasis:names:tc:SAML:2.0:ac:classes:TimeSyncToken", "issuer": null, "interface": null, "authenticationStep": 0},
  "securityContext": {"asNumber": "<CHANGE: any integer AS number>", "asOrg": "<CHANGE: ISP name>", "domain": "torproject.org", "isProxy": true, "isp": "<CHANGE: ISP name>"},
  "debugContext": {"debugData": {"requestId": "<CHANGE: new random hex, 32>", "dtHash": "<CHANGE: new random hex, 64>", "deviceFingerprint": "<CHANGE: new random hex, 32>", "requestUri": "/idp/idx/identify", "url": "/idp/idx/identify?", "factor": "OKTA_VERIFY_PUSH", "risk": "{level=HIGH}"}}
}
```

Why each part is there:

- **The failed login (event 1)** supplies "1 failed logon attempt" and the suspicious source; it is the ingredient silent floods lack.
- **`user.authentication.verify`, then pairs of `system.push.send_factor_verify_push` + `user.mfa.okta_verify.deny_push`** is Okta's own record of a user being prompted and refusing: the base detector counts prompts and rejections in the 30-minute window.
- **One shared `externalSessionId` across the verify, pushes and rejections** ties the flood into one authentication conversation, as Okta does.
- **`credentialType OIE_OKTA_VERIFY_PUSH`, `factor OKTA_VERIFY_PUSH`, reason `USER_REJECTED_OKTA_VERIFY_PUSH`**: the exact strings Okta uses; do not paraphrase them.
- **The same live Tor exit in every event**: the engine recognizes the address from its own Tor feed; the country and ASN labels in the events are not what it reports (a label of Singapore can come back from Cortex as France).
- **Time**: the whole sequence is 4-5 minutes long and ends at now; the detector's window is 30 minutes.
- **The `request.ipChain` block** is present in every event: keep it.

## Step 2: confirm the events landed (about 5 minutes after Step 1)

```
config timeframe = 1h | dataset = okta_sso_raw
| filter actor ~= "<login>"
| comp count() as n by eventtype, outcome
```

Pass when you see 1 `user.authentication.sso` FAILURE row, 1 `user.authentication.verify`, and N each of `system.push.send_factor_verify_push` and `user.mfa.okta_verify.deny_push`.

## Step 3: wait, then check for the alert

**Wait 6 minutes before the first check** (the alert typically arrives about 6 minutes after the last event). Then check every 2 minutes, up to **20 minutes**:

```
dataset = alerts
| filter alert_name ~= "Multiple Okta MFA requests"
| fields _time, alert_id, alert_name, user_name, host_ip, description
| sort desc _time
| limit 10
```

Pass when a new row names your user. The description gives the number of requests and rejections and says "from a rare country for the organization".

If nothing arrives in 20 minutes: re-run Step 2 (all event types present, one IP, one session), check the failure was **inside the same 30 minutes** and from a **live** Tor exit in a **never-seen country**, then retry once with **another user and another exit**. Do not drop the failed login.

## Report back to the operator

State the user, exit IP and country, the number of pushes, the Step 2 counts and either the alert id with its arrival time or what you checked. Say the user is deduplicated for 24 hours.
