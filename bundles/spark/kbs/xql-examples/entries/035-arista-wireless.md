---
id: XQL-035-6352d7c3
title: Arista Wireless
category: general
dataset: arista_cloudvision_raw
tags:
  - alter
  - dataset
  - filter
---

# Arista Wireless

**Dataset**: `arista_cloudvision_raw`

```sql
config case_sensitive = false
| dataset = arista_cloudvision_raw
| alter client_mac = json_extract(radio, "$.macaddress")
| alter client_mac = replace(client_mac,"\"","")
| alter userName = replace(userName, "--","")
| filter active = true
```

## When to use

Arista Wireless. XQL pattern, filtered on `active = true`. Uses stages: `dataset`, `alter`, `filter`.

## Variations

_(No variations are documented for this entry.)_
