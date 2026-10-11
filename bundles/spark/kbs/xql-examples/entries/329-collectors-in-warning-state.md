---
id: XQL-329-35c80f0d
title: Collectors in Warning State
category: investigation
dataset: collection_auditing
tags:
  - filter
  - comp
  - collection_auditing
  - source:dataset
---

# Collectors in Warning State

**Dataset**: `collection_auditing`

```sql
dataset = collection_auditing
| filter classification = "Warning"
| comp latest(_time) by collector_type , instance , classification ,description
```

## When to use

Lists the data collectors in a warning state to help users proactively address potential issues before they escalate to critical errors

## Variations

_(No variations are documented for this entry.)_
