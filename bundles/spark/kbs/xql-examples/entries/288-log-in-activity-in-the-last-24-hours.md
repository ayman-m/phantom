---
id: XQL-288-fb415026
title: Log in Activity in the Last 24 Hours
category: investigation
dataset: management_auditing
tags:
  - config
  - filter
  - fields
  - sort
  - management_auditing
  - source:dataset
---

# Log in Activity in the Last 24 Hours

**Dataset**: `management_auditing`

```sql
config timeframe = 24H 
| dataset = management_auditing 
| filter subtype="Login"
| fields _time , subtype , user_name , user_roles , source_ip ,email , user_agent,*
| sort desc _time
```

## When to use

Displays the users who performed a log in within the last 24 hours and includes the user information, source IP, and timestamp

## Variations

_(No variations are documented for this entry.)_
