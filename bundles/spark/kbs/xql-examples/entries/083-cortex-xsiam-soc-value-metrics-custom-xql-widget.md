---
id: XQL-083-9fb16aaa
title: Cortex XSIAM SOC Value Metrics - Custom XQL Widget
category: investigation
dataset: alerts
tags:
  - arrayexpand
  - comp
  - filter
  - sort
  - view
---

# Cortex XSIAM SOC Value Metrics - Custom XQL Widget

**Dataset**: `alerts`

```sql
dataset = alerts
| arrayexpand original_tags
| filter original_tags contains "DS:"
//| filter original_tags contains "Proofpoint"
| filter resolution_status = ENUM.RESOLVED_OTHER or resolution_status = ENUM.RESOLVED_AUTO_RESOLVE or resolution_status = ENUM.RESOLVED_AUTO_RESOLVE
| comp count_distinct(alert_id) as total_alerts by original_tags
| sort desc total_alerts
//| view column order = populated
| view graph type = column subtype = grouped layout = horizontal header = "Total Auto Resolved Alerts" xaxis = original_tags yaxis = total_alerts seriescolor("total_alerts","#aaec7c") xaxistitle = "Alerts" yaxistitle = "Data Sources" seriestitle("total_alerts","Alerts by Data Source")
```

## When to use

Cortex XSIAM SOC Value Metrics - Custom XQL Widget. Queries the `alerts` dataset directly, filtered on `original_tags contains "DS:"`. Uses stages: `arrayexpand`, `filter`, `comp`, `sort`, `view`.

## Variations

_(No variations are documented for this entry.)_
