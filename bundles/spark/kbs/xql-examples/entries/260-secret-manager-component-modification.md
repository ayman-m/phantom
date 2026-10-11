---
id: XQL-260-199a6936
title: Secret Manager component modification
category: investigation
dataset: cloud_audit_logs
tags:
  - filter
  - cloud_audit_logs
  - source:dataset
---

# Secret Manager component modification

**Dataset**: `cloud_audit_logs`

```sql
// Cloud provider - Any
// Cloud component - Secret
dataset = cloud_audit_logs |
filter operation_name_orig contains "secret" and (operation_name = Delete or operation_name = Create or operation_name = Modify or operation_name = Put) // Filter the logs for action on the secrets component
```

## When to use

Displays modification actions performed on the Secret Manager component.

## Variations

_(No variations are documented for this entry.)_
