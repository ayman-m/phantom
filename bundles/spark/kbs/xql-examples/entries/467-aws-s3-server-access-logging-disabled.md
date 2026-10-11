---
id: XQL-467-ed21e4c5
title: AWS | S3 Server Access Logging Disabled
category: investigation
dataset: amazon_aws_raw
tags:
  - filter
  - fields
  - amazon_aws_raw
  - source:dataset
---

# AWS | S3 Server Access Logging Disabled

**Dataset**: `amazon_aws_raw`

```sql
dataset =  amazon_aws_raw
| filter eventName = "PutBucketLogging" and requestParameters not contains "LoggingEnabled"
| fields _time , recipientAccountId, eventName , userIdentity ,  sourceIPAddress ,eventID, userAgent , eventSource , requestParameters , responseElements , errorCode, *
```

## When to use

Lists the events where the AWS S3 server access logging setting was disabled for a bucket.
Server access logging provides detailed records for the requests that are made to a bucket.

## Variations

_(No variations are documented for this entry.)_
