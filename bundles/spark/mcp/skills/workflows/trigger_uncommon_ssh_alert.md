---
name: trigger_uncommon_ssh_alert
displayName: Trigger the Cortex "Uncommon SSH session was established" analytics alerts
category: workflows
description: 'Fire Cortex XSIAM''s native "Uncommon SSH session was established" analytics BIOC family (T1071) from synthetic Palo Alto NGFW traffic: an internal host that has first been given a few days of back-dated SSH history makes SSH sessions to an external address, on port 22 or on a nonstandard port. Use when the operator asks to trigger, demo, prove or reproduce an uncommon, rare or unusual SSH session, SSH to a rare IP, or SSH on a non-standard port. It needs TWO steps on a fresh host: seed SSH history first, then the trigger burst. Fresh hosts do not fire, seeded or not; an established host (7 days of ordinary traffic) fires the rare-IP variant with no seed at all; the seed-first recipe fires both the port-22 and the nonstandard-port variants on an established host.'
icon: terminal
source: platform
loadingMode: on-demand
locked: false
---

# Skill: Trigger the "Uncommon SSH session was established" alerts

## When this skill applies

The operator wants the **native Cortex Analytics uncommon-SSH detectors** to fire, for example:
*"trigger an uncommon SSH alert"*, *"SSH to a rare IP"*, *"SSH on a non-standard port"*, *"prove T1071 fires from firewall logs"*.

Three variants exist: the port-22 variant, the nonstandard-port variant and the rare-IP variant. None is a correlation rule.

> **Expected result.** From an **established** host (about 7 days of ordinary traffic) the seed-first recipe below fires the port-22 variant and the nonstandard-port variant, each typically 3 to 4 minutes after its burst. With no seed, an established host sending 2 `app=ssh` events to an external address on port 22 fires only the **rare-IP** variant, typically about 4 minutes after the first event. A **fresh** address does not fire, with or without SSH history seeded, even after 80 more ordinary back-dated events over 20 days are added.

## What the detectors look for (Cortex doc: "Uncommon SSH session was established")

| Property | Value |
|---|---|
| Alert names seen | `Uncommon SSH session was established`, `An Uncommon SSH session was established using a nonstandard SSH port`, `An Uncommon SSH session was established to a rare IP address` (all Low, source `XDR Analytics BIOC`, MITRE T1071 Application Layer Protocol) |
| Required data | PAN NGFW traffic logs OR XDR agent OR third-party firewall |
| Test period | single event |
| Deduplication | **1 day** (per host and alert variant) |
| Logic (doc) | An endpoint performed a rare SSH session. The alert text says on how many of the last 30 days the endpoint did the action and, for the rare-IP variant, that the destination is globally rare |

## Why the recipe seeds SSH history (mechanism unproven)

| Host | Earlier SSH sent for it | Trigger | Result |
|---|---|---|---|
| fresh address | none, or seeded | 3 events to an external address on port 22 and on port 2222 | **no alert** |
| established host (7 or more days of traffic) | none | 2 `app=ssh` events to an external address on port 22 | the rare-IP variant fires |
| established host | 20 back-dated SSH events on 2 or 3 past days | the same two shapes | **both alerts fire** |

The recipe below therefore **seeds SSH history first**, for hosts without SSH history. **The mechanism is not proven:** the alert text says "performed the action on 0 days over the past 30 days", so the seeded days are not what Analytics reports, and the destinations used have also been contacted by other hosts. Treat "seed first" as the verified recipe, not as an explanation. The established host is what matters.

## Preconditions: check these BEFORE sending

| # | Must be true | How to check |
|---|---|---|
| 1 | You know the operator's syslog **log destination object** (`logdest:<id>`; typically the broker's CEF port 5514) | `log_destinations_list` or the operator |
| 2 | The source is an **ESTABLISHED host** with no alert of the family in the last 24 h: an IP that has been sending ordinary traffic to the tenant on real calendar days for **at least 7 days**. **Fresh addresses do not fire, even with SSH history seeded** (see Expected result) | `config timeframe = 30d \| dataset = panw_ngfw_traffic_raw \| filter source_ip = "<ip>" \| alter d = format_timestamp("%Y-%m-%d", _time) \| comp count() by d` shows **7 or more distinct past days**; and the Step 4 query without the time filter |
| 3 | The host has the **SSH history from Step 1** on two or three past days, to an ordinary internal server (the verified recipe) | Step 2 |
| 4 | The trigger destinations are **external addresses on ports 22 / 2222**. Do not assume they must be unused: the addresses used in the recipe (3.33.152.147, 34.107.243.93) have already been contacted by other hosts. A destination no one ever used is untested | `dataset = panw_ngfw_traffic_raw \| filter dest_ip = "<ip>" \| comp count()` (informational) |
| 5 | No other bounded burst is running | `phantom_list_workers` shows nothing `Running` |
| 6 | **Back-dating works**: you send CEF `rt` as a 13-digit epoch-millisecond string (an ISO string is ignored). Step 2 proves it | Step 2 |

## Expected result

On an established host, Variant A fires `Uncommon SSH session was established` and Variant B fires `... using a nonstandard SSH port`, each typically 3 to 4 minutes after its burst. With no seed, an established host fires `An Uncommon SSH session was established to a rare IP address` (alert text: "a globally rare external IP", "0 days over the past 30 days"), typically about 4 minutes after the first event.

Does **not** fire: the same trigger shape on fresh hosts. The rare-IP variant is a bonus, not a promise: with the seed-first recipe it does not fire reliably. A fourth alert, the meta-detector `Abnormal increase in network-related alerts on the same host`, can appear once a host has three alerts; it is not reproducible on demand.

