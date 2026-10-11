---
id: XQL-490-6dd2c22b
title: Authentication Story Top 10 Authentication Failed Reasons
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

# Authentication Story Top 10 Authentication Failed Reasons

**Dataset**: `authentication_story`

```sql
preset = authentication_story
| filter auth_outcome = "FAILURE"
| comp count(auth_outcome_reason) as failed_count by auth_outcome_reason
| sort desc failed_count
| limit 10
```

## When to use

Lists the top 10 reasons for failing to authenticate in the authentication_story preset

## Variations

_(No variations are documented for this entry.)_
