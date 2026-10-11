---
id: XQL-462-b9258ca7
title: AWS | RDS Instances Made Publicly Accessible
category: investigation
dataset: amazon_aws_raw
tags:
  - filter
  - alter
  - fields
  - amazon_aws_raw
  - source:dataset
---

# AWS | RDS Instances Made Publicly Accessible

**Dataset**: `amazon_aws_raw`

```sql
dataset = amazon_aws_raw
| filter eventName = "ModifyDBInstance"
| alter publiclyAccessible = json_extract_scalar(requestParameters, "$.publiclyAccessible")
| filter publiclyAccessible = "true"
| fields _time , recipientAccountId, eventName , userIdentity ,  sourceIPAddress ,eventID, userAgent , eventSource , requestParameters , responseElements , errorCode, *
```

## When to use

Lists the events where the changes in RDS made them publicly accessible from the internet

## Variations

_(No variations are documented for this entry.)_
