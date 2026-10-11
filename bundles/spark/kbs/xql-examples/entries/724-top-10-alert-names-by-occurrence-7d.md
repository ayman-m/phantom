---
id: XQL-724-81405d9d
title: Top 10 alert names by occurrence (7d)
category: investigation
dataset: alerts
tags:
  - filter
  - comp
  - sort
  - limit
  - alerts
---

# Top 10 alert names by occurrence (7d)

**Dataset**: `alerts`

```sql
config timeframe = 7d
| dataset = alerts
| comp count() as cnt by alert_name
| sort desc cnt
| limit 10
```

## When to use

Surfaces the most-fired alert rules. Helps prioritize tuning effort (high-volume rules with low fidelity) or identify campaign-level activity (sudden spikes on a single alert name).

## Variations

_(No variations are documented for this entry.)_
