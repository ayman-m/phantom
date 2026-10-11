---
id: XQL-064-46e8257b
title: Cortex XSIAM NGFW Threat Hunting - Custom XQL Widget
category: investigation
dataset: panw_ngfw_traffic_raw
tags:
  - comp
  - view
---

# Cortex XSIAM NGFW Threat Hunting - Custom XQL Widget

**Dataset**: `panw_ngfw_traffic_raw`

```sql
dataset = panw_ngfw_traffic_raw | comp count()
| view graph type = single subtype = standard header = "Total Traffic Logs" yaxis = count_1
```

## When to use

Cortex XSIAM NGFW Threat Hunting - Custom XQL Widget. Queries the `panw_ngfw_traffic_raw` dataset directly. Uses stages: `comp`, `view`.

## Variations

_(No variations are documented for this entry.)_
