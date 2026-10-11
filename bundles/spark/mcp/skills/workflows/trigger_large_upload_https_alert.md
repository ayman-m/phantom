---
name: trigger_large_upload_https_alert
displayName: Trigger the Cortex "Large Upload (HTTPS)" analytics alert
category: workflows
description: 'Fire Cortex XSIAM''s native "Large Upload (HTTPS)" analytics detector (Low, T1048 Exfiltration Over Alternative Protocol) from synthetic Palo Alto NGFW traffic: one internal host sends about 4 GB in total over 8 completed HTTPS sessions (app ssl, port 443, 500 to 570 MB each) to one external address. Use when the operator asks to trigger, demo, prove or reproduce a large HTTPS upload, data exfiltration over HTTPS or "Large Upload (HTTPS)". The log must carry bytes_sent and sub_type end. For uploads over a non-web port use trigger_large_upload_alert.'
icon: cloud_upload
source: platform
loadingMode: on-demand
locked: false
---

# Skill: Trigger the "Large Upload (HTTPS)" alert

## When this skill applies

The operator wants the **native Cortex Analytics "Large Upload (HTTPS)" detector** to fire, for example:
*"trigger a large HTTPS upload alert"*, *"show data leaving over HTTPS"*, *"prove T1048 fires from firewall logs"*.

It is not a correlation rule and needs nothing installed on the tenant. The same family's **Generic** member (a non-web port) is `trigger_large_upload_alert`; FTP and SMTP members do not fire. HTTPS fires both on an established host and on a host with **no earlier traffic** to the destination (a 30-day average of 0 bytes).

> **Expected result.** The alert ("uploaded 1.5GB ... over 3 sessions") typically arrives within 6 to 13 minutes of the first event. Allow 25 minutes.

## What the detector looks for (Cortex doc: "Large Upload (HTTPS)")

| Property | Value |
|---|---|
| Alert name | `Large Upload (HTTPS)` (Low). The catalog lists the base alert as Informational and `... to non-standard port` as Low; the Low base name is what fires |
| Source | `XDR_ANALYTICS`, MITRE T1048 Exfiltration Over Alternative Protocol |
| Required data (doc) | PAN firewall traffic logs OR XDR agent OR third-party firewalls |
| Activation / training (doc) | 14 days / 30 days. In practice the tenant skips them |
| Test period | 1 day (the alert text counts the last 24 hours) |
| Deduplication | 1 day per source host |
| What the alert text says | *"<host> uploaded 1.6GB to the external host <destination> over 3 sessions in the last 24 hours. During that time, <host> downloaded 35.2KB from the same external host. In the past 30 days, the host uploaded data via HTTPS protocol to this external host an average of 58.4KB a day ..."* |

## Preconditions: check these BEFORE sending

| # | Must be true | How to check |
|---|---|---|
| 1 | You know the operator's syslog **log destination object** (`logdest:<id>`). It typically resolves to the broker's CEF port 5514. Do not send to `udp:<ip>:514` | `log_destinations_list` or the operator |
| 2 | The source host has **no `Large Upload (HTTPS)` alert in the last 24 h** (deduplication per host). Both an established host (about 7 days of traffic) and a new one (a 30-day average of 0 bytes to the destination) fire | Step 3 query without the time filter shows no alert for the host in 24 h |
| 3 | The destination is an **ordinary public address**. The recipe below uses `104.18.32.7`. Do not use a documentation range (RFC 5737): it is the likely reason the FTP and SMTP variants stay silent | none |
| 4 | No other bounded burst is running (xlog allows one at a time) | `phantom_list_workers`: no worker `Running` |

## Expected result

The call below fires `Large Upload (HTTPS)` for a fresh host, typically 6 to 13 minutes after the first event. The alert counts only part of the burst (for example "uploaded 1.5GB ... over 3 sessions"), because it fires before all eight sessions have landed. A burst of 24 sessions of about 100 MB every 150 s to the same address also fires (402.5 MB over 3 sessions, a 30-day average of 0 bytes), typically within about 8 minutes.

## Step 1: send the burst (exactly this call)

Call **`phantom_create_data_worker`**. Change only the values marked `<CHANGE>`.

