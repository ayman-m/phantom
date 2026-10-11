---
id: XQL-434-ef025ed7
title: Email Domains Communicated with via Email
category: investigation
dataset: email_data
tags:
  - arrayexpand
  - alter
  - dedup
  - comp
  - email_data
  - source:dataset
---

# Email Domains Communicated with via Email

**Dataset**: `email_data`

```sql
dataset = email_data
| arrayexpand recipients
| alter recipient_address= recipients->address , sender_address = sender -> address
| dedup recipient_address, sender_address
| alter sender_domain = arrayindex(regextract(sender_address,".*\@(.*)"),0), recipient_domain = arrayindex(regextract(recipient_address,".*\@(.*)"),0 )
| comp values(sender_domain ) as sent_from, values(recipient_domain) as recieved_from
```

## When to use

Lists all the email domains that have been commuincated with over email

## Variations

_(No variations are documented for this entry.)_
