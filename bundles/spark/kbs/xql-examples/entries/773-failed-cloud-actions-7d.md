---
id: XQL-773-4167f150
title: Failed cloud actions (7d)
category: detection
dataset: cloud_audit_logs
tags:
  - filter
  - comp
  - sort
  - limit
  - cloud_audit_logs
  - cloud
---

# Failed cloud actions (7d)

**Dataset**: `cloud_audit_logs`

```sql
config timeframe = 7d
| dataset = cloud_audit_logs
| filter operation_status != "success"
| comp count() as cnt by cloud_provider, operation_name, operation_status
| sort desc cnt
| limit 10
```

## When to use

Failed cloud operations by provider/op/status. High failure counts on sensitive ops (DeleteRole, AssumeRole) often indicate probing or misconfig.

## Variations

_(No variations are documented for this entry.)_
