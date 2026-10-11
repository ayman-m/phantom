---
id: XQL-257-ae4502d1
title: Cloud bucket listing actions
category: investigation
dataset: cloud_audit_logs
tags:
  - filter
  - comp
  - cloud_audit_logs
  - source:dataset
---

# Cloud bucket listing actions

**Dataset**: `cloud_audit_logs`

```sql
// Cloud provider - GCP
// Cloud component - Storage
config case_sensitive = false 
| dataset = cloud_audit_logs // Query the normalized cloud audit logs table
| filter resource_type = CloudStorage and operation_name_orig in ("storage.buckets.list","storage.buckets.listChannels") // filter the events for bucket listing
| comp count(_time) as BucketListing by identity_name // count the number of listing performed by a user
```

## When to use

Displays the cloud storage bucket activity sorted by the number of events performed by a user.

## Variations

_(No variations are documented for this entry.)_
