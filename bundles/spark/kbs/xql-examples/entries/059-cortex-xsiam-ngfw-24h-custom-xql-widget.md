---
id: XQL-059-423f4558
title: Cortex XSIAM NGFW 24h - Custom XQL Widget
category: investigation
dataset: panw_ngfw_traffic_raw
tags:
  - comp
  - filter
  - limit
  - sort
  - view
---

# Cortex XSIAM NGFW 24h - Custom XQL Widget

**Dataset**: `panw_ngfw_traffic_raw`

```sql
dataset = panw_ngfw_traffic_raw
| filter app not contains "xdr" and app not contains "paloalto" and app not contains "traps" and app not contains "traps" and app not contains "panos" and action = "allow"
| comp count(app ) as counter by app
| sort desc counter
| limit 10
| view graph type = pie subtype = full xaxis = app yaxis = counter
```

## When to use

Cortex XSIAM NGFW 24h - Custom XQL Widget. Queries the `panw_ngfw_traffic_raw` dataset directly, filtered on `app not contains "xdr" and app not contains "paloalto" and app not contains "traps" and app not contains "traps" and app not contains "panos`. Uses stages: `filter`, `comp`, `sort`, `limit`, `view`.

## Variations

_(No variations are documented for this entry.)_
