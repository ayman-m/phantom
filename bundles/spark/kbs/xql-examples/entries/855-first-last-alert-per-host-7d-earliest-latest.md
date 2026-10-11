---
id: XQL-855-5d9a2526
title: First + last alert per host (7d, earliest/latest)
category: investigation
dataset: alerts
tags:
  - filter
  - comp
  - sort
  - limit
  - alerts
  - earliest
  - latest
---

# First + last alert per host (7d, earliest/latest)

**Dataset**: `alerts`

```sql
config timeframe = 7d
| dataset = alerts
| filter host_name != null
| comp earliest(alert_name) as first_alert, latest(alert_name) as last_alert, count() as alert_count by host_name
| sort desc alert_count
| limit 10
```

## When to use

Per-host first + last alert names via `earliest()` + `latest()` aggregation. Cleaner than windowcomp+dedup when you also want a row count.

## Variations

_(No variations are documented for this entry.)_
