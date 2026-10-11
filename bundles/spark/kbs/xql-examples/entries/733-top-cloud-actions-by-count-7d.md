---
id: XQL-733-53a23ac6
title: Top cloud actions by count (7d)
category: investigation
dataset: cloud_audit_logs
tags:
  - filter
  - comp
  - sort
  - limit
  - cloud_audit_logs
  - cloud
---

# Top cloud actions by count (7d)

**Dataset**: `cloud_audit_logs`

```sql
config timeframe = 7d
| dataset = cloud_audit_logs
| comp count() as cnt by cloud_provider, operation_name
| sort desc cnt
| limit 10
```

## When to use

Cloud audit-log activity baseline. Reveals the most-frequent cloud operations across providers. Spikes in unusual operations (CreateUser, DeleteBucket) warrant attention.

## Variations

_(No variations are documented for this entry.)_
