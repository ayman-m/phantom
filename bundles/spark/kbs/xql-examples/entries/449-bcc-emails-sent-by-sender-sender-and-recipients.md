---
id: XQL-449-316ec1fa
title: BCC Emails Sent by Sender ($sender) and Recipients
category: investigation
dataset: email_data
tags:
  - alter
  - filter
  - fields
  - email_data
  - source:dataset
---

# BCC Emails Sent by Sender ($sender) and Recipients

**Dataset**: `email_data`

```sql
dataset = email_data
| alter country = sender_ip_location -> country,sender_address = sender -> address
| filter sender_address contains $sender
| filter bcc_recipients  != null
| fields bcc_recipients , sender ,sender_address ,*
```

## When to use

Lists the emails that were sent as BCC (Blind Carbon Copy) to additional recipients without the primary recipient being made aware. This query includes the sender and BCC recipients.

## Variations

_(No variations are documented for this entry.)_
