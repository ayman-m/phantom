---
id: XQL-453-6351dde0
title: AWS | Users Creating Login Profiles for Different Users
category: investigation
dataset: amazon_aws_raw
tags:
  - filter
  - alter
  - fields
  - amazon_aws_raw
  - source:dataset
---

# AWS | Users Creating Login Profiles for Different Users

**Dataset**: `amazon_aws_raw`

```sql
dataset = amazon_aws_raw
| filter eventName = "CreateLoginProfile"
| alter userIdentity_arn = userIdentity -> arn,targetUserName = requestParameters -> userName
| filter userIdentity_arn not contains targetUserName
| fields userIdentity_arn, targetUserName , requestID, requestParameters, recipientAccountId, responseElements , *
```

## When to use

Lists the events of users who created login passwords for another user

## Variations

_(No variations are documented for this entry.)_
