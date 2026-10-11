---
id: XQL-130-563d6d47
title: Cortex XSIAM NGFW/Corelight - Custom XQL Widget
category: investigation
dataset: panw_ngfw_threat_raw
tags:
  - alter
  - bin
  - comp
  - fields
  - sort
  - view
---

# Cortex XSIAM NGFW/Corelight - Custom XQL Widget

**Dataset**: `panw_ngfw_threat_raw`

```sql
//Title: NGFW Threats Over Time
//Description: Intended to be used as an XDR Widget to highlight threats over time derived from Pan_Threat logs.
//Dataset: panw_ngfw_threat_raw
//Requirements: PA NGFW Threat Logs, PRO enabled
//Tags: graph,NGFW,noAPI,PANWOpen
//Disable case sensitivity, last 30 days
 dataset = panw_ngfw_threat_raw
|fields _id , _time
| bin _time span = 1d
| comp count(_id) by _time
| alter date = format_timestamp("%b %d", _time)
| sort asc _time
| view graph type = area subtype = standard show_percentage = `false` xaxis = date yaxis = count_1 headerfontsize = 16 legend = `false`
```

## When to use

Cortex XSIAM NGFW/Corelight - Custom XQL Widget. XQL pattern. Uses stages: `fields`, `bin`, `comp`, `alter`, `sort`, `view`.

## Variations

_(No variations are documented for this entry.)_
