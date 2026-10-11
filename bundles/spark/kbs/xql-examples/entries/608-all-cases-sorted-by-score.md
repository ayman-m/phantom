---
id: XQL-608-c93c1664
title: All Cases Sorted by Score
category: investigation
dataset: cases
tags:
  - fields
  - sort
  - cases
  - source:dataset
---

# All Cases Sorted by Score

**Dataset**: `cases`

```sql
dataset = cases
| fields xdm.case.id , xdm.case.platform_severity, xdm.case.status_progress , xdm.case.score, xdm.case.description ,_insert_time, *
| sort desc xdm.case.score
```

## When to use

Lists cases sorted by the highest score

## Variations

_(No variations are documented for this entry.)_
