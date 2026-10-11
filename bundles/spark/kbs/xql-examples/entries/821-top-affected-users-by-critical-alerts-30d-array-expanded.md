---
id: XQL-821-38310801
title: Top affected users by critical alerts (30d) — array-expanded
category: investigation
dataset: alerts
tags:
  - filter
  - arrayexpand
  - comp
  - sort
  - limit
  - alerts
---

# Top affected users by critical alerts (30d) — array-expanded

**Dataset**: `alerts`

```sql
config timeframe = 30d
| dataset = alerts
| filter severity = "CRITICAL" and user_name != null
| arrayexpand user_name
| comp count() as alerts, count_distinct(alert_name) as unique_alert_types by user_name
| sort desc alerts
| limit 10
```

## When to use

Users with the most critical-severity alerts. `user_name` is array-typed — arrayexpand to enable aggregation.

## Variations

_(No variations are documented for this entry.)_
