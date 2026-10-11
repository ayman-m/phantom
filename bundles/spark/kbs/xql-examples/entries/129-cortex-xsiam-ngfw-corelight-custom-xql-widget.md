---
id: XQL-129-563d6d47
title: Cortex XSIAM NGFW/Corelight - Custom XQL Widget
category: investigation
dataset: panw_ngfw_traffic_raw
tags:
  - comp
  - fields
  - filter
  - sort
  - view
---

# Cortex XSIAM NGFW/Corelight - Custom XQL Widget

**Dataset**: `panw_ngfw_traffic_raw`

```sql
dataset = panw_ngfw_traffic_raw
| filter app not contains "not-applicable" and app not contains "incomplete"
| fields app
| comp count(app) as app_num by app
| sort desc app_num
| view graph type = pie xaxis = app yaxis = app_num
```

## When to use

Cortex XSIAM NGFW/Corelight - Custom XQL Widget. Queries the `panw_ngfw_traffic_raw` dataset directly, filtered on `app not contains "not-applicable" and app not contains "incomplete"`. Uses stages: `filter`, `fields`, `comp`, `sort`, `view`.

## Variations

_(No variations are documented for this entry.)_
