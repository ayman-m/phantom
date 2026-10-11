---
id: XQL-097-2fb3b951
title: Cortex XSIAM Network Zones - Custom XQL Widget
category: investigation
dataset: panw
tags:
  - alter
  - comp
  - filter
  - limit
  - sort
  - view
---

# Cortex XSIAM Network Zones - Custom XQL Widget

**Dataset**: `panw`

```sql
dataset = panw*
| comp count(_id) as counter by from_zone, to_zone
| alter zones = concat(from_zone, "-->", to_zone )
| filter zones != "TAP-->TAP"
| sort desc counter
| limit 10
| view graph type = area subtype = standard show_callouts = `true` show_percentage = `false` xaxis = zones yaxis = counter seriescolor("counter","#9b5e19") legend = `false`
```

## When to use

Cortex XSIAM Network Zones - Custom XQL Widget. Queries the `panw` dataset directly, filtered on `zones != "TAP-->TAP"`. Uses stages: `comp`, `alter`, `filter`, `sort`, `limit`, `view`.

## Variations

_(No variations are documented for this entry.)_
