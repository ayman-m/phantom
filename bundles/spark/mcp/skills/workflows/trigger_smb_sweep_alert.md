---
name: trigger_smb_sweep_alert
displayName: Trigger the Cortex "Abnormal SMB activity to multiple hosts" analytics alert
category: workflows
description: 'Fire Cortex XSIAM''s native "Abnormal SMB activity to multiple hosts" analytics detector (Low, T1021 Remote Services, NDR Lateral Movement) from synthetic Palo Alto NGFW traffic: one established internal host opens SMB connections (port 445, app smb) to 40 internal addresses it has never talked to, in one burst. Use when the operator asks to trigger, demo, prove or reproduce an SMB sweep, SMB discovery across hosts, a lateral-movement SMB alert or "Abnormal SMB activity to multiple hosts". The host must already have a little SMB history.'
icon: lan
source: platform
loadingMode: on-demand
locked: false
---

# Skill: Trigger the "Abnormal SMB activity to multiple hosts" alert

## When this skill applies

The operator wants the **native Cortex Analytics "Abnormal SMB activity to multiple hosts" detector** to fire, for example:
*"trigger an SMB sweep alert"*, *"show a host reaching out over SMB to many machines"*, *"prove T1021 fires from firewall logs"*.

It is not a correlation rule and needs nothing installed on the tenant. It is the *one host, SMB to many new hosts* shape. For one target and many ports use `trigger_port_scan_analytics`; for connections nobody answers use `trigger_failed_connections_alert`. It also fires from a worker shaped for the **Port Sweep** detector: Port Sweep itself stays silent, this one fires.

> **Expected result.** From an established host the alert typically arrives about 4 minutes after the burst, counting the 26 to 28 distinct hosts that landed.

## What the detector looks for (Cortex doc: "Abnormal SMB activity to multiple hosts")

| Property | Value |
|---|---|
| Alert name | `Abnormal SMB activity to multiple hosts` (Low). The doc lists Medium variations and `Highly rare SMB activity to multiple hosts`; only this Low one was seen |
| Source | `XDR_ANALYTICS`, MITRE T1021 Remote Services; alert tags `DT:NDR Lateral Movement Analytics`, `DS:panw/ngfw_traffic` |
| Required data (doc) | the doc page lists only the XDR agent; the alert fires from PAN traffic logs alone, so that is a documentation tag error |
| Activation / training (doc) | 14 days / 30 days. In practice the tenant skips them |
| Test period | 5 hours |
| Deduplication | 1 day per source host |
| What the alert text says | *"The host <host> performed a new unfamiliar SMB traffic to multiple hosts in a short period of time. At this current session, the host initiated SMB traffic to 26 different hosts. This host was seen initiating SMB traffic to 3 different hosts in the past 30 days. This host was rarely seen communicating using SMB with these new hosts in the past 30 days"* |

## Preconditions: check these BEFORE sending

| # | Must be true | How to check |
|---|---|---|
| 1 | You know the operator's syslog **log destination object** (`logdest:<id>`). It typically resolves to the broker's CEF port 5514. Do not send to `udp:<ip>:514` | `log_destinations_list` or the operator |
| 2 | The source is an **ESTABLISHED host**: an IP that has been sending ordinary traffic to the tenant for several days and has used SMB (port 445) to a few hosts before. A host with about 7 days of traffic works, and the alert says it had "initiated SMB traffic to 3 different hosts in the past 30 days". A brand-new IP with no SMB history is **untested** | `config timeframe = 30d \| dataset = panw_ngfw_traffic_raw \| filter source_ip = "<ip>" \| alter d = format_timestamp("%Y-%m-%d", _time) \| comp count() by d` shows several past days; no alert of this name for the host in 24 h (Step 3 query without the time filter) |
| 3 | The 40 destination addresses are `.1` to `.40` of **one internal /24 this host has never contacted** (the alert reasons about "new hosts"). Never reuse a /24 from an earlier run on the same host | `dataset = panw_ngfw_traffic_raw \| filter source_ip = "<ip>" and dest_ip ~= "^10\.20\.<third octet>\." \| comp count()` must be 0 |
| 4 | No other bounded burst is running (xlog allows one at a time) | `phantom_list_workers`: no worker `Running` |

## Expected result

A burst of 40 events to 40 hosts of one unused internal range fires the alert for an established host, typically 4 to 5 minutes after the burst; the alert counts the distinct hosts that landed (26 to 28 of the 40).

Does **not** fire: the same worker's sibling shapes, which are other detectors: a domain-controller SMB source (`Suspicious SMB connection from domain controller`), `bittorrent`, an untrusted FTP server and `ms-drsuapi` traffic.

## Step 1: send the burst (exactly this call)

Call **`phantom_create_data_worker`**. Change only the values marked `<CHANGE>`.

