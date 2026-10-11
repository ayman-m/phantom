---
id: XQL-105-ee730375
title: Cortex XSIAM DNS Activity - Custom XQL Widget
category: investigation
tags:
  - alter
  - bin
  - comp
  - filter
  - sort
  - view
---

# Cortex XSIAM DNS Activity - Custom XQL Widget

**Dataset**: `(none)`

```sql
preset = network_story
| bin _time span =1h
| sort asc  _time
| alter app = lowercase(arraystring(action_app_id_transitions,","))
| filter app contains "dns"
| comp count(event_id ) as counter by _time
| view graph type = line xaxis = _time yaxis = counter default_limit = `false` seriescolor("counter","#ec9d7c") seriestitle("counter","DNS Queries")
```

## When to use

Cortex XSIAM DNS Activity - Custom XQL Widget. Queries the `(none)` preset, filtered on `app contains "dns"`. Uses stages: `bin`, `sort`, `alter`, `filter`, `comp`, `view`.

## Variations

_(No variations are documented for this entry.)_
