---
id: XQL-098-2fb3b951
title: Cortex XSIAM Network Zones - Custom XQL Widget
category: investigation
dataset: panw
tags:
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
| comp count(_id) as counter by to_zone
| filter to_zone != "TAP"
| sort desc counter
| limit 10
| view graph type = column subtype = grouped layout = horizontal show_callouts = `true` xaxis = to_zone yaxis = counter seriescolor("counter","#9b5e19") xvaluesfontsize = 15 calloutfontsize = 15 legend = `false`
```

## When to use

Cortex XSIAM Network Zones - Custom XQL Widget. Queries the `panw` dataset directly, filtered on `to_zone != "TAP"`. Uses stages: `comp`, `filter`, `sort`, `limit`, `view`.

## Variations

_(No variations are documented for this entry.)_
