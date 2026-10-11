---
id: XQL-440-1adb9583
title: Display Name for Given Email Address ($email_address)
category: investigation
dataset: email_data
tags:
  - arrayexpand
  - alter
  - filter
  - dedup
  - fields
  - email_data
  - source:dataset
---

# Display Name for Given Email Address ($email_address)

**Dataset**: `email_data`

```sql
dataset = email_data
| arrayexpand recipients
| alter recipient_address= recipients->address ,recipient_name = recipients -> name, sender_address = sender -> address ,sender_name = sender -> name
| filter recipient_address contains $email_address or sender_address contains $email_address
| dedup recipient_address, sender_address
| fields recipient_address,recipient_name,sender_address,sender_name,*
```

## When to use

Details the display name of a given $email_address

## Variations

_(No variations are documented for this entry.)_
