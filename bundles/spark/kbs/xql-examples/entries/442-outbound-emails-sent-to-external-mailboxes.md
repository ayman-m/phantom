---
id: XQL-442-adbaa230
title: Outbound Emails Sent to External Mailboxes
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

# Outbound Emails Sent to External Mailboxes

**Dataset**: `email_data`

```sql
dataset = email_data
| arrayexpand recipients
| alter recipient_address= recipients->address , sender_address = sender -> address
| alter sender_domain = arrayindex(regextract(sender_address,".*\@(.*)"),0), recipient_domain = arrayindex(regextract(recipient_address,".*\@(.*)"),0 )
| filter sender_domain = $company_domain and recipient_domain != $company_domain
| fields _time , sender_domain , recipient_domain , sender , recipients ,return_path  , *
```

## When to use

Lists the emails that left the organization and headed to external mailboxes

## Variations

_(No variations are documented for this entry.)_
