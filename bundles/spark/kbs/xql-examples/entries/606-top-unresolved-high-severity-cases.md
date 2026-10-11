---
id: XQL-606-12a55a68
title: Top Unresolved High Severity Cases
category: investigation
dataset: cases
tags:
  - filter
  - fields
  - cases
  - source:dataset
---

# Top Unresolved High Severity Cases

**Dataset**: `cases`

```sql
dataset = cases
| filter xdm.case.platform_severity in("CRITICAL", "HIGH") and xdm.case.status_progress not contains "RESOLVED"
| fields xdm.case.id , xdm.case.platform_severity, xdm.case.status_progress , xdm.case.description  , _insert_time, xdm.case.score, xdm.case.assigned_to , *
```

## When to use

Filters for high/critical cases that requires immediate action

## Variations

_(No variations are documented for this entry.)_
