---
id: XQL-084-9fb16aaa
title: Cortex XSIAM SOC Value Metrics - Custom XQL Widget
category: investigation
dataset: xsiam_playbookmetrics_raw
tags:
  - alter
  - arrayexpand
  - comp
  - dedup
  - fields
  - filter
  - join
  - sort
---

# Cortex XSIAM SOC Value Metrics - Custom XQL Widget

**Dataset**: `xsiam_playbookmetrics_raw`

```sql
dataset = xsiam_playbookmetrics_raw
| alter Tasks = Tasks->[]
| arrayexpand Tasks
// TODO apply a datamodel to these two objects instead (Tasks and Alert)
| alter
taskState = tasks->state,
taskType = tasks->type,
taskId = tasks->id,
taskName = tasks->name,
scriptID = tasks->scriptId,
incidentID = alert->parentXDRIncident,
alertID = alert->id,
alertName = alert->name,
alertType = alert->type,
playbookId = alert->playbookId
| filter taskType not in ("start", "title", "condition")
| filter playbookId != ""
// Since the job which posts this data runs every 15 min there may be duplicate data the more frequent it is run
| alter dedupkey = concat(incidentID,taskId, alertID )
| dedup dedupkey
// Filter for just automation
//| filter alerttype != "Unclassified"
| filter taskState = "Completed"
| filter tasktype = "regular"
| alter ScriptID  =  if ( scriptID  ~= "^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89abAB][0-9a-f]{3}-[0-9a-f]{12}$", "Custom", ScriptID )
//TODO make this a lookup table and join instead to make it scalable
| join type = inner (dataset = value_tags
| fields Category as value_category, ScriptID as value_scriptid, `Tag` as value_tag, TaskName as value_taskname, Time as value_time, PlaybookID as playbook_id
) as vt (scriptID contains vt.value_scriptid)
| fields value_category, value_scriptid, value_tag, value_taskname, value_time, _time, playbook_id
| filter ((value_time != null and value_time != """"""))
| filter ((value_scriptid != null and value_scriptid != """"""))
| fields value_time , value_category
| alter soc_event_mintutes = to_integer(value_time )
| comp sum(soc_event_mintutes) as total_soc_minutes by value_category
| alter total_soc_hours = round(divide(total_soc_minutes,60))
| sort desc total_soc_minutes
| view graph type = column subtype = grouped layout = horizontal show_callouts = `true` xaxis = value_category yaxis = total_soc_minutes,total_soc_hours seriescolor("total_soc_minutes","#c1ce17") seriescolor("total_soc_hours","#ca79e4") xaxistitle = "Time" yaxistitle = "Category" seriestitle("total_soc_minutes","Total SOC Minutes") seriestitle("total_soc_hours","Total SOC Hours")
```

## When to use

Cortex XSIAM SOC Value Metrics - Custom XQL Widget. Queries the `xsiam_playbookmetrics_raw` dataset directly, filtered on `taskType not in ("start", "title", "condition")`. Uses stages: `alter`, `arrayexpand`, `filter`, `dedup`, `join`, `fields`.

## Variations

_(No variations are documented for this entry.)_
