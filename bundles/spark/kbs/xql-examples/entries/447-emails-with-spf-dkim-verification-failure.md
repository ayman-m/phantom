---
id: XQL-447-ef7d0460
title: Emails with SPF/DKIM Verification Failure
category: investigation
dataset: email_data
tags:
  - filter
  - fields
  - email_data
  - source:dataset
---

# Emails with SPF/DKIM Verification Failure

**Dataset**: `email_data`

```sql
dataset = email_data
| filter to_string(authentication_results) contains "*"
| fields _time , sender , recipients , authentication_results, dkim_signature , received_spf , internet_message_headers , *
```

## When to use

Lists the emails that failed their DKIM/SPF verification

## Variations

_(No variations are documented for this entry.)_
