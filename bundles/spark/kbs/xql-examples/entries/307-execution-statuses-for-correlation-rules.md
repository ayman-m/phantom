---
id: XQL-307-fbcff66d
title: Execution Statuses for Correlation Rules
category: investigation
dataset: correlations_auditing
tags:
  - comp
  - fields
  - correlations_auditing
  - source:dataset
---

# Execution Statuses for Correlation Rules

**Dataset**: `correlations_auditing`

```sql
dataset = correlations_auditing
| comp count(), values(name) as name, values(rule_id) as rule_id  by status
| fields status , *
```

## When to use

Counts the execution statuses for correlation rules, which helps analysts track the status distribution

## Variations

_(No variations are documented for this entry.)_
