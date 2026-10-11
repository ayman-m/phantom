---
id: XQL-456-7c97c67a
title: AWS | Attempts to Delete Log Groups in AWS CloudWatch
category: investigation
dataset: amazon_aws_raw
tags:
  - filter
  - fields
  - amazon_aws_raw
  - source:dataset
---

# AWS | Attempts to Delete Log Groups in AWS CloudWatch

**Dataset**: `amazon_aws_raw`

```sql
dataset = amazon_aws_raw
| filter eventName = "DeleteLogGroup"
| fields _time , recipientAccountId, eventName , userIdentity ,  sourceIPAddress ,eventID, userAgent , eventSource , requestParameters , responseElements , errorCode, *
```

## When to use

Lists the events where users deleted the Amazon CloudWatch Log Group and deleted the archived logs

## Variations

_(No variations are documented for this entry.)_