## Step 1: seed the host's SSH history (back-dated)

Call **`phantom_create_data_worker`** once. Compute `rt` yourself: 20 epoch-millisecond values (13-digit strings) spread between **1 and 3.5 days ago** (so
they fall on at least two calendar days). Change the values marked `<CHANGE>`.

```json
{
  "type": "CEF",
  "vendor": "panw",
  "product": "ngfw_traffic",
  "destination": "<CHANGE: logdest:<id>>",
  "name": "sshhist-<CHANGE: run id>",
  "tags": ["detection-validation", "history"],
  "count": 20,
  "interval": 1,
  "duration_seconds": 60,
  "max_events": 20,
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
    {"name": "log_source", "type": "string"}, {"name": "rt", "type": "string"}
  ],
  "observables_dict": {
    "log_type": ["TRAFFIC"], "sub_type": ["end"], "action": ["allow"], "app": ["ssh"], "protocol": ["tcp"],
    "rule_matched": ["allow-internal"], "from_zone": ["trust"], "to_zone": ["trust"],
    "source_ip": ["<CHANGE: fresh internal IPv4, e.g. 10.20.14.16>"],
    "source_device_host": ["<CHANGE: fresh host name, e.g. WS-SSH-04>"],
    "source_user": ["<CHANGE: bare user name, e.g. turki.alharbi>"],
    "source_port": ["53001", "53002"],
    "dest_ip": ["<CHANGE: an ordinary internal server, e.g. 10.20.86.31>"], "dest_port": ["22"],
    "bytes_sent": ["4200", "9100"], "bytes_received": ["6100", "15000"], "packets_sent": ["38"], "packets_received": ["44"],
    "total_time_elapsed": ["60", "210"], "log_source": ["PA-3220-Acme"],
    "rt": ["<CHANGE: 20 values like \"1790776746573\", each between now-3.5d and now-1d, as 13-digit epoch-ms strings>"]
  }
}
```

Why: ordinary, internal, short SSH sessions (4-15 KB, 1-4 minutes) to one internal server are the history the recipe seeds (the reason it helps is unproven, see above). `rt` is the only lever that places events in the past; the broker uses it as `_time`.

## Step 2: confirm the history landed on the right days (about 2 minutes after Step 1)

```
config timeframe = 7d | dataset = panw_ngfw_traffic_raw
| filter source_device_host = "<your host>"
| alter d = format_timestamp("%Y-%m-%d", _time)
| comp count() as n by d, sub_type
```

Pass when the 20 events appear on **two or three past dates** (not today). If everything is dated today, `rt` was ignored: send it as 13-digit epoch-ms strings and re-send. **Wait 2-3 minutes** after this passes; the alerts typically fire about 3 minutes after history lands.

## Step 3: send the trigger (one burst per variant)

Same call shape; send **one burst, wait about 75 s, then the next**. Use the **same host, IP and user** as Step 1, and **no `rt`** (live events).

Variant A, port 22 to a rare external address (fires `Uncommon SSH session was established`):

```json
{
  "type": "CEF",
  "vendor": "panw",
  "product": "ngfw_traffic",
  "destination": "<CHANGE: logdest:<id>>",
  "name": "sshtrig-a-<CHANGE: run id>",
  "tags": ["detection-validation", "T1071"],
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
    "log_type": ["TRAFFIC"], "sub_type": ["end"], "action": ["allow"], "app": ["ssh"], "protocol": ["tcp"],
    "rule_matched": ["allow-outbound"], "from_zone": ["trust"], "to_zone": ["untrust"],
    "source_ip": ["<CHANGE: the SAME IP as Step 1>"],
    "source_device_host": ["<CHANGE: the SAME host as Step 1>"],
    "source_user": ["<CHANGE: the SAME user as Step 1>"],
    "source_port": ["54001", "54002", "54003"],
    "dest_ip": ["<CHANGE: an external address, e.g. 3.33.152.147>"], "dest_port": ["22"],
    "bytes_sent": ["5200", "8800"], "bytes_received": ["7400", "12000"],
    "packets_sent": ["40"], "packets_received": ["48"],
    "total_time_elapsed": ["95", "140"], "log_source": ["PA-3220-Acme"]
  }
}
```

Variant B, nonstandard port (fires `An Uncommon SSH session was established using a nonstandard SSH port`): send the **same call** with exactly three
changes: `"name": "sshtrig-b-<run id>"`, `"dest_ip": ["<another external address, e.g. 34.107.243.93>"]` and **`"dest_port": ["2222"]`**.

Why: `app: ["ssh"]` is the App-ID; the destinations are external addresses; the port is what makes B different from A; `to_zone: untrust` and `rule_matched: allow-outbound` differ from the history's `trust`/`allow-internal` because the session leaves the network.

## Step 4: wait, then check for the alerts

**Wait 4 minutes before the first check** (the alert typically arrives 3 to 4 minutes after the burst). Then every 2 minutes, up to **15 minutes**:

```
dataset = alerts
| filter alert_name ~= "Uncommon SSH"
| fields _time, alert_id, alert_name, host_name, description, alert_arrival_timestamp
| sort desc _time
| limit 10
```

Pass when new rows name your host; the text reads like *"An endpoint performed a rare SSH session. Destination address and port of this session: 3.33.152.147:22. The endpoint performed the action on 0 days over the past 30 days."*

If nothing arrives in 15 minutes: re-run Step 2 (history on past days?), check precondition 2, and retry once on **another established host**. Do not skip the history, and do not change `app`.

## Report back to the operator

State the worker ids, the Step 2 date table, each trigger's landed events, and the alert ids with arrival times (or what you checked if none arrived). Say that the host is deduplicated for 24 hours.
