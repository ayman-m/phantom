---
id: XQL-370-d1669dfb
title: Users Identified on Specific Host in Last Month
category: investigation
dataset: authentication_story
tags:
  - config
  - preset
  - filter
  - dedup
  - fields
  - authentication_story
  - source:preset
---

# Users Identified on Specific Host in Last Month

**Dataset**: `authentication_story`

```sql
config timeframe = 30d case_sensitive = false |
preset = authentication_story |
filter auth_client  = $host and auth_identity != null |
dedup auth_identity |
fields auth_identity , auth_client , action_local_ip , action_remote_ip
```

## When to use

Lists all the distinct users that were identified on a specific host in the last month

## Variations

_(No variations are documented for this entry.)_
