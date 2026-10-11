---
id: XQL-151-0170f0b5
title: Playbook Automation - Custom XQL Widget
category: investigation
dataset: xsiam_playbookmetrics_raw
tags:
  - alter
  - bin
  - comp
  - dedup
  - filter
  - join
  - view
  - windowcomp
---

# Playbook Automation - Custom XQL Widget

**Dataset**: `xsiam_playbookmetrics_raw`

```sql
dataset = xsiam_playbookmetrics_raw
| alter
incidentID = alert->parentXDRIncident,
alertID = alert->id,
alertName = alert->name,
alertType = alert->type,
playbookId = alert->playbookId
| dedup alertID
| filter playbookId != ""
| join (dataset = playbook_mapping) as playbook_mapping playbook_mapping.PlaybookID = playbookId
| bin _time span = 10m
| alter dedupKey = concat(PlaybookName,"|",_time)
| comp count(_time) as PlaybookTotalRuns by _time
// | windowcomp count(PlaybookName) by dedupKey as PlaybookRuns
// | comp count(PlaybookName ) as PlaybookCount by PlaybookName
// | view graph type = pie xaxis = PlaybookName yaxis = PlaybookCount
| view graph type = line header = "Total Playbook Runs" xaxis = _time yaxis = PlaybookTotalRuns
```

## When to use

Playbook Automation - Custom XQL Widget. Queries the `xsiam_playbookmetrics_raw` dataset directly, filtered on `playbookId != ""`. Uses stages: `alter`, `dedup`, `filter`, `join`, `bin`, `comp`.

## Variations

_(No variations are documented for this entry.)_
