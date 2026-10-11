---
id: XQL-174-f566e3f9
title: Data source collector instance is in error state
category: investigation
dataset: collection_auditing
tags:
  - filter
  - comp
  - collection_auditing
  - source:dataset
---

# Data source collector instance is in error state

**Dataset**: `collection_auditing`

```sql
//Alert on when any data source collector instance is in error state.
dataset = collection_auditing
| filter (classification = """Error""" )
| comp latest(_time) by collector_type , instance , classification ,description
```

## When to use

Data source collector instance is in error state. Queries the `collection_auditing` dataset directly, filtered on `(classification = """Error""" )`. Uses stages: `filter`, `comp`.

## Variations

_(No variations are documented for this entry.)_
