---
id: XQL-791-e221fccd
title: Unique alert names per detector source (30d)
category: investigation
dataset: alerts
tags:
  - filter
  - comp
  - sort
  - limit
  - alerts
---

# Unique alert names per detector source (30d)

**Dataset**: `alerts`

```sql
config timeframe = 30d
| dataset = alerts
| filter alert_source != null
| comp count_distinct(alert_name) as unique_rules, count() as fires by alert_source
| sort desc unique_rules
| limit 10
```

## When to use

Per-detector source: how many unique alert rules fired + how many total fires. Reveals detector breadth (many rules) vs depth (few rules, many fires).

## Variations

_(No variations are documented for this entry.)_
