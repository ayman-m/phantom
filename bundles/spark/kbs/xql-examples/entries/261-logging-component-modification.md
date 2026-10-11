---
id: XQL-261-549a1437
title: Logging component modification
category: investigation
dataset: cloud_audit_logs
tags:
  - filter
  - cloud_audit_logs
  - source:dataset
---

# Logging component modification

**Dataset**: `cloud_audit_logs`

```sql
// Cloud provider - AWS
// Cloud component - Logging
dataset = cloud_audit_logs 
| filter operation_name_orig in ("StopLogging","UpdateTrail","DeleteTrail") // Query for suspicious activities in the logging component
```

## When to use

Displays suspicious activities performed in the Logging component.

## Variations

_(No variations are documented for this entry.)_
