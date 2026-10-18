---
name: trigger_delegation_to_krbtgt_alert
displayName: Trigger the Cortex "User account delegation to KRBTGT" analytics alert
category: workflows
description: 'Fire Cortex XSIAM''s native "User account delegation to KRBTGT" analytics BIOC (High, T1558) by sending ONE synthetic Windows Security event 4738 through the wec-sender connector (Windows Event Collector, Route A) or through http-sender with destination cribl_windows_events (the tenant Cribl endpoint with the Windows UUID, Route B): a new account sets constrained delegation to krbtgt/PHANTOM.LAB on a user account. Use when the operator asks to trigger, demo, prove or reproduce a delegation to krbtgt, a Kerberos delegation abuse or a 4738 AllowedToDelegateTo alert. It fires over both routes and never over syslog/CEF.'
icon: security
source: platform
loadingMode: on-demand
locked: false
---

# Skill: Trigger the "User account delegation to KRBTGT" alert

## When this skill applies

The operator wants the native **Cortex Analytics delegation-to-krbtgt detector** to fire, for example: *"trigger a delegation to krbtgt alert"*, *"show a user account allowed to delegate to the KDC"*, *"prove T1558 fires from Windows events"*.

The detector is **not a correlation rule**; it is Cortex's own analytics (XDR Analytics BIOC), and nothing needs installing on the tenant beyond the Windows pack that already models `microsoft_windows_raw`. It reads Windows events that arrive through a registered Windows source, so the call below goes either to `wec-sender.send_events` (Route A) or to `http-sender.send_events` with `destination: "cribl_windows_events"` (Route B), never to a syslog/CEF worker.

## What the detector looks for (Cortex doc: "User account delegation change")

| Property | Value |
|---|---|
| Alert name | `User account delegation to KRBTGT` (High), a variation of the doc's `User account delegation change` (Informational, invisible). The sibling variation `User account delegation to a DC` (Low) does not fire, see below |
| Source | `XDR Analytics BIOC`, MITRE T1558 Steal or Forge Kerberos Tickets (tactic Credential Access); alert tags `DT:Identity Analytics`, `DS:Microsoft/Windows` |
| Required data (doc) | Windows Event Collector OR XDR Agent with eXtended Threat Hunting (XTH); the doc lists the Identity Analytics module |
| Activation / training (doc) | 14 days / 30 days. In practice the alert typically arrives within a minute or two of its events |
| Test period | single event |
| Deduplication | 1 day |
| What the alert text says | *"A user account was modified with delegation to a service. The account set was <domain>\<target user>. The SPNs set: krbtgt/PHANTOM.LAB. This change was made by <domain>\<actor>. This may indicate the ability to generate TGTs for any account in Active Directory"* |

Did **not** fire `User account delegation to a DC` (Low): `AllowedToDelegateTo` of `ldap/PHDC02.phantom.lab/phantom.lab` and of `ldap/PHDC02.phantom.lab` (the second together with a 5136 `msDS-AllowedToDelegateTo` event), both 4738 on a user account. Only the `krbtgt/...` target raises an alert.

## Which delivery paths fire it (WEC and Cribl, never syslog/CEF)

The detectors in this family read Windows events that arrive through a registered Windows source. Over syslog/CEF the same event types **land and model** in `microsoft_windows_raw` but are stamped `_collector_type = Syslog`, and no Windows identity alert fires from them (the same scenarios sent over syslog/CEF raised none). Two paths carry the same structured events and **both fire**:

- **Route A, WEC**: `wec-sender.send_events` delivers through the Broker VM's Windows Event Collector over mutual TLS. The rows are stamped `_collector_type = WEC`.
- **Route B, Cribl**: `http-sender.send_events` with `destination: "cribl_windows_events"` renders the same events to Windows Event XML and posts them to the tenant's Cribl endpoint with the Windows UUID. The rows land in the same dataset with `_transport = cribl` and no `_collector_type`, with the same columns and `xdm.*` fields. It needs no Broker, no certificate and no subscription.

Do not "test it quickly" over syslog/CEF: a null result there says nothing about the rule.

**This is NOT a mapping problem.** Over syslog/CEF the event already lands in `microsoft_windows_raw` and the modeling rule already fills the same `xdm.*` fields (the syslog `MicrosoftWindowsEvents` source maps 58 of them), so a good mapping there proves nothing about this alert. The alert will not fire over syslog/CEF no matter how complete the mapping is: the detector reads the registered Windows source (the WEC, native-agent or dedicated-UUID Cribl feed), not the syslog/CEF feed. `_collector_type = WEC` is stamped by a real Windows Event Collector delivery and cannot be set from an event body, so no CEF extension, field choice or schema change can reach it.

