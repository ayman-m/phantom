---
id: XQL-328-58faee20
title: Collectors in Error State
category: investigation
dataset: collection_auditing
tags:
  - filter
  - comp
  - collection_auditing
  - source:dataset
---

# Collectors in Error State

**Dataset**: `collection_auditing`

```sql
dataset = collection_auditing
| filter classification = "Error"
| comp latest(_time) by collector_type , instance , classification ,description
```

## When to use

Lists the data collectors in an error state and includes the latest timestamp and description of the issue to help identify malfunctioning data collectors in need of attention

## Variations

_(No variations are documented for this entry.)_
