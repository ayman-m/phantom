---
id: XQL-455-4c4c9cec
title: AWS | Changes to RDS Master User Password
category: investigation
dataset: amazon_aws_raw
tags:
  - filter
  - alter
  - fields
  - amazon_aws_raw
  - source:dataset
---

# AWS | Changes to RDS Master User Password

**Dataset**: `amazon_aws_raw`

```sql
dataset = amazon_aws_raw
| filter eventName = "ModifyDBInstance"
| alter masterUserPassword= json_extract_scalar(requestParameters, "$.masterUserPassword")
| filter masterUserPassword!= null
| fields _time , recipientAccountId, eventName , userIdentity ,  sourceIPAddress ,eventID, userAgent , eventSource , requestParameters , responseElements , errorCode, *
```

## When to use

Lists the events for the attempts to reset the master user password of the RDS resource

## Variations

_(No variations are documented for this entry.)_
