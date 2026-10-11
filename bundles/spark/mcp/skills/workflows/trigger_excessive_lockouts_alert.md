---
name: trigger_excessive_lockouts_alert
displayName: Trigger the Cortex "Excessive user account lockouts" analytics alert
category: workflows
description: 'Fire Cortex XSIAM''s native "Excessive user account lockouts" analytics alert (Low, T1110.003 password spraying) by sending 16 synthetic Windows Security events 4740 through the wec-sender connector (Windows Event Collector, Route A) or through http-sender with destination cribl_windows_events (the tenant Cribl endpoint with the Windows UUID, Route B): 11 different accounts locked out on the domain controller within about 15 minutes. Use when the operator asks to trigger, demo, prove or reproduce a lockout storm, many account lockouts, password spraying seen as lockouts, or a 4740 alert. It fires over both routes and never over syslog/CEF.'
icon: admin_panel_settings
source: platform
loadingMode: on-demand
locked: false
---

# Skill: Trigger the "Excessive user account lockouts" alert

## When this skill applies

The operator wants the native **Cortex Analytics detector for many account lockouts** to fire, for example: *"trigger an account lockout alert"*, *"show a password spray as lockouts"*.

The detector is **not a correlation rule**; it is Cortex's own analytics (XDR Analytics), and nothing needs installing on the tenant beyond the Windows pack that already models `microsoft_windows_raw`. It reads Windows events that arrive through a registered Windows source, so the call below goes either to `wec-sender.send_events` (Route A) or to `http-sender.send_events` with `destination: "cribl_windows_events"` (Route B, see "Route B: Cribl"), never to a syslog/CEF worker.

> **Expected result.** The alert typically arrives within a minute or two of the call and reports the caller host as the origin.

## What the detector looks for (Cortex doc: "Excessive user account lockouts")

| Property | Value |
|---|---|
| Alert name | `Excessive user account lockouts` (Low; the catalog also lists `... from a suspicious source` and `... on suspicious users`, Medium, which do not fire) |
| Source | `XDR Analytics`, MITRE T1110 Brute Force, T1110.003 Password Spraying; alert tags `DT:Identity Analytics`, `DS:Microsoft/Windows` |
| Required data (doc) | Windows Event Collector OR XDR Agent with eXtended Threat Hunting (XTH); the doc lists the Identity Analytics module |
| Activation / training (doc) | 14 days / 30 days in the documentation; in practice every alert arrives within minutes of its events |
| Test period | 1 hour |
| Deduplication | 1 day |
| What the alert text says | *"11 users were locked out in the past hour. These lockouts originated from host PHANTOM. The locked-out users: a.hindi, f.harbi, h.anazi and 8 more... Over the past 30 days, this source host has generated an average of 0 lockouts per day"* |

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

The 16 events in Step 1, with ten new users plus one repeated account and a new caller host, fire the alert over both routes, typically within a minute or two of the send: "11 users ... originated from host <caller host>".

Does **not** fire: 12 events 4740 on **one** account, which is the separate single-account lockout detector.

## Step 1: send the events (exactly this call)

**Route A (WEC).** Call **`wec-sender.send_events`** once with the 16 events below. Replace only the values marked `<CHANGE: ...>` (the same label means the same value everywhere it appears); everything else is the verbatim shape that fires.

| Placeholder | Put here |
|---|---|
| `now-Ns` (also `now`, `now-5m`, `now-1h`) | **leave it as this literal text, do not work out a date or time yourself**: the connector replaces it with its own current UTC time minus N seconds when it sends |
| `<CHANGE: caller host>` | a new workstation name `PHWS-<NNN>`, the host the lockouts come from; the same value in every event, in `TargetDomainName` and in the message |
| `<CHANGE: lockout user 1>` | ten different new account names, `<CHANGE: lockout user 1>` to `<CHANGE: lockout user 10>`, e.g. `l.uNNNN` |
| `<CHANGE: lockout RID 1>` | a new RID per lockout user, `lockout RID 1` to `lockout RID 10`, 4000 or higher, all different |
| `<CHANGE: repeat lockout user>` | one more new account name, used in the last six events |
| `<CHANGE: repeat lockout RID>` | its RID, 4000 or higher |

