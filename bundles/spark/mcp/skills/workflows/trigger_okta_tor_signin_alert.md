---
name: trigger_okta_tor_signin_alert
displayName: Trigger the Cortex "A successful SSO sign-in from TOR" analytics alert
category: workflows
description: 'Fire Cortex XSIAM''s native "A successful SSO sign-in from TOR" analytics alert (High, T1090.003 / T1078, Identity Analytics) by sending ONE synthetic Okta System Log event through the http-sender connector in Cribl mode: a successful user.authentication.sso of a baseline user from a Tor exit node, to a never-seen app. Use when the operator asks to trigger, demo, prove or reproduce a successful Okta sign-in from Tor, a Tor login, or an anonymized-proxy logon. One http-sender generate_events call (profile okta, scenario tor_signin, destination cribl_okta_sso, count 1) with a baseline login as target_user; a single event typically raises its alert within a minute or two. It needs the Cribl route (the instance must have criblUrl and the criblToken secret): the okta_sso HTTP collector does not raise it.'
icon: vpn_lock
source: platform
loadingMode: on-demand
locked: false
---

# Skill: Trigger the "A successful SSO sign-in from TOR" alert

## When this skill applies

The operator wants the **native Cortex Analytics Tor sign-in detector** to fire on Okta data, for example:
*"trigger a Tor login alert"*, *"show a successful sign-in from a Tor exit node"*, *"prove T1090.003 fires from Okta logs"*.

It is not a correlation rule; it is Cortex's own analytics (Identity Analytics), and nothing needs installing on the tenant. It is a fast Okta detector: a single-event call typically raises its alert within a minute or two.

> **It needs the Cribl route.** The destination is `cribl_okta_sso`: the tenant's Cribl integration under Okta's dedicated source identifier, which gives the rows Okta's own native treatment. The generic `okta_sso` HTTP collector does not raise this detector. The instance must therefore have `criblUrl` and the `criblToken` secret set; without them the call is refused with a clear message.

## What the detector looks for (Cortex doc: "A successful SSO sign-in from TOR")

| Property | Value |
|---|---|
| Alert name | `A successful SSO sign-in from TOR` (**High**). A variation `... via Mobile Device` (Medium) exists; the desktop user agent used here raised the High one |
| Source | `XDR Analytics` (Identity Analytics), MITRE shown on the alert: `T1090.003 - Proxy: Multi-hop Proxy` and `T1078 - Valid Accounts`; alert tags `DS:Okta/Sso`, `DT:Identity Analytics` |
| Required data (doc) | one of AzureAD, Azure SignIn Log, Idira, Duo, Okta, OneLogin, PingOne |
| Activation / training (doc) | 14 days / 30 days. In practice the alert typically arrives within a minute or two |
| Test period | single event |
| Deduplication (doc) | 1 hour. In practice it is not a per-user block (see "What `count` does") |
| What the alert text says | *"The user phantom-lab\<login> has signed in successfully from <exit ip>. <exit ip> was a TOR exit node during the time of the event"* |

## Preconditions: check these BEFORE sending

| # | Must be true | How to check |
|---|---|---|
| 1 | The `http-sender` instance is running with Cribl configured: `list_destinations` shows **`cribl_okta_sso`** with `ready: true` | `http-sender.list_destinations` |
| 2 | `target_user` is one of the **twelve baseline users** of the Okta profile, as a bare name: `noura.alharbi`, `khalid.alotaibi`, `abdullah.alzahrani`, `sara.almutairi`, `faisal.alqahtani`, `reem.aldosari`, `omar.alshehri`, `huda.alghamdi`, `yousef.alharthi`, `layla.almalki`, `tariq.alsubaie`, `dana.alanazi`. The detector needs a user with an ordinary history, so an invented name is not covered by this recipe | the list above |
| 3 | Prefer a user with **no** `A successful SSO sign-in from TOR` alert in the last 24 hours (the documented deduplication is 1 hour, and in practice it is looser, but a clean user leaves no doubt about which call raised the alert) | the query in "Pick the user" below |
| 4 | Nothing else: the call generates the event itself, with the time set to now, a Tor exit from the connector's snapshot of exits and a never-seen app name. You never write the event | none |

Pick the user:

```text
config timeframe = 1d | dataset = alerts
| filter alert_name = "A successful SSO sign-in from TOR"
| alter u = arrayindex(user_name, 0)
| comp count() as alerts, max(alert_arrival_timestamp) as last by u
```

## Expected result

