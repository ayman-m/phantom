---
id: XQL-784-46cd1c6a
title: Daily alert trend by category (14d)
category: investigation
dataset: alerts
tags:
  - filter
  - bin
  - comp
  - sort
  - limit
  - alerts
---

# Daily alert trend by category (14d)

**Dataset**: `alerts`

```sql
config timeframe = 14d
| dataset = alerts
| filter category != null
| bin _time span = 1d
| comp count() as cnt by _time, category
| sort desc _time
| limit 10
```

## When to use

Two-week daily alert trend per category. Reveals category-level patterns + spikes.

## Variations

_(No variations are documented for this entry.)_