```json
{
  "events": [
    {"event_id": 4740, "computer": "PHDC02", "time": "now-900s", "provider": "Microsoft-Windows-Security-Auditing", "rendering": {"message": "A user account was locked out.\n\nSubject:\n\tSecurity ID:\t\tS-1-5-18\n\tAccount Name:\t\tSYSTEM\n\tAccount Domain:\t\tPHANTOM\n\tLogon ID:\t\t0x3E7\n\nAccount That Was Locked Out:\n\tSecurity ID:\t\tS-1-5-21-3623811015-3361044348-30300820-<CHANGE: lockout RID 1>\n\tAccount Name:\t\t<CHANGE: lockout user 1>\n\nAdditional Information:\n\tCaller Computer Name:\t\t<CHANGE: caller host>", "task": "User Lockout"}, "event_data": {"SubjectUserSid": "S-1-5-18", "SubjectUserName": "PHDC02$", "SubjectDomainName": "PHANTOM", "SubjectLogonId": "0x3E7", "TargetUserName": "<CHANGE: lockout user 1>", "TargetDomainName": "<CHANGE: caller host>", "TargetSid": "S-1-5-21-3623811015-3361044348-30300820-<CHANGE: lockout RID 1>"}},
    {"event_id": 4740, "computer": "PHDC02", "time": "now-870s", "provider": "Microsoft-Windows-Security-Auditing", "rendering": {"message": "A user account was locked out.\n\nSubject:\n\tSecurity ID:\t\tS-1-5-18\n\tAccount Name:\t\tSYSTEM\n\tAccount Domain:\t\tPHANTOM\n\tLogon ID:\t\t0x3E7\n\nAccount That Was Locked Out:\n\tSecurity ID:\t\tS-1-5-21-3623811015-3361044348-30300820-<CHANGE: lockout RID 2>\n\tAccount Name:\t\t<CHANGE: lockout user 2>\n\nAdditional Information:\n\tCaller Computer Name:\t\t<CHANGE: caller host>", "task": "User Lockout"}, "event_data": {"SubjectUserSid": "S-1-5-18", "SubjectUserName": "PHDC02$", "SubjectDomainName": "PHANTOM", "SubjectLogonId": "0x3E7", "TargetUserName": "<CHANGE: lockout user 2>", "TargetDomainName": "<CHANGE: caller host>", "TargetSid": "S-1-5-21-3623811015-3361044348-30300820-<CHANGE: lockout RID 2>"}},
    {"event_id": 4740, "computer": "PHDC02", "time": "now-840s", "provider": "Microsoft-Windows-Security-Auditing", "rendering": {"message": "A user account was locked out.\n\nSubject:\n\tSecurity ID:\t\tS-1-5-18\n\tAccount Name:\t\tSYSTEM\n\tAccount Domain:\t\tPHANTOM\n\tLogon ID:\t\t0x3E7\n\nAccount That Was Locked Out:\n\tSecurity ID:\t\tS-1-5-21-3623811015-3361044348-30300820-<CHANGE: lockout RID 3>\n\tAccount Name:\t\t<CHANGE: lockout user 3>\n\nAdditional Information:\n\tCaller Computer Name:\t\t<CHANGE: caller host>", "task": "User Lockout"}, "event_data": {"SubjectUserSid": "S-1-5-18", "SubjectUserName": "PHDC02$", "SubjectDomainName": "PHANTOM", "SubjectLogonId": "0x3E7", "TargetUserName": "<CHANGE: lockout user 3>", "TargetDomainName": "<CHANGE: caller host>", "TargetSid": "S-1-5-21-3623811015-3361044348-30300820-<CHANGE: lockout RID 3>"}},
    {"event_id": 4740, "computer": "PHDC02", "time": "now-810s", "provider": "Microsoft-Windows-Security-Auditing", "rendering": {"message": "A user account was locked out.\n\nSubject:\n\tSecurity ID:\t\tS-1-5-18\n\tAccount Name:\t\tSYSTEM\n\tAccount Domain:\t\tPHANTOM\n\tLogon ID:\t\t0x3E7\n\nAccount That Was Locked Out:\n\tSecurity ID:\t\tS-1-5-21-3623811015-3361044348-30300820-<CHANGE: lockout RID 4>\n\tAccount Name:\t\t<CHANGE: lockout user 4>\n\nAdditional Information:\n\tCaller Computer Name:\t\t<CHANGE: caller host>", "task": "User Lockout"}, "event_data": {"SubjectUserSid": "S-1-5-18", "SubjectUserName": "PHDC02$", "SubjectDomainName": "PHANTOM", "SubjectLogonId": "0x3E7", "TargetUserName": "<CHANGE: lockout user 4>", "TargetDomainName": "<CHANGE: caller host>", "TargetSid": "S-1-5-21-3623811015-3361044348-30300820-<CHANGE: lockout RID 4>"}},
    {"event_id": 4740, "computer": "PHDC02", "time": "now-780s", "provider": "Microsoft-Windows-Security-Auditing", "rendering": {"message": "A user account was locked out.\n\nSubject:\n\tSecurity ID:\t\tS-1-5-18\n\tAccount Name:\t\tSYSTEM\n\tAccount Domain:\t\tPHANTOM\n\tLogon ID:\t\t0x3E7\n\nAccount That Was Locked Out:\n\tSecurity ID:\t\tS-1-5-21-3623811015-3361044348-30300820-<CHANGE: lockout RID 5>\n\tAccount Name:\t\t<CHANGE: lockout user 5>\n\nAdditional Information:\n\tCaller Computer Name:\t\t<CHANGE: caller host>", "task": "User Lockout"}, "event_data": {"SubjectUserSid": "S-1-5-18", "SubjectUserName": "PHDC02$", "SubjectDomainName": "PHANTOM", "SubjectLogonId": "0x3E7", "TargetUserName": "<CHANGE: lockout user 5>", "TargetDomainName": "<CHANGE: caller host>", "TargetSid": "S-1-5-21-3623811015-3361044348-30300820-<CHANGE: lockout RID 5>"}},
    {"event_id": 4740, "computer": "PHDC02", "time": "now-750s", "provider": "Microsoft-Windows-Security-Auditing", "rendering": {"message": "A user account was locked out.\n\nSubject:\n\tSecurity ID:\t\tS-1-5-18\n\tAccount Name:\t\tSYSTEM\n\tAccount Domain:\t\tPHANTOM\n\tLogon ID:\t\t0x3E7\n\nAccount That Was Locked Out:\n\tSecurity ID:\t\tS-1-5-21-3623811015-3361044348-30300820-<CHANGE: lockout RID 6>\n\tAccount Name:\t\t<CHANGE: lockout user 6>\n\nAdditional Information:\n\tCaller Computer Name:\t\t<CHANGE: caller host>", "task": "User Lockout"}, "event_data": {"SubjectUserSid": "S-1-5-18", "SubjectUserName": "PHDC02$", "SubjectDomainName": "PHANTOM", "SubjectLogonId": "0x3E7", "TargetUserName": "<CHANGE: lockout user 6>", "TargetDomainName": "<CHANGE: caller host>", "TargetSid": "S-1-5-21-3623811015-3361044348-30300820-<CHANGE: lockout RID 6>"}},
    {"event_id": 4740, "computer": "PHDC02", "time": "now-720s", "provider": "Microsoft-Windows-Security-Auditing", "rendering": {"message": "A user account was locked out.\n\nSubject:\n\tSecurity ID:\t\tS-1-5-18\n\tAccount Name:\t\tSYSTEM\n\tAccount Domain:\t\tPHANTOM\n\tLogon ID:\t\t0x3E7\n\nAccount That Was Locked Out:\n\tSecurity ID:\t\tS-1-5-21-3623811015-3361044348-30300820-<CHANGE: lockout RID 7>\n\tAccount Name:\t\t<CHANGE: lockout user 7>\n\nAdditional Information:\n\tCaller Computer Name:\t\t<CHANGE: caller host>", "task": "User Lockout"}, "event_data": {"SubjectUserSid": "S-1-5-18", "SubjectUserName": "PHDC02$", "SubjectDomainName": "PHANTOM", "SubjectLogonId": "0x3E7", "TargetUserName": "<CHANGE: lockout user 7>", "TargetDomainName": "<CHANGE: caller host>", "TargetSid": "S-1-5-21-3623811015-3361044348-30300820-<CHANGE: lockout RID 7>"}},
    {"event_id": 4740, "computer": "PHDC02", "time": "now-690s", "provider": "Microsoft-Windows-Security-Auditing", "rendering": {"message": "A user account was locked out.\n\nSubject:\n\tSecurity ID:\t\tS-1-5-18\n\tAccount Name:\t\tSYSTEM\n\tAccount Domain:\t\tPHANTOM\n\tLogon ID:\t\t0x3E7\n\nAccount That Was Locked Out:\n\tSecurity ID:\t\tS-1-5-21-3623811015-3361044348-30300820-<CHANGE: lockout RID 8>\n\tAccount Name:\t\t<CHANGE: lockout user 8>\n\nAdditional Information:\n\tCaller Computer Name:\t\t<CHANGE: caller host>", "task": "User Lockout"}, "event_data": {"SubjectUserSid": "S-1-5-18", "SubjectUserName": "PHDC02$", "SubjectDomainName": "PHANTOM", "SubjectLogonId": "0x3E7", "TargetUserName": "<CHANGE: lockout user 8>", "TargetDomainName": "<CHANGE: caller host>", "TargetSid": "S-1-5-21-3623811015-3361044348-30300820-<CHANGE: lockout RID 8>"}},
    {"event_id": 4740, "computer": "PHDC02", "time": "now-660s", "provider": "Microsoft-Windows-Security-Auditing", "rendering": {"message": "A user account was locked out.\n\nSubject:\n\tSecurity ID:\t\tS-1-5-18\n\tAccount Name:\t\tSYSTEM\n\tAccount Domain:\t\tPHANTOM\n\tLogon ID:\t\t0x3E7\n\nAccount That Was Locked Out:\n\tSecurity ID:\t\tS-1-5-21-3623811015-3361044348-30300820-<CHANGE: lockout RID 9>\n\tAccount Name:\t\t<CHANGE: lockout user 9>\n\nAdditional Information:\n\tCaller Computer Name:\t\t<CHANGE: caller host>", "task": "User Lockout"}, "event_data": {"SubjectUserSid": "S-1-5-18", "SubjectUserName": "PHDC02$", "SubjectDomainName": "PHANTOM", "SubjectLogonId": "0x3E7", "TargetUserName": "<CHANGE: lockout user 9>", "TargetDomainName": "<CHANGE: caller host>", "TargetSid": "S-1-5-21-3623811015-3361044348-30300820-<CHANGE: lockout RID 9>"}},
    {"event_id": 4740, "computer": "PHDC02", "time": "now-630s", "provider": "Microsoft-Windows-Security-Auditing", "rendering": {"message": "A user account was locked out.\n\nSubject:\n\tSecurity ID:\t\tS-1-5-18\n\tAccount Name:\t\tSYSTEM\n\tAccount Domain:\t\tPHANTOM\n\tLogon ID:\t\t0x3E7\n\nAccount That Was Locked Out:\n\tSecurity ID:\t\tS-1-5-21-3623811015-3361044348-30300820-<CHANGE: lockout RID 10>\n\tAccount Name:\t\t<CHANGE: lockout user 10>\n\nAdditional Information:\n\tCaller Computer Name:\t\t<CHANGE: caller host>", "task": "User Lockout"}, "event_data": {"SubjectUserSid": "S-1-5-18", "SubjectUserName": "PHDC02$", "SubjectDomainName": "PHANTOM", "SubjectLogonId": "0x3E7", "TargetUserName": "<CHANGE: lockout user 10>", "TargetDomainName": "<CHANGE: caller host>", "TargetSid": "S-1-5-21-3623811015-3361044348-30300820-<CHANGE: lockout RID 10>"}},
    {"event_id": 4740, "computer": "PHDC02", "time": "now-850s", "provider": "Microsoft-Windows-Security-Auditing", "rendering": {"message": "A user account was locked out.\n\nSubject:\n\tSecurity ID:\t\tS-1-5-18\n\tAccount Name:\t\tSYSTEM\n\tAccount Domain:\t\tPHANTOM\n\tLogon ID:\t\t0x3E7\n\nAccount That Was Locked Out:\n\tSecurity ID:\t\tS-1-5-21-3623811015-3361044348-30300820-<CHANGE: repeat lockout RID>\n\tAccount Name:\t\t<CHANGE: repeat lockout user>\n\nAdditional Information:\n\tCaller Computer Name:\t\t<CHANGE: caller host>", "task": "User Lockout"}, "event_data": {"SubjectUserSid": "S-1-5-18", "SubjectUserName": "PHDC02$", "SubjectDomainName": "PHANTOM", "SubjectLogonId": "0x3E7", "TargetUserName": "<CHANGE: repeat lockout user>", "TargetDomainName": "<CHANGE: caller host>", "TargetSid": "S-1-5-21-3623811015-3361044348-30300820-<CHANGE: repeat lockout RID>"}},
    {"event_id": 4740, "computer": "PHDC02", "time": "now-810s", "provider": "Microsoft-Windows-Security-Auditing", "rendering": {"message": "A user account was locked out.\n\nSubject:\n\tSecurity ID:\t\tS-1-5-18\n\tAccount Name:\t\tSYSTEM\n\tAccount Domain:\t\tPHANTOM\n\tLogon ID:\t\t0x3E7\n\nAccount That Was Locked Out:\n\tSecurity ID:\t\tS-1-5-21-3623811015-3361044348-30300820-<CHANGE: repeat lockout RID>\n\tAccount Name:\t\t<CHANGE: repeat lockout user>\n\nAdditional Information:\n\tCaller Computer Name:\t\t<CHANGE: caller host>", "task": "User Lockout"}, "event_data": {"SubjectUserSid": "S-1-5-18", "SubjectUserName": "PHDC02$", "SubjectDomainName": "PHANTOM", "SubjectLogonId": "0x3E7", "TargetUserName": "<CHANGE: repeat lockout user>", "TargetDomainName": "<CHANGE: caller host>", "TargetSid": "S-1-5-21-3623811015-3361044348-30300820-<CHANGE: repeat lockout RID>"}},
    {"event_id": 4740, "computer": "PHDC02", "time": "now-770s", "provider": "Microsoft-Windows-Security-Auditing", "rendering": {"message": "A user account was locked out.\n\nSubject:\n\tSecurity ID:\t\tS-1-5-18\n\tAccount Name:\t\tSYSTEM\n\tAccount Domain:\t\tPHANTOM\n\tLogon ID:\t\t0x3E7\n\nAccount That Was Locked Out:\n\tSecurity ID:\t\tS-1-5-21-3623811015-3361044348-30300820-<CHANGE: repeat lockout RID>\n\tAccount Name:\t\t<CHANGE: repeat lockout user>\n\nAdditional Information:\n\tCaller Computer Name:\t\t<CHANGE: caller host>", "task": "User Lockout"}, "event_data": {"SubjectUserSid": "S-1-5-18", "SubjectUserName": "PHDC02$", "SubjectDomainName": "PHANTOM", "SubjectLogonId": "0x3E7", "TargetUserName": "<CHANGE: repeat lockout user>", "TargetDomainName": "<CHANGE: caller host>", "TargetSid": "S-1-5-21-3623811015-3361044348-30300820-<CHANGE: repeat lockout RID>"}},
    {"event_id": 4740, "computer": "PHDC02", "time": "now-730s", "provider": "Microsoft-Windows-Security-Auditing", "rendering": {"message": "A user account was locked out.\n\nSubject:\n\tSecurity ID:\t\tS-1-5-18\n\tAccount Name:\t\tSYSTEM\n\tAccount Domain:\t\tPHANTOM\n\tLogon ID:\t\t0x3E7\n\nAccount That Was Locked Out:\n\tSecurity ID:\t\tS-1-5-21-3623811015-3361044348-30300820-<CHANGE: repeat lockout RID>\n\tAccount Name:\t\t<CHANGE: repeat lockout user>\n\nAdditional Information:\n\tCaller Computer Name:\t\t<CHANGE: caller host>", "task": "User Lockout"}, "event_data": {"SubjectUserSid": "S-1-5-18", "SubjectUserName": "PHDC02$", "SubjectDomainName": "PHANTOM", "SubjectLogonId": "0x3E7", "TargetUserName": "<CHANGE: repeat lockout user>", "TargetDomainName": "<CHANGE: caller host>", "TargetSid": "S-1-5-21-3623811015-3361044348-30300820-<CHANGE: repeat lockout RID>"}},
    {"event_id": 4740, "computer": "PHDC02", "time": "now-690s", "provider": "Microsoft-Windows-Security-Auditing", "rendering": {"message": "A user account was locked out.\n\nSubject:\n\tSecurity ID:\t\tS-1-5-18\n\tAccount Name:\t\tSYSTEM\n\tAccount Domain:\t\tPHANTOM\n\tLogon ID:\t\t0x3E7\n\nAccount That Was Locked Out:\n\tSecurity ID:\t\tS-1-5-21-3623811015-3361044348-30300820-<CHANGE: repeat lockout RID>\n\tAccount Name:\t\t<CHANGE: repeat lockout user>\n\nAdditional Information:\n\tCaller Computer Name:\t\t<CHANGE: caller host>", "task": "User Lockout"}, "event_data": {"SubjectUserSid": "S-1-5-18", "SubjectUserName": "PHDC02$", "SubjectDomainName": "PHANTOM", "SubjectLogonId": "0x3E7", "TargetUserName": "<CHANGE: repeat lockout user>", "TargetDomainName": "<CHANGE: caller host>", "TargetSid": "S-1-5-21-3623811015-3361044348-30300820-<CHANGE: repeat lockout RID>"}},
    {"event_id": 4740, "computer": "PHDC02", "time": "now-650s", "provider": "Microsoft-Windows-Security-Auditing", "rendering": {"message": "A user account was locked out.\n\nSubject:\n\tSecurity ID:\t\tS-1-5-18\n\tAccount Name:\t\tSYSTEM\n\tAccount Domain:\t\tPHANTOM\n\tLogon ID:\t\t0x3E7\n\nAccount That Was Locked Out:\n\tSecurity ID:\t\tS-1-5-21-3623811015-3361044348-30300820-<CHANGE: repeat lockout RID>\n\tAccount Name:\t\t<CHANGE: repeat lockout user>\n\nAdditional Information:\n\tCaller Computer Name:\t\t<CHANGE: caller host>", "task": "User Lockout"}, "event_data": {"SubjectUserSid": "S-1-5-18", "SubjectUserName": "PHDC02$", "SubjectDomainName": "PHANTOM", "SubjectLogonId": "0x3E7", "TargetUserName": "<CHANGE: repeat lockout user>", "TargetDomainName": "<CHANGE: caller host>", "TargetSid": "S-1-5-21-3623811015-3361044348-30300820-<CHANGE: repeat lockout RID>"}}
  ]
}
```

