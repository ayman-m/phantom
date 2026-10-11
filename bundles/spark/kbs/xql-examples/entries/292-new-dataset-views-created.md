---
id: XQL-292-9874c3e6
title: New Dataset Views Created
category: investigation
dataset: management_auditing
tags:
  - filter
  - alter
  - fields
  - sort
  - management_auditing
  - source:dataset
---

# New Dataset Views Created

**Dataset**: `management_auditing`

```sql
dataset = management_auditing 
| filter subtype = "Create Dataset View"
| alter datasetViewName=arrayindex(regextract(description,"View\s(.*?)\s"),0)
|fields _time, subtype ,user_name , datasetViewName , description,*
|sort desc _time
```

## When to use

Identifies the new dataset views created, and includes the user who created the dataset view and relevant timestamp details

## Variations

_(No variations are documented for this entry.)_
