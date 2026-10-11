---
id: XQL-613-63626711
title: Open Duration for High and Critical Cases
category: investigation
dataset: cases
tags:
  - filter
  - alter
  - fields
  - sort
  - cases
  - source:dataset
---

# Open Duration for High and Critical Cases

**Dataset**: `cases`

```sql
dataset = cases
| filter xdm.case.platform_severity in("CRITICAL", "HIGH") and xdm.case.status_progress not contains "RESOLVED"
| alter open_duration = timestamp_diff(current_time(), _insert_time, "day")
| fields xdm.case.id , xdm.case.platform_severity, xdm.case.status_progress, open_duration
| sort desc open_duration
```

## When to use

Lists unresolved cases with a high and critical severity, and details how long they have remained open in days

## Variations

_(No variations are documented for this entry.)_
