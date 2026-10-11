---
id: XQL-369-2fb7e9d0
title: Auth Story Failed Reasons
category: investigation
dataset: authentication_story
tags:
  - preset
  - filter
  - comp
  - sort
  - limit
  - authentication_story
  - source:preset
---

# Auth Story Failed Reasons

**Dataset**: `authentication_story`

```sql
preset = authentication_story
| filter auth_outcome = "FAILURE"
| comp count(auth_outcome_reason) as failed_count by auth_outcome_reason
| sort desc failed_count
| limit 5
```

## When to use

Lists the top 5 reasons for failing to authenticate

## Variations

_(No variations are documented for this entry.)_
