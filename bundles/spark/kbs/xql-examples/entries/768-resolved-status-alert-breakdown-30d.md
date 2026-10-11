---
id: XQL-768-ce4dada6
title: Resolved-status alert breakdown (30d)
category: investigation
dataset: alerts
tags:
  - filter
  - comp
  - sort
  - limit
  - alerts
---

# Resolved-status alert breakdown (30d)

**Dataset**: `alerts`

```sql
config timeframe = 30d
| dataset = alerts
| filter resolution_status != null
| comp count() as cnt by resolution_status
| sort desc cnt
| limit 10
```

## When to use

Alert lifecycle outcomes — true-positive, false-positive, duplicate, etc. Reveals the noise/signal ratio + which detectors generate the most FP load.

## Variations

_(No variations are documented for this entry.)_
