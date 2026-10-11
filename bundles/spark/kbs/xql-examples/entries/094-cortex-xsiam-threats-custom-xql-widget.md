---
id: XQL-094-a291dbc2
title: Cortex XSIAM Threats - Custom XQL Widget
category: investigation
dataset: panw_ngfw_threat_raw
tags:
  - comp
  - filter
  - limit
  - sort
  - view
---

# Cortex XSIAM Threats - Custom XQL Widget

**Dataset**: `panw_ngfw_threat_raw`

```sql
dataset = panw_ngfw_threat_raw
| filter severity != "Informational"
| comp count(_id ) as counter by severity
| sort desc counter
| limit 10
| view graph type = pie subtype = semi_donut xaxis = severity yaxis = counter
```

## When to use

Cortex XSIAM Threats - Custom XQL Widget. Queries the `panw_ngfw_threat_raw` dataset directly, filtered on `severity != "Informational"`. Uses stages: `filter`, `comp`, `sort`, `limit`, `view`.

## Variations

_(No variations are documented for this entry.)_
