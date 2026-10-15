---
name: trigger_port_scan_analytics
displayName: Trigger the Cortex "Suspicious port scan" analytics alert
category: workflows
description: 'Fire Cortex XSIAM''s native "Suspicious port scan" analytics detector (T1046) from synthetic PAN NGFW traffic, using ONE exact phantom_create_data_worker call — no free-form choices. Use when the operator asks to trigger, demo, prove or reproduce a port scan / network service discovery alert. Gives the verbatim tool arguments, the landing check, the alert check, how long to wait (alerts arrive 4-12 minutes after the burst), the per-host deduplication rule, and the expected result.'
icon: radar
source: platform
loadingMode: on-demand
locked: false
---

# Skill: Trigger the "Suspicious port scan" analytics alert

## When this skill applies

The operator wants the **native Cortex Analytics port-scan detector to fire**, for example:
*"trigger a port scan alert"*, *"demo network discovery detection"*, *"prove T1046 fires"*.

This is not a correlation rule and needs no content on the tenant. Cortex's own Analytics engine
raises it from firewall traffic. Follow the steps below **exactly**. Do not substitute a different
tool, vendor, product, field list or port list: each value here is one known to
fire, and changing it re-opens questions this skill already settles.

> **Caution.** If a run stays silent past the usual 3.5-12 min window, the engine's baseline
> maturity may have raised the bar: retry on a host with ordinary baseline traffic and allow up to
> an hour before calling it a miss.

## What the detector looks for (Cortex doc: "Port Scan")

| Property | Value |
|---|---|
| Alert names | `Suspicious port scan` (Low); variations `Highly suspicious port scan` (Medium), `Port scan by suspicious process` (Low) |
| Source | `XDR_ANALYTICS` |
| Required data | PAN NGFW traffic logs OR third-party firewall traffic |
| Test period | 1 hour: the shape must occur inside one hour |
| Deduplication | **1 day per source host**. The same host does not alert again for 24 h |
| Logic | One endpoint connects, or tries to connect, to **many privileged ports on one target** that other endpoints rarely use. Ports most endpoints use (for example 80 and 443) do not count |

## Expected result

The recipe fires from a new source host connecting to **many distinct privileged ports on one target**, from both PAN NGFW and FortiGate traffic. The alert typically arrives 4-12 minutes after the burst (as early as about 3.5 minutes). This recipe lands about 28 distinct ports to one target from a one-second burst; longer bursts fire too.

These shapes do **not** fire:

- 13 ports spread across 20 targets.
- 24 ports spread across 37 targets (a sweep, a different shape).

The count that matters is **distinct ports to a single target**. The lowest count known to fire is
18; the exact threshold is not published. This recipe lands about 28.

These facts **do not** matter:

- `action`: random junk in the action field still fires.
- `app` labels.
- Whether the source host has history: a brand-new host fires too.

## Step 1: send the burst (exactly this call)

Call the MCP tool **`phantom_create_data_worker`** with these arguments. Change only the
three values marked `<CHANGE>`.

```json
{
  "type": "CEF",
  "vendor": "panw",
  "product": "ngfw_traffic",
  "destination": "<the operator's syslog log destination, e.g. logdest:<id> or udp:<broker-ip>:<port>>",
  "name": "portscan-<CHANGE: short run id>",
  "tags": ["detection-validation", "T1046"],
  "count": 90,
  "interval": 1,
  "duration_seconds": 60,
  "max_events": 90,
  "schema_override": [
    {"name": "action", "type": "string"},
    {"name": "app", "type": "string"},
    {"name": "dest_ip", "type": "ipv4"},
    {"name": "dest_port", "type": "integer"},
    {"name": "protocol", "type": "string"},
    {"name": "source_device_host", "type": "string"},
    {"name": "source_ip", "type": "ipv4"},
    {"name": "source_port", "type": "integer"},
    {"name": "source_user", "type": "string"}
  ],
  "observables_dict": {
    "source_device_host": ["<CHANGE: a host name that has NOT raised a port-scan alert in the last 24 h, e.g. PHWS-036, the outlier's workstation>"],
    "source_ip": ["<CHANGE: that host's internal IPv4, e.g. 10.20.16.55>"],
    "source_user": ["PHANTOM\\\\<CHANGE: that host's user, e.g. aalzamil>"],
    "dest_ip": ["10.20.1.21"],
    "dest_port": ["21","22","23","25","69","110","111","135","139","143","161","389","445","465","514",
                  "636","873","993","995","1025","1433","1521","2049","3306","3389","5432","5900","5985",
                  "6379","11211"],
    "app": ["incomplete"],
    "protocol": ["tcp"],
    "action": ["deny"]
  }
}
```

