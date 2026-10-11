---
name: trigger_large_upload_alert
displayName: Trigger the Cortex "Large Upload (Generic)" analytics alert
category: workflows
description: 'Fire Cortex XSIAM''s native "Large Upload (Generic)" analytics detector from synthetic Palo Alto NGFW traffic: one internal host sends about 2 GB in total (the alert reports 1.3 GB) to a public address it has never uploaded to, over a non-web port (unknown-tcp on 8443). Use when the operator asks to trigger, demo, prove or reproduce a large upload, data transfer to an external site, an exfiltration-volume alert or "Large Upload". The log must carry bytes_sent and sub_type end. The HTTPS variant has its own skill, trigger_large_upload_https_alert; the FTP and SMTP variants do not fire.'
icon: upload
source: platform
loadingMode: on-demand
locked: false
---

# Skill: Trigger the "Large Upload (Generic)" analytics alert

## When this skill applies

The operator wants the **native Cortex Analytics large-upload detector** to fire from firewall logs, for example:
*"trigger a large upload alert"*, *"show data leaving to an unknown destination"*, *"prove the exfil-volume detector works"*.

This is the **Generic** member of the Large Upload family: a transfer over a port that is not HTTP/S, FTP or SMTP. It fires on any fresh host.
The **HTTPS** member has its own skill, `trigger_large_upload_https_alert`; FTP and SMTP do not fire. It is not a correlation rule;
nothing needs installing on the tenant.

> **Expected result.** The alert typically arrives within 4 to 8 minutes of the burst. The HTTPS variant has its own skill; FTP and SMTP are silent.

## What the detector looks for (Cortex doc: "Large Upload (Generic)")

| Property | Value |
|---|---|
| Alert name | `Large Upload (Generic)` (Low). Variants `... Lower than 100 MB` and `... to a Frequently Used Upload Target` are Informational and invisible. The sibling `Large Upload (HTTPS)` is listed Informational in the catalog but fires Low (below) |
| Source | `XDR_ANALYTICS` |
| Required data | PAN NGFW traffic logs OR XDR agent |
| Test period | 1 day (the alert text counts the last 24 hours) |
| Deduplication | **1 day per source host** |
| Logic (doc) | The endpoint sent a large amount of data to an external site over a protocol other than HTTP/S, FTP or SMTP. Analytics assumes uploads go out over those services, so it expects traffic over other ports to be low, and it expects traffic to one destination to stay about the same over long periods |

## Preconditions: check these BEFORE sending

| # | Must be true | How to check |
|---|---|---|
| 1 | You know the operator's syslog **log destination object** (`logdest:<id>`; typically the broker's CEF port 5514) | `log_destinations_list` or the operator |
| 2 | The source **IP and host name are both fresh**: no `Large Upload (Generic)` alert for that host in 24 h, and an IP the tenant has not used (an IP that carried unrelated earlier traffic under another host name may be deduplicated; whether Cortex keys on the IP or the name is unproven, so change both) | Step 3 query without the time filter; `dataset = panw_ngfw_traffic_raw \| filter source_ip = "<ip>" \| comp count()` |
| 3 | The destination is a **public, routable** address (not RFC 5737 documentation space) that this host has **never** sent data to | `dataset = panw_ngfw_traffic_raw \| filter source_device_host = "<host>" and dest_ip = "<dest>" \| comp count()` must be 0 |
| 4 | The application is **not** web, FTP or SMTP: `app` is `unknown-tcp` and the port is `8443` | the call below |
| 5 | No other bounded burst is running | `phantom_list_workers` shows nothing `Running` |

No SSH-style history seeding is needed: a host with no deliberate baseline works, even one with no earlier traffic at all.

## Expected result

Three events of 600-730 MB each land about 2.0 GB in total; the alert reports **1.3 GB** ("uploaded 1.3GB to the external host <destination> in the last 24 hours ... on average of 0 bytes a day in the past 30 days") and typically arrives within 4 to 8 minutes of the burst.

### The sibling variants (same burst shape, 3 events each, `sub_type end`, 300-610 MB)

| Variant | app / port | Destination | Result |
|---|---|---|---|
| **HTTPS** | ssl / 443 | two ordinary public addresses | **fires, 2 alerts** `Large Upload (HTTPS)` (Low): "uploaded 1.1GB to <address> over 4 sessions in the last 24 hours" and "uploaded 584.0MB to <address> over 1 sessions", typically within about 6 minutes: see `trigger_large_upload_https_alert` |
| FTP | ftp / 21 | 198.51.100.77 | no alert |
| SMTP | smtp / 25 | 203.0.113.25 | no alert |

Likely reason for the FTP and SMTP silence, **unproven**: their destinations sit in RFC 5737 documentation ranges, which Analytics may not treat as external hosts (the Generic and HTTPS destinations are ordinary public addresses). If the operator needs FTP or SMTP, send to a public address and
treat it as a new experiment. The HTTPS call has its own skill, `trigger_large_upload_https_alert`, with the exact call.

## Step 1: send the burst (exactly this call)

Call **`phantom_create_data_worker`**. Change only the values marked `<CHANGE>`.