What matters and why:

- **16 events `4740` on `PHDC02`, 11 distinct locked-out accounts**: ten different accounts once each, then one more account six times. The alert counted "11 users"; the repeats on one account added nothing to the count, so ten distinct users is the lever, with one account repeated.
- **In a real 4740 the `TargetDomainName` field holds the CALLER COMPUTER NAME**, the host the lockouts came from, and the alert reports it as "originated from host". Putting the domain name `PHANTOM` there makes the alert say "originated from host PHANTOM". This skill puts a **new workstation name** there instead (and in the message's `Caller Computer Name`), because a repeat run with `PHANTOM` again is the same "host" and its one-day deduplication would hide the second alert.
- **Subject** `SYSTEM` / `S-1-5-18` / `PHDC02$` / logon id `0x3E7`: lockouts are written by the domain controller itself.
- **Spread**: the events span about 12 minutes, inside the 1-hour window.
- **Free to change**: every account name and RID, and the caller host.

## Route B: Cribl (same events, same alert)

Send the **same 16 events as Step 1** through the tenant's Cribl endpoint instead of the Windows Event Collector: call **`http-sender.send_events`** once with the same `events` list (every `<CHANGE: ...>` filled exactly as in Step 1) plus the destination. Do not build any XML: the connector renders each event to Windows Event XML itself. Precondition 1B applies instead of 1A.

```text
http-sender.send_events
{"events": <the same events list as Step 1>, "destination": "cribl_windows_events"}
```

The answer carries `ok: true`, `destination: cribl_windows_events`, `dataset: microsoft_windows_raw` and `num_records` equal to 16. The rows land in `microsoft_windows_raw` with `_transport = "cribl"` and no `_collector_type`; the columns and `xdm.*` fields are the same as over WEC, so Steps 2 and 3 are unchanged (only the stamp check differs).


## Step 2: confirm the events landed and modeled (about 2 minutes after Step 1)

```
config timeframe = 1h | datamodel dataset = microsoft_windows_raw
| filter xdm.event.id = "4740"
| filter xdm.event.description contains "<caller host>"
| fields _time, xdm.event.id, xdm.event.description
```

Pass when **16 rows** return.

## Step 3: wait, then check for the alert

Check **1 minute** after the send, then every minute for up to **15 minutes** (the alert typically arrives within about 2 minutes):

```
dataset = alerts
| filter alert_name = "Excessive user account lockouts"
| fields _time, alert_id, alert_name, severity, host_name, user_name, description
| sort desc _time
| limit 5
```

Pass when a new row names your actor (the alert has no user: match its `description` on `<caller host>`). To list Analytics alerts without naming one, filter on the STORED enum values `alert_source in ("MAGNIFIER","ANALYTICS_BIOC")`: the displayed names `XDR_ANALYTICS` and `XDR_ANALYTICS_BIOC` match nothing.

If nothing arrives in 15 minutes: confirm Step 2 (the events must be in `microsoft_windows_raw` and modeled, with the stamp of the route you used: `_collector_type = "WEC"` for Route A, `_transport = "cribl"` for Route B), confirm every identity was new (precondition 2), then retry **once** with a new actor and new RIDs. Do not change the event body.

## Report back to the operator

State the actor, the RIDs and the host names used, the number of events sent, the Step 2 result and either the alert id with the arrival time or that nothing arrived in 15 minutes and what you checked. Say that the actor must not be reused: the detector's history is per account and its deduplication is one day.
