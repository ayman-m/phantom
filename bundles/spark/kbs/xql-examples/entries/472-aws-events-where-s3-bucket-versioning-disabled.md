---
id: XQL-472-06e34eb5
title: AWS | Events where S3 Bucket Versioning Disabled
category: investigation
dataset: amazon_aws_raw
tags:
  - filter
  - alter
  - fields
  - amazon_aws_raw
  - source:dataset
---

# AWS | Events where S3 Bucket Versioning Disabled

**Dataset**: `amazon_aws_raw`

```sql
dataset = amazon_aws_raw
| filter eventName contains "PutBucketVersioning"
| alter Status = json_extract_scalar(requestParameters, "$.VersioningConfiguration.Status")
| filter Status = "Suspended"
| fields _time , recipientAccountId, eventName, userIdentity,  sourceIPAddress ,eventID, userAgent , eventSource , requestParameters ,Status, responseElements , errorCode, *
```

## When to use

Lists the events where the settings in the S3 buckets were changed so that the bucket object versioning was disabled

## Variations

_(No variations are documented for this entry.)_
