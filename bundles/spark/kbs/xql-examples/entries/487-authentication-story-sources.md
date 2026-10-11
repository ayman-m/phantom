---
id: XQL-487-5bde1fe9
title: Authentication Story Sources
category: investigation
dataset: authentication_story
tags:
  - preset
  - comp
  - arrayexpand
  - authentication_story
  - source:preset
---

# Authentication Story Sources

**Dataset**: `authentication_story`

```sql
preset = authentication_story
| comp values(associated_products) as sources
| arrayexpand sources
```

## When to use

Lists the sources (associated_products) for the authentication_story preset

## Variations

_(No variations are documented for this entry.)_
