---
id: XQL-100-f601fc6b
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
  - union
  - view
---

# Cortex XSIAM HTTP Activity - Custom XQL Widget

**Dataset**: `xdr_data`

```sql
dataset = xdr_data
| filter event_type = ENUM.STORY
| fields http_data, event_id
| filter http_data != null
| alter http_method  = arrayindex(regextract(to_json_string(http_data), "http_req_before_method.*?(\w+)"),0)
| alter http_method = if(http_method = "null","", http_method )
| filter http_method != null
| union (dataset = panw*| fields _id as event_id, http_method  | alter http_method = if(http_method = "unknown","", http_method )| alter http_method = uppercase(http_method ) | filter http_method != "" and http_method != null)
| comp count(event_id) as counter by http_method | filter http_method != ""
| sort desc counter | limit 10
| view graph type = area subtype = standard show_callouts = `true` show_percentage = `false` xaxis = http_method yaxis = counter seriescolor("counter","#5dae44") xvaluesfontsize = 15 calloutfontsize = 15 seriestitle("counter","traffic_count")
```

## When to use

Cortex XSIAM HTTP Activity - Custom XQL Widget. Queries the `xdr_data` dataset directly, filtered on `event_type = ENUM.STORY`. Uses stages: `filter`, `fields`, `alter`, `union`, `comp`, `sort`.

## Variations

_(No variations are documented for this entry.)_
