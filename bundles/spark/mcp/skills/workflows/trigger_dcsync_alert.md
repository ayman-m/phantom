---
name: trigger_dcsync_alert
displayName: Trigger the Cortex "Possible DCSync by an unusual user" analytics alert
category: workflows
description: 'Fire Cortex XSIAM''s native "Possible DCSync by an unusual user" analytics BIOC (Low, T1003.006) by sending synthetic Windows Security events through the wec-sender connector (Windows Event Collector, Route A) or through http-sender with destination cribl_windows_events (the tenant Cribl endpoint with the Windows UUID, Route B): one 4624 network logon of a new user to the domain controller, then four 4662 directory-service replication accesses carrying the DS-Replication GUIDs on the krbtgt object. Use when the operator asks to trigger, demo, prove or reproduce DCSync, a replication request by a non-domain-controller account, or a credential-dumping alert on a domain controller. It fires over both routes and never over syslog/CEF.'
icon: admin_panel_settings
source: platform
loadingMode: on-demand
locked: false
---

# Skill: Trigger the "Possible DCSync by an unusual user" alert

## When this skill applies

The operator wants the native **Cortex Analytics DCSync detector** to fire, for example: *"trigger a DCSync alert"*, *"show credential dumping from a domain controller"*, *"prove T1003.006 fires from Windows events"*.

The detector is **not a correlation rule**; it is Cortex's own analytics (XDR Analytics BIOC), and nothing needs installing on the tenant beyond the Windows pack that already models `microsoft_windows_raw`. It reads Windows events that arrive through a registered Windows source, so the call below goes either to `wec-sender.send_events` (Route A) or to `http-sender.send_events` with `destination: "cribl_windows_events"` (Route B, see "Route B: Cribl"), never to a syslog/CEF worker.

## What the detector looks for (Cortex doc: "Potential DCSync by an unusual user")

| Property | Value |
|---|---|
| Alert name | `Possible DCSync by an unusual user` (Low), a variation of the doc's `Potential DCSync by an unusual user` (Informational, invisible). The catalog lists network siblings (`Possible DCSync from a non domain controller` and its High/Medium variants) that read firewall traffic; they do not fire from the synthetic firewall feed |
| Source | `XDR Analytics BIOC`, MITRE T1003.006 OS Credential Dumping: DCSync, T1207 Rogue Domain Controller; alert tags `DT:Identity Analytics`, `DS:Microsoft/Windows` |
| Required data (doc) | Windows Event Collector OR XDR Agent with eXtended Threat Hunting (XTH); the doc lists the Identity Analytics module |
| Activation / training (doc) | 14 days / 30 days. In practice the alert typically arrives within a minute or two of its events |
| Test period | single event |
| Deduplication | 1 day |
| What the alert text says | *"The account <domain>\<actor> initiated a replication request to PHDC02.phantom.lab, which is a Domain controller. Over the past 30 days, the account was seen performing replications 0 days. The account authenticated 0 days over the past month. The user performing the replication is not a machine account, and is not a user used by Azure AD Connect platform. The user performing the replication, did it for the first time ..."* |

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
| 2 | Every identity below is **new**: a user name and a RID never used in an earlier run (use a RID of **3300 or higher**), and a user name that is not a person's. The detectors report a first-time action per account, and their history is kept per account for 30 days | `config timeframe = 30d \| datamodel dataset = microsoft_windows_raw \| filter xdm.source.user.username = "<actor>" \| limit 1` returns **no row** |
| 3 | Every event time is **now** or a few minutes earlier, UTC. Write it as `now-310s` (the connector resolves it with its own clock; an absolute `YYYY-MM-DDTHH:MM:SSZ` also works): the connector turns `time` into the event's TimeCreated and that becomes `_time`, and the detector windows are evaluated on it. Never in the future | generate at call time |


## Expected result

The recipe fires from a new, non-person account replicating from a workstation to a domain controller; the alert typically arrives within a minute or two of the call (seconds to about three minutes), over Route A and over Route B.

