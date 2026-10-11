---
id: XQL-444-0970a834
title: Where the Emails by $sender Originated From
category: investigation
dataset: email_data
tags:
  - alter
  - filter
  - fields
  - email_data
  - source:dataset
---

# Where the Emails by $sender Originated From

**Dataset**: `email_data`

```sql
dataset = email_data
| alter country = sender_ip_location -> country,sender_address = sender -> address
| filter sender_address contains $sender
| fields country , sender_address , sender_ip , sender_ip_location ,*
```

## When to use

Lists each country the given emails from the given sender ($sender) originated from

## Variations

_(No variations are documented for this entry.)_