```json
{
  "type": "CEF",
  "vendor": "panw",
  "product": "ngfw_traffic",
  "destination": "<CHANGE: logdest:<id> of the operator's syslog destination>",
  "name": "bigup-https-<CHANGE: short run id>",
  "tags": [
    "detection-validation",
    "T1048"
  ],
  "count": 8,
  "interval": 10,
  "duration_seconds": 110,
  "max_events": 8,
  "schema_override": [
    {
      "name": "action",
      "type": "string"
    },
    {
      "name": "app",
      "type": "string"
    },
    {
      "name": "dest_ip",
      "type": "ipv4"
    },
    {
      "name": "dest_port",
      "type": "integer"
    },
    {
      "name": "protocol",
      "type": "string"
    },
    {
      "name": "source_device_host",
      "type": "string"
    },
    {
      "name": "source_ip",
      "type": "ipv4"
    },
    {
      "name": "source_port",
      "type": "integer"
    },
    {
      "name": "source_user",
      "type": "string"
    },
    {
      "name": "bytes_sent",
      "type": "integer"
    },
    {
      "name": "bytes_received",
      "type": "integer"
    },
    {
      "name": "log_type",
      "type": "string"
    },
    {
      "name": "sub_type",
      "type": "string"
    },
    {
      "name": "rule_matched",
      "type": "string"
    },
    {
      "name": "from_zone",
      "type": "string"
    },
    {
      "name": "to_zone",
      "type": "string"
    },
    {
      "name": "packets_sent",
      "type": "integer"
    },
    {
      "name": "packets_received",
      "type": "integer"
    },
    {
      "name": "total_time_elapsed",
      "type": "integer"
    },
    {
      "name": "session_id",
      "type": "integer"
    }
  ],
  "observables_dict": {
    "log_type": [
      "TRAFFIC"
    ],
    "sub_type": [
      "end"
    ],
    "protocol": [
      "tcp"
    ],
    "action": [
      "allow"
    ],
    "rule_matched": [
      "allow-outbound"
    ],
    "from_zone": [
      "trust"
    ],
    "to_zone": [
      "untrust"
    ],
    "source_port": [
      "51000",
      "52000",
      "53000"
    ],
    "source_ip": [
      "<CHANGE: established internal IPv4, e.g. 10.20.63.16>"
    ],
    "source_device_host": [
      "<CHANGE: that host's name, e.g. WS-LU-16>"
    ],
    "source_user": [
      "<CHANGE: a bare user name, no backslash, e.g. n.almutairi>"
    ],
    "dest_ip": [
      "104.18.32.7"
    ],
    "dest_port": [
      "443"
    ],
    "app": [
      "ssl",
      "web-browsing"
    ],
    "bytes_sent": [
      "500000000",
      "510000000",
      "520000000",
      "530000000",
      "540000000",
      "550000000",
      "560000000",
      "570000000"
    ],
    "bytes_received": [
      "12000"
    ],
    "packets_sent": [
      "400000"
    ],
    "packets_received": [
      "8000"
    ],
    "total_time_elapsed": [
      "1800"
    ],
    "session_id": [
      "700000",
      "700001",
      "700002",
      "700003",
      "700004",
      "700005",
      "700006",
      "700007"
    ]
  }
}
```

Why each value is what it is:

- **`app: ["ssl", "web-browsing"]`, `dest_port: ["443"]`**: classifies the sessions as HTTPS. Another app or port selects a different member of the family (Generic needs `unknown-tcp` on a non-web port).
- **`bytes_sent`: eight values from 500,000,000 to 570,000,000 (one per session)**: each session about 500 MB; the total is about 4 GB. The alert counts **3 sessions and about 1.6 GB** (it fires before all eight have landed), and a 24-event run of about 100 MB per session also fires, counting **3 sessions and 402.5 MB**, so the lever is volume to one destination well above the host's own history, not the session count.
- **`bytes_received: ["12000"]`**: almost nothing comes back. The alert text reports "downloaded 35.2KB from the same external host"; the doc says the detector looks for hosts that have not downloaded a lot from the site.
- **`sub_type: ["end"]`, `action: ["allow"]`, `total_time_elapsed: ["1800"]`, `packets_sent: ["400000"]`**: completed sessions of 30 minutes. `sub_type end` is what carries the byte counts into the model.
- **One destination (`dest_ip: ["104.18.32.7"]`)**: the detector sums uploads **to one external host**.
- **`count: 8`, `max_events: 8`, `duration_seconds: 110`, `interval: 10`**: one bounded burst of 8 events, then the worker stops itself; keep these snake_case names.
- **Draws are independent**: every event picks one value per field at random, so every field that must be constant is a one-element list.
- **Burst ceiling**: if the tool answers `burst rejected: 1 burst already running`, wait 60 s and send the same call again.

## Step 2: confirm the shape landed (about 60 s after Step 1)

`bytes_sent` is a string in the raw dataset, so convert it; the size filter keeps the host's own small baseline uploads to the same address out of the count:

```
config timeframe = 1h | dataset = panw_ngfw_traffic_raw
| filter source_device_host = "<your host>" and dest_ip = "104.18.32.7" and log_type = "TRAFFIC"
| alter up = to_integer(bytes_sent) | filter up > 100000000
| comp count() as n, sum(up) as up_total
```

Pass when `n = 8` and `up_total` is between 4.0 and 4.6 billion (eight draws from the 500-570 MB values). Then confirm the model took it:

```
config timeframe = 1h | datamodel dataset = panw_ngfw_traffic_raw
| filter xdm.source.host.hostname = "<your host>" and xdm.target.ipv4 = "104.18.32.7" and xdm.source.sent_bytes > 100000000
| comp count() as n, sum(xdm.source.sent_bytes) as up
```

Pass when the counts match and `xdm.source.sent_bytes` is populated. If it is empty, `sub_type end` did not reach the rule: re-check `schema_override`.

## Step 3: wait, then check for the alert

**Wait 6 minutes before the first check.** The alert typically arrives 6 to 13 minutes after the first event. Then check every 2 minutes, for up to **25 minutes**:

```
dataset = alerts
| filter alert_name = "Large Upload (HTTPS)"
| fields _time, alert_id, alert_name, host_name, description, alert_arrival_timestamp
| sort desc _time
| limit 5
```

Pass when a new row names your host. The description quotes your traffic back: *"<host> uploaded <size> to the external host 104.18.32.7 over N sessions in the last 24 hours"*. To list Analytics alerts without naming one, filter on the STORED enum values `alert_source in ("MAGNIFIER","ANALYTICS_BIOC")`: the displayed names `XDR_ANALYTICS` and `XDR_ANALYTICS_BIOC` match nothing.

If nothing arrives within 25 minutes: re-run Step 2 (the bytes must be in `xdm.source.sent_bytes`), confirm the host has no alert of this name in the last 24 hours, then retry once on **another host**. Do not change `app`, `dest_port` or `sub_type`.

## Report back to the operator

State the host, the source IP, the worker name, the Step 2 result and either the alert id with the arrival time or that nothing arrived and what you checked. Say that the host should not be reused for 24 hours.
