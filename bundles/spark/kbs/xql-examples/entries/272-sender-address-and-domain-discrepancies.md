---
id: XQL-272-4f106c26
title: Sender address and domain discrepancies
category: investigation
dataset: email_data
tags:
  - alter
  - filter
  - fields
  - dedup
  - email_data
  - source:dataset
---

# Sender address and domain discrepancies

**Dataset**: `email_data`

```sql
dataset = email_data
| alter sender_address = json_extract(to_json_string(sender), "$.address")
| alter sender_domain = to_string(regextract(sender_address , "@(?:[a-zA-Z0-9-]+\.)*([a-zA-Z0-9-]+)\.[a-zA-Z]{2,}"))
| alter from_address = json_extract(to_json_string(from) , "$.address")
| alter from_domain = to_string(regextract(from_address , "@(?:[a-zA-Z0-9-]+\.)*([a-zA-Z0-9-]+)\.[a-zA-Z]{2,}"))
| filter from_address != sender_address or from_domain != sender_domain
| fields from_address,from_domain, sender_address, sender_domain
| dedup from_address by asc _time
```

## When to use

Displays mismatches between 'from' address and sender address,  or ‘from’ domain and sender domain. This can indicate a potential spoofing.

## Variations

_(No variations are documented for this entry.)_
