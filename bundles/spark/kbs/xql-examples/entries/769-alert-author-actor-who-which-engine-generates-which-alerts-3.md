---
id: XQL-769-aa7094e7
title: Alert author actor — who/which engine generates which alerts (30d)
category: investigation
dataset: alerts
tags:
  - filter
  - comp
  - sort
  - limit
  - alerts
---

# Alert author actor — who/which engine generates which alerts (30d)

**Dataset**: `alerts`

```sql
config timeframe = 30d
| dataset = alerts
| filter alert_source != null
| comp count() as cnt, count_distinct(host_name) as affected_hosts by alert_source
| sort desc cnt
| limit 10
```

## When to use

Per-engine alert production volume + per-engine blast radius (affected hosts). Useful for the SOC manager to see which engines drive the alert workload.

## Variations

_(No variations are documented for this entry.)_
