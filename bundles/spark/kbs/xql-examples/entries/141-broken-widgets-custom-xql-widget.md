---
id: XQL-141-d782c07a
title: broken_widgets - Custom XQL Widget
category: investigation
dataset: incidents
tags:
  - alter
  - comp
  - filter
  - view
---

# broken_widgets - Custom XQL Widget

**Dataset**: `incidents`

```sql
dataset = incidents
| filter (status = ENUM.NEW or status = ENUM.UNDER_INVESTIGATION)
| alter starred = to_boolean(starred)
| filter starred = true
| comp count_distinct(incident_id)
| alter from_time = parse_timestamp("%Y-%m-%d %H:%M:%S ", "2024-12-06 00:00:00")
| alter to_time = parse_timestamp("%Y-%m-%d %H:%M:%S ", "2024-12-09 00:00:00")
| view graph type = single subtype = standard yaxis = count_distinct_1
```

## When to use

broken_widgets - Custom XQL Widget. Queries the `incidents` dataset directly, filtered on `(status = ENUM.NEW or status = ENUM.UNDER_INVESTIGATION)`. Uses stages: `filter`, `alter`, `comp`, `view`.

## Variations

_(No variations are documented for this entry.)_
