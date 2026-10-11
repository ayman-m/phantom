---
name: trigger_okta_first_sso_access_alert
displayName: Trigger the Cortex "Abnormal first access to a resource via SSO in the organization" analytics alert
category: workflows
description: 'Fire Cortex XSIAM''s native "Abnormal first access to a resource via SSO in the organization" analytics BIOC (T1078.002) by sending a successful synthetic Okta SSO event (user.authentication.sso) through the http-sender connector to the okta_sso collector: a known user reaches a SaaS app that nobody in the organization has opened for 30 days, from a LIVE Tor exit node, with a desktop or scripted (not mobile) user agent. Use when the operator asks to trigger, demo, prove or reproduce an Okta or SSO "first access", "new application", "Tor sign-in" or "suspicious SSO from Tor" alert. Needs a never-used app name, a current Tor exit and a baseline user; the same shape from the user''s own home IP does NOT show an alert.'
icon: lan
source: platform
loadingMode: on-demand
locked: false
---

# Skill: Trigger the "Abnormal first access to a resource via SSO in the organization" alert

## When this skill applies

The operator wants the **native Cortex Analytics identity (SSO) detector** for a *first-ever access to an application from a suspicious address* to fire, for example:
*"trigger an SSO anomaly from Tor"*, *"show a user opening an app nobody uses, from a Tor exit"*, *"prove T1078.002 fires from Okta logs"*.

It is reproducible on demand for the baseline users. It is not a correlation rule.

> **Note.** An agent following this skill authors several ~2 KB events itself; send two or three per attempt (see Step 1).

## What the detector looks for (Cortex doc: "First SSO Resource Access in the Organization")

| Property | Value |
|---|---|
| Alert name | `Abnormal first access to a resource via SSO in the organization` (Low). The base detector `First SSO Resource Access in the Organization` is **Informational** and is invisible in the Issues view; the Low variant appears when the access looks suspicious (here: a Tor exit) |
| Source | `XDR Analytics BIOC`, MITRE T1078.002 Valid Accounts: Domain Accounts |
| Required data | an SSO source: Okta (the doc lists AzureAD, Duo, Okta, OneLogin, PingOne ...) |
| Test period | single event; looks back **30 days across the whole organization** |
| Deduplication | **1 day** (per user and application: one user can get two alerts in the same minute for two apps) |
| What the alert text says | *"The user phantom-lab\<login> accessed the resource <app> via SSO ... This resource has not been observed for the past 30 days. The IP address is routed through a known tunnel operator: TOR_PROXY. The following risk factors have been identified for this IP: ['TUNNEL'] ... The user authentication attempt was made from the country <country>, which has not been seen in the organization over the past 30 days ... the ASN ... has not been seen ...."* |

## What makes it fire: four conditions

1. **A successful SSO** (`user.authentication.sso`, `outcome.result SUCCESS`) to an **application the organization has not opened via SSO for 30 days**. The novelty is *organization-wide and one-time*: once an
   app has appeared in any SSO event, it is "seen" for 30 days.
2. **From a LIVE Tor exit node.** The engine looks the address up in its own Tor feed (the alert text says "known tunnel operator: TOR_PROXY"; the other risk flags it adds, `CALLBACK_PROXY`, `GEO_MISMATCH`, `LOGIN_BRUTEFORCE`, vary). A static "Tor" address that has left the live list does not reliably alert. Fetch today's list every time and use **one address per event**.
3. **A desktop or scripted client, not a phone.** **Mobile user agents (iPhone, Android, Okta Mobile) do not fire; desktop or scripted agents do** (with an occasional unexplained miss, see below).
   Desktop browsers (Windows/macOS), `python-requests`, `PostmanRuntime`, Nmap scripting, AWS scanner, Boto3 and Terraform agents fire. Every mobile agent also carries `client.device: "Mobile"`, so **user agent and device class are
   confounded: use a desktop agent and `client.device: "Computer"` together.**
4. **A known user.** Use a baseline account (`<name>@phantom-lab.example`, with about 10 workdays of ordinary logins on `okta_sso_raw`). A never-seen account is not covered by this recipe.

Does **not** fire: the same kind of event for a baseline user and a never-used app **from the user's own Saudi home IP** raises no alert. That variant also drops `isProxy`, `proxyType`, `threatSuspected` and uses `risk MEDIUM`, so "the address" and "the Tor decorations" are **not separated**; send them together. The base detector for this case is Informational and would not show in the Issues view anyway.

