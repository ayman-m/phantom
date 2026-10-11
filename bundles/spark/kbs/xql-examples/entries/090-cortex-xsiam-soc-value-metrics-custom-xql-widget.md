---
id: XQL-090-9fb16aaa
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
// Total Incidents
| comp count_distinct(incident_id) as total_incidents by original_tags
| sort desc total_incidents
| view graph type = pie header = "Total Incidents" xaxis = original_tags yaxis = total_incidents
```

## When to use

Cortex XSIAM SOC Value Metrics - Custom XQL Widget. Queries the `alerts` dataset directly, filtered on `original_tags contains "DS:"`. Uses stages: `arrayexpand`, `filter`, `comp`, `sort`, `view`.

## Variations

_(No variations are documented for this entry.)_
