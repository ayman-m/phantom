---
id: XQL-820-2bd0631a
title: Alerts by initiator process (30d) — array-expanded
category: investigation
dataset: alerts
tags:
  - filter
  - arrayexpand
  - comp
  - sort
  - limit
  - alerts
---

# Alerts by initiator process (30d) — array-expanded

**Dataset**: `alerts`

```sql
config timeframe = 30d
| dataset = alerts
| filter initiator_path != null
| arrayexpand initiator_path
| comp count() as cnt by initiator_path, severity
| sort desc cnt
| limit 10
```

## When to use

Which initiator processes (the process that triggered the detection) generate the most alerts. `initiator_path` is an array — use arrayexpand before aggregation.

## Variations

_(No variations are documented for this entry.)_
