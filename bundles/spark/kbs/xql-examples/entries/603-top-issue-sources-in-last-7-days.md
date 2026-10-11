---
id: XQL-603-bcb6f286
title: Top Issue Sources in Last 7 Days
category: investigation
dataset: issues
tags:
  - config
  - comp
  - sort
  - issues
  - source:dataset
---

# Top Issue Sources in Last 7 Days

**Dataset**: `issues`

```sql
config timeframe = 7D
| dataset = issues
| comp count() as IssueSourceCount by xdm.issue.detection.method
| sort desc IssueSourceCount
```

## When to use

Counts the number of issues by Issue source in the last 7 days and displays them in descending order based on the count

## Variations

_(No variations are documented for this entry.)_
