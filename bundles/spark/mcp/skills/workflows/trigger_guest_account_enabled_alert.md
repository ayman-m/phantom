---
name: trigger_guest_account_enabled_alert
displayName: Trigger the Cortex "A user enabled the Windows default Guest account" analytics alert
category: workflows
description: 'Fire Cortex XSIAM''s native "A user enabled the Windows default Guest account" analytics BIOC (Low, T1078.001) by sending ONE synthetic Windows Security event 4722 through the wec-sender connector (Windows Event Collector, Route A) or through http-sender with destination cribl_windows_events (the tenant Cribl endpoint with the Windows UUID, Route B): a new administrator account enables the built-in Guest account on a member server. Use when the operator asks to trigger, demo, prove or reproduce an enabled default or Guest account alert, or a 4722 alert. It fires over both routes and never over syslog/CEF.'
icon: admin_panel_settings
source: platform
loadingMode: on-demand
locked: false
---

# Skill: Trigger the "A user enabled the Windows default Guest account" alert

## When this skill applies

The operator wants the native **Cortex Analytics detector for the default Guest account being enabled** to fire, for example: *"trigger a Guest account alert"*, *"show a default account being enabled"*.

The detector is **not a correlation rule**; it is Cortex's own analytics (XDR Analytics BIOC), and nothing needs installing on the tenant beyond the Windows pack that already models `microsoft_windows_raw`. It reads Windows events that arrive through a registered Windows source, so the call below goes either to `wec-sender.send_events` (Route A) or to `http-sender.send_events` with `destination: "cribl_windows_events"` (Route B, see "Route B: Cribl"), never to a syslog/CEF worker.

>

## What the detector looks for (Cortex doc: "A user enabled a default local account")

| Property | Value |
|---|---|
| Alert name | `A user enabled the Windows default Guest account` (Low), a variation of the doc's `A user enabled a default local account` (Informational, invisible) |
| Source | `XDR Analytics BIOC`, MITRE T1078.001 Valid Accounts: Default Accounts, T1098 Account Manipulation; alert tags `DT:Identity Analytics`, `DS:Microsoft/Windows` |
| Required data (doc) | Windows Event Collector OR XDR Agent with eXtended Threat Hunting (XTH); the doc lists the Identity Analytics module |
| Activation / training (doc) | 14 days / 30 days. In practice the alert typically arrives within a minute or two of its events |
| Test period | single event |
| Deduplication | 1 day |
| What the alert text says | *"The user <domain>\<actor> enabled a default account. The default account enabled: <domain>\guest. The user has enabled 0 accounts in the past 30 days"* |

## Which delivery paths fire it (WEC and Cribl, never syslog/CEF)

The detectors in this family read Windows events that arrive through a registered Windows source. Over syslog/CEF the same event types **land and model** in `microsoft_windows_raw` but are stamped `_collector_type = Syslog`, and no Windows identity alert fires from them: the same Windows identity scenarios sent over CEF (DCSync, Kerberoasting, an account-management batch, machine accounts and delegation) raised none. Two paths carry the same structured events and **both fire**:

- **Route A, WEC**: `wec-sender.send_events` delivers through the Broker VM's Windows Event Collector over mutual TLS. The rows are stamped `_collector_type = WEC`.
- **Route B, Cribl**: `http-sender.send_events` with `destination: "cribl_windows_events"` renders the same events to Windows Event XML and posts them to the tenant's Cribl endpoint with the Windows UUID. The rows land in the same dataset with `_transport = cribl` and no `_collector_type`, with the same columns and `xdm.*` fields. All fifteen Windows recipes (this one included) fire over Cribl, typically within a minute or two of sending. It needs no Broker, no certificate and no subscription.

Do not "test it quickly" over syslog/CEF: a null result there says nothing about the rule.

**This is NOT a mapping problem.** Over syslog/CEF the event already lands in `microsoft_windows_raw` and the modeling rule already fills the same `xdm.*` fields (the syslog `MicrosoftWindowsEvents` source maps 58 of them), so a good mapping there proves nothing about this alert. The alert will not fire over syslog/CEF no matter how complete the mapping is: the detector reads the registered Windows source (the WEC, native-agent or dedicated-UUID Cribl feed), not the syslog/CEF feed. `_collector_type = WEC` is stamped by a real Windows Event Collector delivery and cannot be set from an event body, so no CEF extension, field choice or schema change can reach it.

## Preconditions: check these BEFORE sending

| # | Must be true | How to check |
|---|---|---|
| 1A | Route A only: the `wec-sender` connector instance is running and `wec-sender.list_subscriptions` returns `ok: true` with a subscription whose channels include `Security` (for example the subscription "Authentication Event Logs" on the Broker VM, port 5986). Without the Windows Event Collector path Route A cannot fire | call `wec-sender.list_subscriptions` |
| 1B | Route B only: the `http-sender` instance has `criblUrl` and `criblToken` set, so `http-sender.list_destinations` lists `cribl_windows_events` with `ready: true` and `dataset: microsoft_windows_raw`. Route B needs no Broker, no certificate and no subscription | call `http-sender.list_destinations` |
| 2 | Every identity below is **new**: a user name and a RID never used in an earlier run (use **3300 or higher** and never reuse one), and a user name that is not a person's. The detectors report a first-time action per account, and their history is kept per account for 30 days | `config timeframe = 30d \| datamodel dataset = microsoft_windows_raw \| filter xdm.source.user.username = "<actor>" \| limit 1` returns **no row** |
| 3 | Every event time is **now** or a few minutes earlier, UTC. Write it as `now-310s` (the connector resolves it with its own clock; an absolute `YYYY-MM-DDTHH:MM:SSZ` also works): the connector turns `time` into the event's TimeCreated and that becomes `_time`, and the detector windows are evaluated on it. Never in the future | generate at call time |


