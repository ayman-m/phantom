---
id: XQL-470-a0b06b37
title: AWS | Requests to Recover Passwords
category: investigation
dataset: amazon_aws_raw
tags:
  - filter
  - fields
  - amazon_aws_raw
  - source:dataset
---

# AWS | Requests to Recover Passwords

**Dataset**: `amazon_aws_raw`

```sql
dataset = amazon_aws_raw
| filter eventName = "PasswordRecoveryRequested"
| fields _time , recipientAccountId, eventName, userIdentity,  sourceIPAddress ,eventID, userAgent , eventSource , requestParameters , responseElements , errorCode, *
```

## When to use

Lists the events of IAM users who requested to recover their AWS console access password

## Variations

_(No variations are documented for this entry.)_
