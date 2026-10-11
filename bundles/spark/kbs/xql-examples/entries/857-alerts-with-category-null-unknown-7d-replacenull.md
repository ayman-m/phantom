---
id: XQL-857-1630205b
title: Alerts with category null → "unknown" (7d, replacenull)
category: investigation
dataset: alerts
tags:
  - filter
  - replacenull
  - comp
  - sort
  - limit
  - alerts
---

# Alerts with category null → "unknown" (7d, replacenull)

**Dataset**: `alerts`

```sql
config timeframe = 7d
| dataset = alerts
| replacenull category = "unknown"
| replacenull host_name = "unknown"
| comp count() as cnt by category, host_name
| sort desc cnt
| limit 10
```

## When to use

Replaces nulls in named fields with literal defaults BEFORE aggregation. The `replacenull <field> = <value>` syntax — one statement per field. Cleans sparse fields so they aggregate into a visible bucket instead of being dropped.

## Variations

_(No variations are documented for this entry.)_
