---
id: XQL-610-ef97f907
title: Unresolved Cases by Specified Score or Above
category: investigation
dataset: cases
tags:
  - filter
  - fields
  - cases
  - source:dataset
---

# Unresolved Cases by Specified Score or Above

**Dataset**: `cases`

```sql
dataset = cases
| filter xdm.case.score >= to_number($score) and xdm.case.status_progress not contains "RESOLVED"
| fields xdm.case.id ,xdm.case.score, xdm.case.platform_severity, xdm.case.status_progress , xdm.case.description  , _insert_time,*
```

## When to use

Filters for unresolved cases with a score equal to or above a specified threshold

## Variations

_(No variations are documented for this entry.)_
