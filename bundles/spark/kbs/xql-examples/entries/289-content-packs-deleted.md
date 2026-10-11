---
id: XQL-289-c0711568
title: Content Packs Deleted
category: investigation
dataset: management_auditing
tags:
  - filter
  - fields
  - sort
  - management_auditing
  - source:dataset
---

# Content Packs Deleted

**Dataset**: `management_auditing`

```sql
dataset = management_auditing 
| filter subtype="Delete - ContentPack"
| fields _time, subtype , description  , user_name , email,*
| sort desc _time
```

## When to use

Identifies the content packs deleted and includes relevant details, such as the user, timestamp, and description

## Variations

_(No variations are documented for this entry.)_
