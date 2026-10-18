---
name: trigger_spoofed_samaccountname_tickets_alert
displayName: Trigger the Cortex "spoofed sAMAccountName" TGT and service ticket analytics alerts
category: workflows
description: 'Fire Cortex XSIAM''s native noPac analytics alerts "TGT request with a spoofed sAMAccountName - Event log" and "Service ticket request with a spoofed sAMAccountName" (both Medium, T1098 and T1078, CVE-2021-42278 and CVE-2021-42287) with four synthetic Windows Security events sent through the wec-sender connector (Windows Event Collector, Route A) or through http-sender with destination cribl_windows_events (the tenant Cribl endpoint with the Windows UUID, Route B): a machine account renamed to the name of the domain controller that logs the events with the trailing dollar sign dropped (4781), a TGT request (4768) and a service ticket request (4769) for that name, and the rename back. It also raises "Suspicious sAMAccountName change" (Low). Use when the operator asks to trigger, demo, prove or reproduce a noPac, sAMAccountName spoofing or domain controller impersonation alert. It fires over both routes and never over syslog/CEF.'
icon: security
source: platform
loadingMode: on-demand
locked: false
---

# Skill: Trigger the "TGT / Service ticket request with a spoofed sAMAccountName" alerts

## When this skill applies

The operator wants the native **Cortex Analytics noPac detectors** to fire, for example: *"trigger a noPac alert"*, *"show a domain controller impersonation through a spoofed sAMAccountName"*, *"prove CVE-2021-42278 shows up from Windows events"*.

The detectors are **not correlation rules**; they are Cortex's own analytics (XDR Analytics BIOC), and nothing needs installing on the tenant beyond the Windows pack that already models `microsoft_windows_raw`. They read Windows events that arrive through a registered Windows source, so the call below goes either to `wec-sender.send_events` (Route A) or to `http-sender.send_events` with `destination: "cribl_windows_events"` (Route B), never to a syslog/CEF worker.

## What the detector looks for (Cortex docs: "TGT request with a spoofed sAMAccountName - Event log" and "Service ticket request with a spoofed sAMAccountName")

| Property | Value |
|---|---|
| Alert names | `TGT request with a spoofed sAMAccountName - Event log` (Medium) and `Service ticket request with a spoofed sAMAccountName` (Medium), both from the 4768 and 4769 events; the 4781 rename also raises `Suspicious sAMAccountName change` (Low, the recipe of `trigger_samaccountname_change_alert`) |
| Source | `XDR Analytics BIOC`, MITRE T1098 Account Manipulation, T1078 Valid Accounts; alert tags `DT:Identity Analytics`, `DS:Microsoft/Windows` |
| Required data (doc) | Windows Event Collector OR XDR Agent with eXtended Threat Hunting (XTH); the doc lists the Identity Analytics module |
| Activation / training (doc) | 14 days / 30 days in the documentation; in practice every alert arrives within minutes of its events |
| Test period | single event |
| Deduplication | 3 hours (doc). A second run on the same domain controller name inside that time raises no ticket alert, while runs on other domain controller names do: see "Why a fresh domain controller name every run" |
| What the alert text says | *"A TGT for the account <DC name> on domain PHANTOM.LAB has been requested from host <DC name>.phantom.lab. This machine account name was modified to the domain controller name without a trailing $. This may indicate an attempt to impersonate a domain controller by exploiting CVE-2021-42278 and CVE-2021-42287"* and, for the ticket alert, *"A service ticket for the account <DC name>@PHANTOM.LAB ... has been requested from host ..."*. Neither carries a user name, so attribute by the domain controller name in the description |

### Why a fresh domain controller name every run

The detectors compare the account name in the ticket event with the name of the **host that logged the event** (the key distribution centre). Events logged on a known domain controller (`PHDC02`, `PHDC01`) and on a brand-new host name both raise both ticket alerts, so any host name used as the logging computer counts as a domain controller. The same recipe repeated on the same domain controller name less than 3 hours after its first alert raises no second ticket alert (consistent with the documented 3-hour deduplication, which would then be per domain controller name). The recipe therefore uses a new domain controller name `PHDC<RID>` each run, which is also why it can be repeated at any time.

