---
id: XQL-469-733321e6
title: AWS | EC2 Packet Capturing created
category: investigation
dataset: amazon_aws_raw
tags:
  - filter
  - fields
  - amazon_aws_raw
  - source:dataset
---

# AWS | EC2 Packet Capturing created

**Dataset**: `amazon_aws_raw`

```sql
dataset = amazon_aws_raw
| filter eventName contains "CreateTrafficMirror"
| fields _time , recipientAccountId, eventName , userIdentity ,  sourceIPAddress ,eventID, userAgent , eventSource , requestParameters , responseElements , errorCode, *
```

## When to use

Lists the events where the AWS EC2 Network Packet Capture setting was added

## Variations

_(No variations are documented for this entry.)_
