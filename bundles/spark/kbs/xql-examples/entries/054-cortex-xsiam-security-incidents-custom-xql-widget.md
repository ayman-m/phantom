---
id: XQL-054-e758f3ac
title: Cortex XSIAM Security Incidents - Custom XQL Widget
category: investigation
dataset: incidents
tags:
  - alter
  - comp
  - fields
  - view
---

# Cortex XSIAM Security Incidents - Custom XQL Widget

**Dataset**: `incidents`

```sql
dataset = incidents
| fields description, alert_categories, severity, incident_id
| comp count(incident_id) as incidents by severity
| alter from_time = parse_timestamp("%Y-%m-%d %H:%M:%S ", "2024-12-06 00:00:00")
| alter to_time = parse_timestamp("%Y-%m-%d %H:%M:%S ", "2024-12-09 00:00:00")
// view graph type = pie subtype = semi_donut xaxis = severity yaxis = incidents
| view graph type = pie xaxis = severity yaxis = incidents
```

## When to use

Cortex XSIAM Security Incidents - Custom XQL Widget. Queries the `incidents` dataset directly. Uses stages: `fields`, `comp`, `alter`, `view`.

## Variations

_(No variations are documented for this entry.)_