Did **not** fire: the same shape over syslog/CEF, and the network detector `Possible DCSync from a non domain controller` fed with `ms-drsuapi` traffic through the firewall feed.

## Step 1: send the events (exactly this call)

**Route A (WEC).** Call **`wec-sender.send_events`** once with the 5 events below. Replace only the values marked `<CHANGE: ...>` (the same label means the same value everywhere it appears); everything else is the verbatim shape that fired.

| Placeholder | Put here |
|---|---|
| `now-Ns` (also `now`, `now-5m`, `now-1h`) | **leave it as this literal text, do not work out a date or time yourself**: the connector replaces it with its own current UTC time minus N seconds when it sends |
| `<CHANGE: actor>` | a new account name that is not a person's, e.g. `adm.runNNNN` (letters, digits, dot) |
| `<CHANGE: actor RID>` | a new RID, 3300 or higher, never reused (the SID is `S-1-5-21-3623811015-3361044348-30300820-<RID>`) |
| `<CHANGE: actor logon id>` | a new hex logon id such as `0x9A4C21` |
| `<CHANGE: attacker host>` | a new workstation name `PHWS-<NNN>` the account logs on from |
| `<CHANGE: attacker IP>` | a new private address for that workstation, e.g. `10.20.16.<N>` |

```json
{
  "events": [
    {
      "event_id": 4624,
      "computer": "PHDC02",
      "time": "now-310s",
      "event_data": {
        "SubjectUserSid": "S-1-5-18",
        "SubjectUserName": "PHDC02$",
        "SubjectDomainName": "PHANTOM",
        "SubjectLogonId": "0x3E7",
        "TargetUserSid": "S-1-5-21-3623811015-3361044348-30300820-<CHANGE: actor RID>",
        "TargetUserName": "<CHANGE: actor>",
        "TargetDomainName": "PHANTOM",
        "TargetLogonId": "<CHANGE: actor logon id>",
        "LogonType": "3",
        "LogonProcessName": "Kerberos",
        "AuthenticationPackageName": "Kerberos",
        "WorkstationName": "<CHANGE: attacker host>",
        "IpAddress": "<CHANGE: attacker IP>",
        "IpPort": "51510"
      }
    },
    {
      "event_id": 4662,
      "computer": "PHDC02",
      "time": "now-300s",
      "provider": "Microsoft-Windows-Security-Auditing",
      "rendering": {
        "message": "An operation was performed on an object.\n\nSubject :\n\tSecurity ID:\t\tS-1-5-21-3623811015-3361044348-30300820-<CHANGE: actor RID>\n\tAccount Name:\t\t<CHANGE: actor>\n\tAccount Domain:\t\tPHANTOM\n\tLogon ID:\t\t<CHANGE: actor logon id>\n\nObject:\n\tObject Server:\t\tDS\n\tObject Type:\t\t%{bf967aba-0de6-11d0-a285-00aa003049e2}\n\tObject Name:\t\tCN=krbtgt,CN=Users,DC=phantom,DC=lab\n\tHandle ID:\t\t0x0\n\nOperation:\n\tOperation Type:\t\tObject Access\n\tAccess Mask:\t\t0x100\n\tProperties:\t\t{1131f6aa-9c07-11d1-f79f-00c04fc2dcd2}; {1131f6ad-9c07-11d1-f79f-00c04fc2dcd2}; {1131f6ae-9c07-11d1-f79f-00c04fc2dcd2}; {89e95b76-444d-4c62-991a-0facbeda640c}\n\t\t\tCN=krbtgt,CN=Users,DC=phantom,DC=lab\n\nAdditional Information:\n\tParameter 1:\t\t-\n\tParameter 2:\t\t-",
        "task": "Directory Service Access"
      },
      "event_data": {
        "SubjectUserSid": "S-1-5-21-3623811015-3361044348-30300820-<CHANGE: actor RID>",
        "SubjectUserName": "<CHANGE: actor>",
        "SubjectDomainName": "PHANTOM",
        "SubjectLogonId": "<CHANGE: actor logon id>",
        "ObjectServer": "DS",
        "ObjectType": "%{bf967aba-0de6-11d0-a285-00aa003049e2}",
        "ObjectName": "CN=krbtgt,CN=Users,DC=phantom,DC=lab",
        "HandleId": "0x0",
        "OperationType": "Object Access",
        "AccessMask": "0x100",
        "Properties": "{1131f6aa-9c07-11d1-f79f-00c04fc2dcd2}; {1131f6ad-9c07-11d1-f79f-00c04fc2dcd2}; {1131f6ae-9c07-11d1-f79f-00c04fc2dcd2}; {89e95b76-444d-4c62-991a-0facbeda640c}",
        "Parameter1": "-",
        "Parameter2": "-"
      }
    },
    {
      "event_id": 4662,
      "computer": "PHDC02",
      "time": "now-296s",
      "provider": "Microsoft-Windows-Security-Auditing",
      "rendering": {
        "message": "An operation was performed on an object.\n\nSubject :\n\tSecurity ID:\t\tS-1-5-21-3623811015-3361044348-30300820-<CHANGE: actor RID>\n\tAccount Name:\t\t<CHANGE: actor>\n\tAccount Domain:\t\tPHANTOM\n\tLogon ID:\t\t<CHANGE: actor logon id>\n\nObject:\n\tObject Server:\t\tDS\n\tObject Type:\t\t%{bf967aba-0de6-11d0-a285-00aa003049e2}\n\tObject Name:\t\tCN=krbtgt,CN=Users,DC=phantom,DC=lab\n\tHandle ID:\t\t0x0\n\nOperation:\n\tOperation Type:\t\tObject Access\n\tAccess Mask:\t\t0x100\n\tProperties:\t\t{1131f6aa-9c07-11d1-f79f-00c04fc2dcd2}; {1131f6ad-9c07-11d1-f79f-00c04fc2dcd2}; {1131f6ae-9c07-11d1-f79f-00c04fc2dcd2}; {89e95b76-444d-4c62-991a-0facbeda640c}\n\t\t\tCN=krbtgt,CN=Users,DC=phantom,DC=lab\n\nAdditional Information:\n\tParameter 1:\t\t-\n\tParameter 2:\t\t-",
        "task": "Directory Service Access"
      },
      "event_data": {
        "SubjectUserSid": "S-1-5-21-3623811015-3361044348-30300820-<CHANGE: actor RID>",
        "SubjectUserName": "<CHANGE: actor>",
        "SubjectDomainName": "PHANTOM",
        "SubjectLogonId": "<CHANGE: actor logon id>",
        "ObjectServer": "DS",
        "ObjectType": "%{bf967aba-0de6-11d0-a285-00aa003049e2}",
        "ObjectName": "CN=krbtgt,CN=Users,DC=phantom,DC=lab",
        "HandleId": "0x0",
        "OperationType": "Object Access",
        "AccessMask": "0x100",
        "Properties": "{1131f6aa-9c07-11d1-f79f-00c04fc2dcd2}; {1131f6ad-9c07-11d1-f79f-00c04fc2dcd2}; {1131f6ae-9c07-11d1-f79f-00c04fc2dcd2}; {89e95b76-444d-4c62-991a-0facbeda640c}",
        "Parameter1": "-",
        "Parameter2": "-"
      }
    },
    {
      "event_id": 4662,
      "computer": "PHDC02",
      "time": "now-292s",
      "provider": "Microsoft-Windows-Security-Auditing",
      "rendering": {
        "message": "An operation was performed on an object.\n\nSubject :\n\tSecurity ID:\t\tS-1-5-21-3623811015-3361044348-30300820-<CHANGE: actor RID>\n\tAccount Name:\t\t<CHANGE: actor>\n\tAccount Domain:\t\tPHANTOM\n\tLogon ID:\t\t<CHANGE: actor logon id>\n\nObject:\n\tObject Server:\t\tDS\n\tObject Type:\t\t%{bf967aba-0de6-11d0-a285-00aa003049e2}\n\tObject Name:\t\tCN=krbtgt,CN=Users,DC=phantom,DC=lab\n\tHandle ID:\t\t0x0\n\nOperation:\n\tOperation Type:\t\tObject Access\n\tAccess Mask:\t\t0x100\n\tProperties:\t\t{1131f6aa-9c07-11d1-f79f-00c04fc2dcd2}; {1131f6ad-9c07-11d1-f79f-00c04fc2dcd2}; {1131f6ae-9c07-11d1-f79f-00c04fc2dcd2}; {89e95b76-444d-4c62-991a-0facbeda640c}\n\t\t\tCN=krbtgt,CN=Users,DC=phantom,DC=lab\n\nAdditional Information:\n\tParameter 1:\t\t-\n\tParameter 2:\t\t-",
        "task": "Directory Service Access"
      },
      "event_data": {
        "SubjectUserSid": "S-1-5-21-3623811015-3361044348-30300820-<CHANGE: actor RID>",
        "SubjectUserName": "<CHANGE: actor>",
        "SubjectDomainName": "PHANTOM",
        "SubjectLogonId": "<CHANGE: actor logon id>",
        "ObjectServer": "DS",
        "ObjectType": "%{bf967aba-0de6-11d0-a285-00aa003049e2}",
        "ObjectName": "CN=krbtgt,CN=Users,DC=phantom,DC=lab",
        "HandleId": "0x0",
        "OperationType": "Object Access",
        "AccessMask": "0x100",
        "Properties": "{1131f6aa-9c07-11d1-f79f-00c04fc2dcd2}; {1131f6ad-9c07-11d1-f79f-00c04fc2dcd2}; {1131f6ae-9c07-11d1-f79f-00c04fc2dcd2}; {89e95b76-444d-4c62-991a-0facbeda640c}",
        "Parameter1": "-",
        "Parameter2": "-"
      }
    },
    {
      "event_id": 4662,
      "computer": "PHDC02",
      "time": "now-288s",
      "provider": "Microsoft-Windows-Security-Auditing",
      "rendering": {
        "message": "An operation was performed on an object.\n\nSubject :\n\tSecurity ID:\t\tS-1-5-21-3623811015-3361044348-30300820-<CHANGE: actor RID>\n\tAccount Name:\t\t<CHANGE: actor>\n\tAccount Domain:\t\tPHANTOM\n\tLogon ID:\t\t<CHANGE: actor logon id>\n\nObject:\n\tObject Server:\t\tDS\n\tObject Type:\t\t%{bf967aba-0de6-11d0-a285-00aa003049e2}\n\tObject Name:\t\tCN=krbtgt,CN=Users,DC=phantom,DC=lab\n\tHandle ID:\t\t0x0\n\nOperation:\n\tOperation Type:\t\tObject Access\n\tAccess Mask:\t\t0x100\n\tProperties:\t\t{1131f6aa-9c07-11d1-f79f-00c04fc2dcd2}; {1131f6ad-9c07-11d1-f79f-00c04fc2dcd2}; {1131f6ae-9c07-11d1-f79f-00c04fc2dcd2}; {89e95b76-444d-4c62-991a-0facbeda640c}\n\t\t\tCN=krbtgt,CN=Users,DC=phantom,DC=lab\n\nAdditional Information:\n\tParameter 1:\t\t-\n\tParameter 2:\t\t-",
        "task": "Directory Service Access"
      },
      "event_data": {
        "SubjectUserSid": "S-1-5-21-3623811015-3361044348-30300820-<CHANGE: actor RID>",
        "SubjectUserName": "<CHANGE: actor>",
        "SubjectDomainName": "PHANTOM",
        "SubjectLogonId": "<CHANGE: actor logon id>",
        "ObjectServer": "DS",
        "ObjectType": "%{bf967aba-0de6-11d0-a285-00aa003049e2}",
        "ObjectName": "CN=krbtgt,CN=Users,DC=phantom,DC=lab",
        "HandleId": "0x0",
        "OperationType": "Object Access",
        "AccessMask": "0x100",
        "Properties": "{1131f6aa-9c07-11d1-f79f-00c04fc2dcd2}; {1131f6ad-9c07-11d1-f79f-00c04fc2dcd2}; {1131f6ae-9c07-11d1-f79f-00c04fc2dcd2}; {89e95b76-444d-4c62-991a-0facbeda640c}",
        "Parameter1": "-",
        "Parameter2": "-"
      }
    }
  ]
}
```