All through destination `cribl_okta_sso` (dataset `okta_sso_raw`), event time = send time, severity High. A `count: 1` call raises one alert for the user and exit IP of its event, typically within a minute or two. Each alert's description names the user and the exit IP of its own event, so the alerts attribute cleanly.

## What `count` does (read before changing it)

Each event of the call is one successful SSO sign-in by the user **from a different Tor exit and to a different never-seen app**, and **each event raised its own alert**:

- `count: 1` gives **one event and one alert**. This is the value to use: it is enough to fire, and it leaves one alert to explain.
- `count: 20` (the connector's default) raises about **18 alerts on 18 distinct exit addresses, for the one user** inside about a minute: about 18 alerts for 20 events.
- Re-running the same call for the **same user** a few minutes later fires again (a new exit, a new alert). So the documented 1-hour deduplication does not stop a repeat with a different exit; the alerts differ by exit address.

## Step 1: send the event (exactly this call)

Call **`http-sender.generate_events`** once. Replace only the value marked `<CHANGE: ...>`; the call needs no `source_ip`, no event body and nothing else.

```json
{"profile": "okta", "scenario": "tor_signin", "destination": "cribl_okta_sso", "count": 1, "target_user": "<CHANGE: target user, a baseline login such as dana.alanazi>"}
```

The answer carries `sent: 1`, `batch_status: [200]`, `destination: "cribl_okta_sso"`, `dataset: "okta_sso_raw"`, `sample_ids` (the event's `uuid`) and `first_time` (the event time). Keep the `uuid` and the time for the next steps.

If the Tor detector stops firing for a user that is otherwise fine, the connector's exit snapshot is stale (an exit that left the Tor network is no longer recognised). Pass a current Tor exit as one more key of the same call, `"source_ip": "<a live exit>"`, from the bulk exit list at `https://check.torproject.org/torbulkexitlist`; it is normally not needed.

## Step 2: confirm the event landed and modeled (about 1 minute after Step 1)

```text
config timeframe = 1h | dataset = okta_sso_raw
| filter _collector_name = "phantom-http-sender" and uuid = "<the sample_id>"
| fields _time, uuid, eventtype, outcome, actor, client, _collector_type
```

Pass when one row returns with `eventtype = user.authentication.sso`, `outcome.result = SUCCESS`, `_collector_type = Okta`, and `client.ipAddress` the exit. Then:

```text
config timeframe = 1h | datamodel dataset = okta_sso_raw
| filter xdm.event.id = "<the sample_id>"
| fields _time, xdm.event.type, xdm.event.outcome, xdm.source.user.upn, xdm.source.ipv4
```

Pass when `xdm.event.type = authentication`, `xdm.event.outcome = SUCCESS` and `xdm.source.user.upn` is `<login>@phantom-lab.example` (the same query returns all four).

## Step 3: wait, then check for the alert

Check **10 seconds** after the event, then every 10 seconds for up to **3 minutes** (a single-event call typically arrives within a minute or two). `<epoch ms>` is the time of the send in milliseconds:

```text
config timeframe = 1d | dataset = alerts
| filter alert_source in ("MAGNIFIER", "ANALYTICS_BIOC") and alert_name = "A successful SSO sign-in from TOR"
| filter alert_arrival_timestamp > <epoch ms>
| fields alert_arrival_timestamp, alert_id, alert_name, severity, user_name, host_ip, mitre_attack_technique, original_tags, description
| sort desc alert_arrival_timestamp
| limit 10
```

Use the stored enum names `MAGNIFIER` and `ANALYTICS_BIOC`: the displayed names `XDR_ANALYTICS` and `XDR_ANALYTICS_BIOC` match nothing.

Pass when a row names your user (shown as `phantom-lab\<login>`) and `host_ip` is the exit of your event. Expect `severity` HIGH, `mitre_attack_technique` `T1090.003 - Proxy: Multi-hop Proxy|T1078 - Valid Accounts` and `original_tags` containing `DS:Okta/Sso`.

If nothing arrives in 3 minutes: re-run Step 2 (the row must exist in `okta_sso_raw` with `_collector_type = Okta`), check that the destination was `cribl_okta_sso` and not an HTTP collector, then retry **once** with another baseline user. If that is also silent, suspect the exit snapshot (Step 1, last paragraph).

## Report back to the operator

State the user, the exit IP, the event `uuid` and time, the Step 2 result and either the alert id with its arrival time and latency (the detector typically fires within a minute or two) or that nothing arrived in 3 minutes and what you checked. Say that the call sent one event and raised one alert, and that a larger `count` raises one alert per event (about 18 for `count: 20`).
