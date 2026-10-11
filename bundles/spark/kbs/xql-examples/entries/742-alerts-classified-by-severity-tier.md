---
id: XQL-742-654446ba
title: Alerts classified by severity tier
category: investigation
dataset: alerts
tags:
  - filter
  - alter
  - comp
  - sort
  - limit
  - alerts
  - conditional
---

# Alerts classified by severity tier

**Dataset**: `alerts`

```sql
config timeframe = 7d
| dataset = alerts
| alter tier = if(severity = "CRITICAL", "P1", if(severity = "HIGH", "P2", if(severity = "MEDIUM", "P3", "P4")))
| comp count() as cnt by tier
| sort asc tier
| limit 10
```

## When to use

Maps XSIAM severity to priority tiers (P1-P4) via nested `if()`. Useful for SLA reporting where the operations team tracks alerts by priority class.

## Variations

_(No variations are documented for this entry.)_
