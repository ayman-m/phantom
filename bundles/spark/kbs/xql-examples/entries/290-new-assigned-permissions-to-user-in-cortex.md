---
id: XQL-290-b3022e78
title: New assigned permissions to user in cortex
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

# New assigned permissions to user in cortex

**Dataset**: `management_auditing`

```sql
dataset = management_auditing 
| filter subtype = "User Permissions Assigned"
| alter targetUser=arrayindex(regextract(description,"(.*?)\swas"),0), newRole=arrayindex(regextract(description,"role\s(.*?)$"),0)
| fields _time, subtype , user_name , targetUser , newRole , description,* 
| sort desc _time
```

## When to use

Identifies who assigned the user permissions and to whom, and includes the new roles and relevant user information

## Variations

_(No variations are documented for this entry.)_
