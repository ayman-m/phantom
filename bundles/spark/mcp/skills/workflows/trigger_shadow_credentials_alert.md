---
name: trigger_shadow_credentials_alert
displayName: Trigger the Cortex "Possible shadow credentials addition" analytics alert
category: workflows
description: 'Fire Cortex XSIAM''s native "Possible shadow credentials addition" analytics BIOC (Medium, T1556, tags Identity Analytics and Active Directory Certificate Services Analytics) by sending ONE synthetic Windows Security event 5136 through the wec-sender connector (Windows Event Collector, Route A) or through http-sender with destination cribl_windows_events (the tenant Cribl endpoint with the Windows UUID, Route B): a new account adds a value to the msDS-KeyCredentialLink attribute of a computer object. Use when the operator asks to trigger, demo, prove or reproduce a shadow credentials, msDS-KeyCredentialLink or key credential alert. It fires over both routes and never over syslog/CEF.'
icon: security
source: platform
loadingMode: on-demand
locked: false
---

# Skill: Trigger the "Possible shadow credentials addition" alert

## When this skill applies

The operator wants the native **Cortex Analytics shadow-credentials detector** to fire, for example: *"trigger a shadow credentials alert"*, *"show msDS-KeyCredentialLink abuse"*, *"prove T1556 fires from Windows events"*.

The detector is **not a correlation rule**; it is Cortex's own analytics (XDR Analytics BIOC), and nothing needs installing on the tenant beyond the Windows pack that already models `microsoft_windows_raw`. It reads Windows events that arrive through a registered Windows source, so the call below goes either to `wec-sender.send_events` (Route A) or to `http-sender.send_events` with `destination: "cribl_windows_events"` (Route B), never to a syslog/CEF worker.

## What the detector looks for (Cortex doc: "Key credential attribute modification")

| Property | Value |
|---|---|
| Alert name | `Possible shadow credentials addition` (Medium), a variation of the doc's `Key credential attribute modification` (Informational, invisible); the catalog also lists `Key credential attribute addition` (Low) |
| Source | `XDR Analytics BIOC`, MITRE T1556 Modify Authentication Process (tactics Credential Access, Persistence, Defense Impairment); alert tags `DT:Active Directory Certificate Services Analytics`, `DT:Identity Analytics`, `DS:Microsoft/Windows` |
| Required data (doc) | Windows Event Collector OR XDR Agent with eXtended Threat Hunting (XTH); the doc lists the Identity Analytics module |
| Activation / training (doc) | 14 days / 30 days. In practice the alert typically arrives within a minute or two of its events |
| Test period | single event |
| Deduplication | 1 day |
| What the alert text says | *"The user <domain>\<actor> modified the msDS-KeyCredentialLink attribute for an account. The account modified: CN=<machine>,CN=Computers,DC=phantom,DC=lab. A new key credential value was added to the attribute. The attribute changed: msDS-KeyCredentialLink. The account type: computer. The logon ID: <logon id>. This user has modified the attribute on 0 days out of the past 30 days"* |

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

The recipe fires from a new account writing a key credential on a new computer object, over Route A (WEC) and over Route B (Cribl). The Medium alert names the actor (`phantom\<actor>`) and typically arrives within a minute (counted from the start of the send call). Every run must use identities (actor, RIDs, computer names) never seen before.

## Step 1: send the events (exactly this call)

**Route A (WEC).** Call **`wec-sender.send_events`** once with the 1 event below. Replace only the values marked `<CHANGE: ...>` (the same label means the same value everywhere it appears); everything else is the verbatim shape that fires.

| Placeholder | Put here |
|---|---|
| `now-Ns` (also `now`, `now-5m`, `now-1h`) | **leave it as this literal text, do not work out a date or time yourself**: the connector replaces it with its own current UTC time minus N seconds when it sends |
| `<CHANGE: actor>` | a new account name that is not a person's, e.g. `adm.runNNNN` (letters, digits, dot) |
| `<CHANGE: actor RID>` | a new RID, 3300 or higher, never reused (the SID is `S-1-5-21-3623811015-3361044348-30300820-<RID>`) |
| `<CHANGE: actor logon id>` | a new hex logon id such as `0x9A4C21` |
| `<CHANGE: machine>` | a new computer name `PHWS-<NNN>`: the computer object whose key credential is written |