Did **not** fire the two ticket alerts: the same rename and tickets for a name that is **not** the logging host (`PHWS-<n>$` renamed to `PHWS-<n>`, tickets logged on `PHDC02`), and a rename to `PHDC01` with the tickets logged on `PHDC02`: only `Suspicious sAMAccountName change` appeared.

## Which delivery paths fire it (WEC and Cribl, never syslog/CEF)

The detectors in this family read Windows events that arrive through a registered Windows source. Over syslog/CEF the same event types **land and model** in `microsoft_windows_raw` but are stamped `_collector_type = Syslog`, and no Windows identity alert fires from them. Two paths carry the same structured events and **both fire**:

- **Route A, WEC**: `wec-sender.send_events` delivers through the Broker VM's Windows Event Collector over mutual TLS. The rows are stamped `_collector_type = WEC`.
- **Route B, Cribl**: `http-sender.send_events` with `destination: "cribl_windows_events"` renders the same events to Windows Event XML and posts them to the tenant's Cribl endpoint with the Windows UUID. The rows land in the same dataset with `_transport = cribl` and no `_collector_type`, with the same columns and `xdm.*` fields. It needs no Broker, no certificate and no subscription.

Do not "test it quickly" over syslog/CEF: a null result there says nothing about the rule.

**This is NOT a mapping problem.** Over syslog/CEF the event already lands in `microsoft_windows_raw` and the modeling rule already fills the same `xdm.*` fields (the syslog `MicrosoftWindowsEvents` source maps 58 of them), so a good mapping there proves nothing about this alert. The alert will not fire over syslog/CEF no matter how complete the mapping is: the detector reads the registered Windows source (the WEC, native-agent or dedicated-UUID Cribl feed), not the syslog/CEF feed. `_collector_type = WEC` is stamped by a real Windows Event Collector delivery and cannot be set from an event body, so no CEF extension, field choice or schema change can reach it.

## Preconditions: check these BEFORE sending

| # | Must be true | How to check |
|---|---|---|
| 1A | Route A only: the `wec-sender` connector instance is running and `wec-sender.list_subscriptions` returns `ok: true` with a subscription whose channels include `Security` (for example a subscription named "Authentication Event Logs" on the Broker VM, port 5986) | call `wec-sender.list_subscriptions` |
| 1B | Route B only: the `http-sender` instance has `criblUrl` and `criblToken` set, so `http-sender.list_destinations` lists `cribl_windows_events` with `ready: true` and `dataset: microsoft_windows_raw` | call `http-sender.list_destinations` |
| 2 | Every identity below is **new**: a user name, a computer name and a RID never used in an earlier run, and a user name that is not a person's. Alerts for the same domain controller name did not repeat within 3 hours, so use a new DC name each run. | `config timeframe = 30d \| datamodel dataset = microsoft_windows_raw \| filter xdm.source.user.username = "<actor>" \| limit 1` returns **no row** |
| 3 | Every event time is **now** or a few minutes earlier, UTC. Write it as `now-310s` (the connector resolves it with its own clock; an absolute `YYYY-MM-DDTHH:MM:SSZ` also works): the connector turns `time` into the event's TimeCreated and that becomes `_time`, and the detector windows are evaluated on it. Never in the future | generate at call time |


## Expected result

Over both routes (WEC and Cribl) the four events in Step 1, with a new actor, machine, RIDs and a new domain controller name, raise three alerts, typically within about a minute of the send: the TGT request alert (Medium), the service ticket request alert (Medium) and the rename alert `Suspicious sAMAccountName change` (Low). Use identities (actor, RIDs, computer names) never seen before.

Does **not** fire the two ticket alerts (only `Suspicious sAMAccountName change` appears): `PHWS-SF...$` renamed to `PHWS-SF...` (a name that is not the logging host), and a rename to `PHDC01` with the tickets logged on `PHDC02`. A second run on the same domain controller name inside the 3-hour deduplication also raises no ticket alert.

## Step 1: send the events (exactly this call)

**Route A (WEC).** Call **`wec-sender.send_events`** once with the 4 events below. Replace only the values marked `<CHANGE: ...>` (the same label means the same value everywhere it appears); everything else is the verbatim shape that fires.

