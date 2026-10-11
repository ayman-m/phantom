---
id: XQL-722-8f094e72
title: Alert distribution by severity (7d)
category: investigation
dataset: alerts
tags:
  - filter
  - comp
  - sort
  - limit
  - alerts
---

# Alert distribution by severity (7d)

**Dataset**: `alerts`

```sql
config timeframe = 7d
| dataset = alerts
| comp count() as cnt by severity
| sort desc cnt
| limit 10
```

## When to use

Severity baseline for the last 7 days. Useful as the first triage view + for trend monitoring (volume by severity over time).

## Variations

_(No variations are documented for this entry.)_