What matters and why:

- **Four `4662` events, not one**, each a replication access: `AccessMask` `0x100`, `ObjectType` `%{bf967aba-0de6-11d0-a285-00aa003049e2}` (the domain object class), `ObjectName` the `krbtgt` DN, and `Properties` carrying the **DS-Replication GUIDs** `{1131f6aa-...}`, `{1131f6ad-...}`, `{1131f6ae-...}` and `{89e95b76-...}` (Get-Changes, Get-Changes-All, In-Filtered-Set and the replication-extended right). The detector reads them from the message text (`xdm.event.description`), so the `rendering.message` must carry the same `Properties:` line and `Access Mask: 0x100`.
- **The subject is an ordinary new user**, not a domain controller and not a machine account (`...$`): the alert text itself says "not a machine account". Never use a name ending in `$`.
- **The 4624 first**: a network logon (`LogonType` 3, `Kerberos`) of the same user on `PHDC02` from the workstation, about 5 minutes before the 4662 events. Whether it is required is not established, so keep it.
- **Free to change**: the account, the RID, the workstation and its address.

## Route B: Cribl (same events, same alert)

Send the **same 5 events as Step 1** through the tenant's Cribl endpoint instead of the Windows Event Collector: call **`http-sender.send_events`** once with the same `events` list (every `<CHANGE: ...>` filled exactly as in Step 1) plus the destination. Do not build any XML: the connector renders each event to Windows Event XML itself. Precondition 1B applies instead of 1A.

