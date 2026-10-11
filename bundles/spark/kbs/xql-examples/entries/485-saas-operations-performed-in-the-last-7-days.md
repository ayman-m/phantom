---
id: XQL-485-e917a850
title: SaaS Operations Performed in the Last 7 Days
category: investigation
dataset: saas_audit_logs
tags:
  - config
  - comp
  - fields
  - saas_audit_logs
  - source:dataset
---

# SaaS Operations Performed in the Last 7 Days

**Dataset**: `saas_audit_logs`

```sql
config timeframe = 7d
| dataset = saas_audit_logs
| comp count_distinct(operation_name) by operation_name
| fields operation_name, *
```

## When to use

Lists the number of distinct operations in SaaS environments performed by the name of the operation in the Last 7 Days

## Variations

_(No variations are documented for this entry.)_
