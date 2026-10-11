---
id: XQL-270-b6b9521d
title: Non human cli performing operations
category: investigation
dataset: cloud_audit_logs
tags:
  - filter
  - fields
  - comp
  - alter
  - cloud_audit_logs
  - source:dataset
---

# Non human cli performing operations

**Dataset**: `cloud_audit_logs`

```sql
// Non human CLI usage 
dataset = cloud_audit_logs 
| filter cloud_provider = AWS // filter cloud provider 
| filter identity_type != User // exclude users as they tend to work a lot with CLI 
| filter user_agent ~= ".*cli.*"
| filter identity_type != "ANONYMOUS"  // filter scanner (usually denied external access )
| fields _time,  caller_ip_geolocation, user_agent, identity_name, identity_type, operation_name_orig, operation_status 
| comp values(operation_name_orig) as operations by  caller_ip_geolocation, identity_name, identity_type, operation_status
| alter ops = arraystring(operations, ",") 
|comp values(caller_ip_geolocation) as locations by identity_name, identity_type, operation_status, ops
| fields identity_name, identity_type, operation_status, ops, locations
```

## When to use

Displays operations performed by non human cli access

## Variations

_(No variations are documented for this entry.)_