## Preconditions: check these BEFORE sending

| # | Must be true | How to check |
|---|---|---|
| 1 | `http-sender` is running with a destination **`okta_sso`** (`ready: true`). The detector reads `okta_sso_raw`; do not send to `okta_okta` | `http-sender.list_destinations` |
| 2 | You have **today's live Tor exit list**: GET `https://check.torproject.org/torbulkexitlist` (plain text, one IPv4 per line, about 1,400 lines) with the `web` connector (`navigate`, then `get_text` with `mode: "body"` so the plain list is not run through the readability filter) or ask the operator. Pick **one address per event**, never one used in the last 24 h, outside the user's own country | the list |
| 3 | The **app name is new**: never opened via SSO in the org in 30 days | `config timeframe = 30d \| datamodel dataset = okta_sso_raw \| filter xdm.event.original_event_type = "user.authentication.sso" and xdm.target.resource.name = "<name>" \| comp count()` must be 0 |
| 4 | The **user is a baseline user** and you know the Okta `actor.id` they carry **now**: take the id of the **newest** event, never an arbitrary one | `dataset = okta_sso_raw \| filter actor ~= "<login>" \| sort desc _insert_time \| limit 1 \| fields _insert_time, actor` and copy `actor.id` from that row |
| 5 | The user agent is **desktop or scripted** and `client.device` is `Computer`, never a phone | Step 1 below |
| 6 | No alert of this name already exists for that user and app in 24 h | Step 3 query without the time filter |
| 7 | `published` is **now** (UTC, ms, trailing `Z`), never in the future | generate it at call time |

## Expected result

A successful SSO of a baseline user to a never-used app from a live Tor exit, with a desktop or scripted user agent, raises the alert; it typically arrives within one to a few minutes of the event. Not every qualifying event fires: mobile user agents never do, an app name that was already seen does not, and a desktop agent can still miss for no known reason, so **send two or three events per attempt, not one.** The same event without Tor, from the user's home IP, raises no alert.

Not established: whether a different `actor.id` than the user's usual one matters; whether an unknown user fires; whether a `phantom-lab` user is needed or any domain will do.

## Step 1: send the event(s) (exactly this shape)

Call **`http-sender.send_events`** with `destination: "okta_sso"` and an `events` array. Send **2 or 3 events for 2 or 3 different users**, each with its own new app and its own Tor exit,
published a few seconds apart in ascending order. One event looks like this; replace the values marked `<CHANGE>`.

```json
{
  "uuid": "<CHANGE: a new UUID v4>",
  "published": "<CHANGE: now, UTC with milliseconds and a trailing Z>",
  "eventType": "user.authentication.sso",
  "legacyEventType": "app.auth.sso",
  "version": "0",
  "severity": "WARN",
  "displayMessage": "Successful SSO from TOR exit node to <CHANGE: the app name>",
  "actor": {
    "id": "<CHANGE: the user's existing actor.id from precondition 4>",
    "type": "User",
    "alternateId": "<CHANGE: the baseline user's login, e.g. layla.almalki@phantom-lab.example>",
    "displayName": "<CHANGE: e.g. Layla Almalki>",
    "detailEntry": null
  },
  "client": {
    "id": null,
    "device": "Computer",
    "userAgent": {"rawUserAgent": "<CHANGE: a desktop or scripted agent, e.g. python-requests/2.31.0 or a Windows Chrome string>", "os": "Unknown", "browser": "UNKNOWN"},
    "ipAddress": "<CHANGE: ONE live Tor exit from today's list>",
    "geographicalContext": {"city": null, "state": null, "country": "<CHANGE: any country name>", "postalCode": null, "geolocation": {"lat": -4.5833, "lon": 55.6667}},
    "zone": "null"
  },
  "outcome": {"result": "SUCCESS", "reason": null},
  "target": [
    {"id": "<CHANGE: '0oa' + 17 random letters/digits>", "type": "AppInstance", "displayName": "<CHANGE: the new app name>", "alternateId": "<CHANGE: the same app name>", "detailEntry": {"signOnModeType": "SAML_2_0"}},
    {"id": "<CHANGE: '0ua' + 17 hex characters>", "type": "AppUser", "displayName": "<CHANGE: the user's display name>", "alternateId": "<CHANGE: the user's login>", "detailEntry": null}
  ],
  "device": {"id": "<CHANGE: 'guo' + 19 hex characters>", "name": "Unknown Device", "os_platform": "UNKNOWN", "os_version": "Unknown", "managed": true, "registered": true, "status": "ACTIVE", "screenLockType": "PASSCODE"},
  "request": {"ipChain": [{"ip": "<CHANGE: the same Tor exit>", "geographicalContext": {"city": null, "state": null, "country": "<CHANGE: same country name>", "postalCode": null, "geolocation": {"lat": -4.5833, "lon": 55.6667}}, "version": "V4", "source": null}]},
  "transaction": {"type": "WEB", "id": "<CHANGE: 32 random hex characters>", "detail": {}},
  "authenticationContext": {
    "authenticationProvider": "OKTA_AUTHENTICATION_PROVIDER",
    "credentialProvider": "OKTA_CREDENTIAL_PROVIDER",
    "credentialType": "PASSWORD",
    "externalSessionId": "<CHANGE: 'ext-session-' + a new UUID>",
    "authnContextClassRef": "urn:oasis:names:tc:SAML:2.0:ac:classes:Password",
    "issuer": null, "interface": null, "authenticationStep": 0
  },
  "securityContext": {"asNumber": "<CHANGE: any integer AS number>", "asOrg": "<CHANGE: any ISP name>", "domain": "torproject.org", "isProxy": true, "isp": "<CHANGE: same ISP name>"},
  "debugContext": {
    "debugData": {
      "requestId": "<CHANGE: 32 random hex characters>",
      "dtHash": "<CHANGE: 64 random hex characters>",
      "deviceFingerprint": "<CHANGE: 32 random hex characters>",
      "requestUri": "/oauth2/v1/authorize",
      "url": "/oauth2/v1/authorize?",
      "proxyType": "TOR",
      "threatDetections": "{\"TOR Exit Node\": \"HIGH\"}",
      "threatSuspected": "true",
      "risk": "{level=HIGH}",
      "authnRequestId": "<CHANGE: 32 random hex characters>"
    }
  }
}
```

