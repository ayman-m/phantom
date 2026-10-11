---
id: XQL-771-1d0c649c
title: Alerts grouped by week (12w)
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

# Alerts grouped by week (12w)

**Dataset**: `alerts`

```sql
config timeframe = 12w
| dataset = alerts
| bin _time span = 1w
| comp count() as cnt by _time, severity
| sort desc _time
| limit 10
```

## When to use

Weekly alert-volume trend across severities. Useful for executive reporting + spotting macro trends (e.g. steady increase in HIGH alerts over a quarter).

## Variations

_(No variations are documented for this entry.)_
