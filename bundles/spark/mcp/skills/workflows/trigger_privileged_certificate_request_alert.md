---
name: trigger_privileged_certificate_request_alert
displayName: Trigger the Cortex "Suspicious privileged certificate request via certificate template" analytics alert
category: workflows
description: 'Fire Cortex XSIAM''s native "Suspicious privileged certificate request via certificate template" analytics BIOC (Low, T1078.002, ESC8 text) by sending ONE synthetic Windows Security event 4887 (Certificate Services issued a certificate) through the wec-sender connector (Windows Event Collector, Route A) or through http-sender with destination cribl_windows_events (the tenant Cribl endpoint with the Windows UUID, Route B): a machine account obtains a certificate from the DomainController template on the CA PHSRV-CA01. Use when the operator asks to trigger, demo, prove or reproduce an AD CS, ESC8 or privileged certificate template alert. It fires over both routes and never over syslog/CEF.'
icon: security
source: platform
loadingMode: on-demand
locked: false
---

# Skill: Trigger the "Suspicious privileged certificate request via certificate template" alert

## When this skill applies

The operator wants an **AD CS (certificate services) analytics alert** to fire, for example: *"trigger an ESC8 alert"*, *"show a privileged certificate being requested"*, *"prove Active Directory Certificate Services analytics fire from Windows events"*.

The detector is **not a correlation rule**; it is Cortex's own analytics (XDR Analytics BIOC), and nothing needs installing on the tenant beyond the Windows pack that already models `microsoft_windows_raw`. It reads Windows events that arrive through a registered Windows source, so the call below goes either to `wec-sender.send_events` (Route A) or to `http-sender.send_events` with `destination: "cribl_windows_events"` (Route B), never to a syslog/CEF worker.

## What the detector looks for (Cortex doc: "Privileged certificate request via certificate template")

| Property | Value |
|---|---|
| Alert name | `Suspicious privileged certificate request via certificate template` (Low), a variation of the doc's `Privileged certificate request via certificate template` (Informational, invisible); the catalog also lists `Suspicious privileged certificate request denied via certificate template` (Medium) |
| Source | `XDR Analytics BIOC`, MITRE T1078.002 Valid Accounts: Domain Accounts; alert tags `DT:Active Directory Certificate Services Analytics`, `DT:Identity Analytics`, `DS:Microsoft/Windows` |
| Required data (doc) | Windows Event Collector OR XDR Agent with eXtended Threat Hunting (XTH); the doc lists the Identity Analytics module |
| Activation / training (doc) | 14 days / 30 days in the documentation; in practice every alert arrives within minutes of its events |
| Test period | single event |
| Deduplication | 1 day for the family (doc) |
| What the alert text says | *"A privileged certificate was requested by PHANTOM\<requester>$ via certificate template. This certificate was requested via the template DomainController. This may indicate abuse of the ESC8 ADCS attack"*. The alert carries no user name; it is on host `PHSRV-CA01.phantom.lab`, so attribute by the requester in the description |

Did **not** fire this alert: the same 4887 with `CertificateTemplate:Machine` (a plain machine certificate, two shapes). The same 4887 events were also meant to raise the Medium `A machine certificate was issued with a mismatch`; that alert never appeared.

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
| 2 | Every identity below is **new**: a user name, a computer name and a RID never used in an earlier run, and a user name that is not a person's. Use a requester that was never seen. | `config timeframe = 30d \| datamodel dataset = microsoft_windows_raw \| filter xdm.source.user.username = "<actor>" \| limit 1` returns **no row** |
| 3 | Every event time is **now** or a few minutes earlier, UTC. Write it as `now-310s` (the connector resolves it with its own clock; an absolute `YYYY-MM-DDTHH:MM:SSZ` also works): the connector turns `time` into the event's TimeCreated and that becomes `_time`, and the detector windows are evaluated on it. Never in the future | generate at call time |


## Expected result

Over both routes (WEC and Cribl) the event in Step 1, with a new machine and number, fires the alert (Low), typically within a minute of the send call, naming `PHANTOM\<machine>$`. Use identities (machine, number) never seen before.

## Step 1: send the events (exactly this call)

**Route A (WEC).** Call **`wec-sender.send_events`** once with the 1 event below. Replace only the values marked `<CHANGE: ...>` (the same label means the same value everywhere it appears); everything else is the verbatim shape that fires.

