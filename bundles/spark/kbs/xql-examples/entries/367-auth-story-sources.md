---
id: XQL-367-23f30ad2
title: Auth Story Sources
category: investigation
dataset: authentication_story
tags:
  - preset
  - comp
  - arrayexpand
  - authentication_story
  - source:preset
---

# Auth Story Sources

**Dataset**: `authentication_story`

```sql
preset = authentication_story
| comp values(associated_products) as sources
| arrayexpand sources
```

## When to use

Lists all sources that feed the auth_story preset

## Variations

_(No variations are documented for this entry.)_
