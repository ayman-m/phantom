---
id: XQL-459-9b8b56bf
title: AWS | Attempts to List Image Scan Findings in AWS
category: investigation
dataset: amazon_aws_raw
tags:
  - filter
  - fields
  - amazon_aws_raw
  - source:dataset
---

# AWS | Attempts to List Image Scan Findings in AWS

**Dataset**: `amazon_aws_raw`

```sql
dataset = amazon_aws_raw
| filter eventSource="ecr.amazonaws.com" and eventName="DescribeImageScanFindings"
| fields _time , recipientAccountId, eventName , userIdentity ,  sourceIPAddress ,eventID, userAgent , eventSource , requestParameters , responseElements , errorCode, *
```

## When to use

Lists the events where users were trying to list vulnerability findings of existing images within the ECR registry

## Variations

_(No variations are documented for this entry.)_
