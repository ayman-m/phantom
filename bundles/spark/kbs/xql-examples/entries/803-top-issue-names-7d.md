---
id: XQL-803-f5dceaed
title: Top issue names (7d)
category: investigation
dataset: issues
tags:
  - filter
  - comp
  - sort
  - limit
  - issues
  - xdm
---

# Top issue names (7d)

**Dataset**: `issues`

```sql
config timeframe = 7d
| dataset = issues
| comp count() as cnt by xdm.issue.name
| sort desc cnt
| limit 10
```

## When to use

Top issue names via XDM-normalized schema (xdm.issue.name).

## Variations

_(No variations are documented for this entry.)_
