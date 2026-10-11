---
id: XQL-265-14577fe8
title: CreateRole operation parsed to fields
category: investigation
dataset: cloud_audit_logs
tags:
  - filter
  - cloud_audit_logs
  - source:dataset
---

# CreateRole operation parsed to fields

**Dataset**: `cloud_audit_logs`

```sql
// Cloud provider - AWS
// Cloud component - IAM
config case_sensitive = false | 
dataset = cloud_audit_logs |
filter cloud_provider = AWS and resource_type = IAM and operation_name_orig = "CreateRole" | // Filter for CreateRole actions
alter roleName = json_extract(raw_log,"$.requestParameters.roleName"), roleDescription = json_extract(raw_log,"$.requestParameters.description"), accessKeyId= json_extract(raw_log,"$.userIdentity.accessKeyId") | // Extract role name, description and access key from the raw log
fields roleName, roleDescription, identity_invoked_by_name, accessKeyId
```

## When to use

Query for the 'CreateRole' operation, which displays the role name, description, user, and access key related to the event.

## Variations

_(No variations are documented for this entry.)_
