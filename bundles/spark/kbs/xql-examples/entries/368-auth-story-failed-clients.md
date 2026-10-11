---
id: XQL-368-e0bb2a79
title: Auth Story Failed Clients
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

# Auth Story Failed Clients

**Dataset**: `authentication_story`

```sql
preset = authentication_story
| filter auth_outcome = "FAILURE"
| comp count(auth_client) as failed_count by auth_client
| sort desc failed_count
| limit 5
```

## When to use

Lists the top 5 clients failing to authenticate

## Variations

_(No variations are documented for this entry.)_
