---
id: XQL-297-7a534e2a
title: Deleted Dashboards
category: investigation
dataset: management_auditing
tags:
  - filter
  - fields
  - sort
  - management_auditing
  - source:dataset
---

# Deleted Dashboards

**Dataset**: `management_auditing`

```sql
dataset = management_auditing
| filter subtype="Delete Dashboard"
| fields _time, user_name , subtype , description,*
| sort desc _time
```

## When to use

Lists the dashboards deleted and provides the user and timestamp of the action

## Variations

_(No variations are documented for this entry.)_
