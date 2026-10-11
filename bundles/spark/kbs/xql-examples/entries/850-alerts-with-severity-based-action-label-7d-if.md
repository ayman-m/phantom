---
id: XQL-850-9abd7a3f
title: Alerts with severity-based action label (7d, if)
category: investigation
dataset: alerts
tags:
  - filter
  - alter
  - comp
  - sort
  - limit
  - alerts
  - if
  - conditional
---

# Alerts with severity-based action label (7d, if)

**Dataset**: `alerts`

```sql
config timeframe = 7d
| dataset = alerts
| alter action_needed = if(severity = "CRITICAL", "immediate-page", if(severity = "HIGH", "same-day", if(severity = "MEDIUM", "next-business-day", "backlog")))
| comp count() as cnt by action_needed
| sort desc cnt
| limit 10
```

## When to use

Maps each alert to an SLA action label via nested `if()`. Useful for SLA reporting + operator-facing dashboards.

## Variations

_(No variations are documented for this entry.)_
