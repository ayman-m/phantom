---
name: trigger_default_account_masquerade_alert
displayName: Trigger the Cortex "Masquerading as a default local account" analytics alert
category: workflows
description: 'Fire Cortex XSIAM''s native "Masquerading as a default local account" analytics BIOC (Low, T1564.002, T1078.001 and T1036) by sending TWO synthetic Windows Security events 4720 on a member server: a new administrator account creates LOCAL accounts named DefaultAccount and Guest, one alert per account. Two delivery routes fire it: wec-sender (Windows Event Collector) and http-sender with destination cribl_windows_events (the tenant Cribl endpoint with the Windows UUID). Use when the operator asks to trigger, demo, prove or reproduce an account masquerading as a default Windows account, a new local Guest or DefaultAccount user, or a 4720 of a default account name. It never fires over syslog/CEF.'
icon: admin_panel_settings
source: platform
loadingMode: on-demand
locked: false
---

# Skill: Trigger the "Masquerading as a default local account" alert

## When this skill applies

The operator wants the native **Cortex Analytics detector for a new local account that copies a default Windows account name** to fire, for example: *"trigger a default account masquerade alert"*, *"show a new local Guest account being created"*, *"prove T1036 fires from Windows events"*. A send with a new actor or a new host raises two alerts, one per account; an exact repeat raises none (see "Freshness").

The detector is **not a correlation rule**; it is Cortex's own analytics (XDR Analytics BIOC), and nothing needs installing on the tenant beyond the Windows pack that already models `microsoft_windows_raw`. It reads Windows events that arrive through a registered Windows source, so the call below goes either to `wec-sender.send_events` (Route A) or to `http-sender.send_events` with `destination: "cribl_windows_events"` (Route B), never to a syslog/CEF worker.

## What the detector looks for (Cortex doc: "Masquerading as a default local account")

| Property | Value |
|---|---|
| Alert name | `Masquerading as a default local account` (Low). The doc lists variations that do not appear from this recipe: `... for the first time` (Medium), `Potential masquerading as a power user account` (Low) and `Masquerading as a default Administrator account` (Informational, invisible) |
| Source | `XDR Analytics BIOC`, MITRE T1564.002 Hide Artifacts: Hidden Users, T1078.001 Valid Accounts: Default Accounts, T1036 Masquerading (tactics TA0001, TA0003, TA0004, TA0005); alert tags `DS:Microsoft/Windows`, `DOM:Security`, `DT:Identity Analytics` |
| Doc description | A user created a new local account with the name of a default local account, such as Guest and DefaultAccount |
| Required data (doc) | Windows Event Collector OR XDR Agent with eXtended Threat Hunting (XTH); the doc lists the Identity Analytics module |
| Activation / training (doc) | 14 days / 30 days. In practice the alert typically arrives within a minute or two of its events |
| Test period | single event |
| Deduplication | 1 day |
| What the alert text says | *"The user <domain>\<actor> created a new user named <host>\guest. This user has created 0 user accounts in the past 30 days. This user mimics the name of a default Windows local account"* (and the same for `<host>\defaultaccount`) |

## Which delivery paths fire it

Windows identity detectors read the registered Windows source, not the syslog/CEF feed. Over syslog/CEF the same event types **land and model** in `microsoft_windows_raw` but no Windows identity alert fires from them (the same scenarios sent over syslog/CEF raised none). Two paths carry the same structured events and fire:

- **Route A, WEC**: `wec-sender.send_events` delivers through the Broker VM's Windows Event Collector over mutual TLS. Rows land with `_collector_type = WEC`.
- **Route B, Cribl**: `http-sender.send_events` with `destination: "cribl_windows_events"` renders the same events to Windows Event XML and posts them to the tenant's Cribl endpoint with the Windows UUID. Rows land in the same dataset with `_transport = cribl` and no `_collector_type`; the columns and `xdm.*` fields are the same. It needs no Broker, no certificate and no subscription.

Do not "test it quickly" over syslog: a null result there says nothing about the rule.

## Preconditions: check these BEFORE sending

| # | Must be true | How to check |
|---|---|---|
| 1A | Route A only: the `wec-sender` connector instance is running and `wec-sender.list_subscriptions` returns `ok: true` with a subscription whose channels include `Security` (for example the subscription "Authentication Event Logs" on the Broker VM, port 5986) | call `wec-sender.list_subscriptions` |
| 1B | Route B only: the `http-sender` instance has `criblUrl` and `criblToken` set, so `http-sender.list_destinations` lists `cribl_windows_events` with `ready: true` and `dataset: microsoft_windows_raw` | call `http-sender.list_destinations` |
| 2 | The **actor** is new: an account name and RID never used in an earlier run (use **3300 or higher** and never reuse one). That is the safe default. The two created names are fixed by the detector (`DefaultAccount`, `Guest`), so freshness comes from the actor and the host: see "Freshness" | `config timeframe = 30d \| datamodel dataset = microsoft_windows_raw \| filter xdm.source.user.username = "<actor>" \| limit 1` returns **no row** |
| 3 | Every event time is **now** or a few minutes earlier, UTC. Write it as `now-310s` (the connector resolves it with its own clock; an absolute `YYYY-MM-DDTHH:MM:SSZ` also works): the connector turns `time` into the event's TimeCreated and that becomes `_time`, and the detector windows are evaluated on it. Never in the future | generate at call time |

