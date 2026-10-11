---
id: XQL-725-a8a750c9
title: Alerts by host (7d)
category: investigation
dataset: alerts
tags:
  - filter
  - comp
  - sort
  - limit
  - alerts
---

# Alerts by host (7d)

**Dataset**: `alerts`

```sql
config timeframe = 7d
| dataset = alerts
| filter host_name != null
| comp count() as cnt by host_name, severity
| sort desc cnt
| limit 10
```

## When to use

Per-host alert volume by severity. Identifies the noisiest hosts + flags hosts with disproportionately high CRITICAL alert counts.

## Variations

_(No variations are documented for this entry.)_
