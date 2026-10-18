---
name: trigger_privileged_group_add_alert
displayName: Trigger the Cortex "User added to a Windows privileged group" analytics alert
category: workflows
description: 'Fire Cortex XSIAM''s native "User added to a Windows privileged group" analytics BIOC (Low, T1098) by sending ONE synthetic Windows Security event 4728 through the wec-sender connector (Windows Event Collector, Route A) or through http-sender with destination cribl_windows_events (the tenant Cribl endpoint with the Windows UUID, Route B): an account added to the Domain Admins group by a new administrator account. Use when the operator asks to trigger, demo, prove or reproduce a user added to a privileged or admin group, a Domain Admins membership change, or a 4728 alert. It fires over both routes and never over syslog/CEF.'
icon: admin_panel_settings
source: platform
loadingMode: on-demand
locked: false
---

# Skill: Trigger the "User added to a Windows privileged group" alert

## When this skill applies

The operator wants the native **Cortex Analytics detector for an account added to a privileged Windows group** to fire, for example: *"trigger a privileged group alert"*, *"show someone added to Domain Admins"*, *"prove T1098 fires from Windows events"*. It is a sibling of `trigger_machine_account_domain_admins_alert`: the machine-account variant of the same 4728 raises both alerts.

The detector is **not a correlation rule**; it is Cortex's own analytics (XDR Analytics BIOC), and nothing needs installing on the tenant beyond the Windows pack that already models `microsoft_windows_raw`. It reads Windows events that arrive through a registered Windows source, so the call below goes either to `wec-sender.send_events` (Route A) or to `http-sender.send_events` with `destination: "cribl_windows_events"` (Route B, see "Route B: Cribl"), never to a syslog/CEF worker.

>

## What the detector looks for (Cortex doc: "A user was added to a Windows security group")

| Property | Value |
|---|---|
| Alert name | `User added to a Windows privileged group` (Low), a variation of the doc's `A user was added to a Windows security group` (Informational, invisible) |
| Source | `XDR Analytics BIOC`, MITRE T1098 Account Manipulation, T1078 Valid Accounts; alert tags `DT:Identity Analytics`, `DS:Microsoft/Windows` |
| Required data (doc) | Windows Event Collector OR XDR Agent with eXtended Threat Hunting (XTH); the doc lists the Identity Analytics module |
| Activation / training (doc) | 14 days / 30 days. In practice the alert typically arrives within a minute or two of its events |
| Test period | single event |
| Deduplication | 1 day |
| What the alert text says | *"The user <member> was added to a privileged security group. This action was performed by the user <domain>\<actor>. The name of the group is Domain Admins. The group is on the domain PHANTOM"* |

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

The recipe fires from a new administrator account adding a **user** member to `Domain Admins` (4728), over Route A and over Route B; the alert typically arrives within a minute or two of the send. The machine-account alert does **not** fire for a user member.

Did **not** fire: a user added to `Helpdesk Admins` (4728).

## Step 1: send the events (exactly this call)

**Route A (WEC).** Call **`wec-sender.send_events`** once with the 1 event below. Replace only the values marked `<CHANGE: ...>` (the same label means the same value everywhere it appears); everything else is the verbatim shape that fires.

| Placeholder | Put here |
|---|---|
| `now-Ns` (also `now`, `now-5m`, `now-1h`) | **leave it as this literal text, do not work out a date or time yourself**: the connector replaces it with its own current UTC time minus N seconds when it sends |
| `<CHANGE: actor>` | a new account name that is not a person's, e.g. `adm.runNNNN` (letters, digits, dot) |
| `<CHANGE: actor RID>` | a new RID, 3300 or higher, never reused (the SID is `S-1-5-21-3623811015-3361044348-30300820-<RID>`) |
| `<CHANGE: actor logon id>` | a new hex logon id such as `0x9A4C21` |
| `<CHANGE: member display name>` | the added user's display name, e.g. `Run Member NNNN`, used in the member DN |
| `<CHANGE: member RID>` | a new RID for the added user, 3300 or higher, different from the actor's |

```json
{
  "events": [
    {
      "event_id": 4728,
      "computer": "PHDC02",
      "time": "now-120s",
      "provider": "Microsoft-Windows-Security-Auditing",
      "rendering": {
        "message": "A member was added to a security-enabled global group.\n\nSubject:\n\tSecurity ID:\t\tS-1-5-21-3623811015-3361044348-30300820-<CHANGE: actor RID>\n\tAccount Name:\t\t<CHANGE: actor>\n\tAccount Domain:\t\tPHANTOM\n\tLogon ID:\t\t<CHANGE: actor logon id>\n\nMember:\n\tSecurity ID:\t\tS-1-5-21-3623811015-3361044348-30300820-<CHANGE: member RID>\n\tAccount Name:\t\tCN=<CHANGE: member display name>,OU=Users,DC=phantom,DC=lab\n\nGroup:\n\tSecurity ID:\t\tS-1-5-21-3623811015-3361044348-30300820-512\n\tGroup Name:\t\tDomain Admins\n\tGroup Domain:\t\tPHANTOM\n\nAdditional Information:\n\tPrivileges:\t\t-",
        "task": "Security Group Management"
      },
      "event_data": {
        "MemberName": "CN=<CHANGE: member display name>,OU=Users,DC=phantom,DC=lab",
        "MemberSid": "S-1-5-21-3623811015-3361044348-30300820-<CHANGE: member RID>",
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

- **`event_id` 4728 on the DC `PHDC02`**, group `Domain Admins` (`TargetSid` ending `-512`): the group that fires. A user added to `Helpdesk Admins` (4728 then 4729) raises nothing.
- **Member**: a **computer** as the member (`CN=PHWS-110,CN=Computers,...`) also fires, and the alert text calls it "the user PHWS-110". The call below uses a **user** member, which fires **without** the machine-account alert. So both a user and a computer qualify: use a user for this alert and a computer (`trigger_machine_account_domain_admins_alert`) when you want both alerts.
- **`rendering.message`/`rendering.task`/`provider`**: required for this id (not catalogued); keep the message layout.
- **Free to change**: the actor, the member and the RIDs.

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
| fields _time, xdm.event.id, xdm.source.user.username, xdm.target.user.groups, xdm.target.identity.ou
```

Pass when one row returns with `xdm.target.user.groups` containing `Domain Admins`.

## Step 3: wait, then check for the alert

Check **1 minute** after the send, then every minute for up to **15 minutes** (it typically arrives within a minute or two):

```
dataset = alerts
| filter alert_name = "User added to a Windows privileged group"
| fields _time, alert_id, alert_name, severity, host_name, user_name, description
| sort desc _time
| limit 5
```

Pass when a new row names your actor. To list Analytics alerts without naming one, filter on the STORED enum values `alert_source in ("MAGNIFIER","ANALYTICS_BIOC")`: the displayed names `XDR_ANALYTICS` and `XDR_ANALYTICS_BIOC` match nothing.

If nothing arrives in 15 minutes: confirm Step 2 (the events must be in `microsoft_windows_raw` and modeled, with the stamp of the route you used: `_collector_type = "WEC"` for Route A, `_transport = "cribl"` for Route B), confirm every identity was new (precondition 2), then retry **once** with a new actor and new RIDs. Do not change the event body.

## Report back to the operator

State the actor, the RIDs and the host names used, the number of events sent, the Step 2 result and either the alert id with the arrival time or that nothing arrived in 15 minutes and what you checked. Say that the actor must not be reused: the detector's history is per account and its deduplication is one day.
