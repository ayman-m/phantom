---
id: XQL-445-27347d80
title: Top Email Senders in the Organization
category: investigation
dataset: email_data
tags:
  - alter
  - arrayexpand
  - email_data
  - source:dataset
---

# Top Email Senders in the Organization

**Dataset**: `email_data`

```sql
dataset = email_data
| alter sender_address = sender -> address
| alter recipients_address = arraymap(recipients , json_extract_scalar("@element","$.address"))
| arrayexpand recipients_address
| top sender_address
```

## When to use

Lists the top emails senders in the organizaiton

## Variations

_(No variations are documented for this entry.)_
