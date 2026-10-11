---
name: trigger_machine_account_domain_admins_alert
displayName: Trigger the Cortex "Machine account was added to a domain admins group" analytics alert
category: workflows
description: 'Fire Cortex XSIAM''s native "Machine account was added to a domain admins group" analytics BIOC (Medium, T1078.002) by sending ONE synthetic Windows Security event 4728 through the wec-sender connector (Windows Event Collector, Route A) or through http-sender with destination cribl_windows_events (the tenant Cribl endpoint with the Windows UUID, Route B): a computer account added to the Domain Admins group by a new administrator account. The same event also raises "User added to a Windows privileged group". Use when the operator asks to trigger, demo, prove or reproduce a machine account added to domain admins, a computer account in a privileged group, or a 4728 alert. It fires over both routes and never over syslog/CEF.'
icon: admin_panel_settings
source: platform
loadingMode: on-demand
locked: false
---

# Skill: Trigger the "Machine account was added to a domain admins group" alert

## When this skill applies

The operator wants the native **Cortex Analytics detector for a computer account placed in Domain Admins** to fire, for example: *"trigger a machine-account-to-domain-admins alert"*, *"show a computer account being added to Domain Admins"*, *"prove T1078.002 fires from Windows events"*. It fires from one event; the same event also raises the sibling alert **User added to a Windows privileged group** (see `trigger_privileged_group_add_alert`).

The detector is **not a correlation rule**; it is Cortex's own analytics (XDR Analytics BIOC), and nothing needs installing on the tenant beyond the Windows pack that already models `microsoft_windows_raw`. It reads Windows events that arrive through a registered Windows source, so the call below goes either to `wec-sender.send_events` (Route A) or to `http-sender.send_events` with `destination: "cribl_windows_events"` (Route B, see "Route B: Cribl"), never to a syslog/CEF worker.

> **Expected result.** The alert typically arrives within a minute or two of the call, and the privileged-group sibling with it.

## What the detector looks for (Cortex doc: "Machine account was added to a domain admins group")

| Property | Value |
|---|---|
| Alert name | `Machine account was added to a domain admins group` (Medium) |
| Source | `XDR Analytics BIOC`, MITRE T1078.002 Valid Accounts: Domain Accounts; alert tags `DT:Identity Analytics`, `DS:Microsoft/Windows` |
| Required data (doc) | Windows Event Collector OR XDR Agent with eXtended Threat Hunting (XTH); the doc lists the Identity Analytics module |
| Activation / training (doc) | 14 days / 30 days in the documentation; in practice every alert arrives within minutes of its events |
| Test period | single event |
| Deduplication | 1 day |
| What the alert text says | *"The machine account <host> was added to a group with Domain Admins privileges by the user <domain>\<actor>. The name of the group is Domain Admins. The group is on the domain PHANTOM. This is a major security flaw that will grant services running with the machine account full control of the domain"* |

## Which delivery paths fire it (WEC and Cribl, never syslog/CEF)

The detectors in this family read Windows events that arrive through a registered Windows source. Over syslog/CEF the same event types **land and model** in `microsoft_windows_raw` but are stamped `_collector_type = Syslog`, and no Windows identity alert fires from them (DCSync, Kerberoasting, account-management batches, machine accounts and delegation sent over CEF raise none). Two paths carry the same structured events and **both fire**:

- **Route A, WEC**: `wec-sender.send_events` delivers through the Broker VM's Windows Event Collector over mutual TLS. The rows are stamped `_collector_type = WEC`.
- **Route B, Cribl**: `http-sender.send_events` with `destination: "cribl_windows_events"` renders the same events to Windows Event XML and posts them to the tenant's Cribl endpoint with the Windows UUID. The rows land in the same dataset with `_transport = cribl` and no `_collector_type`, with the same columns and `xdm.*` fields. All nine Windows recipes (this one included) fire over Cribl, within seconds to under two minutes of sending. It needs no Broker, no certificate and no subscription.