| Placeholder | Put here |
|---|---|
| `now-Ns` (also `now`, `now-5m`, `now-1h`) | **leave it as this literal text, do not work out a date or time yourself**: the connector replaces it with its own current UTC time minus N seconds when it sends |
| `<CHANGE: actor>` | a new account name that is not a person's, e.g. `adm.runNNNN` (letters, digits, dot) |
| `<CHANGE: actor RID>` | a new RID, 3300 or higher, never reused (the SID is `S-1-5-21-3623811015-3361044348-30300820-<RID>`) |
| `<CHANGE: actor logon id>` | a new hex logon id such as `0x9A4C21` |
| `<CHANGE: machine>` | a new computer name `PHWS-<NNN>`; it appears as `<machine>$` (its real name) and is the account that gets renamed |
| `<CHANGE: machine RID>` | a new RID for the computer, 3300 or higher, different from the actor's |
| `<CHANGE: attacker IP>` | a new private address for the host that requests the tickets, e.g. `10.20.16.<N>` |

```json
{
  "events": [
    {
      "event_id": 4781,
      "computer": "PHDC<CHANGE: actor RID>",
      "time": "now-300s",
      "provider": "Microsoft-Windows-Security-Auditing",
      "rendering": {
        "message": "The name of an account was changed:\n\nSubject:\n\tSecurity ID:\t\tS-1-5-21-3623811015-3361044348-30300820-<CHANGE: actor RID>\n\tAccount Name:\t\t<CHANGE: actor>\n\tAccount Domain:\t\tPHANTOM\n\tLogon ID:\t\t<CHANGE: actor logon id>\n\nAccount Whose Name Was Changed:\n\tSecurity ID:\t\tS-1-5-21-3623811015-3361044348-30300820-<CHANGE: machine RID>\n\tOld Account Name:\t<CHANGE: machine>$\n\tNew Account Name:\tPHDC<CHANGE: actor RID>\n\nAdditional Information:\n\tPrivileges:\t-",
        "task": "User Account Management"
      },
      "event_data": {
        "SubjectUserSid": "S-1-5-21-3623811015-3361044348-30300820-<CHANGE: actor RID>",
        "SubjectUserName": "<CHANGE: actor>",
        "SubjectDomainName": "PHANTOM",
        "SubjectLogonId": "<CHANGE: actor logon id>",
        "OldTargetUserName": "<CHANGE: machine>$",
        "NewTargetUserName": "PHDC<CHANGE: actor RID>",
        "TargetDomainName": "PHANTOM",
        "TargetSid": "S-1-5-21-3623811015-3361044348-30300820-<CHANGE: machine RID>",
        "PrivilegeList": "-"
      }
    },
    {
      "event_id": 4768,
      "computer": "PHDC<CHANGE: actor RID>",
      "time": "now-240s",
      "provider": "Microsoft-Windows-Security-Auditing",
      "rendering": {
        "message": "A Kerberos authentication ticket (TGT) was requested.\n\nAccount Information:\n\tAccount Name:\t\tPHDC<CHANGE: actor RID>\n\tSupplied Realm Name:\tPHANTOM.LAB\n\tUser ID:\t\t\tS-1-5-21-3623811015-3361044348-30300820-<CHANGE: machine RID>\n\nService Information:\n\tService Name:\t\tkrbtgt\n\tService ID:\t\tS-1-5-21-3623811015-3361044348-30300820-502\n\nNetwork Information:\n\tClient Address:\t\t::ffff:<CHANGE: attacker IP>\n\tClient Port:\t\t50001\n\nAdditional Information:\n\tTicket Options:\t\t0x40810010\n\tResult Code:\t\t0x0\n\tTicket Encryption Type:\t0x12\n\tPre-Authentication Type:\t2\n\nCertificate Information:\n\tCertificate Issuer Name:\t\t\n\tCertificate Serial Number:\t\n\tCertificate Thumbprint:\t\t\n",
        "task": "Kerberos Authentication Service"
      },
      "event_data": {
        "TargetUserName": "PHDC<CHANGE: actor RID>",
        "TargetDomainName": "PHANTOM.LAB",
        "TargetSid": "S-1-5-21-3623811015-3361044348-30300820-<CHANGE: machine RID>",
        "ServiceName": "krbtgt",
        "ServiceSid": "S-1-5-21-3623811015-3361044348-30300820-502",
        "TicketOptions": "0x40810010",
        "Status": "0x0",
        "TicketEncryptionType": "0x12",
        "PreAuthType": "2",
        "IpAddress": "::ffff:<CHANGE: attacker IP>",
        "IpPort": "50001",
        "CertIssuerName": "",
        "CertSerialNumber": "",
        "CertThumbprint": ""
      }
    },
    {
      "event_id": 4769,
      "computer": "PHDC<CHANGE: actor RID>",
      "time": "now-220s",
      "provider": "Microsoft-Windows-Security-Auditing",
      "rendering": {
        "message": "A Kerberos service ticket was requested.\n\nAccount Information:\n\tAccount Name:\t\tPHDC<CHANGE: actor RID>@PHANTOM.LAB\n\tAccount Domain:\t\tPHANTOM.LAB\n\tLogon GUID:\t\t{00000003-b22c-4e5f-8a00-000000000004}\n\nService Information:\n\tService Name:\t\tPHDC<CHANGE: actor RID>$\n\tService ID:\t\tS-1-5-21-3623811015-3361044348-30300820-1001\n\nNetwork Information:\n\tClient Address:\t\t::ffff:<CHANGE: attacker IP>\n\tClient Port:\t\t50002\n\nAdditional Information:\n\tTicket Options:\t\t0x40810000\n\tTicket Encryption Type:\t0x12\n\tFailure Code:\t\t0x0\n\tTransited Services:\t-",
        "task": "Kerberos Service Ticket Operations"
      },
      "event_data": {
        "TargetUserName": "PHDC<CHANGE: actor RID>@PHANTOM.LAB",
        "TargetDomainName": "PHANTOM.LAB",
        "ServiceName": "PHDC<CHANGE: actor RID>$",
        "ServiceSid": "S-1-5-21-3623811015-3361044348-30300820-1001",
        "TicketOptions": "0x40810000",
        "TicketEncryptionType": "0x12",
        "IpAddress": "::ffff:<CHANGE: attacker IP>",
        "IpPort": "50002",
        "Status": "0x0",
        "LogonGuid": "{00000003-b22c-4e5f-8a00-000000000004}",
        "TransmittedServices": "-"
      }
    },
    {
      "event_id": 4781,
      "computer": "PHDC<CHANGE: actor RID>",
      "time": "now-150s",
      "provider": "Microsoft-Windows-Security-Auditing",
      "rendering": {
        "message": "The name of an account was changed:\n\nSubject:\n\tSecurity ID:\t\tS-1-5-21-3623811015-3361044348-30300820-<CHANGE: actor RID>\n\tAccount Name:\t\t<CHANGE: actor>\n\tAccount Domain:\t\tPHANTOM\n\tLogon ID:\t\t<CHANGE: actor logon id>\n\nAccount Whose Name Was Changed:\n\tSecurity ID:\t\tS-1-5-21-3623811015-3361044348-30300820-<CHANGE: machine RID>\n\tOld Account Name:\tPHDC<CHANGE: actor RID>\n\tNew Account Name:\t<CHANGE: machine>$\n\nAdditional Information:\n\tPrivileges:\t-",
        "task": "User Account Management"
      },
      "event_data": {
        "SubjectUserSid": "S-1-5-21-3623811015-3361044348-30300820-<CHANGE: actor RID>",
        "SubjectUserName": "<CHANGE: actor>",
        "SubjectDomainName": "PHANTOM",
        "SubjectLogonId": "<CHANGE: actor logon id>",
        "OldTargetUserName": "PHDC<CHANGE: actor RID>",
        "NewTargetUserName": "<CHANGE: machine>$",
        "TargetDomainName": "PHANTOM",
        "TargetSid": "S-1-5-21-3623811015-3361044348-30300820-<CHANGE: machine RID>",
        "PrivilegeList": "-"
      }
    }
  ]
}
```

