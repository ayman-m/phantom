---
id: XQL-258-b6afc963
title: Cloud storage activities
category: investigation
dataset: cloud_audit_logs
tags:
  - filter
  - cloud_audit_logs
  - source:dataset
---

# Cloud storage activities

**Dataset**: `cloud_audit_logs`

```sql
// Cloud provider - AWS
// Cloud component - Storage
config case_sensitive = false 
| dataset = cloud_audit_logs // Query the normalized cloud audit logs table
| filter resource_type = CloudStorage and operation_name_orig in ("PutBucketAcl","PutBucketPublicAccessBlock","CompleteMultipartUpload","CreateEnvironment","PutObjectAcl","PutObject","PutBucketVersioning","CreateMultipartUpload","CopyObject","PutBucketLogging","DeleteBucketPolicy","CreateBucket","DeleteBucket","UploadPart","PutBucketEncryption","DeleteObjects") // Query for suspicious storage actions
```

## When to use

Displays storage activities that can indicate suspicious behaviours.

## Variations

_(No variations are documented for this entry.)_
