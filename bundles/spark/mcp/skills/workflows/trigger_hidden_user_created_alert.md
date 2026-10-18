---
name: trigger_hidden_user_created_alert
displayName: Trigger the Cortex "Suspicious hidden user created" analytics alert
category: workflows
description: 'Fire Cortex XSIAM''s native "Suspicious hidden user created" analytics BIOC (Medium, T1136 and T1564.002) by sending ONE synthetic Windows Security event 4720 on the domain controller: a new administrator account creates a user whose name ends in a dollar sign, so it mimics a machine account. Two delivery routes fire it: wec-sender (Windows Event Collector) and http-sender with destination cribl_windows_events (the tenant Cribl endpoint with the Windows UUID). Use when the operator asks to trigger, demo, prove or reproduce a hidden user, a user named like a machine account, or a 4720 with a trailing dollar sign. It never fires over syslog/CEF.'
icon: admin_panel_settings
source: platform
loadingMode: on-demand
locked: false
---

# Skill: Trigger the "Suspicious hidden user created" alert

## When this skill applies

The operator wants the native **Cortex Analytics detector for a user account named like a machine account** to fire, for example: *"trigger a hidden user alert"*, *"show an account with a trailing dollar sign being created"*, *"prove T1564.002 fires from Windows events"*.

The detector is **not a correlation rule**; it is Cortex's own analytics (XDR Analytics BIOC), and nothing needs installing on the tenant beyond the Windows pack that already models `microsoft_windows_raw`. It reads Windows events that arrive through a registered Windows source, so the call below goes either to `wec-sender.send_events` (Route A) or to `http-sender.send_events` with `destination: "cribl_windows_events"` (Route B), never to a syslog/CEF worker.

## What the detector looks for (Cortex doc: "Suspicious hidden user created")

| Property | Value |
|---|---|
| Alert name | `Suspicious hidden user created` (Medium) |
| Source | `XDR Analytics BIOC`, MITRE T1136 Create Account and T1564.002 Hide Artifacts: Hidden Users (tactics TA0003 Persistence, TA0005 Stealth); alert tags `DS:Microsoft/Windows`, `DT:Identity Analytics`, `R:Domain Controllers` |
| Doc description | A user account was created with a name that mimics a machine account |
| Required data (doc) | Windows Event Collector OR XDR Agent with eXtended Threat Hunting (XTH); the doc lists the Identity Analytics module |
| Activation / training (doc) | 14 days / 30 days. In practice the alert typically arrives within a minute or two of its events |
| Test period | single event |
| Deduplication | 1 day |
| What the alert text says | *"The user <domain>\<actor> created a new user account. This user mimics a machine account with a trailing dollar sign to potentially evade detection. The new user created: <domain>\<name>$. This new account has not been seen in the past 30 days"* |

## Which delivery paths fire it

Windows identity detectors read the registered Windows source, not the syslog/CEF feed. Over syslog/CEF the same event types **land and model** in `microsoft_windows_raw` but no Windows identity alert fires from them (the same scenarios sent over syslog/CEF raised none). Two paths carry the same structured events and fire:

- **Route A, WEC**: `wec-sender.send_events` delivers through the Broker VM's Windows Event Collector over mutual TLS. Rows land with `_collector_type = WEC`.
- **Route B, Cribl**: `http-sender.send_events` with `destination: "cribl_windows_events"` renders the same events to Windows Event XML and posts them to the tenant's Cribl endpoint with the Windows UUID. Rows land in the same dataset with `_transport = cribl` and no `_collector_type`; the columns and `xdm.*` fields are the same. It needs no Broker, no certificate and no subscription.

Do not "test it quickly" over syslog: a null result there says nothing about the rule.

**This is NOT a mapping problem.** Over syslog/CEF the event already lands in `microsoft_windows_raw` and the modeling rule already fills the same `xdm.*` fields (the syslog `MicrosoftWindowsEvents` source maps 58 of them), so a good mapping there proves nothing about this alert. The alert will not fire over syslog/CEF no matter how complete the mapping is: the detector reads the registered Windows source (the WEC, native-agent or dedicated-UUID Cribl feed), not the syslog/CEF feed. `_collector_type = WEC` is stamped by a real Windows Event Collector delivery and cannot be set from an event body, so no CEF extension, field choice or schema change can reach it.

