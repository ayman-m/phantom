---
id: XQL-473-12b06057
title: AWS | Accounts where EBS Encryption By Default Disabled
category: investigation
dataset: amazon_aws_raw
tags:
  - filter
  - fields
  - amazon_aws_raw
  - source:dataset
---

# AWS | Accounts where EBS Encryption By Default Disabled

**Dataset**: `amazon_aws_raw`

```sql
dataset = amazon_aws_raw
| filter eventName = "DisableEbsEncryptionByDefault"
| fields _time , recipientAccountId, eventName , userIdentity ,  sourceIPAddress ,eventID, userAgent , eventSource , requestParameters , responseElements , errorCode, *
```

## When to use

Lists the events, where EBS encryption by default to a specifiec account, was disabled

## Variations

_(No variations are documented for this entry.)_
