---
id: XQL-267-3a43a586
title: Operations performed by identity out of the cloud environment
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

# Operations performed by identity out of the cloud environment

**Dataset**: `cloud_audit_logs`

```sql
// Operations performed by a identity using public access (public = out of the cloud environment)
// Cloud Provider - AWS
// Cloud Component - Storage
dataset = cloud_audit_logs 
| filter cloud_provider = "AWS" // filter cloud provider
| filter resource_type = "CLOUD_STORAGE" // filter different resouce type such as sotage, compute, DB, etc. 
| filter caller_ip !~= "^10.+|^172.+" // filter private IPs 
| filter caller_ip_asn_org !~= "^AMAZON.+|GOOGLE|^MICROSOFT.*" //filter IPs from outside of the cloud account 
| filter operation_status = "SUCCESS"
| fields  caller_ip, identity_name, identity_type, identity_invoked_by_name, operation_name_orig, referenced_resource_name 
| comp values(operation_name_orig) as operations by caller_ip, identity_name, identity_type, identity_invoked_by_name, referenced_resource_name
| alter operations = arraystring(operations, ",")
| comp values(referenced_resource_name) as resources by identity_name, identity_type, identity_invoked_by_name, operations 
| fields  identity_name, identity_type, identity_invoked_by_name, operations, resources 
| alter resources = arraystring(resources, ",")
```

## When to use

Displays the operations performed on storage resources via public access

## Variations

_(No variations are documented for this entry.)_
