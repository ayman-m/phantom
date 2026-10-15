---
name: trigger_spam_bot_alert
displayName: Trigger the Cortex "Spam Bot Traffic" analytics alert
category: workflows
description: 'Fire Cortex XSIAM''s native "Spam Bot Traffic" analytics detector (Low, T1496 Resource Hijacking) from synthetic Palo Alto NGFW traffic: one internal host opens SMTP connections (port 25, app smtp) to 24 external mail-server addresses in one burst, 14 to 19 of them distinct. Use when the operator asks to trigger, demo, prove or reproduce a spam bot, a host connecting to many SMTP servers, or a "Spam Bot Traffic" alert. The detector counts distinct SMTP servers; volume does not matter.'
icon: mail
source: platform
loadingMode: on-demand
locked: false
---

# Skill: Trigger the "Spam Bot Traffic" alert

## When this skill applies

The operator wants the **native Cortex Analytics "Spam Bot Traffic" detector** to fire, for example:
*"trigger a spam bot alert"*, *"show a host connecting to many mail servers"*, *"prove T1496 fires from firewall logs"*.

It is not a correlation rule and needs nothing installed on the tenant. It is a repeatable network detector: it fires on different hosts, including a host that has **no earlier traffic at all** (the burst is its first event).

The traffic is synthetic firewall log records of one host connecting to many external mail-server addresses. It is sent only to the operator's own tenant; nothing is delivered to any mail server and no email is sent.

## What the detector looks for (Cortex doc: "Spam Bot Traffic")

| Property | Value |
|---|---|
| Alert name | `Spam Bot Traffic` (Low). An Informational variation `Failed Spam Bot Traffic` exists and is invisible |
| Source | `XDR_ANALYTICS`, MITRE T1496 Resource Hijacking; alert tag `DS:panw/ngfw_traffic` |
| Required data (doc) | PAN firewall traffic logs OR XDR agent OR third-party firewalls |
| Activation / training (doc) | 14 days / 30 days. In practice the alert typically arrives 4 to 12 minutes after the burst (see Expected result) |
| Test period | 3 days (the alert text counts "in the last 3 days") |
| Deduplication | **3 days per source host** |
| Logic (doc) | The endpoint connected to an excessive number of external SMTP servers. The count is of distinct domains contacted plus unresolved IP addresses; the volume of traffic is not considered |
| What the alert text says | *"<host> connected to N SMTP servers in the last 3 days"* |

## Preconditions: check these BEFORE sending

| # | Must be true | How to check |
|---|---|---|
| 1 | You know the operator's syslog **log destination object** (`logdest:<id>`). It typically resolves to the broker's CEF port 5514. Do not send to `udp:<ip>:514` | `log_destinations_list` or the operator |
| 2 | The source host has **no `Spam Bot Traffic` alert in the last 3 days** (deduplication). A host with no earlier traffic works: it fires on its very first burst | Step 3 query without the time filter shows no alert for the host in 3 days |
| 3 | The 24 destination addresses are **public addresses**, not documentation ranges (RFC 5737) and not internal. The call uses `103.75.0.20-27`, `103.75.1.20-27` and `103.75.2.20-27` | none: the list is in the call below and does not change |
| 4 | No other bounded burst is running (xlog allows one at a time) | `phantom_list_workers`: no worker `Running` |

## Expected result

One bounded burst of 24 events to the 24 addresses below from one internal host fires the alert, including from a host with no earlier traffic. The alert names the distinct SMTP servers that landed (typically 15 to 30, depending on the burst) and typically arrives 4 to 12 minutes after the burst, so allow 20 minutes.

## Step 1: send the burst (exactly this call)

Call **`phantom_create_data_worker`**. Change only the values marked `<CHANGE>`.

