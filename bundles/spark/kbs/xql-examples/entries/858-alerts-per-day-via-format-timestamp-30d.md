---
id: XQL-858-ae5cd799
title: Alerts per day via format_timestamp (30d)
category: investigation
dataset: alerts
tags:
  - filter
  - alter
  - comp
  - sort
  - limit
  - alerts
  - format_timestamp
---

# Alerts per day via format_timestamp (30d)

**Dataset**: `alerts`

```sql
config timeframe = 30d
| dataset = alerts
| alter day_bucket = format_timestamp("%Y-%m-%d", _time)
| comp count() as cnt by day_bucket, severity
| sort desc day_bucket
| limit 10
```

## When to use

Daily alert count per severity using `format_timestamp("%Y-%m-%d", _time)` for day-precision string buckets. Alternative to `bin _time span = 1d` when you want ISO-date strings in the output.

## Variations

_(No variations are documented for this entry.)_
