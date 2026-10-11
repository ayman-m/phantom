---
id: XQL-108-4c54581e
title: Cortex XSIAM URL Activity - Custom XQL Widget
category: investigation
dataset: panw
tags:
  - comp
  - filter
  - limit
  - sort
  - view
---

# Cortex XSIAM URL Activity - Custom XQL Widget

**Dataset**: `panw`

```sql
dataset = panw*
| filter risk_of_app != "Informational"
| comp count(_id) as traffic_count by risk_of_app
| sort  desc traffic_count
| limit 10
| view graph type = pie subtype = semi_donut xaxis = risk_of_app yaxis = traffic_count
```

## When to use

Cortex XSIAM URL Activity - Custom XQL Widget. Queries the `panw` dataset directly, filtered on `risk_of_app != "Informational"`. Uses stages: `filter`, `comp`, `sort`, `limit`, `view`.

## Variations

_(No variations are documented for this entry.)_
