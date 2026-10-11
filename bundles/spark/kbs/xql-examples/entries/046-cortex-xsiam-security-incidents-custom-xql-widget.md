---
id: XQL-046-e758f3ac
title: Cortex XSIAM Security Incidents - Custom XQL Widget
category: investigation
dataset: incidents
tags:
  - alter
  - comp
  - filter
  - view
---

# Cortex XSIAM Security Incidents - Custom XQL Widget

**Dataset**: `incidents`

```sql
dataset = incidents
| filter assigned_user = NULL and status = ENUM.NEW
| comp count_distinct(incident_id)
| alter from_time = parse_timestamp("%Y-%m-%d %H:%M:%S ", "2025-04-01 00:00:00")
| alter to_time = parse_timestamp("%Y-%m-%d %H:%M:%S ", "2025-04-04 00:00:00")
 //view graph type = single subtype = standard yaxis = count_distinct_1 scale_threshold("#00ff00","#ffff00","20","#ff0000","30")
| view graph type = single subtype = standard yaxis = count_distinct_1
```

## When to use

Cortex XSIAM Security Incidents - Custom XQL Widget. Queries the `incidents` dataset directly, filtered on `assigned_user = NULL and status = ENUM.NEW`. Uses stages: `filter`, `comp`, `alter`, `view`.

## Variations

_(No variations are documented for this entry.)_
