---
id: XQL-450-9692ea37
title: AWS | IAM Policy Changes Allowing Access to Resources
category: investigation
dataset: amazon_aws_raw
tags:
  - filter
  - alter
  - arrayexpand
  - fields
  - amazon_aws_raw
  - source:dataset
---

# AWS | IAM Policy Changes Allowing Access to Resources

**Dataset**: `amazon_aws_raw`

```sql
dataset = amazon_aws_raw
| filter eventName = "CreatePolicyVersion"
| alter policyDocument = json_extract_scalar(requestParameters, "$.policyDocument")
| filter policyDocument != null
| alter statement = json_extract_array(policyDocument , "$.Statement")
| arrayexpand statement
| alter Effect = statement -> Effect , Resource = json_extract_array(statement , "$.Resource")
| filter Effect = "Allow"
| fields _time , recipientAccountId, eventName , userIdentity , statement ,  sourceIPAddress ,  eventID   , userAgent , eventSource , requestParameters , responseElements , errorCode, statement , *
```

## When to use

Details the events with a recent policy created that allows accessing any resource

## Variations

_(No variations are documented for this entry.)_
