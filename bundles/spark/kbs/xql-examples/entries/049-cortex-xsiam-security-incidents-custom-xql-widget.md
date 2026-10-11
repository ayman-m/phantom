---
id: XQL-049-e758f3ac
title: Cortex XSIAM Security Incidents - Custom XQL Widget
category: investigation
dataset: incidents
tags:
  - alter
  - bin
  - comp
  - dataset
  - filter
  - sort
  - union
  - view
---

# Cortex XSIAM Security Incidents - Custom XQL Widget

**Dataset**: `incidents`

```sql
config timeframe = 4d|
dataset = incidents
//get created incidents by day
| bin creation_time span = 1d
| alter day = format_timestamp("%b %d", creation_time)
| comp count_distinct(incident_id) as new by day
//union resolved incidents by day
| union (
dataset = incidents
| bin resolved_ts span = 1d
| alter day = format_timestamp("%b %d", resolved_ts)
| comp count_distinct(incident_id) as resolved by day
)
//display in grouped vertical columns
| sort asc day
| filter day contains "Aug"
| view graph type = column subtype = grouped layout = horizontal show_callouts = `true` xaxis = day yaxis = new,resolved seriescolor("new","#479ca2") seriescolor("resolved","#7575a6") seriestitle("new","New Incidents") seriestitle("resolved","Resolved Incidents")
```

## When to use

Cortex XSIAM Security Incidents - Custom XQL Widget. XQL pattern, filtered on `day contains "Aug"`. Uses stages: `dataset`, `bin`, `alter`, `comp`, `union`, `sort`.

## Variations

_(No variations are documented for this entry.)_
