---
id: XQL-156-e9fc23f7
title: Cortex XSIAM Cisco Umbrella DNS - Custom XQL Widget
category: investigation
dataset: cisco_umbrella_raw
tags:
  - bin
  - comp
  - sort
  - view
---

# Cortex XSIAM Cisco Umbrella DNS - Custom XQL Widget

**Dataset**: `cisco_umbrella_raw`

```sql
dataset = cisco_umbrella_raw
| bin _time span =1h
| sort asc  _time
| comp count(_collection_timestamp ) as counter by _time
| view graph type = line xaxis = _time yaxis = counter seriescolor("counter","#30ec01") legend = `false`
```

## When to use

Cortex XSIAM Cisco Umbrella DNS - Custom XQL Widget. Queries the `cisco_umbrella_raw` dataset directly. Uses stages: `bin`, `sort`, `comp`, `view`.

## Variations

_(No variations are documented for this entry.)_
