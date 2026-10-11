---
id: XQL-296-5f344456
title: New API Key Created
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

# New API Key Created

**Dataset**: `management_auditing`

```sql
dataset = management_auditing
| filter subtype = "Add New Key"
| alter apiKeyID=arrayindex(regextract(description ,"ID\s(\d+)\swas"),0)
| fields _time, user_name , subtype , apiKeyID ,description,*
| sort desc _time
```

## When to use

Finds all the created API keys, and shows who created that API key, when, and what role is accosiated with that key

## Variations

_(No variations are documented for this entry.)_
