---
id: XQL-437-92817a1e
title: Outbound Emails Sent to Private/Personal Email Account
category: investigation
dataset: email_data
tags:
  - alter
  - arrayexpand
  - filter
  - fields
  - email_data
  - source:dataset
---

# Outbound Emails Sent to Private/Personal Email Account

**Dataset**: `email_data`

```sql
dataset = email_data
| alter sender_address = sender -> address
| alter recipients_address = arraymap(recipients , json_extract_scalar("@element","$.address"))
| arrayexpand recipients_address
| filter recipients_address ~= ".*gmail|yahoo|outlook|microsoft.*"
| fields sender , sender_address , recipients , recipients_address , attachments
```

## When to use

Lists the people who have forwarded emails to their personal email account, which can indicate that somone is trying to leak sensitive data

## Variations

_(No variations are documented for this entry.)_