Do not "test it quickly" over syslog/CEF: a null result there says nothing about the rule.

## Preconditions: check these BEFORE sending

| # | Must be true | How to check |
|---|---|---|
| 1A | Route A only: the `wec-sender` connector instance is running and `wec-sender.list_subscriptions` returns `ok: true` with a subscription whose channels include `Security` (for example a subscription named "Authentication Event Logs" on the Broker VM, port 5986). Without the Windows Event Collector path Route A cannot fire | call `wec-sender.list_subscriptions` |
| 1B | Route B only: the `http-sender` instance has `criblUrl` and `criblToken` set, so `http-sender.list_destinations` lists `cribl_windows_events` with `ready: true` and `dataset: microsoft_windows_raw`. Route B needs no Broker, no certificate and no subscription | call `http-sender.list_destinations` |
| 2 | Every identity below is **new**: a user name and a RID never used in an earlier run, and a user name that is not a person's. The detectors report a first-time action per account, and their history is kept per account for 30 days | `config timeframe = 30d \| datamodel dataset = microsoft_windows_raw \| filter xdm.source.user.username = "<actor>" \| limit 1` returns **no row** |
| 3 | Every event time is **now** or a few minutes earlier, UTC. Write it as `now-310s` (the connector resolves it with its own clock; an absolute `YYYY-MM-DDTHH:MM:SSZ` also works): the connector turns `time` into the event's TimeCreated and that becomes `_time`, and the detector windows are evaluated on it. Never in the future | generate at call time |


## Expected result

The event in Step 1, with a new actor, computer and RIDs, fires the alert over both routes, typically within a minute or two of the send, and the privileged-group alert `User added to a Windows privileged group` comes with it (Medium).

Does **not** fire: the same 4728 into `Helpdesk Admins` (a user member), which is expected for a Domain Admins rule.

## Step 1: send the events (exactly this call)

**Route A (WEC).** Call **`wec-sender.send_events`** once with the 1 event below. Replace only the values marked `<CHANGE: ...>` (the same label means the same value everywhere it appears); everything else is the verbatim shape that fires.

| Placeholder | Put here |
|---|---|
| `now-Ns` (also `now`, `now-5m`, `now-1h`) | **leave it as this literal text, do not work out a date or time yourself**: the connector replaces it with its own current UTC time minus N seconds when it sends |
| `<CHANGE: actor>` | a new account name that is not a person's, e.g. `adm.runNNNN` (letters, digits, dot) |
| `<CHANGE: actor RID>` | a new RID, 3300 or higher, never reused (the SID is `S-1-5-21-3623811015-3361044348-30300820-<RID>`) |
| `<CHANGE: actor logon id>` | a new hex logon id such as `0x9A4C21` |
| `<CHANGE: machine>` | a new computer name `PHWS-<NNN>` (no `$`), used in the member DN |
| `<CHANGE: machine RID>` | a new RID for the computer, 3300 or higher, different from the actor's |