## Expected result

One send raises **two alerts**, one for `DefaultAccount` and one for `Guest` (the alert text names `<host>\defaultaccount` or `<host>\guest`), over Route A and over Route B. Each alert is attributed by the identity in the alert (`user_name`, host and the account named in the text), never by time alone. They typically arrive within a minute of the send call (the call itself takes about 10 s). Every alert is `LOW` with tags `DS:Microsoft/Windows`, `DOM:Security`, `DT:Identity Analytics`, MITRE T1564.002, T1078.001 and T1036; the alert text reads: *"The user phantom\<actor> created a new user named <host>\guest. This user has created 0 user accounts in the past 30 days. This user mimics the name of a default Windows local account"*. The count of accounts created stays `0` even for an actor who created local accounts a few minutes earlier.

Not covered by this recipe: its event shape over syslog/CEF; a Cribl exact repeat; whether the doc's variation `... for the first time` (Medium) can be raised (it does not appear from any send).

## Step 1: send the events (exactly this call)

Both routes send the **same 2 events**. Replace only the values marked `<CHANGE: ...>` (the same label means the same value everywhere it appears); everything else is the verbatim shape that fires.

| Placeholder | Put here |
|---|---|
| `now-Ns` (also `now`, `now-5m`, `now-1h`) | **leave it as this literal text, do not work out a date or time yourself**: the connector replaces it with its own current UTC time minus N seconds when it sends |
| `<CHANGE: actor>` | a new account name that is not a person's, e.g. `adm.runNNNN` (letters, digits, dot) |
| `<CHANGE: actor RID>` | a new RID, 3300 or higher, never reused (the SID is `S-1-5-21-3623811015-3361044348-30300820-<RID>`) |
| `<CHANGE: actor logon id>` | a new hex logon id such as `0x9A4C21` |
| `<CHANGE: machine>` | the member server's computer name, which is also the local account domain. Use a name such as `PHSRV-WEB01`, and a new name `PHSRV-WEBnn` for a new host (see "Freshness") |
| `<CHANGE: machine RID>` | the RID of the new local `DefaultAccount` (local SID `S-1-5-21-7654321-7654321-7654321-<RID>`), 3300 or higher |
| `<CHANGE: member RID>` | the RID of the new local `Guest`, 3300 or higher, different from the other two |

**Route A (WEC).** Call **`wec-sender.send_events`** once with this body:

