---
id: XQL-825-9cad7191
title: CVEs by OS type (array-expanded)
category: detection
dataset: va_cves
tags:
  - filter
  - arrayexpand
  - comp
  - sort
  - limit
  - va_cves
  - vulnerability
---

# CVEs by OS type (array-expanded)

**Dataset**: `va_cves`

```sql
dataset = va_cves
| filter os_type != null
| arrayexpand os_type
| comp count() as cnt by os_type, severity
| sort desc cnt
| limit 10
```

## When to use

CVE distribution by OS type. `os_type` in va_cves is an array (a CVE can affect multiple OS families); arrayexpand flattens before aggregation.

## Variations

_(No variations are documented for this entry.)_
