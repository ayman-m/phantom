---
name: trigger_samaccountname_change_alert
displayName: Trigger the Cortex "Suspicious sAMAccountName change" analytics alert
category: workflows
description: 'Fire Cortex XSIAM''s native "Suspicious sAMAccountName change" analytics BIOC (Low, T1098, CVE-2021-42278 / 42287 noPac) by sending ONE synthetic Windows Security event 4781 through the wec-sender connector (Windows Event Collector, Route A) or through http-sender with destination cribl_windows_events (the tenant Cribl endpoint with the Windows UUID, Route B): a new administrator account renames a computer account so that its trailing dollar sign disappears (PHWS-210$ to PHWS-210). Use when the operator asks to trigger, demo, prove or reproduce a sAMAccountName spoofing, noPac, or machine-account rename alert, or a 4781 alert. It fires over both routes and never over syslog/CEF.'
icon: admin_panel_settings
source: platform
loadingMode: on-demand
locked: false
---

# Skill: Trigger the "Suspicious sAMAccountName change" alert

## When this skill applies

The operator wants the native **Cortex Analytics detector for a machine account renamed without its trailing `$`** to fire, for example: *"trigger a noPac alert"*, *"show a sAMAccountName spoofing attempt"*, *"prove T1098 fires from Windows events"*.

The detector is **not a correlation rule**; it is Cortex's own analytics (XDR Analytics BIOC), and nothing needs installing on the tenant beyond the Windows pack that already models `microsoft_windows_raw`. It reads Windows events that arrive through a registered Windows source, so the call below goes either to `wec-sender.send_events` (Route A) or to `http-sender.send_events` with `destination: "cribl_windows_events"` (Route B, see "Route B: Cribl"), never to a syslog/CEF worker.

> **Expected result.** The alert typically arrives within about 30 seconds of the call.

## What the detector looks for (Cortex doc: "Suspicious sAMAccountName change")

| Property | Value |
|---|---|
| Alert name | `Suspicious sAMAccountName change` (Low). The catalog's Medium variation `Suspicious sAMAccountName change to DC hostname` did not fire from a rename to a DC's name |
| Source | `XDR Analytics BIOC`, MITRE T1098 Account Manipulation, T1078 Valid Accounts; alert tags `DT:Identity Analytics`, `DS:Microsoft/Windows` |
| Required data (doc) | Windows Event Collector OR XDR Agent with eXtended Threat Hunting (XTH); the doc lists the Identity Analytics module |
| Activation / training (doc) | 14 days / 30 days in the documentation; in practice every alert arrives within minutes of its events |
| Test period | single event |
| Deduplication | 1 day |
| What the alert text says | *"The name of an account was changed from <machine>$ to <machine>. This action was performed by <domain>\<actor>. This may indicate an attempt to impersonate a domain controller by exploiting CVE-2021-42278 and CVE-2021-42287"* |

## Which delivery paths fire it (WEC and Cribl, never syslog/CEF)

The detectors in this family read Windows events that arrive through a registered Windows source. Over syslog/CEF the same event types **land and model** in `microsoft_windows_raw` but are stamped `_collector_type = Syslog`, and no Windows identity alert fires from them (DCSync, Kerberoasting, account-management batches, machine accounts and delegation sent over CEF raise none). Two paths carry the same structured events and **both fire**:

- **Route A, WEC**: `wec-sender.send_events` delivers through the Broker VM's Windows Event Collector over mutual TLS. The rows are stamped `_collector_type = WEC`.
- **Route B, Cribl**: `http-sender.send_events` with `destination: "cribl_windows_events"` renders the same events to Windows Event XML and posts them to the tenant's Cribl endpoint with the Windows UUID. The rows land in the same dataset with `_transport = cribl` and no `_collector_type`, with the same columns and `xdm.*` fields. All fifteen Windows recipes (this one included) fire over Cribl, within seconds to under two minutes of sending. It needs no Broker, no certificate and no subscription.

Do not "test it quickly" over syslog/CEF: a null result there says nothing about the rule.

**This is NOT a mapping problem.** Over syslog/CEF the event already lands in `microsoft_windows_raw` and the modeling rule already fills the same `xdm.*` fields (the syslog `MicrosoftWindowsEvents` source maps 58 of them), so a good mapping there proves nothing about this alert. The alert will not fire over syslog/CEF no matter how complete the mapping is: the detector reads the registered Windows source (the WEC, native-agent or dedicated-UUID Cribl feed), not the syslog/CEF feed. `_collector_type = WEC` is stamped by a real Windows Event Collector delivery and cannot be set from an event body, so no CEF extension, field choice or schema change can reach it.

## Preconditions: check these BEFORE sending

| # | Must be true | How to check |
|---|---|---|
| 1A | Route A only: the `wec-sender` connector instance is running and `wec-sender.list_subscriptions` returns `ok: true` with a subscription whose channels include `Security` (for example a subscription named "Authentication Event Logs" on the Broker VM, port 5986). Without the Windows Event Collector path Route A cannot fire | call `wec-sender.list_subscriptions` |
| 1B | Route B only: the `http-sender` instance has `criblUrl` and `criblToken` set, so `http-sender.list_destinations` lists `cribl_windows_events` with `ready: true` and `dataset: microsoft_windows_raw`. Route B needs no Broker, no certificate and no subscription | call `http-sender.list_destinations` |
| 2 | Every identity below is **new**: a user name and a RID never used in an earlier run, and a user name that is not a person's. The detectors report a first-time action per account, and their history is kept per account for 30 days | `config timeframe = 30d \| datamodel dataset = microsoft_windows_raw \| filter xdm.source.user.username = "<actor>" \| limit 1` returns **no row** |
| 3 | Every event time is **now** or a few minutes earlier, UTC. Write it as `now-310s` (the connector resolves it with its own clock; an absolute `YYYY-MM-DDTHH:MM:SSZ` also works): the connector turns `time` into the event's TimeCreated and that becomes `_time`, and the detector windows are evaluated on it. Never in the future | generate at call time |


