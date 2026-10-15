---
name: trigger_failed_connections_alert
displayName: Trigger the Cortex "Failed Connections" analytics alert
category: workflows
description: 'Fire Cortex XSIAM''s native "Failed Connections" analytics detector (T1018, Remote System Discovery) from synthetic Palo Alto NGFW traffic: one internal host whose denied connections reach 40 internal addresses nobody has talked to before. Use when the operator asks to trigger, demo, prove or reproduce "Failed Connections", "failed connection spike", "connections to inactive hosts" or a network-discovery alert that is not a port scan. The call is exact; the log must carry sub_type deny and zero bytes or the detector sees nothing.'
icon: link_off
source: platform
loadingMode: on-demand
locked: false
---

# Skill: Trigger the "Failed Connections" analytics alert

## When this skill applies

The operator wants the **native Cortex Analytics "Failed Connections" detector** to fire, for example:
*"trigger failed connections"*, *"show a host probing machines that are not there"*, *"prove T1018
fires from firewall logs"*.

This is not a correlation rule and needs nothing installed on the tenant. It is the *many hosts, none
answer* shape. For the *one target, many ports* shape use `trigger_port_scan_analytics`.

> **Expected result.** From an **established** source host the alert typically arrives 3 to 5 minutes after the burst. A fresh source IP does not fire: the burst lands and models as the skill says (120 events, about 39 distinct targets, all `FAILED`) but no alert follows, even after back-dated ordinary events spread over 20 days are added and the burst is re-fired. The likely missing ingredient is real calendar history for the host (back-dated `rt` events do not substitute for it), which is why precondition 2 demands an established host. Replay-verify against the organization hosts before relying on this skill.

## What the detector looks for (Cortex doc: "Failed Connections")

| Property | Value |
|---|---|
| Alert name | `Failed Connections` (Low). Two Informational variants exist and are invisible in the Issues view |
| Source | `XDR_ANALYTICS` |
| MITRE | T1018 Remote System Discovery |
| Required data | PAN NGFW traffic logs OR XDR agent OR third-party firewall |
| Test period | 1 day (the alert text counts the last 24 hours) |
| Deduplication | **1 day per source host** |
| Logic (doc) | An endpoint has failed connections to endpoints that were inactive for more than 24 hours, or that Analytics has never seen on the network, in an abnormally large number or mixture |

## Why the schema carries `sub_type` (read this, it is most likely the whole trick)

The PANW modeling rule sets `xdm.event.outcome` to FAILED **only** when the CEF key `sub_type` is `deny` or
`drop`. The 9-field schema from the port-scan skill (`action`, `app`, `dest_ip`,
`dest_port`, `protocol`, `source_*`) carries no `sub_type`, no `log_type`, no bytes and no duration:
the connections land and model, but nothing marks them as failed. With the keys below the burst goes
straight to an alert, and the identical call fires again on another host. The rule line is certain; that the missing keys are the only reason the 9-field bursts stay silent is the most likely explanation, not an isolated test (the 9-field schema also lacks `log_type`, bytes and duration).

## Preconditions: check these BEFORE sending

