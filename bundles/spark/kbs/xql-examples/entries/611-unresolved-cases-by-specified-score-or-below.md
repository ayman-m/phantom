---
id: XQL-611-76d2ba44
title: Unresolved Cases by Specified Score or Below
category: investigation
dataset: cases
tags:
  - filter
  - fields
  - cases
  - source:dataset
---

# Unresolved Cases by Specified Score or Below

**Dataset**: `cases`

```sql
dataset = cases
| filter xdm.case.score <= to_number($score) and xdm.case.status_progress not contains "RESOLVED"
| fields xdm.case.id , xdm.case.score, xdm.case.platform_severity, xdm.case.status_progress , xdm.case.description  , _insert_time, *
```

## When to use

Filters for unresolved cases with a score equal to or below a specified threshold

## Variations

_(No variations are documented for this entry.)_
