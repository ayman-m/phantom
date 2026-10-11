---
id: XQL-266-beae8cab
title: Finds activities performed by a key/credentials
category: investigation
dataset: cloud_audit_logs
tags:
  - filter
  - dedup
  - fields
  - sort
  - cloud_audit_logs
  - source:dataset
---

# Finds activities performed by a key/credentials

**Dataset**: `cloud_audit_logs`

```sql
// Investigation - find what actions/operations were executed by a specific key/credentials
// Change the <KEY_ID> value
dataset = cloud_audit_logs 
| filter identity_orig contains "<KEY_ID>"
| dedup _time, identity_name , identity_invoked_by_name, caller_ip, caller_ip_geolocation, operation_name_orig, operation_status, resource_type  
| fields _time, identity_name , identity_invoked_by_name, caller_ip, caller_ip_geolocation, operation_name_orig, operation_status, resource_type 
| sort desc _time
```

## When to use

Displays the activities performed by a key/credentials

## Variations

_(No variations are documented for this entry.)_
