---
id: XQL-299-40cabc14
title: New Correlation Rules Created
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

# New Correlation Rules Created

**Dataset**: `management_auditing`

```sql
dataset = management_auditing
| filter subtype = "Create" and description ~= "Correlations rule created"
| alter correlationName=arrayindex(regextract(description,"name:\s(.*?)\,"),0)
| fields _time, subtype , description , correlationName , user_name , user_roles,*
| sort desc _time
```

## When to use

Lists the new correlation rules created, and provides the correlation rule name, user information, and timestamp

## Variations

_(No variations are documented for this entry.)_
