---
id: XQL-068-47e963ed
title: 'Cortex XSIAM NGFW Remote Access Activity [Front] - Custom XQL Widget'
category: investigation
dataset: panw_ngfw_traffic_raw
tags:
  - comp
  - fields
  - filter
  - sort
---

# Cortex XSIAM NGFW Remote Access Activity [Front] - Custom XQL Widget

**Dataset**: `panw_ngfw_traffic_raw`

```sql
dataset = panw_ngfw_traffic_raw
| filter url_category = "proxy-avoidance-and-anonymizers"
| fields app, app_sub_category, from_zone
| comp count(app) as hits by app, app_sub_category, from_zone
| sort desc hits
| filter (from_zone != """noc_wifi""")
| filter (from_zone != """noc_wired""")
| filter (from_zone != """TAP-FW-1""")
| filter (app != """ssl""")
```

## When to use

Cortex XSIAM NGFW Remote Access Activity [Front] - Custom XQL Widget. Queries the `panw_ngfw_traffic_raw` dataset directly, filtered on `url_category = "proxy-avoidance-and-anonymizers"`. Uses stages: `filter`, `fields`, `comp`, `sort`.

## Variations

_(No variations are documented for this entry.)_
