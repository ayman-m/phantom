---
id: XQL-172-c918f651
title: TimeStamp - Example 1
category: investigation
dataset: endpoints
tags:
  - config
  - alter
  - fields
  - endpoints
  - source:dataset
---

# TimeStamp - Example 1

**Dataset**: `endpoints`

```sql
config timeframe  = 1M | 
dataset = endpoints | 
alter test_field="1709040000000" | fields test_field | alter new_time = to_timestamp(to_integer(test_field), "MILLIS") | fields test_field , new_time
```

## When to use

TimeStamp - Example 1. Queries the `endpoints` dataset directly. Uses stages: `config`, `alter`, `fields`.

## Variations

_(No variations are documented for this entry.)_
