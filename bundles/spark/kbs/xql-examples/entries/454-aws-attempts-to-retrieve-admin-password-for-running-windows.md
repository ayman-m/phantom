---
id: XQL-454-5220d408
title: AWS | Attempts to Retrieve Admin Password for Running Windows EC2 Instance
category: investigation
dataset: amazon_aws_raw
tags:
  - filter
  - alter
  - fields
  - amazon_aws_raw
  - source:dataset
---

# AWS | Attempts to Retrieve Admin Password for Running Windows EC2 Instance

**Dataset**: `amazon_aws_raw`

```sql
dataset = amazon_aws_raw
| filter eventName="GetPasswordData" and eventSource = "ec2.amazonaws.com"
| alter instanceId = requestParameters -> instanceId, principalId = userIdentity -> principalId
| fields _time , recipientAccountId, eventName , userIdentity ,  sourceIPAddress ,eventID, userAgent , eventSource , requestParameters , responseElements , errorCode, *
```

## When to use

Lists the events of Credential Access attempts to a EC2 windows instance

## Variations

_(No variations are documented for this entry.)_
