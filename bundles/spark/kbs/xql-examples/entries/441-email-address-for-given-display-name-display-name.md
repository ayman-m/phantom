---
id: XQL-441-02fac293
title: Email Address for Given Display Name ($display_name)
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

# Email Address for Given Display Name ($display_name)

**Dataset**: `email_data`

```sql
dataset = email_data
| arrayexpand recipients
| alter recipient_address= recipients->address ,recipient_name = recipients -> name, sender_address = sender -> address ,sender_name = sender -> name
| filter recipient_name contains $display_name or sender_name contains $display_name
| dedup recipient_address, sender_address
| fields recipient_address,recipient_name,sender_address,sender_name,*
```

## When to use

Details the $email_address of a given $display_name

## Variations

_(No variations are documented for this entry.)_
