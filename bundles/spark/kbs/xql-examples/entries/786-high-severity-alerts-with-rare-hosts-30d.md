---
id: XQL-786-f353f82b
title: High-severity alerts with rare hosts (30d)
category: detection
dataset: alerts
tags:
  - filter
  - comp
  - sort
  - limit
  - alerts
  - rare
---

# High-severity alerts with rare hosts (30d)

**Dataset**: `alerts`

```sql
config timeframe = 30d
| dataset = alerts
| filter severity in ("HIGH", "CRITICAL")
| comp count() as alerts_per_host by host_name, severity
| filter alerts_per_host = 1
| sort desc alerts_per_host
| limit 10
```

## When to use

Hosts that only had ONE high/critical alert in the timeframe. Lower-noise hosts where a single hit is more meaningful + more likely a true positive.

## Variations

_(No variations are documented for this entry.)_
