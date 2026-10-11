---
id: XQL-264-9ee09b28
title: App Service component modification
category: investigation
dataset: cloud_audit_logs
tags:
  - filter
  - comp
  - cloud_audit_logs
  - source:dataset
---

# App Service component modification

**Dataset**: `cloud_audit_logs`

```sql
// Cloud provider - Azure
// Cloud component - AppService
config case_sensitive = false | 
dataset = cloud_audit_logs |
filter cloud_provider = Azure and operation_name_orig in ("MICROSOFT.WEB/*/WRITE","MICROSOFT.WEB/*/DELETE","MICROSOFT.WEB/*/CREATE") // Filter for privileged actions on Azure App Service
| comp count(_time) as PrivilegedActions by operation_name_orig ,referenced_resource_name // Count the operations performed on App Service Resource
```

## When to use

Displays suspicious activities performed in the App Service component.

## Variations

_(No variations are documented for this entry.)_
