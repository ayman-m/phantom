---
id: XQL-298-91789324
title: New Dashboards Created
category: investigation
dataset: management_auditing
tags:
  - filter
  - fields
  - sort
  - management_auditing
  - source:dataset
---

# New Dashboards Created

**Dataset**: `management_auditing`

```sql
dataset = management_auditing
| filter subtype="Create New Dashboard"
| fields _time, user_name , subtype , description,*
| sort desc _time
```

## When to use

Lists the new dashboards created, and provides the user and timestamp of the action

## Variations

_(No variations are documented for this entry.)_
