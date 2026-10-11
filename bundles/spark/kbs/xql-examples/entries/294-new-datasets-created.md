---
id: XQL-294-990fd7da
title: New Datasets Created
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

# New Datasets Created

**Dataset**: `management_auditing`

```sql
dataset = management_auditing 
| filter subtype = "Create dataset"
| alter datasetName=arrayindex(regextract(description , "Dataset\s(.*?)\sof"),0), datasetType=arrayindex(regextract(description , "type\s(.*?)\swas"),0)
| fields _time, user_name, subtype , datasetType ,datasetName , description,*
| sort desc _time
```

## When to use

Lists the new datasets created, and provides the dataset type, user information, and timestamp details

## Variations

_(No variations are documented for this entry.)_
