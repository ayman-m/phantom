---
id: XQL-087-9fb16aaa
title: Cortex XSIAM SOC Value Metrics - Custom XQL Widget
category: investigation
dataset: incidents
tags:
  - alter
  - comp
  - dataset
  - fields
  - filter
  - view
---

# Cortex XSIAM SOC Value Metrics - Custom XQL Widget

**Dataset**: `incidents`

```sql
config timeframe = 7D
| dataset = incidents
| fields incident_id, creation_time, description, resolved_ts, status
| filter timestamp_diff(current_time(),creation_time, "DAY") <= 7 and status not in (ENUM.NEW,
ENUM.UNDER_INVESTIGATION, "STATUS_HOLD")
| alter MTTR = divide(timestamp_diff(resolved_ts,creation_time,"MILLISECOND"),600000)//1000 * 60 = 1000 milliseconds and 60 seconds per minute
| comp avg(MTTR) as MTTR
| alter MTTR = round(MTTR)
| view graph type = gauge subtype = radial header = "MTTR" yaxis = MTTR maxscalerange = 192 scale_threshold("#12e6e6") dataunit = "minutes" default_limit = `false` headerfontsize = 30 legendfontsize = 30
```

## When to use

Cortex XSIAM SOC Value Metrics - Custom XQL Widget. XQL pattern, filtered on `timestamp_diff(current_time(),creation_time, "DAY") <= 7 and status not in (ENUM.NEW,`. Uses stages: `dataset`, `fields`, `filter`, `alter`, `comp`, `view`.

## Variations

_(No variations are documented for this entry.)_
