---
id: XQL-484-66da93b8
title: Count SaaS Products Accessed in the Last 7 Days
category: investigation
dataset: saas_audit_logs
tags:
  - config
  - comp
  - fields
  - saas_audit_logs
  - source:dataset
---

# Count SaaS Products Accessed in the Last 7 Days

**Dataset**: `saas_audit_logs`

```sql
config timeframe = 7d
| dataset = saas_audit_logs
| comp count_distinct(product) by product
| fields product, *
```

## When to use

Counts the number of distinct SaaS products accessed in the Last 7 Days

## Variations

_(No variations are documented for this entry.)_
