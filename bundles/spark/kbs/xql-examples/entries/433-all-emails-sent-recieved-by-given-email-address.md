---
id: XQL-433-1f1da216
title: All Emails Sent/Recieved by Given Email Address
category: investigation
dataset: email_data
tags:
  - filter
  - fields
  - email_data
  - source:dataset
---

# All Emails Sent/Recieved by Given Email Address

**Dataset**: `email_data`

```sql
dataset = email_data
| filter to_string(sender) contains $sender or to_string(recipients) contains $sender or to_string(cc_recipients) contains $sender or to_string(bcc_recipients) contains $sender
| fields _time, sender , sender_ip , recipients , from, attachments , has_attachments , *
```

## When to use

Lists all the related emails that were sent/recieved by this email address

## Variations

_(No variations are documented for this entry.)_
