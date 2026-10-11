---
id: XQL-471-6c7fbf21
title: AWS | Adding IAM Users to Admin Group 
category: investigation
dataset: amazon_aws_raw
tags:
  - filter
  - alter
  - fields
  - amazon_aws_raw
  - source:dataset
---

# AWS | Adding IAM Users to Admin Group 

**Dataset**: `amazon_aws_raw`

```sql
dataset = amazon_aws_raw
| filter eventName = "AddUserToGroup"
| alter groupName = json_extract_scalar(requestParameters, "$.groupName")
| filter groupName ~= "A|admin"
| fields _time , recipientAccountId, eventName, userIdentity,  sourceIPAddress ,eventID, userAgent , eventSource , groupName , requestParameters , responseElements , errorCode, *
```

## When to use

Lists the events where IAM users were added to the Admin Groups in AWS

## Variations

_(No variations are documented for this entry.)_
