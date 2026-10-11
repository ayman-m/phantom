---
id: XQL-101-f601fc6b
title: Cortex XSIAM HTTP Activity - Custom XQL Widget
category: investigation
dataset: xdr_data
tags:
  - alter
  - comp
  - fields
  - filter
  - limit
  - sort
  - view
---

# Cortex XSIAM HTTP Activity - Custom XQL Widget

**Dataset**: `xdr_data`

```sql
dataset = xdr_data
| filter event_type = ENUM.STORY
| fields http_data, event_id
| alter responsecode  = arrayindex(regextract(to_json_string(http_data), "http_rsp_code\"\:(\d+)"),0)
| filter responsecode  != null
| comp count(event_id) as traffic_count by responsecode
| sort desc traffic_count
| limit 10
| view graph type = column subtype = grouped layout = horizontal show_callouts = `true` xaxis = responsecode yaxis = traffic_count seriescolor("traffic_count","#5dae44") xvaluesfontsize = 15 calloutfontsize = 15
```

## When to use

Cortex XSIAM HTTP Activity - Custom XQL Widget. Queries the `xdr_data` dataset directly, filtered on `event_type = ENUM.STORY`. Uses stages: `filter`, `fields`, `alter`, `comp`, `sort`, `limit`.

## Variations

_(No variations are documented for this entry.)_