## Expected result

The recipe fires from a new administrator account enabling the built-in `Guest` account on a member server, over Route A and over Route B. The alert typically arrives within a minute of the send (often within about 30 seconds).

## Step 1: send the events (exactly this call)

**Route A (WEC).** Call **`wec-sender.send_events`** once with the 1 event below. Replace only the values marked `<CHANGE: ...>` (the same label means the same value everywhere it appears); everything else is the verbatim shape that fires.

| Placeholder | Put here |
|---|---|
| `now-Ns` (also `now`, `now-5m`, `now-1h`) | **leave it as this literal text, do not work out a date or time yourself**: the connector replaces it with its own current UTC time minus N seconds when it sends |
| `<CHANGE: actor>` | a new account name that is not a person's, e.g. `adm.runNNNN` (letters, digits, dot) |
| `<CHANGE: actor RID>` | a new RID, 3300 or higher, never reused (the SID is `S-1-5-21-3623811015-3361044348-30300820-<RID>`) |
| `<CHANGE: actor logon id>` | a new hex logon id such as `0x9A4C21` |

```json
{
  "events": [
    {
      "event_id": 4722,
      "computer": "PHSRV-FS01",
      "time": "now-70s",
      "provider": "Microsoft-Windows-Security-Auditing",
      "rendering": {
        "message": "A user account was enabled.\n\nSubject:\n\tSecurity ID:\t\tS-1-5-21-3623811015-3361044348-30300820-<CHANGE: actor RID>\n\tAccount Name:\t\t<CHANGE: actor>\n\tAccount Domain:\t\tPHANTOM\n\tLogon ID:\t\t<CHANGE: actor logon id>\n\nTarget Account:\n\tSecurity ID:\t\tS-1-5-21-3623811015-3361044348-30300820-501\n\tAccount Name:\t\tGuest\n\tAccount Domain:\t\tPHANTOM",
        "task": "User Account Management"
      },
      "event_data": {
        "SubjectUserSid": "S-1-5-21-3623811015-3361044348-30300820-<CHANGE: actor RID>",
        "SubjectUserName": "<CHANGE: actor>",
        "SubjectDomainName": "PHANTOM",
        "SubjectLogonId": "<CHANGE: actor logon id>",
        "TargetUserName": "Guest",
        "TargetDomainName": "PHANTOM",
        "TargetSid": "S-1-5-21-3623811015-3361044348-30300820-501"
      }
    }
  ]
}
```

What matters and why:

- **`event_id` 4722 on a member server** (`PHSRV-FS01`): "a user account was enabled". Target `Guest` with `TargetSid` ending **`-501`** (the well-known Guest RID). The alert text says "default account", which the detector derives from that RID or the name.
- **`rendering.message`/`task`/`provider`** are required (not catalogued).
- **Free to change**: the actor and its RID and logon id. The detector counts what the **actor** enabled in 30 days, so the actor must be new (the alert said "0 accounts in the past 30 days").
- The other events of an account-management batch (4738 password never expires, 4616 time change, 4720 local "Administrator", 4724 reset, 4781 rename, two 4742 changes) raised no alert of their own.

## Route B: Cribl (same events, same alert)

Send the **same 1 event as Step 1** through the tenant's Cribl endpoint instead of the Windows Event Collector: call **`http-sender.send_events`** once with the same `events` list (every `<CHANGE: ...>` filled exactly as in Step 1) plus the destination. Do not build any XML: the connector renders each event to Windows Event XML itself. Precondition 1B applies instead of 1A.

```text
http-sender.send_events
{"events": <the same events list as Step 1>, "destination": "cribl_windows_events"}
```

The answer carries `ok: true`, `destination: cribl_windows_events`, `dataset: microsoft_windows_raw` and `num_records` equal to 1. The rows land in `microsoft_windows_raw` with `_transport = "cribl"` and no `_collector_type`; the columns and `xdm.*` fields are the same as over WEC, so Steps 2 and 3 are unchanged (only the stamp check differs).


## Step 2: confirm the events landed and modeled (about 2 minutes after Step 1)

```
config timeframe = 1h | datamodel dataset = microsoft_windows_raw
| filter xdm.event.id = "4722" and xdm.source.user.username = "<actor>"
| fields _time, xdm.event.id, xdm.source.user.username, xdm.source.host.hostname, xdm.event.description
```

Pass when one row returns for host `PHSRV-FS01.phantom.lab`.

## Step 3: wait, then check for the alert

Check **1 minute** after the send, then every minute for up to **15 minutes** (it typically arrives within a minute):

```
dataset = alerts
| filter alert_name = "A user enabled the Windows default Guest account"
| fields _time, alert_id, alert_name, severity, host_name, user_name, description
| sort desc _time
| limit 5
```

Pass when a new row names your actor. To list Analytics alerts without naming one, filter on the STORED enum values `alert_source in ("MAGNIFIER","ANALYTICS_BIOC")`: the displayed names `XDR_ANALYTICS` and `XDR_ANALYTICS_BIOC` match nothing.

If nothing arrives in 15 minutes: confirm Step 2 (the events must be in `microsoft_windows_raw` and modeled, with the stamp of the route you used: `_collector_type = "WEC"` for Route A, `_transport = "cribl"` for Route B), confirm every identity was new (precondition 2), then retry **once** with a new actor and new RIDs. Do not change the event body.

## Report back to the operator

State the actor, the RIDs and the host names used, the number of events sent, the Step 2 result and either the alert id with the arrival time or that nothing arrived in 15 minutes and what you checked. Say that the actor must not be reused: the detector's history is per account and its deduplication is one day.