```json
{
  "type": "CEF",
  "vendor": "panw",
  "product": "ngfw_traffic",
  "destination": "<CHANGE: logdest:<id> of the operator's syslog destination>",
  "name": "bigup-generic-<CHANGE: short run id>",
  "tags": ["detection-validation", "T1048"],
  "count": 3,
  "interval": 1,
  "duration_seconds": 60,
  "max_events": 3,
  "schema_override": [
    {"name": "log_type", "type": "string"}, {"name": "sub_type", "type": "string"},
    {"name": "action", "type": "string"}, {"name": "app", "type": "string"},
    {"name": "protocol", "type": "string"}, {"name": "rule_matched", "type": "string"},
    {"name": "from_zone", "type": "string"}, {"name": "to_zone", "type": "string"},
    {"name": "source_ip", "type": "ipv4"}, {"name": "source_port", "type": "integer"},
    {"name": "source_user", "type": "string"}, {"name": "source_device_host", "type": "string"},
    {"name": "dest_ip", "type": "ipv4"}, {"name": "dest_port", "type": "integer"},
    {"name": "bytes_sent", "type": "integer"}, {"name": "bytes_received", "type": "integer"},
    {"name": "packets_sent", "type": "integer"}, {"name": "packets_received", "type": "integer"},
    {"name": "total_time_elapsed", "type": "integer"}, {"name": "session_id", "type": "integer"},
    {"name": "log_source", "type": "string"}
  ],
  "observables_dict": {
    "log_type": ["TRAFFIC"],
    "sub_type": ["end"],
    "action": ["allow"],
    "app": ["unknown-tcp"],
    "protocol": ["tcp"],
    "rule_matched": ["allow-outbound"],
    "from_zone": ["trust"],
    "to_zone": ["untrust"],
    "source_ip": ["<CHANGE: fresh internal IPv4, e.g. 10.20.14.14>"],
    "source_device_host": ["<CHANGE: fresh host name, e.g. WS-LU-02>"],
    "source_user": ["<CHANGE: a bare user name, no backslash, e.g. rana.alqahtani>"],
    "source_port": ["51501", "51502"],
    "dest_ip": ["<CHANGE: a public address this host never uploaded to, e.g. 185.199.110.153>"],
    "dest_port": ["8443"],
    "bytes_sent": ["629145600", "734003200"],
    "bytes_received": ["524288"],
    "packets_sent": ["450000"],
    "packets_received": ["6000"],
    "total_time_elapsed": ["2000", "2600"],
    "log_source": ["PA-3220-Acme"]
  }
}
```

Why each value is what it is:

- **`bytes_sent` 629145600 / 734003200 (600-730 MB), 3 events**: the three events land about 2.0 GB in total; the alert text reported 1.3 GB (it counts what it
  considers the upload). It fires reliably. Smaller totals are untested; the Informational "lower than 100 MB" variant exists because the Low alert needs more.
- **`sub_type: ["end"]`**: the log of a finished session carries the byte totals. `start` logs carry zero bytes and would show nothing.
- **`app: ["unknown-tcp"]`, `dest_port: ["8443"]`**: keeps the traffic out of the HTTPS/FTP/SMTP detectors (each has its own). This pairing must stay together.
- **`total_time_elapsed` 2000 / 2600 seconds**: a 35-45 minute transfer, a believable duration for 600 MB.
- **`bytes_received` small**: an upload is lopsided.
- **`sub_type`, `app`, `dest_*` are one-element lists** (or two values that behave the same): draws are independent per event, so a constant needs a single value.
- **`count: 3`, `max_events: 3`**: bounded burst; one tick, then the worker stops. Both bounds, with these snake_case names.

## Step 2: confirm the shape landed (about 60 s after Step 1)

```
config timeframe = 1h | datamodel dataset = panw_ngfw_traffic_raw
| filter xdm.source.host.hostname = "<your host>"
| comp count() as n, sum(xdm.source.sent_bytes) as bytes_out, count_distinct(xdm.target.ipv4) as ndst
```

Pass when `n = 3`, `ndst = 1` and `bytes_out >= 1800000000` (about 2.0 GB lands). If `bytes_out` is empty, `bytes_sent` did not reach the rule.

## Step 3: wait, then check for the alert

**Wait 4 minutes before the first check.** The alert typically arrives 4 to 8 minutes after the burst. Then check every 2 minutes, up to **15 minutes**:

```
dataset = alerts
| filter alert_name = "Large Upload (Generic)"
| fields _time, alert_id, alert_name, host_name, description, alert_arrival_timestamp
| sort desc _time
| limit 5
```

Pass when a new row names your host; the description quotes your traffic back (size, destination, and "on average of 0 bytes a day" in the past 30 days).

If nothing arrives in 15 minutes: re-run Step 2; check dedup (precondition 2) and that the destination was really never used (precondition 3); then retry once with a **new host, a new IP and a new public destination**. Do not change the app, port or field list.

## Report back to the operator

State the worker id, the landed `n`, `bytes_out` and destination, and either the alert id and its arrival time, or that it did not arrive in 15 minutes and what you checked. Say that the host is now deduplicated for 24 hours.
