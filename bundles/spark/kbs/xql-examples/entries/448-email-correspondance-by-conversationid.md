---
id: XQL-448-f2c46016
title: Email Correspondance by $conversationid
category: investigation
dataset: email_data
tags:
  - filter
  - fields
  - email_data
  - source:dataset
---

# Email Correspondance by $conversationid

**Dataset**: `email_data`

```sql
dataset = email_data
| filter conversation_id contains $conversationid
| fields conversation_id , conversation_index , sender , recipients , internet_message_headers , o365_data , *
```

## When to use

Lists the entire email correspondance by the email conversation ID ($conversationid)

## Variations

_(No variations are documented for this entry.)_