What matters and why:

- **Everything is logged on one host, the domain controller** `PHDC<actor RID>` (a name that is new each run, for example `PHDC3800` when the actor RID is `3800`). The renamed account becomes exactly that name **without** the `$`: `PHWS-<n>$` to `PHDC3800`.
- **`4781`** (the name of an account was changed) twice: first `<machine>$` to the DC name, last the DC name back to `<machine>$`. The first one is what raises `Suspicious sAMAccountName change` (the recipe `trigger_samaccountname_change_alert` explains that detector).
- **`4768`** (TGT request) for the spoofed name `PHDC<RID>` (no `$`, no `@`), `ServiceName krbtgt`, `TargetSid` the **renamed machine's** SID. This raises `TGT request with a spoofed sAMAccountName - Event log`.
- **`4769`** (service ticket request) for `PHDC<RID>@PHANTOM.LAB` asking for the service `PHDC<RID>$` (the S4U2self shape of noPac). This raises `Service ticket request with a spoofed sAMAccountName`.
- **Free to change**: the actor, the machine, the RIDs, the attacker address. Keep the DC name equal to the computer name of all four events.
- **Untested**: whether the 4781 rename back is needed (it is kept because the attack does it), and whether a domain-admin actor changes anything (the actors were ordinary new accounts).