## Preconditions: check these BEFORE sending

| # | Must be true | How to check |
|---|---|---|
| 1A | Route A only: the `wec-sender` connector instance is running and `wec-sender.list_subscriptions` returns `ok: true` with a subscription whose channels include `Security` (for example the subscription "Authentication Event Logs" on the Broker VM, port 5986) | call `wec-sender.list_subscriptions` |
| 1B | Route B only: the `http-sender` instance has `criblUrl` and `criblToken` set, so `http-sender.list_destinations` lists `cribl_windows_events` with `ready: true` and `dataset: microsoft_windows_raw` | call `http-sender.list_destinations` |
| 2 | Every identity below is **new**: a user name, a computer name and a RID never used in an earlier run (use **3300 or higher** and never reuse one), and a user name that is not a person's. The detector reports a first-time action per account, and its history is kept per account for 30 days. | `config timeframe = 30d \| datamodel dataset = microsoft_windows_raw \| filter xdm.source.user.username = "<actor>" \| limit 1` returns **no row** |
| 3 | Every event time is **now** or a few minutes earlier, UTC. Write it as `now-310s` (the connector resolves it with its own clock; an absolute `YYYY-MM-DDTHH:MM:SSZ` also works): the connector turns `time` into the event's TimeCreated and that becomes `_time`, and the detector windows are evaluated on it. Never in the future | generate at call time |


## Expected result

The recipe fires from a new account that sets `krbtgt/PHANTOM.LAB` on a new user account, over Route A (WEC) and over Route B (Cribl). The High alert names the actor (`phantom\<actor>`) and typically arrives within a minute or two (counted from the start of the send call). Every run must use identities (actor, RIDs, computer names) never seen before.

## Step 1: send the events (exactly this call)

**Route A (WEC).** Call **`wec-sender.send_events`** once with the 1 event below. Replace only the values marked `<CHANGE: ...>` (the same label means the same value everywhere it appears); everything else is the verbatim shape that fires.

| Placeholder | Put here |
|---|---|
| `now-Ns` (also `now`, `now-5m`, `now-1h`) | **leave it as this literal text, do not work out a date or time yourself**: the connector replaces it with its own current UTC time minus N seconds when it sends |
| `<CHANGE: actor>` | a new account name that is not a person's, e.g. `adm.runNNNN` (letters, digits, dot) |
| `<CHANGE: actor RID>` | a new RID, 3300 or higher, never reused (the SID is `S-1-5-21-3623811015-3361044348-30300820-<RID>`) |
| `<CHANGE: actor logon id>` | a new hex logon id such as `0x9A4C21` |
| `<CHANGE: machine RID>` | a new RID for the target user account, 3300 or higher, different from the actor's; the account is named `svc.dl.<actor RID>` |

```json
{
  "events": [
    {
      "event_id": 4738,
      "computer": "PHDC02",
      "time": "now-120s",
      "provider": "Microsoft-Windows-Security-Auditing",
      "rendering": {
        "message": "A user account was changed.\n\nSubject:\n\tSecurity ID:\t\tS-1-5-21-3623811015-3361044348-30300820-<CHANGE: actor RID>\n\tAccount Name:\t\t<CHANGE: actor>\n\tAccount Domain:\t\tPHANTOM\n\tLogon ID:\t\t<CHANGE: actor logon id>\n\nTarget Account:\n\tSecurity ID:\t\tS-1-5-21-3623811015-3361044348-30300820-<CHANGE: machine RID>\n\tAccount Name:\t\tsvc.dl.<CHANGE: actor RID>\n\tAccount Domain:\t\tPHANTOM\n\nChanged Attributes:\n\tSAM Account Name:\t-\n\tDisplay Name:\t-\n\tUser Principal Name:\t-\n\tHome Directory:\t-\n\tHome Drive:\t-\n\tScript Path:\t-\n\tProfile Path:\t-\n\tUser Workstations:\t-\n\tPassword Last Set:\t-\n\tAccount Expires:\t-\n\tPrimary Group ID:\t-\n\tAllowedToDelegateTo:\tkrbtgt/PHANTOM.LAB\n\tOld UAC Value:\t0x10\n\tNew UAC Value:\t0x1000010\n\tUser Account Control:\t\n\t\t'Trusted To Authenticate For Delegation' - Enabled\n\tUser Parameters:\t-\n\tSID History:\t-\n\tLogon Hours:\t-\n\nAdditional Information:\n\tPrivileges:\t\t-",
        "task": "User Account Management"
      },
      "event_data": {
        "Dummy": "-",
        "SubjectUserSid": "S-1-5-21-3623811015-3361044348-30300820-<CHANGE: actor RID>",
        "SubjectUserName": "<CHANGE: actor>",
        "SubjectDomainName": "PHANTOM",
        "SubjectLogonId": "<CHANGE: actor logon id>",
        "TargetUserName": "svc.dl.<CHANGE: actor RID>",
        "TargetDomainName": "PHANTOM",
        "TargetSid": "S-1-5-21-3623811015-3361044348-30300820-<CHANGE: machine RID>",
        "PrivilegeList": "-",
        "SamAccountName": "-",
        "DisplayName": "-",
        "UserPrincipalName": "-",
        "HomeDirectory": "-",
        "HomePath": "-",
        "ScriptPath": "-",
        "ProfilePath": "-",
        "UserWorkstations": "-",
        "PasswordLastSet": "-",
        "AccountExpires": "-",
        "PrimaryGroupId": "-",
        "AllowedToDelegateTo": "krbtgt/PHANTOM.LAB",
        "OldUacValue": "0x10",
        "NewUacValue": "0x1000010",
        "UserAccountControl": "\n\t\t%%2096",
        "UserParameters": "-",
        "SidHistory": "-",
        "LogonHours": "-"
      }
    }
  ]
}
```

