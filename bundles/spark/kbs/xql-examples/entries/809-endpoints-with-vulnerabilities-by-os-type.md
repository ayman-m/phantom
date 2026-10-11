---
id: XQL-809-b8156e4c
title: Endpoints with vulnerabilities by OS type
category: investigation
dataset: va_endpoints
tags:
  - filter
  - comp
  - sort
  - limit
  - va_endpoints
  - vulnerability
---

# Endpoints with vulnerabilities by OS type

**Dataset**: `va_endpoints`

```sql
dataset = va_endpoints
| filter os_type != null
| comp count() as endpoints, avg(severity_score) as avg_severity_score by os_type
| sort desc endpoints
| limit 10
```

## When to use

Vulnerable endpoint count + average severity per OS. Useful for OS-level patch-prioritization.

## Variations

_(No variations are documented for this entry.)_
