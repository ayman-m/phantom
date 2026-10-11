---
id: XQL-808-30f685fb
title: Top vulnerable endpoints by severity score
category: investigation
dataset: va_endpoints
tags:
  - filter
  - fields
  - sort
  - limit
  - va_endpoints
  - vulnerability
---

# Top vulnerable endpoints by severity score

**Dataset**: `va_endpoints`

```sql
dataset = va_endpoints
| filter severity_score != null
| fields endpoint_name, endpoint_type, os_type, severity, severity_score
| sort desc severity_score
| limit 10
```

## When to use

Endpoints ranked by computed severity_score. Uses only fields confirmed in the va_endpoints schema (endpoint_name, endpoint_type, os_type, severity, severity_score).

## Variations

_(No variations are documented for this entry.)_
