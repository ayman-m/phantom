---
id: XQL-474-bee9ba97
title: Vulnerabilities Associated with a Given Endpoint ($endpoint)
category: investigation
dataset: va_endpoints
tags:
  - filter
  - va_endpoints
  - source:dataset
---

# Vulnerabilities Associated with a Given Endpoint ($endpoint)

**Dataset**: `va_endpoints`

```sql
dataset = va_endpoints
| filter endpoint_name contains  $endpoint
```

## When to use

Lists all the related vulnerabilities associated to a specific endpoint for the XDR agents installed

## Variations

_(No variations are documented for this entry.)_