## Preconditions: check these BEFORE sending

| # | Must be true | How to check |
|---|---|---|
| 1A | Route A only: the `wec-sender` connector instance is running and `wec-sender.list_subscriptions` returns `ok: true` with a subscription whose channels include `Security` (for example the subscription "Authentication Event Logs" on the Broker VM, port 5986) | call `wec-sender.list_subscriptions` |
| 1B | Route B only: the `http-sender` instance has `criblUrl` and `criblToken` set, so `http-sender.list_destinations` lists `cribl_windows_events` with `ready: true` and `dataset: microsoft_windows_raw` | call `http-sender.list_destinations` |
| 2 | Every identity below is **new**: an actor name and RID never used in an earlier run (use **3300 or higher** and never reuse one), and a hidden-account name never created before. The alert says the account "has not been seen in the past 30 days", and the actor's history is kept per account for 30 days | `config timeframe = 30d \| datamodel dataset = microsoft_windows_raw \| filter xdm.source.user.username = "<actor>" \| limit 1` returns **no row** |
| 3 | Every event time is **now** or a few minutes earlier, UTC. Write it as `now-310s` (the connector resolves it with its own clock; an absolute `YYYY-MM-DDTHH:MM:SSZ` also works): the connector turns `time` into the event's TimeCreated and that becomes `_time`, and the detector windows are evaluated on it. Never in the future | generate at call time |

## Expected result

The recipe fires over Route A and over Route B from a new actor creating a new hidden account name (ending in `$`). Each alert is attributed by the identity in the alert (`user_name` and the account named in the alert text), never by time alone, and typically arrives within a minute of the send call (the call itself takes about 10 s). Every alert is `MEDIUM`, host `PHDC02.phantom.lab`, tags `DS:Microsoft/Windows`, `DOM:Security`, `R:Domain Controllers`, `DT:Identity Analytics`; the alert text reads: *"The user phantom\<actor> created a new user account. This user mimics a machine account with a trailing dollar sign ... The new user created: phantom\<hidden>$. This new account has not been seen in the past 30 days"*.

Not covered by this recipe: its event shape over syslog/CEF. The general result for Windows identity detectors is in "Which delivery paths fire it".

## Step 1: send the events (exactly this call)

Both routes send the **same 1 event**. Replace only the values marked `<CHANGE: ...>` (the same label means the same value everywhere it appears); everything else is the verbatim shape that fires.

| Placeholder | Put here |
|---|---|
| `now-Ns` (also `now`, `now-5m`, `now-1h`) | **leave it as this literal text, do not work out a date or time yourself**: the connector replaces it with its own current UTC time minus N seconds when it sends |
| `<CHANGE: actor>` | a new account name that is not a person's, e.g. `adm.runNNNN` (letters, digits, dot) |
| `<CHANGE: actor RID>` | a new RID, 3300 or higher, never reused (the SID is `S-1-5-21-3623811015-3361044348-30300820-<RID>`) |
| `<CHANGE: actor logon id>` | a new hex logon id such as `0x9A4C21` |
| `<CHANGE: machine>` | the new hidden account's name **without** the trailing `$` (the template appends it), a stem never used before, e.g. `svcprintNN`; it must not be the name of an existing user or computer |
| `<CHANGE: machine RID>` | a new RID for the hidden account, 3300 or higher, different from the actor's |

**Route A (WEC).** Call **`wec-sender.send_events`** once with this body:

