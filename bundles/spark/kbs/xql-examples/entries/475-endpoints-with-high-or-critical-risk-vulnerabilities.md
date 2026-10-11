---
id: XQL-475-5d51e06f
title: Endpoints with High or Critical Risk Vulnerabilities
category: investigation
dataset: va_endpoints
tags:
  - filter
  - va_endpoints
  - source:dataset
---

# Endpoints with High or Critical Risk Vulnerabilities

**Dataset**: `va_endpoints`

```sql
dataset = va_endpoints
| filter severity in(ENUM.CRITICAL , ENUM.HIGH )
```

## When to use

Lists all the endpoint vulnerabilities that have a high or critcal risk severity for the XDR agents installed

## Variations

_(No variations are documented for this entry.)_