```json
{
  "events": [
    {
      "event_id": 5136,
      "computer": "PHDC02",
      "time": "now-120s",
      "provider": "Microsoft-Windows-Security-Auditing",
      "rendering": {
        "message": "A directory service object was modified.\n\nSubject:\n\tSecurity ID:\t\tS-1-5-21-3623811015-3361044348-30300820-<CHANGE: actor RID>\n\tAccount Name:\t\t<CHANGE: actor>\n\tAccount Domain:\t\tPHANTOM\n\tLogon ID:\t\t<CHANGE: actor logon id>\n\nDirectory Service:\n\tName:\tphantom.lab\n\tType:\tActive Directory Domain Services\n\nObject:\n\tDN:\tCN=<CHANGE: machine>,CN=Computers,DC=phantom,DC=lab\n\tGUID:\t{<CHANGE: actor RID>0000-4d5e-6f70-8192-a3b4c5d6e7f8}\n\tClass:\tcomputer\n\nAttribute:\n\tLDAP Display Name:\tmsDS-KeyCredentialLink\n\tSyntax (OID):\t2.5.5.7\n\tValue:\tB:828:0002000020000a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1:CN=<CHANGE: machine>,CN=Computers,DC=phantom,DC=lab\n\nOperation:\n\tType:\tValue Added\n\tCorrelation ID:\t{<CHANGE: actor RID>1111-1f2a-3b4c-5d6e-7f8091a2b3c4}\n\tApplication Correlation ID:\t-",
        "task": "Directory Service Changes"
      },
      "event_data": {
        "OpCorrelationID": "{<CHANGE: actor RID>1111-1f2a-3b4c-5d6e-7f8091a2b3c4}",
        "AppCorrelationID": "-",
        "SubjectUserSid": "S-1-5-21-3623811015-3361044348-30300820-<CHANGE: actor RID>",
        "SubjectUserName": "<CHANGE: actor>",
        "SubjectDomainName": "PHANTOM",
        "SubjectLogonId": "<CHANGE: actor logon id>",
        "DSName": "phantom.lab",
        "DSType": "%%14676",
        "ObjectDN": "CN=<CHANGE: machine>,CN=Computers,DC=phantom,DC=lab",
        "ObjectGUID": "{<CHANGE: actor RID>0000-4d5e-6f70-8192-a3b4c5d6e7f8}",
        "ObjectClass": "computer",
        "AttributeLDAPDisplayName": "msDS-KeyCredentialLink",
        "AttributeSyntaxOID": "2.5.5.7",
        "AttributeValue": "B:828:0002000020000a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1:CN=<CHANGE: machine>,CN=Computers,DC=phantom,DC=lab",
        "OperationType": "%%14674"
      }
    }
  ]
}
```

What matters and why:

- **`event_id` 5136** (a directory service object was modified) on the domain controller `PHDC02`: `AttributeLDAPDisplayName` **`msDS-KeyCredentialLink`**, `OperationType` **`%%14674`** (value added; the message says `Value Added`), `ObjectClass` `computer`, `ObjectDN` the computer's DN, `AttributeSyntaxOID` `2.5.5.7`.
- **`AttributeValue`** is a key-credential blob in the real `B:<length>:<hex>:<owner DN>` layout. A repeated `a1` pattern works as the hex; keep the prefix and the trailing DN of the same object.
- **The subject is a new account** that is not the object itself. The alert says the user "has modified the attribute on 0 days out of the past 30 days", so the actor must be new.
- **`rendering.message`/`task`/`provider`** are required (not catalogued). The `Operation: Type: Value Added` line and the `Attribute:` block carry the same values as `event_data`; keep the layout.
- **Free to change**: the actor, its RID and logon id, the computer name. Only the computer-object shape is covered; a user object (`ObjectClass user`) is not.

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
| filter xdm.event.id = "5136" and xdm.source.identity.username = "<actor>"
| fields _time, xdm.event.id, xdm.source.identity.username, xdm.source.host.hostname, xdm.event.description
```

Pass when one row returns for host `PHDC02.phantom.lab` and its description contains `msDS-KeyCredentialLink`. Over Route A add `_collector_type = "WEC"` (raw dataset) and over Route B `_transport = "cribl"` to confirm the stamp.

## Step 3: wait, then check for the alert

Check **1 minute** after the send, then every minute for up to **15 minutes** (it typically arrives within a minute):

```
dataset = alerts
| filter alert_name = "Possible shadow credentials addition"
| fields _time, alert_id, alert_name, severity, host_name, user_name, description
| sort desc _time
| limit 5
```

Pass when a new row names your actor. To list Analytics alerts without naming one, filter on the STORED enum values `alert_source in ("MAGNIFIER","ANALYTICS_BIOC")`: the displayed names `XDR_ANALYTICS` and `XDR_ANALYTICS_BIOC` match nothing.

If nothing arrives in 15 minutes: confirm Step 2, confirm every identity was new (precondition 2), then retry **once** with a new actor and new RIDs. Do not change the event body.

## Report back to the operator

State the actor, the RIDs, the computer name used, the number of events sent, the Step 2 result and either the alert id with the arrival time or that nothing arrived in 15 minutes and what you checked. Say that the actor must not be reused: the detector's history is per account and its deduplication is one day.
