---
name: trigger_okta_fastpass_phishing_alert
displayName: Trigger the Cortex "Okta FastPass reported phishing attack suspected" analytics alert
category: workflows
description: 'Fire Cortex XSIAM''s native "Okta FastPass reported phishing attack suspected" analytics BIOC (T1566) by sending ONE synthetic Okta System Log event through the http-sender connector to the okta_sso collector: a user.authentication.auth_via_mfa FAILURE whose reason is "FastPass declined phishing attempt" with threatSuspected true. Use when the operator asks to trigger, demo, prove or reproduce an Okta phishing, FastPass or MFA-phishing-resistance alert. The event goes to an okta_sso destination ONLY (the okta_okta twin never fires): the Cribl destination cribl_okta_sso (Route C, the okta fastpass_phishing profile scenario, one call) or the generic okta_sso HTTP collector destination; use a fresh user and a fresh IP for every attempt. It must go through http-sender: the same event sent as syslog/CEF landed and modeled identically but raised no alert.'
icon: phishing
source: platform
loadingMode: on-demand
locked: false
---

# Skill: Trigger the "Okta FastPass reported phishing attack suspected" alert

## When this skill applies

The operator wants the **native Cortex Analytics Okta FastPass detector** to fire, for example:
*"trigger an Okta phishing alert"*, *"show FastPass blocking a phishing site"*, *"prove T1566 fires from Okta logs"*.

It is the most reliable Okta detector: it fires from any fresh user and fresh IP. It needs **no baseline, no history,
no known user and no real Tor address**. It is not a correlation rule; nothing needs installing on the tenant beyond the Okta pack that already models `okta_sso_raw`.

> **Expected result.** The alert typically arrives within one to three minutes of the event.
>
> **It must go through http-sender (the Cribl destination `cribl_okta_sso` or the generic `okta_sso` HTTP collector destination).** The same event body sent as syslog/CEF into the same dataset `okta_sso_raw` (spec-escaped, naive, or with the header spelled like the HTTP stamp) lands with the same columns, the same parsing result and the same 58 `xdm.*` fields, and **raises no alert**, while the HTTP copy alerts within about a minute. Whether the gate is the collector-type stamp or the collector being a registered Okta source is not established. So never test this detector over syslog.

## What the detector looks for (Cortex doc: "Okta FastPass reported phishing attack suspected")

| Property | Value |
|---|---|
| Alert name | `Okta FastPass reported phishing attack suspected` (Low). A variant "... from a suspicious IP" (Medium) exists; it does **not** appear for Tor or ordinary public addresses |
| Source | `XDR Analytics BIOC`, MITRE T1566 Phishing |
| Required data (doc) | the doc page lists PAN firewall EAL/threat logs; that is a documentation tag error: the alert fires on Okta events alone |
| Test period | single event |
| Deduplication | **1 day**. Use a fresh user and a fresh IP on every attempt |
| What the alert text says | *"Okta has reported a potential phishing attack on the organization. The user ... was denied access due to suspected phishing. The user authenticated from <ip>, which is located in <country>. ... the country <cc> has not been seen in the organization over the past 30 days ... the ASN <n> has not been seen ..."* |

## Preconditions: check these BEFORE sending

| # | Must be true | How to check |
|---|---|---|
| 1 | The `http-sender` connector is running and has a destination **`okta_sso`** (collector vendor Okta / product SSO, dataset `okta_sso_raw`) with `ready: true` | `http-sender.list_destinations` |
| 2 | You will send to **`okta_sso`**, not `okta_okta`. In a clean pair (identical desktop body, a fresh user and a fresh live Tor exit each) the `okta_sso` copy fires and the `okta_okta` copy, which lands and models in `okta_okta_raw` (outcome FAILED, risk flags populated), stays silent | the `destination` argument below |
| 3 | The user is **new**: a never-before-used login `fastpass.phishing.<run id>@examplecorp.com` | no row in `dataset = okta_sso_raw` for that login |
| 4 | The IP is **new**: a public address not used by an earlier FastPass attempt in the last 24 h. A live Tor exit works, and so does an ordinary public address or a Telegram-network address that is not a Tor exit. Keep the country label equal to the address's real country; a mismatch is untested | your own ledger of earlier attempts |
| 5 | `published` is **now** (UTC, millisecond ISO, trailing `Z`), never in the future | generate it at call time |
| 6 | The event is sent through the **HTTP collector** (`http-sender.send_events`), never as syslog/CEF. The identical event over CEF does not fire (see the note above) | the tool you call |

## Expected result

One event to collector `okta_sso`, with a **different user and a different IP each time**, fires the alert, typically within one to three minutes. A live Tor exit works, and so does an ordinary public address and a Telegram-network address that is not a Tor exit. A Mobile `client.device` (Android) fires as well, so FastPass is **not** sensitive to the phone-versus-desktop split the first-access skill is.

Did **not** fire: the same event body sent as syslog/CEF into `okta_sso_raw`, and the same body sent to collector `okta_okta` (dataset `okta_okta_raw`), which lands and models there but stays silent, including a Mobile-device variant.

