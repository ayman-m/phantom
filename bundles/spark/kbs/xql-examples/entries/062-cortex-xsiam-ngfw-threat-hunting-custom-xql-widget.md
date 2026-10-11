---
id: XQL-062-46e8257b
title: Cortex XSIAM NGFW Threat Hunting - Custom XQL Widget
category: investigation
dataset: panw_ngfw_traffic_raw
tags:
  - comp
  - filter
  - view
---

# Cortex XSIAM NGFW Threat Hunting - Custom XQL Widget

**Dataset**: `panw_ngfw_traffic_raw`

```sql
dataset = panw_ngfw_traffic_raw | filter app contains "unknown" | comp count(app) as app_count by app
| view graph type = pie header = "Unkown UDP and TCP" xaxis = app yaxis = app_count
```

## When to use

Cortex XSIAM NGFW Threat Hunting - Custom XQL Widget. Queries the `panw_ngfw_traffic_raw` dataset directly, filtered on `app contains "unknown"`. Uses stages: `filter`, `comp`, `view`.

## Variations

_(No variations are documented for this entry.)_
