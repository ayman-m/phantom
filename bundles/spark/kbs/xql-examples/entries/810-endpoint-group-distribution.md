---
id: XQL-810-add3d68f
title: Endpoint group distribution
category: investigation
dataset: endpoints
tags:
  - filter
  - arrayexpand
  - comp
  - sort
  - limit
  - endpoints
---

# Endpoint group distribution

**Dataset**: `endpoints`

```sql
dataset = endpoints
| filter group_names != null
| arrayexpand group_names
| comp count() as cnt by group_names
| sort desc cnt
| limit 10
```

## When to use

Endpoints aggregated by group via `group_names` (the live tenant's field name) using arrayexpand for multi-value flattening.

## Variations

_(No variations are documented for this entry.)_
