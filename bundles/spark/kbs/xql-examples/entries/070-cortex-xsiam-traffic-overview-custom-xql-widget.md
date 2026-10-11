---
id: XQL-070-1800f63a
title: Cortex XSIAM Traffic Overview - Custom XQL Widget
category: investigation
tags:
  - alter
  - comp
  - limit
  - sort
  - view
---

# Cortex XSIAM Traffic Overview - Custom XQL Widget

**Dataset**: `(none)`

```sql
preset = network_story
| alter app = arrayindex(action_app_id_transitions ,2)
| comp count(event_id ) as traffic_count by app
| sort desc traffic_count
| limit 12
| view graph type = column subtype = grouped layout = horizontal show_callouts = `true` xaxis = app yaxis = traffic_count seriescolor("traffic_count","#4384c2") xvaluesfontsize = 12 legend = `false`
```

## When to use

Cortex XSIAM Traffic Overview - Custom XQL Widget. Queries the `(none)` preset. Uses stages: `alter`, `comp`, `sort`, `limit`, `view`.

## Variations

_(No variations are documented for this entry.)_
