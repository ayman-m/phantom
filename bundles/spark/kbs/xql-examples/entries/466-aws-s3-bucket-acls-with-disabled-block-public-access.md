---
id: XQL-466-ed64c0f3
title: AWS | S3 Bucket ACLs with Disabled Block Public Access
category: investigation
dataset: amazon_aws_raw
tags:
  - filter
  - fields
  - amazon_aws_raw
  - source:dataset
---

# AWS | S3 Bucket ACLs with Disabled Block Public Access

**Dataset**: `amazon_aws_raw`

```sql
dataset =  amazon_aws_raw
| filter eventName = "BucketBlockPublicAccessDisabled"
| fields _time , recipientAccountId, eventName , userIdentity ,  sourceIPAddress ,eventID, userAgent , eventSource , requestParameters , responseElements , errorCode, *
```

## When to use

Lists the events where the AWS S3 Block Public Access was disabled for the Amazon S3 bucket, which can indicate a denial of service attack

## Variations

_(No variations are documented for this entry.)_