Why each value is what it is:

- **`eventType` `user.authentication.sso` with `outcome.result SUCCESS`**: the event type the SSO detectors read (the Okta rule maps it to `xdm.event.type = authentication`; the doc names it as the one event that must be collected).
- **`target[0]` is the `AppInstance`** (the modeling rule reads only the first target for the resource name, `xdm.target.resource.name`); the `AppUser` target second.
- **`ipAddress` / `ipChain[0].ip`: the same live Tor exit.** The engine resolves the address itself and named it a Tor proxy in the alert text. `proxyType: TOR`, `threatDetections` and `isProxy: true` are the Okta-side markers; whether the engine needs them or only the address was not isolated, so send all of them.
- **`threatSuspected` the string `"true"`, `risk {level=HIGH}`**: keep them as written; the doc does not say whether they are required, so keep them.
- **The user agent and `client.device`**: desktop or scripted agents with device `Computer` fire; mobile agents (device `Mobile`) do not. Never use an iPhone, Android or "Okta Mobile" agent for this recipe.
- **`actor.id`**: reuse the user's existing id (precondition 4) so the account stays one identity; the engine names the user `phantom-lab\<local part>` from the login.
- **Free to change**: every id, hash, `uuid`, `published`, the geography and AS labels. Not free: eventType, outcome, the `AppInstance`-first target order, the Tor address, the client class (desktop/scripted, device Computer).

## Step 2: confirm it landed and modeled (about 5 minutes after Step 1)

```
dataset = okta_sso_raw
| filter uuid = "<your uuid>"
| fields _time, eventtype, outcome, actor, client
```

Pass when your rows return. Then confirm the app is now "seen" (it will not fire a second time): the precondition 3 query returns 1.

## Step 3: wait, then check for the alerts

Check **1 minute** after sending, then every minute for up to **10 minutes** (arrivals take from about a minute up to a few minutes):

```
dataset = alerts
| filter alert_name = "Abnormal first access to a resource via SSO in the organization"
| fields _time, alert_id, alert_name, user_name, host_ip, description
| sort desc _time
| limit 20
```

Pass when new rows name your users; the description names your **app**, your **IP**, `TOR_PROXY` and the country. Match them by app name, not just by time.

If an event is missing from the results after 10 minutes: it is usually a mobile agent or a name that was already seen. Check the agent and precondition 3, pick **another new app and another exit**, and resend that one event. Do not change the structure.

## Report back to the operator

For each event: user, app, exit IP, agent class, and either the alert id and arrival time or "no alert". State how many of N fired. Say that each app is now used up for 30 days and each user/app pair for 24 hours.
