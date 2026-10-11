---
id: XQL-173-1c5bc355
title: Errored Data Sources
category: investigation
dataset: collection_auditing
tags:
  - filter
  - comp
  - collection_auditing
  - source:dataset
---

# Errored Data Sources

**Dataset**: `collection_auditing`

```sql
dataset = collection_auditing
| filter (classification = """Error""" )
| comp latest(_time) by collector_type , instance , classification ,description
```

## When to use

Errored Data Sources. Queries the `collection_auditing` dataset directly, filtered on `(classification = """Error""" )`. Uses stages: `filter`, `comp`.

## Variations

_(No variations are documented for this entry.)_
