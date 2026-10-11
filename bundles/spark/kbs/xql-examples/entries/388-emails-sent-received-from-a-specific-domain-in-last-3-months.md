---
id: XQL-388-a345bab7
title: Emails Sent / Received from a Specific Domain in Last 3 Months
category: investigation
dataset: email_data
tags:
  - config
  - filter
  - email_data
  - source:dataset
---

# Emails Sent / Received from a Specific Domain in Last 3 Months

**Dataset**: `email_data`

```sql
config timeframe = 3mo | dataset = email_data
| filter to_string(from) contains $domain or to_string(from_normalized) contains $domain or to_string(sender) contains $domain or to_string(sender_normalized) contains $domain
```

## When to use

After reviewing the emails from Office365 and Gmail, lists the emails sent/received from a given domain in the last 3 months, and includes the applicable fields

## Variations

_(No variations are documented for this entry.)_
