---
id: XQL-295-242f5dff
title: New Roles Created
category: investigation
dataset: management_auditing
tags:
  - filter
  - fields
  - management_auditing
  - source:dataset
---

# New Roles Created

**Dataset**: `management_auditing`

```sql
dataset = management_auditing
| filter subtype="Role Created"
| fields _time , user_name , user_roles ,description,*
```

## When to use

Identifies the new roles created and the user who created them

## Variations

_(No variations are documented for this entry.)_
