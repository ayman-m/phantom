---
id: XQL-256-3e221592
title: Last 5 users who performed suspicious storage activities.
category: investigation
dataset: cloud_audit_logs
tags:
  - filter
  - comp
  - sort
  - limit
  - cloud_audit_logs
  - source:dataset
---

# Last 5 users who performed suspicious storage activities.

**Dataset**: `cloud_audit_logs`

```sql
// Cloud provider - GCP
// Cloud component - Storage
config case_sensitive = false 
| dataset = cloud_audit_logs // Query the normalized cloud audit logs table
| filter resource_type = CloudStorage and operation_name_orig in ("storage.setIamPermissions","storage.buckets.delete","storage.buckets.update","storage.buckets.create") // Query for suspicious storage actions
| comp count(_time) as LeastUsers by identity_name // Count the users that made the actions and sort for the least 5
| sort asc LeastUsers 
| limit 5
```

## When to use

Displays last 5 users who performed suspicious storage activities.

## Variations

_(No variations are documented for this entry.)_
