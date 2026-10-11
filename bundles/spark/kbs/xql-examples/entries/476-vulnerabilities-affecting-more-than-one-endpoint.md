---
id: XQL-476-5ea24813
title: Vulnerabilities Affecting More Than One Endpoint
category: investigation
dataset: va_cves
tags:
  - filter
  - fields
  - va_cves
  - source:dataset
---

# Vulnerabilities Affecting More Than One Endpoint

**Dataset**: `va_cves`

```sql
dataset = va_cves
| filter array_length(affected_hosts ) > 1
| fields affected_hosts, affected_hosts_count, affected_products, name, description, *
```

## When to use

Lists the vulnerabilities that affect multiple endpoints for the XDR agents installed

## Variations

_(No variations are documented for this entry.)_
