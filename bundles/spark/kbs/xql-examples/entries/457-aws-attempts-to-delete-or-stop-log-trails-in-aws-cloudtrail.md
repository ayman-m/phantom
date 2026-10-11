---
id: XQL-457-38fd58ef
title: AWS | Attempts to Delete or Stop Log Trails in AWS CloudTrail
category: investigation
dataset: amazon_aws_raw
tags:
  - filter
  - fields
  - amazon_aws_raw
  - source:dataset
---

# AWS | Attempts to Delete or Stop Log Trails in AWS CloudTrail

**Dataset**: `amazon_aws_raw`

```sql
dataset = amazon_aws_raw
| filter eventName in ("DeleteTrail","StopLogging") and eventSource = "cloudtrail.amazonaws.com"
| fields _time , recipientAccountId, eventName , userIdentity ,  sourceIPAddress ,eventID, userAgent , eventSource , requestParameters , responseElements , errorCode, *
```

## When to use

Lists the events where users deleted or stopped the Amazon CloudTrail trail

## Variations

_(No variations are documented for this entry.)_
