---
id: XQL-800-f116e8a9
title: Alert detection-source breakdown (30d)
category: investigation
dataset: alerts
tags:
  - filter
  - comp
  - sort
  - limit
  - alerts
---

# Alert detection-source breakdown (30d)

**Dataset**: `alerts`

```sql
config timeframe = 30d
| dataset = alerts
| filter alert_source != null
| comp count() as cnt by alert_source, severity
| sort desc cnt
| limit 10
```

## When to use

Per-detection-source alert volume by severity. Reveals which detector source generates which severities. The detection source is the `alert_source` field.

## Variations

_(No variations are documented for this entry.)_
