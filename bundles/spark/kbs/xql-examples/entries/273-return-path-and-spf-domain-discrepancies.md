---
id: XQL-273-99058c9c
title: Return Path and SPF domain discrepancies
category: investigation
dataset: email_data
tags:
  - alter
  - filter
  - fields
  - email_data
  - source:dataset
---

# Return Path and SPF domain discrepancies

**Dataset**: `email_data`

```sql
dataset = email_data
| alter spf_domain = json_extract(to_json_string(received_spf), "$.domain")
| alter spf_main_domain = to_string(regextract(spf_domain , "@?(?:[a-zA-Z0-9-]+\.)*([a-zA-Z0-9-]+)\.[a-zA-Z]{2,}"))
| alter return_path_domain = to_string(regextract(return_path , "@(?:[a-zA-Z0-9-]+\.)*([a-zA-Z0-9-]+)\.[a-zA-Z]{2,}"))
| filter return_path_domain != null and spf_domain != null and spf_main_domain != return_path_domain
| fields spf_main_domain, return_path_domain
```

## When to use

Displays mismatches between SPF detected domain and return path domain. These should align since SPF verifies the domain specified in the return path.
If they don’t match, it can indicate a potential spoofing.

## Variations

_(No variations are documented for this entry.)_