## Route B: Cribl (same events, same alert)

Send the **same 4 events as Step 1** through the tenant's Cribl endpoint instead of the Windows Event Collector: call **`http-sender.send_events`** once with the same `events` list (every `<CHANGE: ...>` filled exactly as in Step 1) plus the destination. Do not build any XML: the connector renders each event to Windows Event XML itself. Precondition 1B applies instead of 1A.

```text
http-sender.send_events
{"events": <the same events list as Step 1>, "destination": "cribl_windows_events"}
```

The answer carries `ok: true`, `destination: cribl_windows_events`, `dataset: microsoft_windows_raw` and `num_records` equal to the number of events. The rows land in `microsoft_windows_raw` with `_transport = "cribl"` and no `_collector_type`; the columns and `xdm.*` fields are the same as over WEC, so Steps 2 and 3 are unchanged (only the stamp check differs).

## Step 2: confirm the events landed and modeled (about 2 minutes after Step 1)

```
config timeframe = 1h | datamodel dataset = microsoft_windows_raw
| filter xdm.source.host.hostname = "PHDC<actor RID>.phantom.lab" and xdm.event.id in ("4781","4768","4769")
| fields _time, xdm.event.id, xdm.source.identity.username, xdm.event.description
| sort asc _time
```

Pass when **4 rows** return (two 4781, one 4768, one 4769). Over Route A add `_collector_type = "WEC"` (raw dataset) and over Route B `_transport = "cribl"` to confirm the stamp.

## Step 3: wait, then check for the alert

Check **1 minute** after the send, then every minute for up to **15 minutes** (the alerts typically arrive within about a minute):

```
dataset = alerts
| filter alert_name in ("TGT request with a spoofed sAMAccountName - Event log", "Service ticket request with a spoofed sAMAccountName", "Suspicious sAMAccountName change")
| filter description contains "PHDC<actor RID>" or description contains "<machine>"
| fields _time, alert_id, alert_name, severity, host_name, user_name, description
| sort desc _time
| limit 10
```

Pass when **three** rows come back: the two Medium ticket alerts (host `PHDC<actor RID>.phantom.lab`, no user name) and the Low `Suspicious sAMAccountName change` naming your actor. To list Analytics alerts without naming one, filter on the STORED enum values `alert_source in ("MAGNIFIER","ANALYTICS_BIOC")`: the displayed names `XDR_ANALYTICS` and `XDR_ANALYTICS_BIOC` match nothing.

If nothing arrives in 15 minutes: confirm Step 2, confirm every identity **and the DC name** was new, then retry **once** with a new actor, new RIDs and a new DC name. Do not change the event body.

## Report back to the operator

State the actor, the machine, the RIDs, the domain controller name used, the number of events sent, the Step 2 result and the alert ids with arrival times (two Medium ticket alerts and the Low rename alert), or that nothing arrived in 15 minutes and what you checked. Say that the DC name should not be reused within 3 hours (the same name raises no second ticket alert in that time).