```json
{
  "type": "CEF",
  "vendor": "panw",
  "product": "ngfw_traffic",
  "destination": "<CHANGE: logdest:<id> of the operator's syslog destination>",
  "name": "smbsweep-<CHANGE: short run id>",
  "tags": [
    "detection-validation",
    "T1021"
  ],
  "count": 40,
  "interval": 2,
  "duration_seconds": 110,
  "max_events": 40,
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
      "allow-internal"
    ],
    "from_zone": [
      "trust"
    ],
    "to_zone": [
      "trust"
    ],
    "source_ip": [
      "<CHANGE: established internal IPv4, e.g. 10.20.63.14>"
    ],
    "source_device_host": [
      "<CHANGE: that host's name, e.g. WS-SMB-14>"
    ],
    "source_user": [
      "<CHANGE: a bare user name, no backslash, e.g. f.alqahtani>"
    ],
    "source_port": [
      "51000",
      "52000",
      "53000"
    ],
    "dest_ip": [
      "<CHANGE: 40 strings, the addresses .1 to .40 of one internal /24 this host has never talked to, e.g. \"10.20.30.1\", ... \"10.20.30.40\">"
    ],
    "dest_port": [
      "445"
    ],
    "app": [
      "smb"
    ],
    "bytes_sent": [
      "2400",
      "9600"
    ],
    "bytes_received": [
      "48000",
      "180000"
    ],
    "packets_sent": [
      "30",
      "120"
    ],
    "packets_received": [
      "45",
      "200"
    ],
    "total_time_elapsed": [
      "3",
      "12",
      "45"
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

- **`app: ["smb"]`, `dest_port: ["445"]`**: SMB is what the detector counts; `smb` populates `xdm.network.application_protocol`. Any other pairing is a different detector.
- **40 `dest_ip` values drawn 40 times with replacement**: About 26 to 28 distinct addresses land and the alert counts the same number ("SMB traffic to 26 different hosts"), so every landed address is counted. A shorter list is untested; the doc gives no numeric threshold.
- **`sub_type: ["end"]`, `action: ["allow"]`, `to_zone: ["trust"]`, `rule_matched: ["allow-internal"]`**: completed, allowed internal connections. The failed-connection variant of this shape (`deny`) belongs to `trigger_failed_connections_alert`.
- **Bytes, packets and `total_time_elapsed`**: ordinary small SMB sessions; they are not what the detector keys on, but they keep the log complete (the PAN modeling rule needs them for duration and volume).
- **`count: 40`, `max_events: 40`, `duration_seconds: 110`, `interval: 2`**: one bounded burst of 40 events, then the worker stops itself; keep these snake_case names. 40 events per tick is under xlog's 500 events/s ceiling.
- **Draws are independent**: every event picks one value per field at random, so every field that must be constant is a one-element list.
- **`source_user` without a backslash**: a doubled backslash breaks the shell-quoting of some call paths; a bare name is enough.
- **Burst ceiling**: if the tool answers `burst rejected: 1 burst already running`, wait 60 s and send the same call again.

## Step 2: confirm the shape landed (about 60 s after Step 1)

The filter on the destination /24 keeps the host's own earlier SMB traffic out of the count. Use the same /24 prefix as in Step 1, with the dots escaped:

```
config timeframe = 1h | dataset = panw_ngfw_traffic_raw
| filter source_device_host = "<your host>" and app = "smb" and dest_ip ~= "^<prefix, e.g. 10\.20\.141>\."
| comp count() as n, count_distinct(dest_ip) as ndst
```

Pass when `n = 40` and `ndst >= 20` (26 to 28 land). Then confirm the model took it:

```
config timeframe = 1h | datamodel dataset = panw_ngfw_traffic_raw
| filter xdm.source.host.hostname = "<your host>" and xdm.network.application_protocol = "smb" and xdm.target.ipv4 ~= "^<prefix, e.g. 10\.20\.141>\."
| comp count() as n, count_distinct(xdm.target.ipv4) as ndst
```

Pass when the counts match.

## Step 3: wait, then check for the alert

**Wait 4 minutes before the first check.** The alert typically arrives 4 to 5 minutes after the burst. Then check every 2 minutes, for up to **20 minutes**:

```
dataset = alerts
| filter alert_name = "Abnormal SMB activity to multiple hosts"
| fields _time, alert_id, alert_name, host_name, description, alert_arrival_timestamp
| sort desc _time
| limit 5
```

Pass when a new row names your host. The description quotes your traffic back: *"The host <host> performed a new unfamiliar SMB traffic to multiple hosts ... initiated SMB traffic to N different hosts"*. To list Analytics alerts without naming one, filter on the STORED enum values `alert_source in ("MAGNIFIER","ANALYTICS_BIOC")`: the displayed names `XDR_ANALYTICS` and `XDR_ANALYTICS_BIOC` match nothing.

If nothing arrives within 20 minutes: re-run Step 2 (the traffic must be in `panw_ngfw_traffic_raw` with `app smb`), check preconditions 2 and 3 (an established host and a /24 it has never contacted), then retry once on **another established host and another /24**. Do not change `app` or `dest_port`.

## Report back to the operator

State the host, the source IP, the worker name, the Step 2 result and either the alert id with the arrival time or that nothing arrived and what you checked. Say that the host and the destination /24 should not be reused for 24 hours.
