---
id: XQL-089-9fb16aaa
title: Cortex XSIAM SOC Value Metrics - Custom XQL Widget
category: investigation
dataset: alerts
tags:
  - comp
  - sort
  - view
---

# Cortex XSIAM SOC Value Metrics - Custom XQL Widget

**Dataset**: `alerts`

```sql
dataset = alerts
// Total Alerts
| comp count_distinct(alert_id) as total_alerts by alert_source
| sort desc total_alerts
| view graph type = pie show_callouts = `true` show_callouts_names = `true` xaxis = alert_source yaxis = total_alerts
```

## When to use

Cortex XSIAM SOC Value Metrics - Custom XQL Widget. Queries the `alerts` dataset directly. Uses stages: `comp`, `sort`, `view`.

## Variations

_(No variations are documented for this entry.)_
