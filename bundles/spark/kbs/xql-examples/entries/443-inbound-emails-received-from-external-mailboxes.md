---
id: XQL-443-3daecd68
title: Inbound Emails Received from External Mailboxes
category: investigation
dataset: email_data
tags:
  - arrayexpand
  - alter
  - filter
  - fields
  - email_data
  - source:dataset
---

# Inbound Emails Received from External Mailboxes

**Dataset**: `email_data`

```sql
dataset = email_data
| arrayexpand recipients
| alter recipient_address= recipients->address , sender_address = sender -> address
| alter sender_domain = arrayindex(regextract(sender_address,".*\@(.*)"),0), recipient_domain = arrayindex(regextract(recipient_address,".*\@(.*)"),0 )
| filter sender_domain != $company_domain and recipient_domain contains $company_domain
| fields _time , sender_domain , recipient_domain , sender , recipients ,return_path  , *
```

## When to use

Lists emails that were recieved from external mailboxes to an email address associated with the organization

## Variations

_(No variations are documented for this entry.)_
