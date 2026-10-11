---
id: XQL-103-f601fc6b
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
| alter a = to_json_string(http_data)
| alter user_agent  = arrayindex(regextract(to_json_string(http_data), "http_req_user_agent_header\"\:\"(.*?)\""),0)
| filter user_agent  != null
| comp count(event_id) as traffic_count by user_agent
| sort desc traffic_count
| limit 10
| view graph type = column subtype = grouped layout = horizontal show_callouts = `true` xaxis = user_agent yaxis = traffic_count seriescolor("traffic_count","#5dae44") xvaluesfontsize = 15 calloutfontsize = 15
```

## When to use

Cortex XSIAM HTTP Activity - Custom XQL Widget. Queries the `xdr_data` dataset directly, filtered on `event_type = ENUM.STORY`. Uses stages: `filter`, `fields`, `alter`, `comp`, `sort`, `limit`.

## Variations

_(No variations are documented for this entry.)_
