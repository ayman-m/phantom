---
id: XQL-463-da6937ac
title: AWS | MFA Devices Removed or Disabled
category: investigation
dataset: amazon_aws_raw
tags:
  - filter
  - fields
  - amazon_aws_raw
  - source:dataset
---

# AWS | MFA Devices Removed or Disabled

**Dataset**: `amazon_aws_raw`

```sql
dataset = amazon_aws_raw
| filter eventName= "DeleteVirtualMFADevice" OR eventName="DeactivateMFADevice"
| fields _time , recipientAccountId, eventName , userIdentity ,  sourceIPAddress ,eventID, userAgent , eventSource , requestParameters , responseElements , errorCode, *
```

## When to use

Lists events where the AWS Multi-Factor Authentication (MFA) device was removed, and as a result the MFA was disabled.

## Variations

_(No variations are documented for this entry.)_
