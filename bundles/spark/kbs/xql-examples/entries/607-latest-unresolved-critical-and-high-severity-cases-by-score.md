---
id: XQL-607-416880e3
title: Latest Unresolved Critical and High Severity Cases by Score


category: investigation
dataset: cases
tags:
  - filter
  - fields
  - sort
  - cases
  - source:dataset
---

# Latest Unresolved Critical and High Severity Cases by Score



**Dataset**: `cases`

```sql
dataset = cases
| filter xdm.case.platform_severity in("CRITICAL", "HIGH") and xdm.case.status_progress not contains "RESOLVED"
| fields xdm.case.id , xdm.case.platform_severity, xdm.case.status_progress , xdm.case.description  , _insert_time, xdm.case.score, xdm.case.assigned_to , *
| sort desc xdm.case.score
```

## When to use

Lists the most recent high severity cases with the highest score

## Variations

_(No variations are documented for this entry.)_
