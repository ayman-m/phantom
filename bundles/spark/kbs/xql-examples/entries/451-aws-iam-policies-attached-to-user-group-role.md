---
id: XQL-451-7c9dabc5
title: AWS | IAM Policies Attached to User/Group/Role
category: investigation
dataset: amazon_aws_raw
tags:
  - filter
  - fields
  - amazon_aws_raw
  - source:dataset
---

# AWS | IAM Policies Attached to User/Group/Role

**Dataset**: `amazon_aws_raw`

```sql
dataset = amazon_aws_raw
| filter eventName ~= "Attach\w+Policy$"
| fields _time , recipientAccountId, eventName , userIdentity ,  sourceIPAddress ,  eventID   , userAgent , eventSource , requestParameters , responseElements , errorCode, *
```

## When to use

Lists the IAM Policies that were attached to a user/group/role

## Variations

_(No variations are documented for this entry.)_
