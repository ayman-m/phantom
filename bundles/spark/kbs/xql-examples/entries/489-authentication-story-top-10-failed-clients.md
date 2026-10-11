---
id: XQL-489-74655ac3
title: Authentication Story Top 10 Failed Clients
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

# Authentication Story Top 10 Failed Clients

**Dataset**: `authentication_story`

```sql
preset = authentication_story
| filter auth_outcome = "FAILURE"
| comp count(auth_client) as failed_count by auth_client
| sort desc failed_count
| limit 10
```

## When to use

Lists the top 10 clients that failed to authenticate in the authentication_story preset

## Variations

_(No variations are documented for this entry.)_
