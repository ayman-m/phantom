---
id: XQL-057-423f4558
title: Cortex XSIAM NGFW 24h - Custom XQL Widget
category: investigation
dataset: panw_ngfw_traffic_raw
tags:
  - comp
  - filter
  - view
---

# Cortex XSIAM NGFW 24h - Custom XQL Widget

**Dataset**: `panw_ngfw_traffic_raw`

```sql
dataset = panw_ngfw_traffic_raw
| filter app not contains "xdr" and app not contains "paloalto" and app not contains "traps" and app not contains "traps" and app not contains "panos" and action = "drop"
| comp count(action)
| view graph type = single subtype = standard header = "Drop" yaxis = count_1 headcolor = "#ffba00" headerfontsize = 60
```

## When to use

Cortex XSIAM NGFW 24h - Custom XQL Widget. Queries the `panw_ngfw_traffic_raw` dataset directly, filtered on `app not contains "xdr" and app not contains "paloalto" and app not contains "traps" and app not contains "traps" and app not contains "panos`. Uses stages: `filter`, `comp`, `view`.

## Variations

_(No variations are documented for this entry.)_
