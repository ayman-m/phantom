---
id: XQL-723-5f864da8
title: Alert distribution by category + alert_source (7d)
category: investigation
dataset: alerts
tags:
  - filter
  - comp
  - sort
  - limit
  - alerts
---

# Alert distribution by category + alert_source (7d)

**Dataset**: `alerts`

```sql
config timeframe = 7d
| dataset = alerts
| comp count() as cnt by category, alert_source
| sort desc cnt
| limit 10
```

## When to use

Aggregate alerts by category and source detector. Useful for understanding which detection sources are firing the most + which categories dominate the tenant's alert mix.

## Variations

_(No variations are documented for this entry.)_
