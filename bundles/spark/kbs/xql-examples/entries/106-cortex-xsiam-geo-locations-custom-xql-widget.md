---
id: XQL-106-1fef4d0f
title: Cortex XSIAM Geo Locations - Custom XQL Widget
category: investigation
tags:
  - comp
  - filter
  - iploc
  - limit
  - sort
  - union
  - view
---

# Cortex XSIAM Geo Locations - Custom XQL Widget

**Dataset**: `(none)`

```sql
preset = network_story
| iploc action_remote_ip loc_country
| filter loc_country != null
| union (preset = network_story| iploc action_local_ip loc_country | filter loc_country != null)
| comp count(event_id) as counter by loc_country
| sort desc counter
| limit 10
| view graph type = pie subtype = semi_donut xaxis = loc_country yaxis = counter
```

## When to use

Cortex XSIAM Geo Locations - Custom XQL Widget. Queries the `(none)` preset, filtered on `loc_country != null`. Uses stages: `iploc`, `filter`, `union`, `comp`, `sort`, `limit`.

## Variations

_(No variations are documented for this entry.)_