What matters and why:

- **`event_id` 4738** (a user account was changed) on the domain controller `PHDC02`, with the full real 4738 field list (every attribute not changed is `-`). The changed attribute is **`AllowedToDelegateTo`**: **`krbtgt/PHANTOM.LAB`**. That value is the whole detection.
- **`OldUacValue 0x10` to `NewUacValue 0x1000010`** (the `Trusted To Authenticate For Delegation` flag, `%%2096`) is the flag value Windows uses for constrained delegation with protocol transition; the message repeats it in clear text. Whether the detector reads these two fields is not established; the `AllowedToDelegateTo` value is the known trigger.
- **The target is a new user account** (`svc.dl.<actor RID>`, SID `...-<machine RID>`), changed by a **new** subject.
- **`rendering.message`/`task`/`provider`** are required (not catalogued). The `Changed Attributes:` block repeats `AllowedToDelegateTo: krbtgt/PHANTOM.LAB`; keep the layout.
- **Free to change**: the actor, the RIDs, the logon id. Do not change the delegation target: `ldap/<DC>` does not fire.

## Route B: Cribl (same events, same alert)

Send the **same 1 event as Step 1** through the tenant's Cribl endpoint instead of the Windows Event Collector: call **`http-sender.send_events`** once with the same `events` list (every `<CHANGE: ...>` filled exactly as in Step 1) plus the destination. Do not build any XML: the connector renders each event to Windows Event XML itself. Precondition 1B applies instead of 1A.

```text
http-sender.send_events
{"events": <the same events list as Step 1>, "destination": "cribl_windows_events"}
```

The answer carries `ok: true`, `destination: cribl_windows_events`, `dataset: microsoft_windows_raw` and `num_records` equal to the number of events. The rows land in `microsoft_windows_raw` with `_transport = "cribl"` and no `_collector_type`; the columns and `xdm.*` fields are the same as over WEC, so Steps 2 and 3 are unchanged (only the stamp check differs).

## Step 2: confirm the events landed and modeled (about 2 minutes after Step 1)

```
config timeframe = 1h | datamodel dataset = microsoft_windows_raw
| filter xdm.event.id = "4738" and xdm.source.identity.username = "<actor>"
| fields _time, xdm.event.id, xdm.source.identity.username, xdm.source.host.hostname, xdm.event.description
```

Pass when one row returns for host `PHDC02.phantom.lab` and its description contains `krbtgt/PHANTOM.LAB`. Over Route A add `_collector_type = "WEC"` (raw dataset) and over Route B `_transport = "cribl"` to confirm the stamp.

## Step 3: wait, then check for the alert

Check **1 minute** after the send, then every minute for up to **15 minutes** (it typically arrives within a minute or two):

```
dataset = alerts
| filter alert_name = "User account delegation to KRBTGT"
| fields _time, alert_id, alert_name, severity, host_name, user_name, description
| sort desc _time
| limit 5
```

Pass when a new row names your actor. To list Analytics alerts without naming one, filter on the STORED enum values `alert_source in ("MAGNIFIER","ANALYTICS_BIOC")`: the displayed names `XDR_ANALYTICS` and `XDR_ANALYTICS_BIOC` match nothing.

If nothing arrives in 15 minutes: confirm Step 2, confirm every identity was new (precondition 2), then retry **once** with a new actor and new RIDs. Do not change the event body.

## Report back to the operator

State the actor, the RIDs, the target account used, the number of events sent, the Step 2 result and either the alert id (High) with the arrival time or that nothing arrived in 15 minutes and what you checked. Say that the actor must not be reused: the detector's deduplication is one day.