Why each value is what it is:

- **`vendor: "panw"`, `product: "ngfw_traffic"`**: the wire literal that lands in
  `panw_ngfw_traffic_raw`, which the PANW modeling rule maps. Do not use the display names
  `Palo Alto Networks`/`NGFW Traffic`.
- **`schema_override` with only these 9 fields**: a narrow schema keeps the event under the ~4 KB
  syslog limit, and nothing is left to be filled with random values. The modeling rule derives the
  rest.
- **`count: 90`, `max_events: 90`, `duration_seconds: 60`**: this is a bounded burst. One tick sends 90
  events and the worker stops itself. Both bounds must be set, and they must use exactly these
  snake_case names. `durationSeconds`/`maxEvents` are **not** this tool's arguments. Without a bound the
  worker would send 90 events every second until it is killed.
- **The port list has 30 values.** Each event draws one port at random, with replacement. Ninety draws
  from 30 values land about 28 distinct ports, well above the 18 known to fire. The pool contains
  privileged and uncommon service ports only, not 80 or 443, because the detector ignores ports that
  many endpoints use.
- **One `dest_ip`**: the detector counts ports per target. Never give a list of targets. That turns
  the traffic into a sweep, which is a different detector.
- **A fresh `source_device_host`**: port scan deduplicates per host for 1 day. Before choosing a
  name, run the alert check in Step 3 without the time filter to see which hosts have already fired.
- **Burst ceiling**: xlog runs one bounded burst at a time. If the tool answers
  `burst rejected: 1 burst already running`, wait 60 s and send the same call again. Do not send
  two bursts together.

The call returns the worker id, e.g. `[{"worker": "worker_<timestamp>", "status": "Running", ...}]`.

## Step 2: confirm the shape landed (about 30-60 s after Step 1)

Run this XQL through the XSIAM connector's `run_xql_query` over the last 1 hour:

```
dataset = panw_ngfw_traffic_raw
| filter source_device_host = "<your host>"
| comp count() as n, count_distinct(dest_port) as nports, count_distinct(dest_ip) as ndst by source_ip
```

Pass when `n = 90`, `nports >= 20` and `ndst = 1`. If `nports` is below 20, send Step 1 once
more **from a different host name**. If `n = 0`, the destination or the routing literal is wrong:
check the `destination` value before anything else.

## Step 3: wait, then check for the alert

**Wait 5 minutes before the first check.** Alerts typically arrive 3.5-12 minutes after the burst. Then
check every 2-3 minutes, for up to **15 minutes** after the burst:

```
dataset = alerts
| filter alert_name in ("Suspicious port scan", "Highly suspicious port scan", "Port scan by suspicious process")
| fields _time, alert_id, alert_name, host_name, description, alert_arrival_timestamp
| sort desc _time
| limit 5
```

Pass when a new row names your host. The description quotes your traffic back, for example
*"PHWS-036 connected or attempted to connect to 10.20.1.21 119 times over 36 or more unique ports"* (the target is PHSRV-APP01, an organization server; the recipe was verified earlier with a different internal target address). Replay-verify against the organization hosts before relying on this skill.

If nothing arrives within 15 minutes:

1. Re-run Step 2. The shape must have `nports >= 20` to one target.
2. Check that the host has not alerted in the last 24 h (dedup).
3. Only then try once more with a new host name. Do not change the vendor, fields or port pool.
   Those are what fires.

## Report back to the operator

State the worker id, the landed `n`/`nports`/`ndst`, and either the alert id and how many minutes it
took to arrive, or that it did not arrive within 15 minutes and which of the three checks above you
ran.
