---
id: XQL-465-d817f284
title: AWS | Multiple Failed Logins by the Same IP
category: investigation
dataset: amazon_aws_raw
tags:
  - filter
  - alter
  - comp
  - amazon_aws_raw
  - source:dataset
---

# AWS | Multiple Failed Logins by the Same IP

**Dataset**: `amazon_aws_raw`

```sql
dataset =  amazon_aws_raw
| filter eventName = "ConsoleLogin"
| alter outcome = responseElements -> ConsoleLogin , arn = userIdentity -> arn
| filter outcome = "Failure"
| comp count() as c, values(arn), values(userAgent) by sourceIPAddress, outcome, eventName
| filter c > 10
```

## When to use

Lists the events with multiple failed login attempts by the same IP events for AWS

## Variations

_(No variations are documented for this entry.)_
