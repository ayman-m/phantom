---
id: XQL-036-d0121688
title: Arista Wireless Misbehaving
category: general
dataset: arista_cloudvision_raw
tags:
  - alter
  - dataset
  - filter
---

# Arista Wireless Misbehaving

**Dataset**: `arista_cloudvision_raw`

```sql
config case_sensitive = false
| dataset = arista_cloudvision_raw
| alter client_mac = json_extract(radio, "$.macaddress")
| alter client_mac = replace(client_mac,"\"","")
| alter userName = replace(userName, "--","")
| filter active = true and misbehaving = "YES"
```

## When to use

Arista Wireless Misbehaving. XQL pattern, filtered on `active = true and misbehaving = "YES"`. Uses stages: `dataset`, `alter`, `filter`.

## Variations

_(No variations are documented for this entry.)_