```json
{
  "events": [
    {
      "event_id": 4720,
      "computer": "<CHANGE: machine>",
      "time": "now-130s",
      "provider": "Microsoft-Windows-Security-Auditing",
      "rendering": {
        "message": "A user account was created.\n\nSubject:\n\tSecurity ID:\t\tS-1-5-21-3623811015-3361044348-30300820-<CHANGE: actor RID>\n\tAccount Name:\t\t<CHANGE: actor>\n\tAccount Domain:\t\tPHANTOM\n\tLogon ID:\t\t<CHANGE: actor logon id>\n\nNew Account:\n\tSecurity ID:\t\tS-1-5-21-7654321-7654321-7654321-<CHANGE: machine RID>\n\tAccount Name:\t\tDefaultAccount\n\tAccount Domain:\t\t<CHANGE: machine>\n\nAttributes:\n\tSAM Account Name:\tDefaultAccount",
        "task": "User Account Management"
      },
      "event_data": {
        "SubjectUserSid": "S-1-5-21-3623811015-3361044348-30300820-<CHANGE: actor RID>",
        "SubjectUserName": "<CHANGE: actor>",
        "SubjectDomainName": "PHANTOM",
        "SubjectLogonId": "<CHANGE: actor logon id>",
        "TargetUserName": "DefaultAccount",
        "TargetDomainName": "<CHANGE: machine>",
        "TargetSid": "S-1-5-21-7654321-7654321-7654321-<CHANGE: machine RID>",
        "SamAccountName": "DefaultAccount",
        "PrivilegeList": "-"
      }
    },
    {
      "event_id": 4720,
      "computer": "<CHANGE: machine>",
      "time": "now-120s",
      "provider": "Microsoft-Windows-Security-Auditing",
      "rendering": {
        "message": "A user account was created.\n\nSubject:\n\tSecurity ID:\t\tS-1-5-21-3623811015-3361044348-30300820-<CHANGE: actor RID>\n\tAccount Name:\t\t<CHANGE: actor>\n\tAccount Domain:\t\tPHANTOM\n\tLogon ID:\t\t<CHANGE: actor logon id>\n\nNew Account:\n\tSecurity ID:\t\tS-1-5-21-7654321-7654321-7654321-<CHANGE: member RID>\n\tAccount Name:\t\tGuest\n\tAccount Domain:\t\t<CHANGE: machine>\n\nAttributes:\n\tSAM Account Name:\tGuest",
        "task": "User Account Management"
      },
      "event_data": {
        "SubjectUserSid": "S-1-5-21-3623811015-3361044348-30300820-<CHANGE: actor RID>",
        "SubjectUserName": "<CHANGE: actor>",
        "SubjectDomainName": "PHANTOM",
        "SubjectLogonId": "<CHANGE: actor logon id>",
        "TargetUserName": "Guest",
        "TargetDomainName": "<CHANGE: machine>",
        "TargetSid": "S-1-5-21-7654321-7654321-7654321-<CHANGE: member RID>",
        "SamAccountName": "Guest",
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

- **Two `4720` events on a member server**, not a domain controller: the created accounts are **local** (`TargetDomainName` is the server's own name and `TargetSid` is a local SID `S-1-5-21-7654321-7654321-7654321-...`, not the domain SID). One alert is raised per created account.
- **The names `DefaultAccount` and `Guest` are the detector's** and cannot be changed. The doc says the detector watches default local account names "such as Guest and DefaultAccount".
- **The actor is an ordinary new account** that created no accounts in the past 30 days (the alert text says "has created 0 user accounts in the past 30 days").
- **`rendering.message`/`task`/`provider`** are required (event 4720 is not catalogued); keep the layout (tabs, blank lines).
- **Free to change**: the actor, its RID and logon id, the host name and the two local RIDs.

## Freshness: what makes a second run fire again

The two created names are fixed by the detector, so only the actor and the host can change. Over WEC, with the events landing in `microsoft_windows_raw` every time:

- A **new actor on the same host** fires again: two alerts.
- The **same actor on a new host** fires again: two alerts. The actor's two local accounts created minutes earlier do not suppress it, and the alert text still says "has created 0 user accounts in the past 30 days".
- An **exact repeat** (same actor, same host, same RIDs, fresh event times) lands and raises **no alert**, which fits the detector's 1-day deduplication.

So to fire it again, change the actor or the host. Changing both works too, over WEC and over Cribl. Never send the same actor on the same host again within a day. The single-variable behaviours above were observed over WEC only.

## Step 2: confirm the events landed and modeled (about 1 to 2 minutes after Step 1)

```text
config timeframe = 1h | datamodel dataset = microsoft_windows_raw
| filter xdm.event.id = "4720" and xdm.source.user.username = "<actor>"
| fields _time, xdm.event.id, xdm.source.user.username, xdm.source.host.hostname, xdm.event.description
```

Pass when **2 rows** return for the member server's host (`<host>.phantom.lab`), one whose `xdm.event.description` shows `Account Name:` `DefaultAccount` under "New Account" and one `Guest`. To prove which route carried them:

```text
config timeframe = 1h | dataset = microsoft_windows_raw
| filter event_id = "4720" and message contains "<actor>"
| fields _time, computer_name, event_id, _transport, _collector_type
```

Route A shows `_collector_type = WEC` and no `_transport`; Route B shows `_transport = cribl` and no `_collector_type`.

## Step 3: wait, then check for the alerts

Check **1 minute** after the send, then every minute for up to **15 minutes** (a fresh send typically arrives within a minute):

```text
config timeframe = 1d
| dataset = alerts
| filter alert_source in ("MAGNIFIER", "ANALYTICS_BIOC") and alert_name = "Masquerading as a default local account"
| fields _time, alert_id, alert_name, severity, host_name, user_name, description, alert_arrival_timestamp
| sort desc alert_arrival_timestamp
| limit 8
```

Pass when **two** new rows name your actor and your host, one reading `<host>\defaultaccount` and one `<host>\guest`. The filter uses the **stored** enum names `MAGNIFIER` and `ANALYTICS_BIOC`; the displayed names (`XDR_ANALYTICS...`) match nothing.

If nothing arrives in 15 minutes: confirm Step 2 (the events must be in `microsoft_windows_raw` and modeled, with the stamps of the route you used), confirm the actor was new (precondition 2), then retry **once** with a new actor, new RIDs and a new host name. Do not change the event body.

## Report back to the operator

State the route used, the actor, the host name, the RIDs, the number of events sent, the Step 2 result and either the alert ids with the arrival times (expect two, one per account) or that nothing arrived in 15 minutes and what you checked. Say that the same actor on the same host must not be sent twice within a day: an exact repeat raises no alert (see "Freshness"); a new actor or a new host fires again.
