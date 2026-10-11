---
id: XQL-093-a291dbc2
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
| comp count(_id ) as no_of_traffic by from_zone
| sort desc no_of_traffic
| limit 10
| view graph type = column subtype = grouped layout = horizontal show_callouts = `true` xaxis = from_zone yaxis = no_of_traffic seriescolor("no_of_traffic","#32c262") legend = `false`
```

## When to use

Cortex XSIAM Threats - Custom XQL Widget. Queries the `panw_ngfw_threat_raw` dataset directly, filtered on `severity != "Informational"`. Uses stages: `filter`, `comp`, `sort`, `limit`, `view`.

## Variations

_(No variations are documented for this entry.)_
