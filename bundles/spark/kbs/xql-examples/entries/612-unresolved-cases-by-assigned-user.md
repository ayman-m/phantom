---
id: XQL-612-87d64152
title: Unresolved Cases by Assigned User
category: investigation
dataset: cases
tags:
  - filter
  - fields
  - cases
  - source:dataset
---

# Unresolved Cases by Assigned User

**Dataset**: `cases`

```sql
dataset = cases
| filter xdm.case.assigned_to in ($assigned_user) and xdm.case.status_progress not contains "RESOLVED"
| fields xdm.case.id , xdm.case.platform_severity, xdm.case.status_progress, xdm.case.score, xdm.case.assigned_to , xdm.case.description  , _insert_time,*
```

## When to use

Lists unresolved cases that are assigned to a specified user

## Variations

_(No variations are documented for this entry.)_