```json
{
  "events": [
    {
      "event_id": 4720,
      "computer": "PHDC02",
      "time": "now-120s",
      "provider": "Microsoft-Windows-Security-Auditing",
      "rendering": {
        "message": "A user account was created.\n\nSubject:\n\tSecurity ID:\t\tS-1-5-21-3623811015-3361044348-30300820-<CHANGE: actor RID>\n\tAccount Name:\t\t<CHANGE: actor>\n\tAccount Domain:\t\tPHANTOM\n\tLogon ID:\t\t<CHANGE: actor logon id>\n\nNew Account:\n\tSecurity ID:\t\tS-1-5-21-3623811015-3361044348-30300820-<CHANGE: machine RID>\n\tAccount Name:\t\t<CHANGE: machine>$\n\tAccount Domain:\t\tPHANTOM\n\nAttributes:\n\tSAM Account Name:\t<CHANGE: machine>$\n\tDisplay Name:\t\t-\n\tUser Principal Name:\t-",
        "task": "User Account Management"
      },
      "event_data": {
        "SubjectUserSid": "S-1-5-21-3623811015-3361044348-30300820-<CHANGE: actor RID>",
        "SubjectUserName": "<CHANGE: actor>",
        "SubjectDomainName": "PHANTOM",
        "SubjectLogonId": "<CHANGE: actor logon id>",
        "TargetUserName": "<CHANGE: machine>$",
        "TargetDomainName": "PHANTOM",
        "TargetSid": "S-1-5-21-3623811015-3361044348-30300820-<CHANGE: machine RID>",
        "SamAccountName": "<CHANGE: machine>$",
        "DisplayName": "-",
        "UserPrincipalName": "-",
        "PrivilegeList": "-"
      }
    }
  ]
}
```

**Route B (Cribl).** Call **`http-sender.send_events`** once with the SAME `events` list, plus the destination. Do not build any XML: the connector renders each event to Windows Event XML itself.

```text
http-sender.send_events
{"events": <the same events list as Route A>, "destination": "cribl_windows_events"}
```

The answer carries `ok: true`, `destination: cribl_windows_events`, `dataset: microsoft_windows_raw` and `num_records` equal to the number of events.

What matters and why:

- **`event_id` 4720 on the DC `PHDC02`**: "a user account was created". The alert carries the tag `R:Domain Controllers`, so the host is a domain controller.
- **The name ends in `$`** in `TargetUserName`, `SamAccountName` and the message text, while the object is an ordinary user (`TargetSid` is a domain SID, `PrivilegeList` `-`). That is the whole signal: a user mimicking a machine account.
- **The actor is an ordinary new account** (not a machine account, not a person). The alert text says the new account "has not been seen in the past 30 days"; both the actor and the hidden name must be new.
- **`rendering.message`/`task`/`provider`** are required (event 4720 is not catalogued); keep the layout (tabs, blank lines).
- **Free to change**: the actor, both RIDs, the logon id and the hidden name's stem.

## Step 2: confirm the event landed and modeled (about 1 to 2 minutes after Step 1)

```text
config timeframe = 1h | datamodel dataset = microsoft_windows_raw
| filter xdm.event.id = "4720" and xdm.source.user.username = "<actor>"
| fields _time, xdm.event.id, xdm.source.user.username, xdm.source.host.hostname, xdm.event.description
```

Pass when **1 row** returns for host `PHDC02.phantom.lab` and `xdm.event.description` contains `Account Name:` followed by your hidden account name ending in `$`. To prove which route carried it:

```text
config timeframe = 1h | dataset = microsoft_windows_raw
| filter event_id = "4720" and message contains "<hidden account>$"
| fields _time, computer_name, event_id, _transport, _collector_type
```

Route A shows `_collector_type = WEC` and no `_transport`; Route B shows `_transport = cribl` and no `_collector_type`.

## Step 3: wait, then check for the alert

Check **1 minute** after the send, then every minute for up to **15 minutes** (it typically arrives within a minute):

```text
config timeframe = 1d
| dataset = alerts
| filter alert_source in ("MAGNIFIER", "ANALYTICS_BIOC") and alert_name = "Suspicious hidden user created"
| fields _time, alert_id, alert_name, severity, host_name, user_name, description, alert_arrival_timestamp
| sort desc alert_arrival_timestamp
| limit 5
```

Pass when a new row names your actor and your hidden account (`The new user created: phantom\<name>$`). The filter uses the **stored** enum names `MAGNIFIER` and `ANALYTICS_BIOC`; the displayed names (`XDR_ANALYTICS...`) match nothing.

If nothing arrives in 15 minutes: confirm Step 2 (the event must be in `microsoft_windows_raw` and modeled, with the stamps of the route you used), confirm every identity was new (precondition 2), then retry **once** with a new actor, new RIDs and a new hidden-account stem. Do not change the event body.

## Report back to the operator

State the route used, the actor, the hidden account name, the RIDs and the host name, the number of events sent, the Step 2 result and either the alert id with the arrival time or that nothing arrived in 15 minutes and what you checked. Say that the actor and the hidden account's name must not be reused: the detector's history is per account and its deduplication is one day.