```text
http-sender.send_events
{"events": <the same events list as Step 1>, "destination": "cribl_windows_events"}
```

The answer carries `ok: true`, `destination: cribl_windows_events`, `dataset: microsoft_windows_raw` and `num_records` equal to 5. The rows land in `microsoft_windows_raw` with `_transport = "cribl"` and no `_collector_type`; the columns and `xdm.*` fields are the same as over WEC, so Steps 2 and 3 are unchanged (only the stamp check differs).


## Step 2: confirm the events landed and modeled (about 2 minutes after Step 1)

```
config timeframe = 1h | datamodel dataset = microsoft_windows_raw
| filter xdm.event.id = "4662" and xdm.source.user.username = "<actor>"
| fields _time, xdm.event.id, xdm.source.user.username, xdm.source.host.hostname, xdm.event.description
```

Pass when **4 rows** return and `xdm.event.description` contains `1131f6aa-9c07-11d1-f79f-00c04fc2dcd2` and `0x100`.

## Step 3: wait, then check for the alert

Check **1 minute** after the send, then every minute for up to **15 minutes** (it typically arrives within a minute or two):

```
dataset = alerts
| filter alert_name = "Possible DCSync by an unusual user"
| fields _time, alert_id, alert_name, severity, host_name, user_name, description
| sort desc _time
| limit 5
```

Pass when a new row names your actor. To list Analytics alerts without naming one, filter on the STORED enum values `alert_source in ("MAGNIFIER","ANALYTICS_BIOC")`: the displayed names `XDR_ANALYTICS` and `XDR_ANALYTICS_BIOC` match nothing.

If nothing arrives in 15 minutes: confirm Step 2 (the events must be in `microsoft_windows_raw` and modeled, with the stamp of the route you used: `_collector_type = "WEC"` for Route A, `_transport = "cribl"` for Route B), confirm every identity was new (precondition 2), then retry **once** with a new actor and new RIDs. Do not change the event body.

## Report back to the operator

State the actor, the RIDs and the host names used, the number of events sent, the Step 2 result and either the alert id with the arrival time or that nothing arrived in 15 minutes and what you checked. Say that the actor must not be reused: the detector's history is per account and its deduplication is one day.
