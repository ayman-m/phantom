---
id: XQL-293-dcb813f7
title: Content Packs Installed
category: investigation
dataset: management_auditing
tags:
  - filter
  - fields
  - sort
  - management_auditing
  - source:dataset
---

# Content Packs Installed

**Dataset**: `management_auditing`

```sql
dataset = management_auditing 
| filter subtype="Install - ContentPack"
| fields _time, subtype , user_name , description,*
| sort desc _time
```

## When to use

Lists the new content packs installed with the user details and timestamp information

## Variations

_(No variations are documented for this entry.)_
