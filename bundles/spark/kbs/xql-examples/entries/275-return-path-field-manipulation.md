---
id: XQL-275-52ecb4bb
title: Return Path field Manipulation
category: investigation
dataset: email_data
tags:
  - alter
  - filter
  - fields
  - email_data
  - source:dataset
---

# Return Path field Manipulation

**Dataset**: `email_data`

```sql
dataset = email_data
| alter return_path_domain = to_string(regextract(return_path , "@(?:[a-zA-Z0-9-]+\.)*([a-zA-Z0-9-]+)\.[a-zA-Z]{2,}"))
| alter from_address = json_extract(to_json_string(from) , "$.address")
| alter from_domain = to_string(regextract(from_address , "@(?:[a-zA-Z0-9-]+\.)*([a-zA-Z0-9-]+)\.[a-zA-Z]{2,}"))
| filter return_path_domain != null and from_domain != null and (from_domain != return_path_domain or from_address not contains return_path)
| fields return_path_domain ,return_path , from_domain , from_address
```

## When to use

Displays mismatches between the “From” address domain and return path domain, or mismatches between “from” address and return path. Usually, the return path should align with the “from” address, but if they don’t align, the domains should align anyways.

## Variations

_(No variations are documented for this entry.)_
