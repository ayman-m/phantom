---
id: XQL-807-3e2b16b9
title: CVEs by severity distribution
category: investigation
dataset: va_cves
tags:
  - comp
  - sort
  - limit
  - va_cves
  - vulnerability
---

# CVEs by severity distribution

**Dataset**: `va_cves`

```sql
dataset = va_cves
| comp count() as cnt by severity
| sort desc cnt
| limit 10
```

## When to use

Snapshot of the tenant's CVE-catalog distribution by severity.

## Variations

_(No variations are documented for this entry.)_