**Not tested**: a baseline user of the `phantom.lab` domain as the actor, a repeat of the same user or IP inside 24 h, any other `eventType`, and a country label that differs from the address.

## Step 1: send the event (exactly this call)

Call **`http-sender.send_events`** with `destination: "okta_sso"` and a one-element `events` array. Replace only the values marked `<CHANGE>`; everything else is
the verbatim shape that fires.

```json
{
  "destination": "okta_sso",
  "events": [
    {
      "uuid": "<CHANGE: a new UUID v4>",
      "published": "<CHANGE: now, e.g. 2026-10-02T03:33:13.106Z>",
      "eventType": "user.authentication.auth_via_mfa",
      "legacyEventType": "core.user.factor.attempt_success",
      "version": "0",
      "severity": "WARN",
      "displayMessage": "FastPass declined phishing attempt",
      "actor": {
        "id": "<CHANGE: '00u' + 17 random letters/digits>",
        "type": "User",
        "alternateId": "<CHANGE: fastpass.phishing.<run id>@examplecorp.com>",
        "displayName": "<CHANGE: e.g. Fastpass Phishing P1>",
        "detailEntry": null
      },
      "client": {
        "id": null,
        "device": "Computer",
        "userAgent": {
          "rawUserAgent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36 Edg/121.0.0.0",
          "os": "Unknown",
          "browser": "UNKNOWN"
        },
        "ipAddress": "<CHANGE: the new public IP>",
        "geographicalContext": {
          "city": null, "state": null, "country": "<CHANGE: any plausible country name>", "postalCode": null,
          "geolocation": {"lat": 48.8001, "lon": 17.013}
        },
        "zone": "null"
      },
      "outcome": {"result": "FAILURE", "reason": "FastPass declined phishing attempt"},
      "target": [],
      "device": {
        "id": "<CHANGE: 'guo' + 19 hex characters>",
        "name": "Unknown Device", "os_platform": "UNKNOWN", "os_version": "Unknown",
        "managed": true, "registered": true, "status": "ACTIVE", "screenLockType": "PASSCODE"
      },
      "request": {
        "ipChain": [
          {
            "ip": "<CHANGE: the same new public IP>",
            "geographicalContext": {
              "city": null, "state": null, "country": "<CHANGE: same country as above>", "postalCode": null,
              "geolocation": {"lat": 48.8001, "lon": 17.013}
            },
            "version": "V4", "source": null
          }
        ]
      },
      "transaction": {"type": "WEB", "id": "<CHANGE: 32 random hex characters>", "detail": {}},
      "authenticationContext": {
        "authenticationProvider": "FACTOR_PROVIDER",
        "credentialProvider": "OKTA_CREDENTIAL_PROVIDER",
        "credentialType": "SIGNED_NONCE",
        "externalSessionId": "<CHANGE: 'ext-session-' + a new UUID>",
        "authnContextClassRef": "urn:oasis:names:tc:SAML:2.0:ac:classes:TimeSyncToken",
        "issuer": null, "interface": null, "authenticationStep": 0
      },
      "securityContext": {
        "asNumber": "<CHANGE: any integer AS number, e.g. 16019>",
        "asOrg": "<CHANGE: any ISP name>",
        "domain": "torproject.org",
        "isProxy": true,
        "isp": "<CHANGE: same ISP name>"
      },
      "debugContext": {
        "debugData": {
          "requestId": "<CHANGE: 32 random hex characters>",
          "dtHash": "<CHANGE: 64 random hex characters>",
          "deviceFingerprint": "<CHANGE: 32 random hex characters>",
          "requestUri": "/api/internal/v1/mappings",
          "url": "/api/internal/v1/mappings?",
          "factor": "SIGNED_NONCE",
          "risk": "{level=HIGH}",
          "behaviors": "{New Geo-Location=POSITIVE, New Device=NEGATIVE, New IP=POSITIVE, New State=NEGATIVE, New Country=NEGATIVE, Velocity Behavior=NEGATIVE, New City=NEGATIVE}",
          "threatSuspected": "true",
          "logOnlySecurityData": "{\"behaviors\":{},\"phishingUrl\":\"https://login-okta-verify.co/login/login.htm?fromURI=%2Fapp%2FuserHome\",\"originCheckResult\":\"MISMATCH\",\"requestedUri\":\"/idp/idx/challenge/answer?\"}",
          "threatDetections": "{\"Phishing Attempt Blocked\": \"HIGH\"}"
        }
      }
    }
  ]
}
```

What matters and why (what stayed **constant** across all five successes, so keep it exactly):

