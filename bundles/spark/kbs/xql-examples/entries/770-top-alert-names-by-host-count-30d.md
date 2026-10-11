---
id: XQL-770-7a7e89b8
title: Top alert names by host count (30d)
category: investigation
dataset: alerts
tags:
  - filter
  - comp
  - sort
  - limit
  - alerts
---

# Top alert names by host count (30d)

**Dataset**: `alerts`

```sql
config timeframe = 30d
| dataset = alerts
| comp count_distinct(host_name) as host_count, count() as alert_count by alert_name
| sort desc host_count
| limit 10
```

## When to use

Alert names ranked by how many distinct hosts they fired against. High host-count alerts often indicate widespread issues (env-wide misconfig, broad campaign).

## Variations

_(No variations are documented for this entry.)_
