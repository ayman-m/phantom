---
id: XQL-287-ab4519ac
title: Datasets Deleted
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

# Datasets Deleted

**Dataset**: `management_auditing`

```sql
dataset = management_auditing 
| filter subtype="Delete dataset"
| alter datasetName=arrayindex(regextract(description , "Dataset\s(.*?)\sof"),0), datasetType=arrayindex(regextract(description , "type\s(.*?)\swas"),0)
| fields _time , user_name , user_roles , subtype , datasetType , datasetType ,description 
| sort desc _time
```

## When to use

Identifies the datasets deleted and provides the timestamp, user who performed the action, user roles, and dataset details

## Variations

_(No variations are documented for this entry.)_
