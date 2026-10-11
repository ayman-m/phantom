---
id: XQL-458-a9b98376
title: AWS | Attempts to Tamper with AWS Security Measures
category: investigation
dataset: amazon_aws_raw
tags:
  - filter
  - fields
  - amazon_aws_raw
  - source:dataset
---

# AWS | Attempts to Tamper with AWS Security Measures

**Dataset**: `amazon_aws_raw`

```sql
dataset = amazon_aws_raw
| filter eventName  in ("DeleteLogStream","DeleteDetector","DeleteIPSet","DeleteWebACL","DeleteRule","DeleteRuleGroup","DeleteLoggingConfiguration")
| fields _time , recipientAccountId, eventName , userIdentity ,  sourceIPAddress ,eventID, userAgent , eventSource , requestParameters , responseElements , errorCode, *
```

## When to use

Lists the events where users deleted monitoring or security components in AWS

## Variations

_(No variations are documented for this entry.)_
