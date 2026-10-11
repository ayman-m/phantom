---
id: XQL-728-680eaa09
title: Critical + high alerts in the last 24 hours
category: investigation
dataset: alerts
tags:
  - filter
  - fields
  - sort
  - limit
  - alerts
---

# Critical + high alerts in the last 24 hours

**Dataset**: `alerts`

```sql
config timeframe = 24h
| dataset = alerts
| filter severity in ("CRITICAL", "HIGH")
| fields _time, severity, alert_name, host_name, description
| sort desc _time
| limit 10
```

## When to use

Triage view for the high-severity tail. Returns the most recent CRITICAL + HIGH alerts in the last day with the description for quick context.

## Variations

_(No variations are documented for this entry.)_