```json
{
  "events": [
    {
      "event_id": 4728,
      "computer": "PHDC02",
      "time": "now-120s",
      "provider": "Microsoft-Windows-Security-Auditing",
      "rendering": {
        "message": "A member was added to a security-enabled global group.\n\nSubject:\n\tSecurity ID:\t\tS-1-5-21-3623811015-3361044348-30300820-<CHANGE: actor RID>\n\tAccount Name:\t\t<CHANGE: actor>\n\tAccount Domain:\t\tPHANTOM\n\tLogon ID:\t\t<CHANGE: actor logon id>\n\nMember:\n\tSecurity ID:\t\tS-1-5-21-3623811015-3361044348-30300820-<CHANGE: machine RID>\n\tAccount Name:\t\tCN=<CHANGE: machine>,CN=Computers,DC=phantom,DC=lab\n\nGroup:\n\tSecurity ID:\t\tS-1-5-21-3623811015-3361044348-30300820-512\n\tGroup Name:\t\tDomain Admins\n\tGroup Domain:\t\tPHANTOM\n\nAdditional Information:\n\tPrivileges:\t\t-",
        "task": "Security Group Management"
      },
      "event_data": {
        "MemberName": "CN=<CHANGE: machine>,CN=Computers,DC=phantom,DC=lab",
        "MemberSid": "S-1-5-21-3623811015-3361044348-30300820-<CHANGE: machine RID>",
        "SubjectUserSid": "S-1-5-21-3623811015-3361044348-30300820-<CHANGE: actor RID>",
        "SubjectUserName": "<CHANGE: actor>",
        "SubjectDomainName": "PHANTOM",
        "SubjectLogonId": "<CHANGE: actor logon id>",
        "TargetUserName": "Domain Admins",
        "TargetDomainName": "PHANTOM",
        "TargetSid": "S-1-5-21-3623811015-3361044348-30300820-512",
        "PrivilegeList": "-"
      }
    }
  ]
}
```

What matters and why:

- **`event_id` 4728 on the DC `PHDC02`**: "a member was added to a security-enabled global group". The detector reads the group and the member.
- **Group**: `TargetUserName` `Domain Admins`, `TargetSid` ending `-512` (the well-known Domain Admins RID), in the message text too. Another group name (the same call with "Helpdesk Admins") raises nothing.
- **Member**: `MemberName` is the computer's distinguished name under `CN=Computers`, and `MemberSid` its SID. The alert text names the computer without a `$` (for example `PHWS-110`). Whether the `CN=Computers` path or the SID is what marks it as a machine account was not isolated.
- **`rendering.message` and `rendering.task`**: the message text carries the same subject, member and group; keep the layout (tabs, blank lines). `provider` must be `Microsoft-Windows-Security-Auditing`; this id is not catalogued, so the connector needs provider, message and task.
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
| filter xdm.event.id = "4728" and xdm.source.user.username = "<actor>"
| fields _time, xdm.event.id, xdm.source.user.username, xdm.target.user.groups, xdm.source.host.hostname
```

Pass when one row returns with `xdm.target.user.groups` containing `Domain Admins`. To prove the WEC stamp: `dataset = microsoft_windows_raw | filter _collector_type = "WEC" | sort desc _time | limit 5` shows the event with `_collector_type = WEC`. For Route B use `dataset = microsoft_windows_raw | filter _transport = "cribl" | sort desc _time | limit 5`: the event shows `_transport = cribl` and no `_collector_type`.

## Step 3: wait, then check for the alert

Check **1 minute** after the send, then every minute for up to **15 minutes** (the alert typically arrives within about 3 minutes):

```
dataset = alerts
| filter alert_name = "Machine account was added to a domain admins group"
| fields _time, alert_id, alert_name, severity, host_name, user_name, description
| sort desc _time
| limit 5
```

Pass when a new row names your actor and the machine account name; a second alert, `User added to a Windows privileged group`, should appear at the same time. To list Analytics alerts without naming one, filter on the STORED enum values `alert_source in ("MAGNIFIER","ANALYTICS_BIOC")`: the displayed names `XDR_ANALYTICS` and `XDR_ANALYTICS_BIOC` match nothing.

If nothing arrives in 15 minutes: confirm Step 2 (the events must be in `microsoft_windows_raw` and modeled, with the stamp of the route you used: `_collector_type = "WEC"` for Route A, `_transport = "cribl"` for Route B), confirm every identity was new (precondition 2), then retry **once** with a new actor and new RIDs. Do not change the event body.

## Report back to the operator

State the actor, the RIDs and the host names used, the number of events sent, the Step 2 result and either the alert id with the arrival time or that nothing arrived in 15 minutes and what you checked. Say that the actor must not be reused: the detector's history is per account and its deduplication is one day.