| # | Must be true | How to check |
|---|---|---|
| 1 | You know the operator's syslog **log destination object** (`logdest:<id>`). It typically resolves to the broker's CEF port 5514. Do not send to `udp:<ip>:514` | `log_destinations_list` or the operator |
| 2 | The source is an **ESTABLISHED host** that has no `Failed Connections` alert in the last 24 h: an IP that has been sending ordinary traffic to the tenant, on real calendar days, for **at least 14 days**. **A fresh IP does not fire, even with 20 days of back-dated traffic added** (see Expected result). The source must be an organization host that the baseline job covers (default: the outlier's workstation, PHWS-036 at `10.20.16.55` on Phantom Lab; `baseline_normal_activity` gives it ordinary traffic). The 14 days are a property of that host's traffic on the tenant, not of this skill, so check them with the query. Do not pick a host the baseline job does not cover | `config timeframe = 30d \| dataset = panw_ngfw_traffic_raw \| filter source_ip = "<ip>" \| alter d = format_timestamp("%Y-%m-%d", _time) \| comp count() by d` must show **14 or more distinct past days**; and the Step 3 query without the time filter shows no alert for the host in 24 h |
| 3 | The 40 destination addresses are **consecutive addresses `.10` to `.49` of ONE internal /24 that has never appeared** as a source or destination in `panw_ngfw_traffic_raw` in 30 days. **Never reuse a /24 from an earlier burst**: its addresses are no longer "never seen" | `dataset = panw_ngfw_traffic_raw \| filter dest_ip ~= "^10\.20\.<third octet>\." or source_ip ~= "^10\.20\.<third octet>\." \| comp count()` must be 0 |
| 4 | No other bounded burst is running (xlog allows one at a time) | `phantom_list_workers`: no worker `Running` |
| 5 | The log carries the keys in Step 1 exactly. No user object and no seeding step is needed beyond precondition 2 | Step 2 |

## Expected result

A burst of 120 events to 40 hosts `.10`-`.49` of one unused internal /24 fires `Failed Connections` for an established source host, typically 3 to 5 minutes after the burst. The alert counts the destination addresses that landed (for example "tried to connect to 37 hosts in the last 24 hours").

Does **not** fire (so do not "simplify" toward these):

- The same shape with the 9-field schema and `action=deny` only (FortiGate-style and PAN): no alert in 1 day. The cause is the missing `sub_type`.
- A fresh source IP (see precondition 2).
- Destinations spread over fewer than about 30 distinct addresses are untested; 37-40 is the verified
  value. The doc gives no numeric threshold.

## Step 1: send the burst (exactly this call)

Call **`phantom_create_data_worker`**. Change only the values marked `<CHANGE>`.

```json
{
  "type": "CEF",
  "vendor": "panw",
  "product": "ngfw_traffic",
  "destination": "<CHANGE: logdest:<id> of the operator's syslog destination>",
  "name": "failedconn-<CHANGE: short run id>",
  "tags": ["detection-validation", "T1018"],
  "count": 120,
  "interval": 1,
  "duration_seconds": 60,
  "max_events": 120,
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
    "sub_type": ["deny"],
    "action": ["deny"],
    "app": ["incomplete"],
    "protocol": ["tcp"],
    "rule_matched": ["deny-internal"],
    "from_zone": ["trust"],
    "to_zone": ["trust"],
    "source_ip": ["<CHANGE: the address of an established organization host the baseline job covers, default 10.20.16.55>"],
    "source_device_host": ["<CHANGE: that host's name, default PHWS-036>"],
    "source_user": ["<CHANGE: that host's user as a bare name, no backslash, default aalzamil>"],
    "source_port": ["49152", "49153", "49154", "49155"],
    "dest_ip": ["<CHANGE: 40 strings, the addresses .10 to .49 of one unused internal /24 from precondition 3, e.g. \"10.20.<unused>.10\", \"10.20.<unused>.11\", ... \"10.20.<unused>.49\">"],
    "dest_port": ["445", "3389", "135", "5985", "22"],
    "bytes_sent": ["0"],
    "bytes_received": ["0"],
    "packets_sent": ["1"],
    "packets_received": ["0"],
    "total_time_elapsed": ["0"],
    "log_source": ["PA-3220-Acme"]
  }
}
```

Why each value is what it is:

- **`vendor: "panw"`, `product: "ngfw_traffic"`**: the wire literal that lands in `panw_ngfw_traffic_raw`. Never the display names.
- **`sub_type: ["deny"]` (single value)**: this is what makes `xdm.event.outcome` FAILED. `drop` works the same. A list that mixes `end`
  and `deny` dilutes it; keep the single value.
- **`action: ["deny"]`, `bytes_* : ["0"]`, `total_time_elapsed: ["0"]`, `packets_sent: ["1"]`, `packets_received: ["0"]`**: what a refused
  connection looks like on a firewall: one packet out, nothing back, no session time. They are not what the detector keys on, but they keep the log truthful.
- **`app: ["incomplete"]`**: PAN's App-ID for a handshake that never completed.
- **40 `dest_ip` values drawn 120 times with replacement**: About 37 distinct addresses land from 120 draws and the alert counts 37, so every landed address is counted. A shorter list is untested. They must all be
  internal-range addresses nobody has used (precondition 3), because "inactive for more than 24 hours or never seen" is the condition.
- **`count: 120`, `max_events: 120`, `duration_seconds: 60`, `interval: 1`**: one bounded burst: 120 events in one tick, then the worker stops itself.
  Both bounds must be set with these snake_case names. 120 events per second is under xlog's 500 events/s ceiling; do not raise `count` without
  raising `interval` to `ceil(count / 400)`.
- **Draws are independent**: every event picks one value per field at random. That is why every field that must be constant is a one-element list.
- **`source_user` without a backslash**: a doubled backslash breaks the shell-quoting of some call paths. A bare name is enough for this detector.
- **Burst ceiling**: if the tool answers `burst rejected: 1 burst already running`, wait 60 s and send the same call again. Never send two bursts together.

## Step 2: confirm the shape landed (about 60 s after Step 1)

```
dataset = panw_ngfw_traffic_raw
| filter source_device_host = "<your host>" and log_type = "TRAFFIC"
| comp count() as n, count_distinct(dest_ip) as ndst by sub_type
```

Pass when one row shows `sub_type = deny`, `n = 120` and `ndst >= 35` (about 37 land). Then confirm the model took it:

```
config timeframe = 1h | datamodel dataset = panw_ngfw_traffic_raw
| filter xdm.source.host.hostname = "<your host>"
| comp count() as n, count_distinct(xdm.target.ipv4) as ndst by xdm.event.outcome
```

Pass when `xdm.event.outcome = FAILED` for all 120. If outcome is empty, `sub_type` did not reach the rule: re-check the schema_override.

## Step 3: wait, then check for the alert

**Wait 4 minutes before the first check.** The alert typically arrives 3 to 5 minutes after the burst. Then check every 2 minutes, for up to **15 minutes**:

```
dataset = alerts
| filter alert_name = "Failed Connections"
| fields _time, alert_id, alert_name, host_name, description, alert_arrival_timestamp
| sort desc _time
| limit 5
```

Pass when a new row names your host. The description quotes your traffic back: *"<host> tried to connect to 37 hosts in the last 24 hours"*.

If nothing arrives within 15 minutes:

1. Re-run Step 2. `xdm.event.outcome` must be FAILED and `ndst` at least 35.
2. Check precondition 2 (dedup) and precondition 3 (were the targets really never seen?).
3. Only then try once more with a new host name, a new source IP **and a new destination /24**. Do not change vendor, product, field list or the single-value lists. Those are what make it fire.

## Report back to the operator

State the worker id, the landed `n`/`ndst` and the FAILED count, and either the alert id with the minutes it took, or that it did not arrive in
15 minutes and which of the three checks you ran. Say that the host is now deduplicated for 24 hours.
