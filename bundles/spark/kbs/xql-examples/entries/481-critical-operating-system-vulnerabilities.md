---
id: XQL-481-c4f1c903
title: Critical Operating System Vulnerabilities
category: investigation
dataset: va_cves
tags:
  - filter
  - fields
  - va_cves
  - source:dataset
---

# Critical Operating System Vulnerabilities

**Dataset**: `va_cves`

```sql
dataset = va_cves
| filter type = ENUM.OPERATING_SYSTEM and severity = ENUM.CRITICAL
| fields name, cve_id , affected_products , affected_hosts , severity , description, *
```

## When to use

Lists the critical Operating System vulnerabilities for the XDR agents installed

## Variations

_(No variations are documented for this entry.)_
