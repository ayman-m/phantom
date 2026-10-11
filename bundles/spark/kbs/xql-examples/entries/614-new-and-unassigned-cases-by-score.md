---
id: XQL-614-2d624ec7
title: New and Unassigned Cases by Score
category: investigation
dataset: cases
tags:
  - filter
  - sort
  - cases
  - source:dataset
---

# New and Unassigned Cases by Score

**Dataset**: `cases`

```sql
dataset = cases
| filter xdm.case.assigned_to=null and xdm.case.status_progress="New"
| sort desc xdm.case.score
```

## When to use

Lists new and unresolved cases by their score

## Variations

_(No variations are documented for this entry.)_