- **`eventType` `user.authentication.auth_via_mfa`, `outcome.result` `FAILURE`, `outcome.reason` `FastPass declined phishing attempt`**: the triple Okta itself documents for a blocked FastPass phishing attempt.
- **`debugContext.debugData.threatSuspected` the string `"true"`, `risk` `{level=HIGH}`, `threatDetections` and `logOnlySecurityData` as JSON-encoded strings (not objects)**, `behaviors` with `New Geo-Location=POSITIVE` and `New IP=POSITIVE`: Okta's own risk evidence. The Okta modeling rule maps `threatSuspected` into `xdm.alert.risks`.
- **`authenticationContext` with `credentialType` `SIGNED_NONCE` and `authenticationProvider` `FACTOR_PROVIDER`**: the FastPass signature (a signed nonce from the Okta Verify app).
- **`securityContext`**: `isProxy` was `true` in every firing; `domain` was `torproject.org` for the Tor runs and `telegram.org` for run 2, and AS number/ISP differed in every run. Keep `isProxy` true; set `domain` to the address's own network. Whether `isProxy` is needed was not isolated.
- **Free to change** (they differed between the firings): user, IP, country, AS number and name, `client.device`/`os`, the user-agent string, `requestUri`/`url`, every id, `uuid`, hashes and `published`. The detector read the country from the address itself in the alert text ("located in Czechia" for 93.99.104.18).
- **Never** send `DOMAIN\user` or a bare name without the domain: use the `@examplecorp.com` form.

## Route C: Cribl (one call, no hand-built event)

The same alert also fires through the tenant's **Cribl** route, and there the connector builds the event itself: Step 1's body is not needed. It needs the `http-sender` instance to have `criblUrl` and the `criblToken` secret (`list_destinations` shows **`cribl_okta_sso`** with `ready: true`). Call **`http-sender.generate_events`** once with these arguments (not a runnable block of this skill: the JSON block above is a `send_events` body with placeholders, so the arguments are given as text):

```text
{"profile": "okta", "scenario": "fastpass_phishing", "destination": "cribl_okta_sso", "count": 1}
```

- `count: 1` is one event and one alert. Leave `count` in: an omitted count is **20** for this scenario, and every event is a new user on a new Tor exit, so the default sends 20 users.
- The call invents the user (`fastpass.phishing.<6 hex>@phantom.lab`), a Tor exit from the connector's snapshot, the `FastPass declined phishing attempt` outcome and the risk fields of Step 1 (with a reserved `.invalid` phishing host and no geolocation). Nothing is replaced by hand. If the alert stops appearing, the exit snapshot may be stale; add `"source_ip": "<a live Tor exit>"`.
- It goes to the dedicated Okta source of the Cribl endpoint, not to the `okta_sso` HTTP collector, but the rows still land in `okta_sso_raw` (`_collector_name = "phantom-http-sender"`, `_collector_type = Okta`), so Step 2 and Step 3 below apply unchanged: filter Step 2 on the `sample_ids` value as `uuid`, and match the alert by its `host_ip` (the exit) and the `fastpass.phishing.` prefix of `user_name` (`phantom\fastpass.phishing.<hex>`): Cortex shortens the login in the alert.


Step 2 returns one row: `eventtype user.authentication.auth_via_mfa`, `outcome` FAILURE with reason `FastPass declined phishing attempt`, `_collector_type` Okta. The alert is Low, MITRE `T1566 - Phishing`, tags `DS:Okta/Sso` and `DT:Identity Analytics`, typically within about 30 seconds. Hand-built events sent to the same Cribl destination fire as well.

## Step 2: confirm the event landed and modeled (about 5 minutes after Step 1; ingestion lags)

```
dataset = okta_sso_raw
| filter uuid = "<your uuid>"
| fields _time, eventtype, outcome, actor, client
```

Pass when one row returns with `eventtype = user.authentication.auth_via_mfa`. Then:

```
config timeframe = 1h | datamodel dataset = okta_sso_raw
| filter xdm.event.original_event_type = "user.authentication.auth_via_mfa" and xdm.source.user.upn = "<your login>"
| fields xdm.event.outcome, xdm.alert.risks, xdm.source.ipv4
```

Pass when `xdm.event.outcome = FAILED` and `xdm.alert.risks` contains `risky_signin: TRUE`.

## Step 3: wait, then check for the alert

Check **1 minute** after the event, then every minute for up to **10 minutes** (the alert typically arrives within about 1 to 3 minutes):

```
dataset = alerts
| filter alert_name = "Okta FastPass reported phishing attack suspected"
| fields _time, alert_id, alert_name, user_name, host_ip, description
| sort desc _time
| limit 5
```

Pass when a new row names your user (shown as `examplecorp\<login local part>`).

If nothing arrives in 10 minutes: confirm Step 2 (it must have landed in **`okta_sso_raw`**), confirm the destination was `okta_sso`, then retry once with a **new user and a new IP**. Do not change the event body.

## Report back to the operator

State the user, IP, `uuid`, the Step 2 result and either the alert id with the arrival time or that nothing arrived in 10 minutes and what you checked. Say that the user and the IP should not be reused for 24 hours.

Note: the Cortex `user_name` prefix shown above (`phantom\`) is the first label of the organization's email domain (`phantom.lab`); it was `phantom-lab\` on the previous domain. It has not been re-measured on the tenant, so confirm it on the first replay.
