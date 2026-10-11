---
id: XQL-468-d68e2c3e
title: AWS | Cloudwatch Alarms Deleted
category: investigation
dataset: amazon_aws_raw
tags:
  - filter
  - fields
  - amazon_aws_raw
  - source:dataset
---

# AWS | Cloudwatch Alarms Deleted

**Dataset**: `amazon_aws_raw`

```sql
dataset = amazon_aws_raw
| filter eventName = "DeleteAlarms" and eventSource = "monitoring.amazonaws.com"
| fields _time , recipientAccountId, eventName , userIdentity ,  sourceIPAddress ,eventID, userAgent , eventSource , requestParameters , *
```

## When to use

Lists the events where the AWS CloudWatch alarms have been deleted

## Variations

_(No variations are documented for this entry.)_
