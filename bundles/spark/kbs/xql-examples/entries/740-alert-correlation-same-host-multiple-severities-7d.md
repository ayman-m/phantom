---
id: XQL-740-324d1f53
title: Alert correlation — same host + multiple severities (7d)
category: detection
dataset: alerts
tags:
  - filter
  - comp
  - sort
  - limit
  - alerts
---

# Alert correlation — same host + multiple severities (7d)

**Dataset**: `alerts`

```sql
config timeframe = 7d
| dataset = alerts
| filter host_name != null
| comp count_distinct(severity) as sev_count, values(severity) as severities, count() as alert_count by host_name
| filter sev_count >= 2
| sort desc alert_count
| limit 10
```

## When to use

Hosts with alerts at multiple severities within the timeframe. Could indicate an active campaign (multiple detection rules firing) or chronic noise (always-noisy host).

## Variations

_(No variations are documented for this entry.)_
