---
id: XQL-778-54eb983f
title: Earliest alert per host + its detail (30d)
category: detection
dataset: alerts
tags:
  - filter
  - windowcomp
  - fields
  - sort
  - limit
  - alerts
  - row_number
---

# Earliest alert per host + its detail (30d)

**Dataset**: `alerts`

```sql
config timeframe = 30d
| dataset = alerts
| filter host_name != null
| windowcomp row_number() by host_name sort asc _time as rn
| filter rn = 1
| fields _time, host_name, alert_name, severity
| sort desc _time
| limit 10
```

## When to use

First-seen alert per host — useful for compromise-onset triage. `row_number()` partitioned by host + sorted ascending gives the earliest row per host.

## Variations

_(No variations are documented for this entry.)_
