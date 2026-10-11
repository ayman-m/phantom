---
id: XQL-452-7df4d824
title: AWS | Users Creating Access Keys for Different Users
category: investigation
dataset: amazon_aws_raw
tags:
  - filter
  - alter
  - fields
  - amazon_aws_raw
  - source:dataset
---

# AWS | Users Creating Access Keys for Different Users

**Dataset**: `amazon_aws_raw`

```sql
dataset = amazon_aws_raw
| filter eventName = "CreateAccessKey"
| alter userName = userIdentity -> userName,targetUserName = requestParameters -> userName
| filter userName != targetUserName
| fields _time , recipientAccountId, eventName , userIdentity ,  sourceIPAddress ,eventID, userAgent , eventSource , requestParameters , responseElements , errorCode, *
```

## When to use

Lists the AWS users who created a new ASW secret acces key and corresponding AWS access key ID for another specified user

## Variations

_(No variations are documented for this entry.)_