```json
{
  "type": "CEF",
  "vendor": "panw",
  "product": "ngfw_traffic",
  "destination": "<CHANGE: logdest:<id> of the operator's syslog destination>",
  "name": "spambot-<CHANGE: short run id>",
  "tags": [
    "detection-validation",
    "T1496"
  ],
  "count": 24,
  "interval": 1,
  "duration_seconds": 60,
  "max_events": 24,
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
      "51000"
    ],
    "source_ip": [
      "<CHANGE: a new internal IPv4 from the organization's unmanaged block (10.20.100.0 to 10.20.199.255), e.g. 10.20.150.22; never the address of a person's workstation>"
    ],
    "source_device_host": [
      "<CHANGE: a new host name PHWS-<NNN> above the organization's last workstation (PHWS-050 on Phantom Lab), e.g. PHWS-122>"
    ],
    "source_user": [
      "<CHANGE: a bare user name, no backslash, that is not a person's, e.g. svc.runNNNN>"
    ],
    "dest_port": [
      "25"
    ],
    "app": [
      "smtp"
    ],
    "dest_ip": [
      "103.75.0.20",
      "103.75.0.21",
      "103.75.0.22",
      "103.75.0.23",
      "103.75.0.24",
      "103.75.0.25",
      "103.75.0.26",
      "103.75.0.27",
      "103.75.1.20",
      "103.75.1.21",
      "103.75.1.22",
      "103.75.1.23",
      "103.75.1.24",
      "103.75.1.25",
      "103.75.1.26",
      "103.75.1.27",
      "103.75.2.20",
      "103.75.2.21",
      "103.75.2.22",
      "103.75.2.23",
      "103.75.2.24",
      "103.75.2.25",
      "103.75.2.26",
      "103.75.2.27"
    ]
  }
}
```

Why each value is what it is:

- **`app: ["smtp"]`, `dest_port: ["25"]`**: what makes each connection an SMTP-server contact. Both must stay.
- **24 `dest_ip` values drawn 24 times with replacement**: only **14 to 19 distinct** addresses land per burst, and the alerts count between 15 and 30. The distinct-server count is what matters, so 24 addresses give a comfortable margin over the 15 that fires; do not shorten the list.
- **`action: ["allow"]`, `sub_type: ["end"]`, `log_type: ["TRAFFIC"]`**: completed, allowed connections. Failed attempts count as a separate, Informational variation.
- **`to_zone: ["untrust"]`**: external servers.
- **Thin schema (14 fields)**: no bytes or packets are needed because volume is not considered.
- **`count: 24`, `max_events: 24`, `duration_seconds: 60`, `interval: 1`**: one bounded burst of 24 events, then the worker stops itself. An unbounded job (`count 24, interval 300`, no bound) repeats every five minutes (24 events per tick, hourly); the alert comes from its first tick, so one burst is enough and the call here is bounded on purpose.
- **Draws are independent**: every event picks one value per field at random, so every field that must be constant is a one-element list.
- **Burst ceiling**: if the tool answers `burst rejected: 1 burst already running`, wait 60 s and send the same call again.

## Step 2: confirm the shape landed (about 60 s after Step 1)

```
config timeframe = 1h | dataset = panw_ngfw_traffic_raw
| filter source_device_host = "<your host>" and app = "smtp"
| comp count() as n, count_distinct(dest_ip) as ndst
```

Pass when `n = 24` and `ndst >= 14` (14 to 19 landed per burst). Then confirm the model took it:

```
config timeframe = 1h | datamodel dataset = panw_ngfw_traffic_raw
| filter xdm.source.host.hostname = "<your host>" and xdm.network.application_protocol = "smtp"
| comp count() as n, count_distinct(xdm.target.ipv4) as ndst
```

Pass when the counts match.

## Step 3: wait, then check for the alert

**Wait 3 minutes before the first check.** Alerts typically arrive 4 to 12 minutes after the burst. Then check every 2 minutes, for up to **20 minutes**:

```
dataset = alerts
| filter alert_name = "Spam Bot Traffic"
| fields _time, alert_id, alert_name, host_name, description, alert_arrival_timestamp
| sort desc _time
| limit 5
```

Pass when a new row names your host. The description is *"<host> connected to N SMTP servers in the last 3 days"* with N the distinct servers that landed. To list Analytics alerts without naming one, filter on the STORED enum values `alert_source in ("MAGNIFIER","ANALYTICS_BIOC")`: the displayed names `XDR_ANALYTICS` and `XDR_ANALYTICS_BIOC` match nothing.

If nothing arrives within 20 minutes: re-run Step 2 (the traffic must be in `panw_ngfw_traffic_raw` with `app smtp`), confirm the host has no alert of this name in the last 3 days, then retry once on **another host**. Do not change `app`, `dest_port` or the destination list.

## Report back to the operator

State the host, the source IP, the worker name, the Step 2 result and either the alert id with the arrival time or that nothing arrived and what you checked. Say that the host should not be reused for 3 days.
