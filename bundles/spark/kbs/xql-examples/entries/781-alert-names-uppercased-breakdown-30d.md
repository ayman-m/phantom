---
id: XQL-781-f16592d3
title: Alert names — uppercased breakdown (30d)
category: investigation
dataset: alerts
tags:
  - filter
  - alter
  - comp
  - sort
  - limit
  - alerts
  - uppercase
---

# Alert names — uppercased breakdown (30d)

**Dataset**: `alerts`

```sql
config timeframe = 30d
| dataset = alerts
| alter alert_upper = uppercase(alert_name)
| comp count() as cnt by alert_upper
| sort desc cnt
| limit 10
```

## When to use

Case-normalized alert-name aggregation. Useful when alert names show up with mixed casing from different sources.

## Variations

_(No variations are documented for this entry.)_
