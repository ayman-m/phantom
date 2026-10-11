---
id: XQL-438-140799a7
title: Incoming Emails where Reply To is Different from Sender
category: investigation
dataset: email_data
tags:
  - alter
  - filter
  - arrayexpand
  - fields
  - email_data
  - source:dataset
---

# Incoming Emails where Reply To is Different from Sender

**Dataset**: `email_data`

```sql
dataset = email_data
| alter sender_address = sender -> address
| filter reply_to != null
| arrayexpand reply_to
| filter reply_to -> address != sender_address
| fields reply_to , sender , *
```

## When to use

Lists any incoming emails that replying to them would actually go to different email address

## Variations

_(No variations are documented for this entry.)_