## Expected result

The event in Step 1, with a new actor and computer, fires the alert over both routes, typically within about 30 seconds of the send.

Does **not** fire: a rename **to** a domain controller's name with the `$` kept (`PHWS-110$` to `PHDC02$`), also not when followed by a 4768 for the spoofed name and the rename back.

## Step 1: send the events (exactly this call)

**Route A (WEC).** Call **`wec-sender.send_events`** once with the 1 event below. Replace only the values marked `<CHANGE: ...>` (the same label means the same value everywhere it appears); everything else is the verbatim shape that fires.

| Placeholder | Put here |
|---|---|
| `now-Ns` (also `now`, `now-5m`, `now-1h`) | **leave it as this literal text, do not work out a date or time yourself**: the connector replaces it with its own current UTC time minus N seconds when it sends |
| `<CHANGE: actor>` | a new account name that is not a person's, e.g. `adm.runNNNN` (letters, digits, dot) |
| `<CHANGE: actor RID>` | a new RID, 3300 or higher, never reused (the SID is `S-1-5-21-3623811015-3361044348-30300820-<RID>`) |
| `<CHANGE: actor logon id>` | a new hex logon id such as `0x9A4C21` |
| `<CHANGE: machine>` | a new computer name `PHWS-<NNN>`; it appears as `<machine>$` (old name) and `<machine>` (new name) |
| `<CHANGE: machine RID>` | a new RID for the computer, 3300 or higher, different from the actor's |

```json
{
  "events": [
    {
      "event_id": 4781,
      "computer": "PHDC02",
      "time": "now-260s",
      "provider": "Microsoft-Windows-Security-Auditing",
      "rendering": {
        "message": "The name of an account was changed:\n\nSubject:\n\tSecurity ID:\t\tS-1-5-21-3623811015-3361044348-30300820-<CHANGE: actor RID>\n\tAccount Name:\t\t<CHANGE: actor>\n\tAccount Domain:\t\tPHANTOM\n\tLogon ID:\t\t<CHANGE: actor logon id>\n\nAccount Whose Name Was Changed:\n\tSecurity ID:\t\tS-1-5-21-3623811015-3361044348-30300820-<CHANGE: machine RID>\n\tOld Account Name:\t<CHANGE: machine>$\n\tNew Account Name:\t<CHANGE: machine>",
        "task": "User Account Management"
      },
      "event_data": {
        "SubjectUserSid": "S-1-5-21-3623811015-3361044348-30300820-<CHANGE: actor RID>",
        "SubjectUserName": "<CHANGE: actor>",
        "SubjectDomainName": "PHANTOM",
        "SubjectLogonId": "<CHANGE: actor logon id>",
        "OldTargetUserName": "<CHANGE: machine>$",
        "NewTargetUserName": "<CHANGE: machine>",
        "TargetSid": "S-1-5-21-3623811015-3361044348-30300820-<CHANGE: machine RID>"
      }
    }
  ]
}
```

What matters and why:

- **`event_id` 4781** (the name of an account was changed) on the DC `PHDC02`. `OldTargetUserName` ends with **`$`** and `NewTargetUserName` is the **same name without the `$`**: that missing dollar sign is the whole detection (the catalog: "changed to a sAMAccountName with a missing trailing dollar sign").
- **Wrong way round**: a rename **to** a domain controller's name with the `$` kept (`PHWS-110$` to `PHDC02$`) does **not** raise this alert.
- **`rendering.message`** repeats the old and new names under "Account Whose Name Was Changed"; keep the layout.
- **Free to change**: the actor, the computer name and the RIDs.

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
| filter xdm.event.id = "4781" and xdm.source.user.username = "<actor>"
| fields _time, xdm.event.id, xdm.source.user.username, xdm.event.description
```

Pass when one row returns and its description shows the new name **without** a `$`.

## Step 3: wait, then check for the alert

Check **1 minute** after the send, then every minute for up to **15 minutes** (the alert typically arrives within about 30 seconds):

```
dataset = alerts
| filter alert_name = "Suspicious sAMAccountName change"
| fields _time, alert_id, alert_name, severity, host_name, user_name, description
| sort desc _time
| limit 5
```

Pass when a new row names your actor. To list Analytics alerts without naming one, filter on the STORED enum values `alert_source in ("MAGNIFIER","ANALYTICS_BIOC")`: the displayed names `XDR_ANALYTICS` and `XDR_ANALYTICS_BIOC` match nothing.

If nothing arrives in 15 minutes: confirm Step 2 (the events must be in `microsoft_windows_raw` and modeled, with the stamp of the route you used: `_collector_type = "WEC"` for Route A, `_transport = "cribl"` for Route B), confirm every identity was new (precondition 2), then retry **once** with a new actor and new RIDs. Do not change the event body.

## Report back to the operator

State the actor, the RIDs and the host names used, the number of events sent, the Step 2 result and either the alert id with the arrival time or that nothing arrived in 15 minutes and what you checked. Say that the actor must not be reused: the detector's history is per account and its deduplication is one day.
