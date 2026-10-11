---
id: XQL-842-18cb5f54
title: Alert age + tier composite scoring (30d)
category: investigation
dataset: alerts
tags:
  - filter
  - alter
  - fields
  - sort
  - limit
  - alerts
  - if
  - math
  - scoring
---

# Alert age + tier composite scoring (30d)

**Dataset**: `alerts`

```sql
config timeframe = 30d
| dataset = alerts
| filter severity != null
| alter sev_weight = if(severity = "CRITICAL", 4, if(severity = "HIGH", 3, if(severity = "MEDIUM", 2, 1)))
| alter age_hours = divide(timestamp_diff(current_time(), _time, "HOUR"), 1)
| alter age_decay = if(age_hours < 24, 1.0, if(age_hours < 72, 0.7, if(age_hours < 168, 0.4, 0.1)))
| alter priority_score = multiply(sev_weight, age_decay)
| fields _time, host_name, alert_name, severity, age_hours, priority_score
| sort desc priority_score
| limit 10
```

## When to use

Composite priority score: severity weight × age decay. Newer + higher-severity alerts get the top score. Demonstrates chained `alter` steps to engineer derived columns from raw data — the pattern adapts to any custom scoring need.

## Variations

_(No variations are documented for this entry.)_
