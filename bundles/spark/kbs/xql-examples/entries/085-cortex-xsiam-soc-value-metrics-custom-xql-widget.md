---
id: XQL-085-9fb16aaa
title: Cortex XSIAM SOC Value Metrics - Custom XQL Widget
category: investigation
dataset: incidents
tags:
  - alter
  - comp
  - fields
  - filter
  - join
  - view
---

# Cortex XSIAM SOC Value Metrics - Custom XQL Widget

**Dataset**: `incidents`

```sql
dataset = incidents
| fields incident_id, creation_time, description , severity
//| filter timestamp_diff(current_time(),creation_time, "DAY") <= 1
| filter severity  in (ENUM.CRITICAL,ENUM.HIGH,ENUM.MEDIUM )
| join (
    dataset = alerts
    | fields _time , incident_id as inc_id
    ) as alert_table
    alert_table.inc_id = incident_id
| comp max(_time ) as event_time by incident_id, creation_time
| alter MTTD = divide(timestamp_diff(creation_time,event_time,"MILLISECOND"),60000) //1000 * 60 = 1000 milliseconds and 60 seconds per minute
| alter MTTD = if(MTTD<0, 0, MTTD)
| comp avg(MTTD) as MTTD
| view graph type = gauge subtype = radial header = "MTTD" yaxis = MTTD maxscalerange = 20 scale_threshold("#8ad036","#e5832c","7","#df3016","10") dataunit = "minutes" headcolor = "rgba(245,243,243,0.99)" headerfontsize = 30 legendfontsize = 30
```

## When to use

Cortex XSIAM SOC Value Metrics - Custom XQL Widget. Queries the `incidents` dataset directly, filtered on `timestamp_diff(current_time(),creation_time, "DAY") <= 1`. Uses stages: `fields`, `filter`, `join`, `comp`, `alter`, `view`.

## Variations

_(No variations are documented for this entry.)_