| Placeholder | Put here |
|---|---|
| `now-Ns` (also `now`, `now-5m`, `now-1h`) | **leave it as this literal text, do not work out a date or time yourself**: the connector replaces it with its own current UTC time minus N seconds when it sends |
| `<CHANGE: actor RID>` | a new number, 3300 or higher, never reused: it is the request id and part of the certificate serial number |
| `<CHANGE: machine>` | a new computer name `PHWS-<NNN>` that requests the certificate; the requester shows as `PHANTOM\<machine>$` |

```json
{
  "events": [
    {
      "event_id": 4887,
      "computer": "PHSRV-CA01",
      "time": "now-120s",
      "provider": "Microsoft-Windows-Security-Auditing",
      "rendering": {
        "message": "Certificate Services approved a certificate request and issued a certificate.\n\nRequest ID:\t<CHANGE: actor RID>\nRequester:\tPHANTOM\\<CHANGE: machine>$\nAttributes:\tCertificateTemplate:DomainController\nccm:PHDC02.phantom.lab\nDisposition:\t3\nSubject Key Identifier:\t0a1b2c3d4e5f60718293a4b5c6d7e8f9<CHANGE: actor RID>00000\nSerial Number:\t5a6b7c8d9e0f1a2b3c4d5e6f<CHANGE: actor RID>0000",
        "task": "Certification Services"
      },
      "event_data": {
        "RequestId": "<CHANGE: actor RID>",
        "Requester": "PHANTOM\\<CHANGE: machine>$",
        "Attributes": "CertificateTemplate:DomainController\nccm:PHDC02.phantom.lab",
        "Disposition": "3",
        "SubjectKeyIdentifier": "0a1b2c3d4e5f60718293a4b5c6d7e8f9<CHANGE: actor RID>00000",
        "SerialNumber": "5a6b7c8d9e0f1a2b3c4d5e6f<CHANGE: actor RID>0000"
      }
    }
  ]
}
```

What matters and why:

- **`event_id` 4887** on the certificate authority host **`PHSRV-CA01`**, provider `Microsoft-Windows-Security-Auditing`, task `Certification Services`: "Certificate Services approved a certificate request and issued a certificate". `event_data`: `RequestId`, `Requester` (`PHANTOM\<machine>$`), `Attributes`, `Disposition 3` (issued), `SubjectKeyIdentifier`, `SerialNumber`.
- **`Attributes` carries the template**: `CertificateTemplate:DomainController`, plus `ccm:PHDC02.phantom.lab` (the requested machine name). The template name is what makes the request "privileged"; `CertificateTemplate:Machine` does not fire.
- **The requester is a new machine account**, so the alert names it (`PHANTOM\<machine>$`).
- **`rendering.message`/`task`/`provider`** are required (not catalogued).
- **Free to change**: the machine name and the number. Keep the template `DomainController`.

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
| filter xdm.event.id = "4887" and xdm.event.description contains "<machine>"
| fields _time, xdm.event.id, xdm.source.host.hostname, xdm.event.description
```

Pass when one row returns for host `PHSRV-CA01.phantom.lab` and its description contains `CertificateTemplate:DomainController`. Over Route A add `_collector_type = "WEC"` (raw dataset) and over Route B `_transport = "cribl"` to confirm the stamp.

## Step 3: wait, then check for the alert

Check **1 minute** after the send, then every minute for up to **15 minutes** (the alert typically arrives within about a minute):

```
dataset = alerts
| filter alert_name = "Suspicious privileged certificate request via certificate template"
| filter description contains "<machine>"
| fields _time, alert_id, alert_name, severity, host_name, user_name, description
| sort desc _time
| limit 5
```

Pass when a new row names your requester. To list Analytics alerts without naming one, filter on the STORED enum values `alert_source in ("MAGNIFIER","ANALYTICS_BIOC")`: the displayed names `XDR_ANALYTICS` and `XDR_ANALYTICS_BIOC` match nothing.

If nothing arrives in 15 minutes: confirm Step 2, confirm the machine name was new, then retry **once** with a new machine and number. Do not change the event body.

## Report back to the operator

State the machine, the number, the number of events sent, the Step 2 result and either the alert id with the arrival time or that nothing arrived in 15 minutes and what you checked. Say that the requester must not be reused.
