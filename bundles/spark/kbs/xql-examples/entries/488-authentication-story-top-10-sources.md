---
id: XQL-488-3d2b3ecb
title: Authentication Story Top 10 Sources
category: investigation
dataset: authentication_story
tags:
  - preset
  - comp
  - sort
  - limit
  - authentication_story
  - source:preset
---

# Authentication Story Top 10 Sources

**Dataset**: `authentication_story`

```sql
preset = authentication_story
| comp count() as event_count by associated_products
| sort desc event_count
| limit 10
```

## When to use

Identifies the top 10 sources for the authentication_story preset

## Variations

_(No variations are documented for this entry.)_
